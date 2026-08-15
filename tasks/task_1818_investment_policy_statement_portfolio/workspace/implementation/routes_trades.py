from flask import Blueprint, request

import store as db
import logical_clock as clock
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import get_or_404, is_restricted
from logic2 import void_trade
from serialize import trade_out
from validate import pagination, body, no_unknown

bp = Blueprint("trades", __name__)


@bp.get("/advisory/trade-instructions")
def list_trades():
    authorize("Advisor", "ComplianceOfficer")
    limit, offset = pagination()
    rows = sorted(db.trades.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    prop_id = request.args.get("proposal_id")
    if prop_id is not None:
        rows = [t for t in rows if t["proposal_id"] == prop_id]
    sec_id = request.args.get("security_id")
    if sec_id is not None:
        rows = [t for t in rows if t["security_id"] == sec_id]
    status = request.args.get("status")
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    total = len(rows)
    return page([trade_out(t) for t in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/trade-instructions/<tid>")
def get_trade(tid):
    authorize("Advisor", "ComplianceOfficer")
    t = get_or_404(db.trades, tid)
    return obj(trade_out(t))


@bp.post("/advisory/trade-instructions/<tid>/release")
def release_trade(tid):
    authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), set())
    t = get_or_404(db.trades, tid)
    # PRD §3.5 release battery order: BLOCKED -> restriction -> LISTED -> APPROVED.
    if t["status"] != "BLOCKED":
        raise ApiError("ERR_TRADE_INVALID_STATE", 409,
                       "Release requires BLOCKED")
    if is_restricted(t["security_id"], t["side"]):
        raise ApiError("ERR_SECURITY_RESTRICTED", 422,
                       "An ACTIVE restriction blocks this trade's side")
    if db.securities[t["security_id"]]["trading_status"] != "LISTED":
        raise ApiError("ERR_SECURITY_NOT_TRADEABLE", 422,
                       "Security is not LISTED")
    prop = db.proposals[t["proposal_id"]]
    if prop["status"] != "APPROVED":
        raise ApiError("ERR_PROPOSAL_INVALID_STATE", 409,
                       "Release requires the proposal to be APPROVED")
    t["status"] = "PENDING"
    from logic import touch
    touch(t)
    return obj(trade_out(t))


@bp.post("/advisory/trade-instructions/<tid>/void")
def void(tid):
    authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), set())
    t = get_or_404(db.trades, tid)
    if t["status"] != "EXECUTED":
        raise ApiError("ERR_TRADE_INVALID_STATE", 409,
                       "Void requires EXECUTED")
    if t["executed_at_dt"].date() != clock.now().date():
        raise ApiError("ERR_TRADE_VOID_WINDOW_EXPIRED", 422,
                       "Void is allowed only on the UTC date of execution")
    void_trade(t)
    return obj(trade_out(t))
