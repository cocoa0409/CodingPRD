from flask import Blueprint, request

import store as db
import logical_clock as clock
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import (new_common, touch, get_or_404, resolve, compute_drift,
                   refresh_portfolio, append_event, cash_balance, total_value,
                   active_ips_of_client, OPEN_PROPOSAL_STATES,
                   OPEN_WITHDRAWAL_STATES)
from serialize import portfolio_out, event_out
from validate import (body, no_unknown, req_str, req_int, req_enum, req_dt,
                      pagination)

bp = Blueprint("portfolios", __name__)

TAX_STATUSES = {"TAXABLE", "TAX_DEFERRED", "TAX_EXEMPT"}


def _client_owns(uid, pf):
    if pf["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Clients may access only their own portfolios")


@bp.post("/advisory/portfolios")
def create_portfolio():
    authorize("Advisor")
    b = body()
    no_unknown(b, {"client_id", "name", "tax_status"})
    client_id = req_str(b, "client_id")
    name = req_str(b, "name")
    tax_status = req_enum(b, "tax_status", TAX_STATUSES)
    resolve(db.clients, client_id, "client_id")
    pf = new_common()
    pf.update({
        "client_id": client_id, "name": name, "tax_status": tax_status,
        "lifecycle_status": "OPEN", "drift_status": "UNTRACKED",
        "lifetime_realized_gains_cents": 0,
    })
    # drift_status derived at creation too: WITHIN_BANDS if client has an
    # ACTIVE IPS (total is zero); UNTRACKED otherwise.
    pf["drift_status"] = compute_drift(pf)
    db.portfolios[pf["id"]] = pf
    return obj(portfolio_out(pf), 201)


@bp.get("/advisory/portfolios")
def list_portfolios():
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    limit, offset = pagination()
    rows = sorted(db.portfolios.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    if role == "Client":
        rows = [p for p in rows if p["client_id"] == uid]
    client_id = request.args.get("client_id")
    if client_id is not None:
        rows = [p for p in rows if p["client_id"] == client_id]
    ls = request.args.get("lifecycle_status")
    if ls is not None:
        rows = [p for p in rows if p["lifecycle_status"] == ls]
    ds = request.args.get("drift_status")
    if ds is not None:
        rows = [p for p in rows if p["drift_status"] == ds]
    total = len(rows)
    return page([portfolio_out(p) for p in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/portfolios/<pid>")
def get_portfolio(pid):
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    pf = get_or_404(db.portfolios, pid)
    if role == "Client":
        _client_owns(uid, pf)
    return obj(portfolio_out(pf))


@bp.post("/advisory/portfolios/<pid>/activate")
def activate_portfolio(pid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    pf = get_or_404(db.portfolios, pid)
    if pf["lifecycle_status"] != "OPEN":
        raise ApiError("ERR_PORTFOLIO_INVALID_STATE", 409,
                       "Portfolio activation requires OPEN")
    client = db.clients[pf["client_id"]]
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_INVALID_STATE", 409, "Client must be ACTIVE")
    if active_ips_of_client(pf["client_id"]) is None:
        raise ApiError("ERR_NO_ACTIVE_IPS", 409,
                       "Client must hold an ACTIVE IPS")
    pf["lifecycle_status"] = "ACTIVE"
    pf["drift_status"] = compute_drift(pf)
    touch(pf)
    return obj(portfolio_out(pf))


@bp.post("/advisory/portfolios/<pid>/freeze")
def freeze_portfolio(pid):
    authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), set())
    pf = get_or_404(db.portfolios, pid)
    if pf["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_PORTFOLIO_INVALID_STATE", 409,
                       "Freeze requires ACTIVE")
    pf["lifecycle_status"] = "FROZEN"
    touch(pf)
    return obj(portfolio_out(pf))


@bp.post("/advisory/portfolios/<pid>/unfreeze")
def unfreeze_portfolio(pid):
    authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), set())
    pf = get_or_404(db.portfolios, pid)
    if pf["lifecycle_status"] != "FROZEN":
        raise ApiError("ERR_PORTFOLIO_INVALID_STATE", 409,
                       "Unfreeze requires FROZEN")
    pf["lifecycle_status"] = "ACTIVE"
    touch(pf)
    return obj(portfolio_out(pf))


@bp.post("/advisory/portfolios/<pid>/close")
def close_portfolio(pid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    pf = get_or_404(db.portfolios, pid)
    if pf["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_PORTFOLIO_INVALID_STATE", 409,
                       "Close requires ACTIVE")
    has_holdings = any(p["portfolio_id"] == pid and p["quantity"] > 0
                       for p in db.positions.values())
    if has_holdings or cash_balance(pid) != 0:
        raise ApiError("ERR_PORTFOLIO_NOT_EMPTY", 422,
                       "Close requires zero holdings and zero cash")
    for w in db.withdrawals.values():
        if w["portfolio_id"] == pid and w["status"] in OPEN_WITHDRAWAL_STATES:
            raise ApiError("ERR_OPEN_WORK_ITEMS", 422,
                           "Open withdrawal requests block closure")
    for prop in db.proposals.values():
        if (prop["portfolio_id"] == pid
                and prop["status"] in ("PROPOSED", "NEEDS_REVISION", "APPROVED")):
            raise ApiError("ERR_OPEN_WORK_ITEMS", 422,
                           "Open rebalance proposals block closure")
    pf["lifecycle_status"] = "CLOSED"
    pf["drift_status"] = "WITHIN_BANDS"   # vacuous: total == 0
    touch(pf)
    return obj(portfolio_out(pf))


@bp.post("/advisory/portfolios/<pid>/cash-movements")
def cash_movement(pid):
    authorize("Advisor")
    b = body()
    no_unknown(b, {"direction", "amount_cents", "occurred_at"})
    direction = req_enum(b, "direction", {"DEPOSIT", "WITHDRAWAL"})
    amount = req_int(b, "amount_cents", lo=1)
    occurred = req_dt(b, "occurred_at")
    pf = get_or_404(db.portfolios, pid)
    if pf["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_PORTFOLIO_NOT_ACTIVE", 409,
                       "Cash movements require an ACTIVE portfolio")
    if occurred > clock.now():
        raise ApiError("ERR_EVENT_IN_FUTURE", 422,
                       "occurred_at may not be future-dated")
    if direction == "DEPOSIT":
        kind, signed = "MANUAL_DEPOSIT", amount
    else:
        if amount > cash_balance(pid):
            raise ApiError("ERR_INSUFFICIENT_CASH", 422,
                           "Withdrawal exceeds current cash balance")
        kind, signed = "MANUAL_WITHDRAWAL", -amount
    ev = append_event(pf, kind, signed, occurred, "MANUAL", None)
    refresh_portfolio(pf, revert=True)
    return obj(event_out(ev), 201)
