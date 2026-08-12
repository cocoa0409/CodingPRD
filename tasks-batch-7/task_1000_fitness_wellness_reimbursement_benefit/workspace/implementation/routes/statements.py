"""Statement endpoints (calc_statement_totals provisional/final variants)."""
from flask import Blueprint, request, g

from db import STORE
from errors import (err, ERR_STATEMENT_NOT_FOUND, ERR_MEMBER_NOT_FOUND,
                    ERR_MEMBER_TERMINATED, ERR_STATEMENT_NOT_OPEN,
                    ERR_STATEMENT_NOT_FINALIZED, ERR_STATEMENT_LOCKED)
from middleware import require_roles, is_member, member_owns
from response import success, paginate
from services.core import new_entity, touch, serialize, sort_created
from util import body_json, req, as_str, month_range

bp = Blueprint("statements", __name__)

READ_ROLES = ("BenefitsAdmin", "Auditor", "Member")


def get_statement(sid):
    s = STORE.statements.get(sid)
    if s is None:
        raise err(ERR_STATEMENT_NOT_FOUND, 404, "statement id does not resolve")
    return s


def _period_claims(member_id, yyyymm):
    start, nxt = month_range(yyyymm)
    return [c for c in STORE.claims.values()
            if c["member_id"] == member_id and start <= c["_service_dt"] < nxt], (start, nxt)


def provisional_total(member_id, yyyymm):
    claims, (start, nxt) = _period_claims(member_id, yyyymm)
    total = 0
    for c in claims:
        rs, ps = c["review_status"], c["payment_status"]
        if rs in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            total += c["claimed_amount_cents"]
        elif rs == "APPROVED" and ps == "UNPAID":
            total += c["approved_amount_cents"] or 0
        elif ps == "PAID":
            total += c["approved_amount_cents"] or 0
        elif ps == "CLAWED_BACK":
            paid = c["_paid_at"]
            if paid is not None and start <= paid < nxt:
                total -= c["approved_amount_cents"] or 0
    return total, len(claims)


def finalized_total(member_id, yyyymm):
    claims, (start, nxt) = _period_claims(member_id, yyyymm)
    total = 0
    for c in claims:
        paid = c["_paid_at"]
        if paid is None or not (start <= paid < nxt):
            continue
        if c["payment_status"] == "PAID":
            total += c["approved_amount_cents"] or 0
        elif c["payment_status"] == "CLAWED_BACK":
            total -= c["approved_amount_cents"] or 0
    return total


@bp.post("/api/statements")
def create_statement():
    require_roles("BenefitsAdmin")
    body = body_json()
    member_id = as_str(req(body, "member_id"), "member_id")
    period = as_str(req(body, "period_yyyymm"), "period_yyyymm")
    month_range(period)  # validates format -> ERR_INVALID_REQUEST
    m = STORE.members.get(member_id)
    if m is None:
        raise err(ERR_MEMBER_NOT_FOUND, 404, "member id does not resolve")
    if m["eligibility_status"] == "TERMINATED":
        raise err(ERR_MEMBER_TERMINATED, 409, "member TERMINATED")
    total, count = provisional_total(member_id, period)
    s = new_entity()
    s.update({
        "member_id": member_id,
        "period_yyyymm": period,
        "status": "OPEN",
        "provisional_total_cents": total,
        "finalized_total_cents": None,
        "claim_count": count,
    })
    STORE.statements[s["id"]] = s
    return success(serialize(s), 201)


@bp.get("/api/statements/<sid>")
def read_statement(sid):
    require_roles(*READ_ROLES)
    s = get_statement(sid)
    member_owns(s["member_id"])
    return success(serialize(s))


@bp.get("/api/statements")
def list_statements():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.statements.values())
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if is_member():
        if member_id is not None and member_id != g.user_id:
            member_owns(member_id)
        items = [s for s in items if s["member_id"] == g.user_id]
    elif member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate([serialize(s) for s in items])


@bp.post("/api/statements/<sid>/finalize")
def finalize_statement(sid):
    require_roles("BenefitsAdmin")
    s = get_statement(sid)
    if s["status"] == "DELIVERED":
        raise err(ERR_STATEMENT_LOCKED, 409, "DELIVERED statement accepts no further transitions")
    if s["status"] != "OPEN":
        raise err(ERR_STATEMENT_NOT_OPEN, 409, "finalize requires statement OPEN")
    s["finalized_total_cents"] = finalized_total(s["member_id"], s["period_yyyymm"])
    s["status"] = "FINALIZED"
    touch(s)
    return success(serialize(s))


@bp.post("/api/statements/<sid>/reopen")
def reopen_statement(sid):
    require_roles("BenefitsAdmin")
    s = get_statement(sid)
    if s["status"] == "DELIVERED":
        raise err(ERR_STATEMENT_LOCKED, 409, "DELIVERED statement accepts no further transitions")
    if s["status"] != "FINALIZED":
        raise err(ERR_STATEMENT_NOT_FINALIZED, 409, "reopen requires statement FINALIZED")
    s["finalized_total_cents"] = None
    total, count = provisional_total(s["member_id"], s["period_yyyymm"])
    s["provisional_total_cents"] = total
    s["claim_count"] = count
    s["status"] = "OPEN"
    touch(s)
    return success(serialize(s))


@bp.post("/api/statements/<sid>/deliver")
def deliver_statement(sid):
    require_roles("BenefitsAdmin")
    s = get_statement(sid)
    if s["status"] == "DELIVERED":
        raise err(ERR_STATEMENT_LOCKED, 409, "DELIVERED statement accepts no further transitions")
    if s["status"] != "FINALIZED":
        raise err(ERR_STATEMENT_NOT_FINALIZED, 409, "deliver requires statement FINALIZED")
    s["status"] = "DELIVERED"
    touch(s)
    return success(serialize(s))
