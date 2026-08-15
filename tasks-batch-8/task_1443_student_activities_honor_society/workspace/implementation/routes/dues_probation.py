"""DuesPayment and ProbationCase endpoints."""

from datetime import timedelta

from flask import Blueprint

import db
from core import (as_int, as_str, body, cascade_member_dismissal, check_frozen,
                  create_ledger_entry, get_chapter, get_dues_payment,
                  get_member, get_probation_case, new_record,
                  recompute_chapter, recompute_member, require_fields, touch)
from db import now, now_iso, parse_dt
from errors import (ERR_APPEAL_WINDOW_CLOSED,
                    ERR_INSUFFICIENT_FUNDS_FOR_REMITTANCE,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_MEMBER_MISMATCH, ApiError)
from middleware import auth, require_roles
from response import (apply_filters, list_response, serialize, serialize_many,
                      sorted_items, success)

bp = Blueprint("dues_probation", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")
REASON_CODES = ("GPA_BELOW_THRESHOLD", "SERVICE_HOURS_SHORTFALL",
                "CONDUCT_VIOLATION", "MISSED_MEETINGS")
OUTCOMES = ("STANDARDS_VIOLATION_CONFIRMED", "STANDARDS_VIOLATION_NOT_CONFIRMED")


# --- DuesPayment ---

@bp.route("/chapters/<chapterId>/members/<memberId>/dues-payments", methods=["POST"])
def create_dues_payment(chapterId, memberId):
    _, role = auth()
    require_roles(role, ("Member", "Officer", "Advisor"))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    check_frozen(ch)
    data = body()
    require_fields(data, ["academic_year", "amount_cents", "paid_at"])
    amount = as_int(data["amount_cents"], "amount_cents")
    if amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents must be greater than zero")
    rec = new_record({
        "chapter_id": ch["id"],
        "member_id": m["id"],
        "academic_year": as_str(data["academic_year"], "academic_year"),
        "amount_cents": amount,
        "paid_at": db.iso(parse_dt(data["paid_at"], "paid_at")),
        "status": "PENDING_REMITTANCE",
        "remitted_at": None,
    })
    db.dues_payments[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>/members/<memberId>/dues-payments", methods=["GET"])
def list_dues_payments(chapterId, memberId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    items = [p for p in db.dues_payments.values() if p["member_id"] == m["id"]]
    items = apply_filters(items, ["status", "academic_year"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/members/<memberId>/dues-payments/<paymentId>", methods=["GET"])
def fetch_dues_payment(chapterId, memberId, paymentId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    p = get_dues_payment(m, paymentId)
    return success(serialize(p), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/dues-payments/<paymentId>/remit", methods=["POST"])
def remit_dues_payment(chapterId, memberId, paymentId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    p = get_dues_payment(m, paymentId)
    check_frozen(ch)
    if p["status"] != "PENDING_REMITTANCE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PENDING_REMITTANCE payment can be remitted")
    if m["status"] not in ("ACTIVE", "ON_PROBATION"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Member must be ACTIVE or ON_PROBATION to remit dues")
    if ch["fund_balance_cents"] < p["amount_cents"]:
        raise ApiError(ERR_INSUFFICIENT_FUNDS_FOR_REMITTANCE, 409,
                       "Chapter fund balance is insufficient to remit this payment")
    p["status"] = "REMITTED"
    p["remitted_at"] = now_iso()
    touch(p)
    create_ledger_entry(ch, "NATIONAL_DUES_PAYMENT", -p["amount_cents"], "CLEARED",
                        description=f"National dues remittance for member {m['id']}")
    recompute_chapter(ch)
    return success(serialize(p), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/dues-payments/<paymentId>/void", methods=["POST"])
def void_dues_payment(chapterId, memberId, paymentId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    p = get_dues_payment(m, paymentId)
    check_frozen(ch)
    if p["status"] != "PENDING_REMITTANCE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PENDING_REMITTANCE payment can be voided")
    p["status"] = "VOID"
    touch(p)
    return success(serialize(p), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/dues-payments/<paymentId>/refund", methods=["POST"])
def refund_dues_payment(chapterId, memberId, paymentId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    p = get_dues_payment(m, paymentId)
    check_frozen(ch)
    if p["status"] != "REMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REMITTED payment can be refunded")
    if m["status"] != "DISMISSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Dues may only be refunded once the member is DISMISSED")
    p["status"] = "REFUNDED"
    touch(p)
    create_ledger_entry(ch, "ADJUSTMENT", p["amount_cents"], "CLEARED",
                        description=f"Dues refund for dismissed member {m['id']}")
    recompute_chapter(ch)
    return success(serialize(p), 200)


# --- ProbationCase ---

@bp.route("/chapters/<chapterId>/members/<memberId>/probation-cases", methods=["POST"])
def create_probation_case(chapterId, memberId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    check_frozen(ch)
    data = body()
    require_fields(data, ["opened_by_user_id", "reason_code", "evidence_text"])
    reason = as_str(data["reason_code"], "reason_code")
    if reason not in REASON_CODES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "reason_code must be one of GPA_BELOW_THRESHOLD, "
                       "SERVICE_HOURS_SHORTFALL, CONDUCT_VIOLATION, MISSED_MEETINGS")
    rec = new_record({
        "chapter_id": ch["id"],
        "member_id": m["id"],
        "opened_by_user_id": as_str(data["opened_by_user_id"], "opened_by_user_id"),
        "reason_code": reason,
        "evidence_text": as_str(data["evidence_text"], "evidence_text"),
        "opened_at": now_iso(),
        "status": "OPEN",
        "outcome": None,
        "probation_end_date": None,
        "resolved_by_user_id": None,
    })
    db.probation_cases[rec["id"]] = rec
    recompute_member(m)
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>/members/<memberId>/probation-cases", methods=["GET"])
def list_probation_cases(chapterId, memberId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    items = [c for c in db.probation_cases.values() if c["member_id"] == m["id"]]
    items = apply_filters(items, ["status", "reason_code"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/members/<memberId>/probation-cases/<caseId>", methods=["GET"])
def fetch_probation_case(chapterId, memberId, caseId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    c = get_probation_case(m, caseId)
    return success(serialize(c), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/probation-cases/<caseId>/appeal", methods=["POST"])
def appeal_probation_case(chapterId, memberId, caseId):
    uid, role = auth()
    require_roles(role, ("Member",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    c = get_probation_case(m, caseId)
    check_frozen(ch)
    if c["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN case can be appealed")
    # identity check before the window check (PRD 3.7)
    if uid != c["member_id"]:
        raise ApiError(ERR_MEMBER_MISMATCH, 403,
                       "Caller's X-User-ID must be the id of the member under review")
    opened = parse_dt(c["opened_at"], "opened_at")
    if not now() < opened + timedelta(days=14):
        raise ApiError(ERR_APPEAL_WINDOW_CLOSED, 409,
                       "The 14-day appeal window has closed")
    c["status"] = "APPEALED"
    touch(c)
    return success(serialize(c), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/probation-cases/<caseId>/resolve", methods=["POST"])
def resolve_probation_case(chapterId, memberId, caseId):
    uid, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    c = get_probation_case(m, caseId)
    check_frozen(ch)
    if c["status"] not in ("OPEN", "APPEALED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an OPEN or APPEALED case can be resolved")
    data = body()
    if "outcome" not in data or data["outcome"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "outcome is required")
    outcome = as_str(data["outcome"], "outcome")
    if outcome not in OUTCOMES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "outcome must be STANDARDS_VIOLATION_CONFIRMED or "
                       "STANDARDS_VIOLATION_NOT_CONFIRMED")
    end_date = None
    if outcome == "STANDARDS_VIOLATION_CONFIRMED":
        if "probation_end_date" not in data or data["probation_end_date"] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "probation_end_date is required when the violation is confirmed")
        end_date = parse_dt(data["probation_end_date"], "probation_end_date")
        if not end_date > now():
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "probation_end_date must lie strictly after the current time")
    c["status"] = "RESOLVED"
    c["outcome"] = outcome
    if end_date is not None:
        c["probation_end_date"] = db.iso(end_date)
    elif data.get("probation_end_date") is not None:
        c["probation_end_date"] = db.iso(parse_dt(data["probation_end_date"], "probation_end_date"))
    c["resolved_by_user_id"] = uid
    touch(c)
    if outcome == "STANDARDS_VIOLATION_CONFIRMED":
        if m["status"] == "ACTIVE":
            m["status"] = "ON_PROBATION"
        recompute_member(m)
        if m["probation_strikes"] >= 2 and m["status"] in ("ACTIVE", "ON_PROBATION"):
            # second confirmed strike cascades to dismissal with full side effects
            m["status"] = "DISMISSED"
            cascade_member_dismissal(m)
            recompute_member(m)
    else:
        recompute_member(m)
    recompute_chapter(ch)
    return success(serialize(c), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/probation-cases/<caseId>/dismiss-case", methods=["POST"])
def dismiss_probation_case(chapterId, memberId, caseId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    c = get_probation_case(m, caseId)
    check_frozen(ch)
    if c["status"] not in ("OPEN", "APPEALED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an OPEN or APPEALED case can be dismissed")
    c["status"] = "DISMISSED"
    c["outcome"] = "STANDARDS_VIOLATION_NOT_CONFIRMED"
    touch(c)
    recompute_member(m)
    return success(serialize(c), 200)
