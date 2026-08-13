"""FraudCase endpoints: open, read, list, confirm (subject cascade), clear."""

from flask import Blueprint, request

from db import STORE, stamp_new, touch, idem_marker
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_SUBJECT_AMBIGUOUS,
)
from middleware import (
    IdempotencyReplay,
    authenticate,
    ensure_valid_json,
    get_body,
    idempotency_guard,
    opt_str,
    paginate,
    req_str,
)
from response import success_list, success_object
from routes.common import get_path_entity, ref_exists, replay_response
from services.domain import (
    change_token_status,
    reject_submission_quarantine,
    serialize_fraud_case,
)

bp = Blueprint("fraud_cases", __name__)

CASE_READ_ROLES = ["ProgramAdmin", "Auditor"]


@bp.route("/fraud-cases", methods=["POST"])
def create_fraud_case():
    authenticate(["Auditor"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)

    # Priority 6: subject id existence (before shape, before ambiguity).
    ref_exists("vendors", body.get("vendor_id"))
    ref_exists("shoppers", body.get("shopper_id"))
    ref_exists("tokens", body.get("token_id"))

    ensure_valid_json(body)
    reason = req_str(body, "reason")
    vendor_id = opt_str(body, "vendor_id")
    shopper_id = opt_str(body, "shopper_id")
    token_id = opt_str(body, "token_id")

    # Priority 26: exactly one subject.
    subjects = [x for x in (vendor_id, shopper_id, token_id) if x is not None]
    if len(subjects) != 1:
        raise ApiError(ERR_SUBJECT_AMBIGUOUS, 422,
                       "Exactly one of vendor_id, shopper_id, token_id must be set")

    case = stamp_new({
        "vendor_id": vendor_id,
        "shopper_id": shopper_id,
        "token_id": token_id,
        "reason": reason,
        "origin": "MANUAL",
        "status": "OPEN",
    })
    STORE["fraud_cases"][case["id"]] = case

    # Opening a token-targeted case flags a REDEEMED token immediately (§3.7).
    if token_id is not None:
        token = STORE["tokens"][token_id]
        if token["status"] == "REDEEMED":
            change_token_status(token, "FLAGGED")

    env, status = success_object(serialize_fraud_case(case), 201)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/fraud-cases/<cid>", methods=["GET"])
def get_fraud_case(cid):
    authenticate(CASE_READ_ROLES)
    case = get_path_entity("fraud_cases", cid)
    return success_object(serialize_fraud_case(case))


@bp.route("/fraud-cases", methods=["GET"])
def list_fraud_cases():
    authenticate(CASE_READ_ROLES)
    vendor_id = request.args.get("vendor_id")
    shopper_id = request.args.get("shopper_id")
    token_id = request.args.get("token_id")
    status_filter = request.args.get("status")
    items = list(STORE["fraud_cases"].values())
    if vendor_id is not None:
        items = [c for c in items if c.get("vendor_id") == vendor_id]
    if shopper_id is not None:
        items = [c for c in items if c.get("shopper_id") == shopper_id]
    if token_id is not None:
        items = [c for c in items if c.get("token_id") == token_id]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_fraud_case(c) for c in page], limit, offset, total)


def _confirm_vendor_cascade(vendor):
    """Hop 1: ACTIVE -> SUSPENDED. Hop 2: SUBMITTED/DISPUTED claims -> REJECTED
    (each with the hop-3 token quarantine inside reject_submission_quarantine)."""
    if vendor["status"] == "ACTIVE":
        vendor["status"] = "SUSPENDED"
        touch(vendor)
    targets = [
        s for s in STORE["submissions"].values()
        if s["vendor_id"] == vendor["id"] and s["status"] in ("SUBMITTED", "DISPUTED")
    ]
    targets.sort(key=lambda s: (s["created_at"], s["_seq"]))
    for sub in targets:
        reject_submission_quarantine(sub)


def _confirm_token_cascade(token):
    """FLAGGED -> CONFISCATED; REDEEMED -> FLAGGED then CONFISCATED (both
    steps' ledger effects applied in order, so a REDEEMED token bumps twice);
    ISSUED -> FLAGGED (review hold, stops there). Confiscation detaches the
    token from any non-terminal claim."""
    if token["status"] == "REDEEMED":
        change_token_status(token, "FLAGGED")
    if token["status"] == "FLAGGED":
        change_token_status(token, "CONFISCATED", detach=True)
    elif token["status"] == "ISSUED":
        change_token_status(token, "FLAGGED")


@bp.route("/fraud-cases/<cid>/confirm", methods=["POST"])
def confirm_fraud_case(cid):
    authenticate(["ProgramAdmin"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    case = get_path_entity("fraud_cases", cid)
    if case["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"FraudCase in status {case['status']} cannot be confirmed")

    if case.get("vendor_id"):
        vendor = STORE["vendors"].get(case["vendor_id"])
        if vendor is not None:
            _confirm_vendor_cascade(vendor)
    elif case.get("shopper_id"):
        shopper = STORE["shoppers"].get(case["shopper_id"])
        if shopper is not None and shopper["status"] == "ACTIVE":
            shopper["status"] = "SUSPENDED"
            touch(shopper)
    elif case.get("token_id"):
        token = STORE["tokens"].get(case["token_id"])
        if token is not None:
            _confirm_token_cascade(token)

    case["status"] = "CONFIRMED"
    touch(case)
    env, status = success_object(serialize_fraud_case(case), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/fraud-cases/<cid>/clear", methods=["POST"])
def clear_fraud_case(cid):
    authenticate(["ProgramAdmin"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    case = get_path_entity("fraud_cases", cid)
    if case["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"FraudCase in status {case['status']} cannot be cleared")

    # Compensation only where the ledger was touched: a token subject that is
    # currently FLAGGED returns FLAGGED -> REDEEMED. Vendor/shopper subjects
    # are never auto-reinstated (PRD §3.7).
    if case.get("token_id"):
        token = STORE["tokens"].get(case["token_id"])
        if token is not None and token["status"] == "FLAGGED":
            change_token_status(token, "REDEEMED")

    case["status"] = "CLEARED"
    touch(case)
    env, status = success_object(serialize_fraud_case(case), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status
