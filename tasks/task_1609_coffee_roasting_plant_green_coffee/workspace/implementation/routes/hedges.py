"""Futures hedges: place, approve (SoD), lift, cancel (PRD §3.3)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_OVER_HEDGE,
    ERR_SEGREGATION_OF_DUTIES, err,
)
from middleware import (
    COMMON_SYS, D, base_fields, check_unknown_fields, get_json_body,
    is_number, paginate, pub, q5, require_fields, require_role, sort_created,
    touch, v_enum, v_int, v_num,
)
from response import success_list, success_object
from services import hedge_realized_pnl, recompute_counterparty_exposure

bp = Blueprint("hedges", __name__)

HEDGE_ALLOWED = {
    "contract_id", "hedge_side", "hedge_lbs", "entry_price_usd_per_lb",
    "exit_price_usd_per_lb", "realized_pnl_usd", "hedge_status",
    "approved_by_risk_id",
} | COMMON_SYS

LIFT_ALLOWED = {"exit_price_usd_per_lb"} | COMMON_SYS | {
    "realized_pnl_usd", "hedge_status", "approved_by_risk_id", "contract_id",
    "hedge_side", "hedge_lbs", "entry_price_usd_per_lb"}

READ_ROLES = ("Trader", "RiskManager")


def get_hedge_or_404(hedge_id):
    h = DB.futures_hedges.get(hedge_id)
    if h is None:
        raise err(ERR_NOT_FOUND, "Futures hedge id does not exist")
    return h


def _recompute_parent_exposure(hedge):
    contract = DB.contracts.get(hedge["contract_id"])
    if contract is not None:
        cp = DB.counterparties.get(contract["counterparty_id"])
        if cp is not None:
            recompute_counterparty_exposure(cp)


@bp.post("/roastery/contracts/<contract_id>/futures-hedges")
def create_hedge(contract_id):
    user_id, _ = require_role("Trader")
    contract = DB.contracts.get(contract_id)
    if contract is None:
        raise err(ERR_NOT_FOUND, "Contract id does not exist")
    body = get_json_body()
    check_unknown_fields(body, HEDGE_ALLOWED)
    require_fields(body, ["hedge_side", "hedge_lbs", "entry_price_usd_per_lb"])
    side = v_enum(body, "hedge_side", {"BUY_FUTURES", "SELL_FUTURES"})
    lbs = v_int(body, "hedge_lbs", gt=0)
    entry = v_num(body, "entry_price_usd_per_lb", gt=0)
    h = base_fields()
    h.update({
        "contract_id": contract_id,
        "hedge_side": side,
        "hedge_lbs": lbs,
        "entry_price_usd_per_lb": q5(entry),
        "exit_price_usd_per_lb": None,
        "realized_pnl_usd": None,
        "hedge_status": "WORKING",
        "approved_by_risk_id": None,
        "_submitted_by": user_id,
    })
    DB.futures_hedges[h["id"]] = h
    return success_object(pub(h), status=201)


@bp.get("/roastery/futures-hedges/<hedge_id>")
def get_hedge(hedge_id):
    require_role(*READ_ROLES)
    return success_object(pub(get_hedge_or_404(hedge_id)))


@bp.get("/roastery/contracts/<contract_id>/futures-hedges")
def list_hedges(contract_id):
    require_role(*READ_ROLES)
    if contract_id not in DB.contracts:
        raise err(ERR_NOT_FOUND, "Contract id does not exist")
    items = sort_created(
        [h for h in DB.futures_hedges.values() if h["contract_id"] == contract_id])
    status = request.args.get("hedge_status")
    if status is not None:
        items = [h for h in items if h["hedge_status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([pub(h) for h in page], limit, offset, total)


@bp.post("/roastery/futures-hedges/<hedge_id>/approve")
def approve_hedge(hedge_id):
    user_id, _ = require_role("RiskManager")
    h = get_hedge_or_404(hedge_id)
    get_json_body()
    if h["hedge_status"] != "WORKING":
        raise err(ERR_INVALID_STATE, "Approve requires hedge_status WORKING")

    # Priority 8: segregation of duties — approver != submitting trader.
    if user_id == h.get("_submitted_by"):
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "The approving RiskManager must differ from the submitting Trader")

    # Priority 25: over-hedge cap against unpriced_lbs at approval time.
    contract = DB.contracts.get(h["contract_id"])
    if contract is not None:
        approved_lbs = sum(
            other["hedge_lbs"] for other in DB.futures_hedges.values()
            if other["contract_id"] == contract["id"]
            and other["hedge_status"] == "APPROVED"
        )
        if approved_lbs + h["hedge_lbs"] > contract["unpriced_lbs"]:
            raise err(ERR_OVER_HEDGE,
                      "Cumulative APPROVED hedge_lbs would exceed contract unpriced_lbs")

    h["hedge_status"] = "APPROVED"
    h["approved_by_risk_id"] = user_id
    touch(h)
    _recompute_parent_exposure(h)
    return success_object(pub(h))


@bp.post("/roastery/futures-hedges/<hedge_id>/lift")
def lift_hedge(hedge_id):
    require_role("Trader")
    h = get_hedge_or_404(hedge_id)
    body = get_json_body()
    if h["hedge_status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Lift requires hedge_status APPROVED")
    check_unknown_fields(body, LIFT_ALLOWED)
    require_fields(body, ["exit_price_usd_per_lb"])
    exit_raw = body.get("exit_price_usd_per_lb")
    if not is_number(exit_raw):
        raise err(ERR_INVALID_REQUEST, "exit_price_usd_per_lb must be a number")
    # Transition precondition: exit price strictly positive.
    if not (exit_raw > 0):
        raise err(ERR_INVALID_STATE, "exit_price_usd_per_lb must be strictly positive")
    h["exit_price_usd_per_lb"] = q5(exit_raw)
    h["realized_pnl_usd"] = hedge_realized_pnl(h)
    h["hedge_status"] = "LIFTED"
    touch(h)
    _recompute_parent_exposure(h)
    return success_object(pub(h))


@bp.post("/roastery/futures-hedges/<hedge_id>/cancel")
def cancel_hedge(hedge_id):
    require_role("Trader")
    h = get_hedge_or_404(hedge_id)
    get_json_body()
    if h["hedge_status"] != "WORKING":
        raise err(ERR_INVALID_STATE, "Only WORKING hedges may be cancelled")
    h["hedge_status"] = "CANCELLED"
    touch(h)
    return success_object(pub(h))
