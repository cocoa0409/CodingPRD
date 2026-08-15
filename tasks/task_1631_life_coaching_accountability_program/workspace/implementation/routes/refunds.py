"""Refund requests and adjudication (PRD §3.9).

Basis and amount are computed once at filing and snapshotted onto the request:
days_elapsed <= 14 (day 14 included) -> COOLING_OFF (paid minus $75.00 per
consumed session); >= 15 -> PRO_RATA (unused-session value from the pinned
price basis, capped at paid, minus the flat $50.00 admin fee, floored at 0).
"""
from flask import Blueprint, request

import calc
from auth import authenticate, require_role, require_ownership, body
from db import store
from engine import (cancel_scheduled_sessions_of_enrollment,
                    remove_enrollment_memberships)
from envelope import success, success_list, paginate
from errors import (ApiError, ERR_INVALID_STATE, ERR_REFUND_NOT_ALLOWED, not_found)
from serializers import refund_request as ser_refund, base_row, touch

bp = Blueprint("refunds", __name__)


def _get_refund(rid):
    r = store.refunds.get(rid)
    if r is None:
        raise not_found("RefundRequest not found")
    return r


@bp.post("/refund-requests")
def create_refund():
    role, uid = authenticate()
    require_role(role, uid, ("Client", "PracticeManager"))
    b = body()
    eid = b.get("enrollment_id")
    e = store.enrollments.get(eid) if isinstance(eid, str) else None
    if e is None:
        raise not_found("enrollment_id does not reference an existing enrollment")
    if role == "Client":
        require_ownership(e["client_id"], uid)
    # Priority 19: refund precondition.
    prior_approved = any(r["enrollment_id"] == eid and r["refund_status"] == "APPROVED"
                         for r in store.refunds.values())
    if (e["lifecycle_status"] not in ("ACTIVE", "PAUSED")
            or e["activated_at"] is None
            or calc.paid_cents(eid) <= 0
            or prior_approved):
        raise ApiError(ERR_REFUND_NOT_ALLOWED, 422,
                       "Refund requires an ACTIVE or PAUSED enrollment with activated_at set, "
                       "paid_cents > 0, and no prior APPROVED refund request")
    basis, amount = calc.refund_quote(e)
    r = base_row()
    r.update({
        "enrollment_id": eid,
        "requested_by_role": role,
        "basis": basis,
        "amount_cents": amount,
        "refund_status": "PENDING",
    })
    store.refunds[r["id"]] = r
    return success(ser_refund(r)), 201


@bp.get("/refund-requests/<rid>")
def get_refund(rid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    return success(ser_refund(_get_refund(rid)))


@bp.get("/refund-requests")
def list_refunds():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    rows = list(store.refunds.values())
    for param in ("enrollment_id", "refund_status"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if r[param] == v]
    rows.sort(key=lambda r: (r["created_at"], r["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_refund(r) for r in page], meta)


@bp.post("/refund-requests/<rid>/approve")
def approve_refund(rid):
    """Approve a PENDING request: enrollment -> REFUNDED, refunded_cents
    recomputes, SCHEDULED sessions cancel, memberships -> REMOVED with waitlist
    promotion on each affected cohort (PRD §3.9)."""
    role, uid = authenticate()
    require_role(role, uid, ("PracticeManager",))
    r = _get_refund(rid)
    e = store.enrollments.get(r["enrollment_id"])
    if r["refund_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PENDING refund request can be approved")
    if e is None or e["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Approval requires the enrollment to be ACTIVE or PAUSED")
    r["refund_status"] = "APPROVED"
    touch(r)
    e["lifecycle_status"] = "REFUNDED"
    touch(e)
    cancel_scheduled_sessions_of_enrollment(e["id"])
    remove_enrollment_memberships(e["id"])
    return success(ser_refund(r))


@bp.post("/refund-requests/<rid>/deny")
def deny_refund(rid):
    role, uid = authenticate()
    require_role(role, uid, ("PracticeManager",))
    r = _get_refund(rid)
    if r["refund_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PENDING refund request can be denied")
    r["refund_status"] = "DENIED"
    touch(r)
    return success(ser_refund(r))
