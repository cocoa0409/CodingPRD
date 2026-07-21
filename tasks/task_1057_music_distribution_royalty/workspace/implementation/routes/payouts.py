"""Payout approval, payment and reversal — PRD §3.9."""

from flask import Blueprint, request

from db import db, days, now, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import ok, ok_list, paginate, read_pagination
from services import calc, core
import validation as v

bp = Blueprint("payouts", __name__)


def owned_payout(user_id, role, payout_id):
    payout = db.payouts.get(payout_id)
    if payout is not None:
        if role == "Collaborator":
            require_ownership(user_id == payout["collaborator_id"])
        elif role == "Artist":
            require_ownership(user_id == core.artist_of_payout(payout))
    return core.find_payout(payout_id)


@bp.get("/api/payouts/<payout_id>")
def read_payout(payout_id):
    user_id, role = auth("FinanceOps", "Collaborator", "Artist", "PlatformAdmin")
    return ok(owned_payout(user_id, role, payout_id))


@bp.get("/api/payouts")
def list_payouts():
    user_id, role = auth("FinanceOps", "Collaborator", "Artist", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.payouts.values())
    if role == "Collaborator":
        rows = [p for p in rows if p["collaborator_id"] == user_id]
    elif role == "Artist":
        rows = [p for p in rows if core.artist_of_payout(p) == user_id]
    collaborator_id = request.args.get("collaborator_id")
    if collaborator_id is not None:
        rows = [p for p in rows if p["collaborator_id"] == collaborator_id]
    statement_id = request.args.get("royalty_statement_id")
    if statement_id is not None:
        rows = [p for p in rows if p["royalty_statement_id"] == statement_id]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/api/payouts/<payout_id>/approve")
def approve_payout(payout_id):
    user_id, _role = auth("FinanceOps")
    payout = core.find_payout(payout_id)
    if payout["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    payout["status"] = "APPROVED"
    payout["approved_by_user_id"] = user_id
    payout["auto_approved"] = False
    touch(payout)
    return ok(payout)


@bp.post("/api/payouts/<payout_id>/pay")
def pay_payout(payout_id):
    user_id, _role = auth("FinanceOps")
    payout = core.find_payout(payout_id)
    if payout["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    if payout["approved_by_user_id"] is not None and payout["approved_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    collaborator = db.collaborators.get(payout["collaborator_id"])
    if collaborator is None or collaborator["tax_form_status"] != "VERIFIED":
        raise ApiError("ERR_TAX_FORM_NOT_VERIFIED")
    if payout["net_cents"] < core.PAYOUT_THRESHOLD_CENTS:
        raise ApiError("ERR_PAYOUT_BELOW_THRESHOLD")

    payout["status"] = "PAID"
    payout["paid_at"] = now()
    payout["paid_by_user_id"] = user_id
    touch(payout)
    calc.recompute_collaborator_totals(collaborator)
    return ok(payout)


@bp.post("/api/payouts/<payout_id>/reverse")
def reverse_payout(payout_id):
    auth("FinanceOps")
    data = v.body()
    reason_code = v.req_string(data, "reason_code")

    payout = core.find_payout(payout_id)
    if payout["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE")
    if now() >= payout["paid_at"] + days(core.PAYOUT_REVERSAL_WINDOW_DAYS):
        raise ApiError("ERR_REVERSAL_WINDOW_EXPIRED")

    payout["status"] = "REVERSED"
    payout["reversal_reason_code"] = reason_code
    touch(payout)
    collaborator = db.collaborators.get(payout["collaborator_id"])
    if collaborator is not None:
        calc.recompute_collaborator_totals(collaborator)
    return ok(payout)
