from flask import Blueprint, request

import store as db
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import (new_common, touch, get_or_404, resolve, cash_balance,
                   total_value, clear_model)
from logic2 import run_withdrawal_model, settle_withdrawal
from serialize import withdrawal_out
from validate import (body, no_unknown, req_str, req_int, req_enum, pagination)

bp = Blueprint("withdrawals", __name__)

FUNDING_MODES = {"CASH_FIRST", "PRO_RATA", "TAX_AWARE"}


def _owns(uid, w):
    pf = db.portfolios[w["portfolio_id"]]
    return pf["client_id"] == uid


def _require_active(pf):
    if pf["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_PORTFOLIO_NOT_ACTIVE", 409,
                       "Operation requires an ACTIVE portfolio")


def _exceeds_check(w, pf):
    if w["amount_cents"] > total_value(pf["id"]):
        raise ApiError("ERR_WITHDRAWAL_EXCEEDS_VALUE", 422,
                       "amount_cents exceeds portfolio total value")


@bp.post("/advisory/withdrawal-requests")
def create_withdrawal():
    uid, role = authorize("Advisor", "Client")
    b = body()
    no_unknown(b, {"portfolio_id", "amount_cents", "funding_mode"})
    portfolio_id = req_str(b, "portfolio_id")
    amount = req_int(b, "amount_cents", lo=1)
    mode = req_enum(b, "funding_mode", FUNDING_MODES)
    pf = resolve(db.portfolios, portfolio_id, "portfolio_id")
    if role == "Client" and pf["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Clients may create withdrawals only on their own portfolios")
    w = new_common()
    w.update({
        "portfolio_id": portfolio_id, "amount_cents": amount,
        "funding_mode": mode, "status": "SUBMITTED",
        "modeled_at_dt": None, "modeled_plan": None,
        "modeled_proceeds_cents": None, "modeled_tax_cost_cents": None,
        "modeled_cash_used_cents": None, "post_withdrawal_drift_status": None,
    })
    db.withdrawals[w["id"]] = w
    return obj(withdrawal_out(w), 201)


@bp.get("/advisory/withdrawal-requests")
def list_withdrawals():
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    limit, offset = pagination()
    rows = sorted(db.withdrawals.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    if role == "Client":
        rows = [w for w in rows if _owns(uid, w)]
    pf_id = request.args.get("portfolio_id")
    if pf_id is not None:
        rows = [w for w in rows if w["portfolio_id"] == pf_id]
    status = request.args.get("status")
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    total = len(rows)
    return page([withdrawal_out(w) for w in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/withdrawal-requests/<wid>")
def get_withdrawal(wid):
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    w = get_or_404(db.withdrawals, wid)
    if role == "Client" and not _owns(uid, w):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Clients may read only their own withdrawals")
    return obj(withdrawal_out(w))


@bp.post("/advisory/withdrawal-requests/<wid>/model-impact")
def model_impact(wid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    w = get_or_404(db.withdrawals, wid)
    if w["status"] != "SUBMITTED":
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE", 409,
                       "Modeling requires SUBMITTED")
    pf = db.portfolios[w["portfolio_id"]]
    _require_active(pf)
    if (w["funding_mode"] == "CASH_FIRST"
            and cash_balance(pf["id"]) < w["amount_cents"]):
        raise ApiError("ERR_INSUFFICIENT_CASH", 422,
                       "CASH_FIRST requires cash to cover the full amount")
    _exceeds_check(w, pf)
    run_withdrawal_model(w, pf)
    w["status"] = "MODELED"
    touch(w)
    return obj(withdrawal_out(w))


@bp.post("/advisory/withdrawal-requests/<wid>/approve")
def approve_withdrawal(wid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    w = get_or_404(db.withdrawals, wid)
    if w["status"] != "MODELED":
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE", 409,
                       "Approval requires MODELED")
    pf = db.portfolios[w["portfolio_id"]]
    _require_active(pf)
    _exceeds_check(w, pf)
    w["status"] = "APPROVED"
    touch(w)
    return obj(withdrawal_out(w))


@bp.post("/advisory/withdrawal-requests/<wid>/reject")
def reject_withdrawal(wid):
    authorize("Advisor")
    if request.data:
        b = body()
        no_unknown(b, {"reason"})
        if "reason" in b and b["reason"] is not None and not isinstance(b["reason"], str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "reason must be a string")
    w = get_or_404(db.withdrawals, wid)
    if w["status"] not in ("SUBMITTED", "MODELED"):
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE", 409,
                       "Reject requires SUBMITTED or MODELED")
    if w["status"] == "MODELED":
        clear_model(w)
    w["status"] = "REJECTED"
    touch(w)
    return obj(withdrawal_out(w))


@bp.post("/advisory/withdrawal-requests/<wid>/cancel")
def cancel_withdrawal(wid):
    uid, role = authorize("Client")
    if request.data:
        no_unknown(body(), set())
    w = get_or_404(db.withdrawals, wid)
    if not _owns(uid, w):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Only the owning client may cancel")
    if w["status"] not in ("SUBMITTED", "MODELED"):
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE", 409,
                       "Cancel requires SUBMITTED or MODELED")
    if w["status"] == "MODELED":
        clear_model(w)
    w["status"] = "CANCELLED"
    touch(w)
    return obj(withdrawal_out(w))


@bp.post("/advisory/withdrawal-requests/<wid>/settle")
def settle(wid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    w = get_or_404(db.withdrawals, wid)
    if w["status"] != "APPROVED":
        raise ApiError("ERR_WITHDRAWAL_INVALID_STATE", 409,
                       "Settle requires APPROVED")
    pf = db.portfolios[w["portfolio_id"]]
    _require_active(pf)
    _exceeds_check(w, pf)
    settle_withdrawal(w, pf)   # includes the plan-feasibility gate
    return obj(withdrawal_out(w))
