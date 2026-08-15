from flask import Blueprint, request

import store as db
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import new_common, get_or_404, resolve, refresh_portfolio
from serialize import position_out
from validate import body, no_unknown, req_str, req_int, pagination

bp = Blueprint("positions", __name__)


@bp.post("/advisory/positions")
def create_position():
    """Transfer-in. Restricted list does NOT block transfer-ins."""
    authorize("Advisor")
    b = body()
    no_unknown(b, {"portfolio_id", "security_id", "quantity",
                   "opening_cost_basis_cents"})
    portfolio_id = req_str(b, "portfolio_id")
    security_id = req_str(b, "security_id")
    quantity = req_int(b, "quantity", lo=1)
    basis = req_int(b, "opening_cost_basis_cents", lo=0)
    pf = resolve(db.portfolios, portfolio_id, "portfolio_id")
    sec = resolve(db.securities, security_id, "security_id")
    if pf["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_PORTFOLIO_NOT_ACTIVE", 409,
                       "Position intake requires an ACTIVE portfolio")
    if sec["trading_status"] != "LISTED":
        raise ApiError("ERR_SECURITY_NOT_TRADEABLE", 422,
                       "Security must be LISTED for transfer-in")
    for p in db.positions.values():
        if p["portfolio_id"] == portfolio_id and p["security_id"] == security_id:
            raise ApiError("ERR_POSITION_EXISTS", 422,
                           "(portfolio_id, security_id) pair already held")
    p = new_common()
    p.update({"portfolio_id": portfolio_id, "security_id": security_id,
              "quantity": quantity, "cost_basis_cents": basis})
    db.positions[p["id"]] = p
    refresh_portfolio(pf, revert=True)
    return obj(position_out(p), 201)


def _scope(rows, uid, role):
    if role == "Client":
        rows = [p for p in rows
                if db.portfolios[p["portfolio_id"]]["client_id"] == uid]
    return rows


@bp.get("/advisory/positions")
def list_positions():
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    limit, offset = pagination()
    rows = sorted(db.positions.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    rows = _scope(rows, uid, role)
    pf_id = request.args.get("portfolio_id")
    if pf_id is not None:
        rows = [p for p in rows if p["portfolio_id"] == pf_id]
    sec_id = request.args.get("security_id")
    if sec_id is not None:
        rows = [p for p in rows if p["security_id"] == sec_id]
    total = len(rows)
    return page([position_out(p) for p in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/positions/<pid>")
def get_position(pid):
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    p = get_or_404(db.positions, pid)
    if role == "Client" and db.portfolios[p["portfolio_id"]]["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Clients may read only their own positions")
    return obj(position_out(p))
