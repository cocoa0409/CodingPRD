"""Holdings: retrieve, list, allocations, DRIP toggle (PRD §3.5)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services import domain, serialize
from services.paginate import get_pagination, order_and_page
from services import validate as V

bp = Blueprint("holdings", __name__)

READ_ROLES = {"FundManager", "ComplianceOfficer", "Operator", "Investor"}


@bp.get("/holdings/<hid>")
def get_holding(hid):
    require_role(READ_ROLES)
    e = domain.get_holding(hid)
    return success(serialize.holding(e))


@bp.get("/holdings")
def list_holdings():
    require_role(READ_ROLES)
    limit, offset = get_pagination()
    items = list(db.holdings.values())
    inv = request.args.get("investor_id")
    sc = request.args.get("share_class_id")
    if inv is not None:
        items = [h for h in items if h["investor_id"] == inv]
    if sc is not None:
        items = [h for h in items if h["share_class_id"] == sc]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.holding(h) for h in page], limit, offset, total)


@bp.get("/holdings/<hid>/allocations")
def list_holding_allocations(hid):
    require_role(READ_ROLES)
    domain.get_holding(hid)
    limit, offset = get_pagination()
    items = [a for a in db.allocations.values() if a["holding_id"] == hid]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.allocation(a) for a in page], limit, offset, total)


@bp.patch("/holdings/<hid>")
def patch_holding(hid):
    user_id, _ = require_role({"Investor"})
    holding = domain.get_holding(hid)
    # Ownership (priority 3): investor must own the holding
    if holding["investor_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this holding")
    body = V.get_body()
    drip = V.req_bool(body, "drip_elected")
    holding["drip_elected"] = drip
    db.touch(holding)
    return success(serialize.holding(holding))
