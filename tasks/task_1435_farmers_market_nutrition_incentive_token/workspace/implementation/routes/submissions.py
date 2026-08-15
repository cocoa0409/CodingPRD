"""RedemptionSubmission endpoints: create, read, list, verify, resubmit, decide."""

from datetime import timedelta

from flask import Blueprint, request

from db import STORE, stamp_new, touch, idem_marker
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_MARKET_DAY_NOT_CLOSED,
    ERR_SUBMISSION_EMPTY,
    ERR_SUBMISSION_WINDOW_CLOSED,
    ERR_TOKEN_ALREADY_SUBMITTED,
    ERR_TOKEN_FLAGGED,
    ERR_TOKEN_VENDOR_MISMATCH,
    ERR_VENDOR_NOT_ACTIVE,
)
from logical_clock import CLOCK, _parse_iso
from middleware import (
    IdempotencyReplay,
    authenticate,
    ensure_valid_json,
    get_body,
    idempotency_guard,
    paginate,
    req_enum,
    req_str,
    req_str_list,
)
from response import success_list, success_object
from routes.common import get_path_entity, ref_exists, replay_response
from services.domain import (
    NON_TERMINAL_SUBMISSION_STATUSES,
    RESUBMIT_GRACE_HOURS,
    SUBMISSION_WINDOW_DAYS,
    bulk_change_tokens,
    compute_approved_amount,
    compute_provisional_amount,
    iso,
    reject_submission_quarantine,
    serialize_submission,
    tokens_of_submission,
)

bp = Blueprint("submissions", __name__)

SUB_READ_ROLES = ["ProgramAdmin", "MarketManager", "Auditor", "Vendor"]


def _load_tokens_or_refs(body):
    """Priority 6 for token_ids elements happens before shape (priority 8)."""
    raw = body.get("token_ids")
    if isinstance(raw, list):
        for element in raw:
            ref_exists("tokens", element)


def _attachment_ladder(tokens, vendor_id, exclude_submission_id=None):
    """Strict per-token ladder (PRD §3.6): quarantine (16), vendor mismatch
    (19), already-submitted (20)."""
    for token in tokens:
        if token["status"] == "FLAGGED":
            raise ApiError(ERR_TOKEN_FLAGGED, 409,
                           "A flagged token cannot be claimed")
    for token in tokens:
        if token.get("redeemed_vendor_id") != vendor_id:
            raise ApiError(ERR_TOKEN_VENDOR_MISMATCH, 409,
                           "Token was not redeemed by the submitting vendor")
    for token in tokens:
        sid = token.get("submission_id")
        if sid is None or sid == exclude_submission_id:
            continue
        holder = STORE["submissions"].get(sid)
        if holder is not None and holder["status"] in NON_TERMINAL_SUBMISSION_STATUSES:
            raise ApiError(ERR_TOKEN_ALREADY_SUBMITTED, 409,
                           "Token is already attached to a non-terminal submission")


def _within_submission_window(day, now):
    """PRD §3.6: while the day is OPEN, or after close within 7 days of
    closes_at (inclusive). Post-close states (CLOSED / VARIANCE_FLAGGED /
    RECONCILED) all count as 'after close'."""
    if day["status"] == "OPEN":
        return True
    if day["status"] in ("CLOSED", "VARIANCE_FLAGGED", "RECONCILED"):
        closes_at = _parse_iso(day["closes_at"])
        return now <= closes_at + timedelta(days=SUBMISSION_WINDOW_DAYS)
    return False


def _check_day_closed_family(day):
    """Priority 15: verify/decide require CLOSED or VARIANCE_FLAGGED; a
    RECONCILED day is terminally locked (ERR_INVALID_STATE)."""
    if day["status"] in ("CLOSED", "VARIANCE_FLAGGED"):
        return
    if day["status"] == "RECONCILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The market day is RECONCILED and terminally locked")
    raise ApiError(ERR_MARKET_DAY_NOT_CLOSED, 409,
                   "The market day is not closed yet")


@bp.route("/redemption-submissions", methods=["POST"])
def create_submission():
    _role, vendor_id = authenticate(["Vendor"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)

    # Priority 6: body FK existence.
    ref_exists("market_days", body.get("market_day_id"))
    _load_tokens_or_refs(body)
    # Priority 8: shape.
    ensure_valid_json(body)
    market_day_id = req_str(body, "market_day_id")
    token_ids = req_str_list(body, "token_ids")
    # Priority 9: emptiness.
    if len(token_ids) == 0:
        raise ApiError(ERR_SUBMISSION_EMPTY, 422, "token_ids must not be empty")

    vendor = STORE["vendors"][vendor_id]
    day = STORE["market_days"][market_day_id]
    tokens = [STORE["tokens"][tid] for tid in token_ids]

    # Priority 13: vendor standing.
    if vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_NOT_ACTIVE, 409,
                       "Vendor must be ACTIVE to submit a claim")
    # Priorities 16/19/20: strict attachment ladder.
    _attachment_ladder(tokens, vendor_id)
    # Priority 22: submission window.
    now = CLOCK.now()
    if not _within_submission_window(day, now):
        raise ApiError(ERR_SUBMISSION_WINDOW_CLOSED, 409,
                       "The submission window for this market day has closed")

    sub = stamp_new({
        "vendor_id": vendor_id,
        "market_day_id": market_day_id,
        "status": "SUBMITTED",
        "provisional_amount_cents": compute_provisional_amount(tokens),
        "approved_amount_cents": None,
        "paid_amount_cents": None,
        "approved_at": None,
        "disputed_at": None,
    })
    STORE["submissions"][sub["id"]] = sub
    for token in tokens:
        if token.get("submission_id") != sub["id"]:
            token["submission_id"] = sub["id"]
            touch(token)

    env, status = success_object(serialize_submission(sub), 201)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/redemption-submissions/<sid>", methods=["GET"])
def get_submission(sid):
    role, user_id = authenticate(SUB_READ_ROLES)
    sub = get_path_entity("submissions", sid)
    if role == "Vendor" and sub["vendor_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "A vendor may only read its own submissions")
    return success_object(serialize_submission(sub))


@bp.route("/redemption-submissions", methods=["GET"])
def list_submissions():
    role, user_id = authenticate(SUB_READ_ROLES)
    vendor_id = request.args.get("vendor_id")
    market_day_id = request.args.get("market_day_id")
    status_filter = request.args.get("status")
    if role == "Vendor":
        # Entity-backed scoping: a vendor sees only its own claims.
        vendor_id = user_id
    items = list(STORE["submissions"].values())
    if vendor_id is not None:
        items = [s for s in items if s["vendor_id"] == vendor_id]
    if market_day_id is not None:
        items = [s for s in items if s["market_day_id"] == market_day_id]
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_submission(s) for s in page], limit, offset, total)


@bp.route("/redemption-submissions/<sid>/verify", methods=["POST"])
def verify_submission(sid):
    authenticate(["MarketManager"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    sub = get_path_entity("submissions", sid)
    ensure_valid_json(body)
    outcome = req_enum(body, "outcome", {"VERIFIED", "DISPUTED"})
    if sub["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Submission in status {sub['status']} cannot be verified")
    day = STORE["market_days"].get(sub["market_day_id"])
    _check_day_closed_family(day)

    sub["status"] = outcome
    if outcome == "DISPUTED":
        sub["disputed_at"] = CLOCK.now_iso()
    touch(sub)
    env, status = success_object(serialize_submission(sub), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/redemption-submissions/<sid>/resubmit", methods=["POST"])
def resubmit_submission(sid):
    _role, vendor_id = authenticate(["Vendor"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    sub = get_path_entity("submissions", sid)

    # Ownership (resource-dependent priority 2).
    if sub["vendor_id"] != vendor_id:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Only the owning vendor may resubmit this claim")
    # Priority 6 / 8 / 9.
    _load_tokens_or_refs(body)
    ensure_valid_json(body)
    token_ids = req_str_list(body, "token_ids")
    if len(token_ids) == 0:
        raise ApiError(ERR_SUBMISSION_EMPTY, 422, "token_ids must not be empty")

    # Priority 11: only a DISPUTED claim can be cured.
    if sub["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Submission in status {sub['status']} cannot be resubmitted")
    vendor = STORE["vendors"][vendor_id]
    # Priority 13: vendor standing.
    if vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_NOT_ACTIVE, 409,
                       "Vendor must be ACTIVE to resubmit a claim")
    tokens = [STORE["tokens"][tid] for tid in token_ids]
    # Priorities 16/19/20 (attachments to this same claim are being replaced).
    _attachment_ladder(tokens, vendor_id, exclude_submission_id=sub["id"])
    # Priority 22: ordinary window, or 72h grace measured from disputed_at.
    day = STORE["market_days"].get(sub["market_day_id"])
    now = CLOCK.now()
    in_window = day is not None and _within_submission_window(day, now)
    in_grace = False
    if sub.get("disputed_at"):
        in_grace = now <= _parse_iso(sub["disputed_at"]) + timedelta(hours=RESUBMIT_GRACE_HOURS)
    if not (in_window or in_grace):
        raise ApiError(ERR_SUBMISSION_WINDOW_CLOSED, 409,
                       "Resubmission is outside both the submission window and "
                       "the 72-hour dispute grace")

    # Side effects: detach old, attach new, reprice, back to SUBMITTED.
    for token in tokens_of_submission(sub["id"]):
        token["submission_id"] = None
        touch(token)
    for token in tokens:
        token["submission_id"] = sub["id"]
        touch(token)
    sub["provisional_amount_cents"] = compute_provisional_amount(tokens)
    sub["status"] = "SUBMITTED"
    touch(sub)
    env, status = success_object(serialize_submission(sub), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/redemption-submissions/<sid>/decide", methods=["POST"])
def decide_submission(sid):
    authenticate(["ProgramAdmin"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    sub = get_path_entity("submissions", sid)
    ensure_valid_json(body)
    outcome = req_enum(body, "outcome", {"APPROVED", "REJECTED"})

    # Priority 11: generic invalid-from rejection.
    if outcome == "APPROVED" and sub["status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Submission in status {sub['status']} cannot be approved")
    if outcome == "REJECTED" and sub["status"] not in ("VERIFIED", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Submission in status {sub['status']} cannot be rejected")
    # Priority 15: day must be in the closed family (RECONCILED is locked).
    day = STORE["market_days"].get(sub["market_day_id"])
    _check_day_closed_family(day)

    if outcome == "APPROVED":
        attached = tokens_of_submission(sub["id"])
        sub["approved_amount_cents"] = compute_approved_amount(attached)
        sub["approved_at"] = CLOCK.now_iso()
        sub["status"] = "APPROVED"
        # HOP-1: attached tokens still REDEEMED -> SETTLED (each token bumps;
        # each affected market day recomputes and bumps once — REDEEMED and
        # SETTLED both count, so variance does not move).
        bulk_change_tokens(
            [t for t in attached if t["status"] == "REDEEMED"],
            lambda t: "SETTLED",
        )
        # HOP-2: vendor payable recomputes (computed field; version bumps).
        vendor = STORE["vendors"].get(sub["vendor_id"])
        if vendor is not None:
            touch(vendor)
        touch(sub)
    else:
        # REJECTED: token-quarantine cascade (shared with the system reject).
        reject_submission_quarantine(sub)

    env, status = success_object(serialize_submission(sub), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status
