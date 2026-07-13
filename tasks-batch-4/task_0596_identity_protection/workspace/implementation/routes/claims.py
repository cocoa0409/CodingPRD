from flask import Blueprint, request

from db import by_seq, db, new_row, touch
from errors import ApiError
from middleware import (
    auth,
    body,
    must_exist,
    must_exist_fk,
    req_expenses,
    req_int,
    req_str,
    require_enrollment_active,
    require_subscriber_owner,
)
from response import ok, ok_list, paginate, read_pagination
from serializers import ser, ser_many
from services import calc

bp = Blueprint("claims", __name__)

UNDERWRITING_CEILING = 75


@bp.post("/idp/insurance-claims")
def create_claim():
    role, user_id = auth("Subscriber")
    data = body()

    case = must_exist_fk("cases", data, "case_id")
    if case is not None:
        require_subscriber_owner(role, user_id, case["subscriber_id"])
    else:
        req_str(data, "case_id")

    expected_case_version = req_int(data, "expected_case_version")
    expenses = req_expenses(data)

    if expected_case_version != case["version"]:
        raise ApiError(
            "ERR_STALE_CASE_VERSION",
            "expected_case_version does not match the case's current version.",
        )

    subscriber = db.subscribers[case["subscriber_id"]]
    require_enrollment_active(subscriber)

    # A case carries at most one non-terminal claim: supersede any existing DRAFT.
    for existing in db.claims.values():
        if existing["case_id"] == case["id"] and existing["status"] == "DRAFT":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    claim = new_row(
        case_id=case["id"],
        subscriber_id=case["subscriber_id"],
        expenses=expenses,
        provisional_amount_cents=None,
        approved_cents=None,
        status="DRAFT",
        approved_by_user_id=None,
        denial_reason=None,
        reversal_reason=None,
    )
    db.claims[claim["id"]] = claim

    touch(case)
    return ok(ser(claim), 201)


@bp.get("/idp/insurance-claims")
def list_claims():
    role, user_id = auth("Subscriber", "PlatformAdmin", "ClaimsAdjuster")
    limit, offset = read_pagination()

    rows = list(db.claims.values())
    if role == "Subscriber":
        rows = [c for c in rows if c["subscriber_id"] == user_id]

    for key in ("subscriber_id", "case_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [c for c in rows if c[key] == value]

    rows = by_seq(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_many(page), limit, offset, total)


@bp.get("/idp/insurance-claims/<claim_id>")
def read_claim(claim_id):
    role, user_id = auth("Subscriber", "PlatformAdmin", "ClaimsAdjuster")
    claim = must_exist("claims", claim_id)
    require_subscriber_owner(role, user_id, claim["subscriber_id"])
    return ok(ser(claim))


@bp.post("/idp/insurance-claims/<claim_id>/submit")
def submit(claim_id):
    role, user_id = auth("Subscriber")
    claim = must_exist("claims", claim_id)
    require_subscriber_owner(role, user_id, claim["subscriber_id"])
    body()

    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Claim is not DRAFT.")

    case = db.cases[claim["case_id"]]
    if case["status"] != "RESOLVED":
        raise ApiError("ERR_CASE_NOT_RESOLVED", "The restoration case is not RESOLVED.")

    subscriber = db.subscribers[claim["subscriber_id"]]
    require_enrollment_active(subscriber)

    if subscriber["insurance_status"] != "AVAILABLE":
        raise ApiError("ERR_INSURANCE_EXHAUSTED", "The lifetime insurance budget is exhausted.")
    if (subscriber["underwriting_risk_score"] or 0) > UNDERWRITING_CEILING:
        raise ApiError(
            "ERR_UNDERWRITING_RISK_TOO_HIGH",
            "The subscriber's underwriting risk score exceeds 75.",
        )

    claim["provisional_amount_cents"] = calc.claim_reimbursement(
        claim, "PROVISIONAL", subscriber
    )
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(ser(claim))


@bp.post("/idp/insurance-claims/<claim_id>/approve")
def approve(claim_id):
    role, user_id = auth("ClaimsAdjuster")
    claim = must_exist("claims", claim_id)
    body()

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not SUBMITTED.")

    subscriber = db.subscribers[claim["subscriber_id"]]
    claim["approved_cents"] = calc.claim_reimbursement(claim, "FINAL", subscriber)
    claim["approved_by_user_id"] = user_id
    claim["status"] = "APPROVED"
    touch(claim)
    return ok(ser(claim))


@bp.post("/idp/insurance-claims/<claim_id>/deny")
def deny(claim_id):
    auth("ClaimsAdjuster")
    claim = must_exist("claims", claim_id)
    data = body()
    reason = req_str(data, "denial_reason")

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not SUBMITTED.")

    claim["denial_reason"] = reason
    claim["status"] = "DENIED"
    touch(claim)
    return ok(ser(claim))


@bp.post("/idp/insurance-claims/<claim_id>/pay")
def pay(claim_id):
    role, user_id = auth("PlatformAdmin")
    claim = must_exist("claims", claim_id)
    body()

    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not APPROVED.")
    if user_id == claim["approved_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who approved a claim may not disburse it.",
        )

    claim["status"] = "PAID"
    touch(claim)

    subscriber = db.subscribers[claim["subscriber_id"]]
    calc.recompute_insurance(subscriber)
    touch(subscriber)
    return ok(ser(claim))


@bp.post("/idp/insurance-claims/<claim_id>/reverse")
def reverse(claim_id):
    auth("PlatformAdmin")
    claim = must_exist("claims", claim_id)
    data = body()
    reason = req_str(data, "reversal_reason")

    if claim["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", "Claim is not PAID.")

    claim["status"] = "REVERSED"
    claim["reversal_reason"] = reason
    touch(claim)

    subscriber = db.subscribers[claim["subscriber_id"]]
    calc.recompute_insurance(subscriber)
    touch(subscriber)
    return ok(ser(claim))
