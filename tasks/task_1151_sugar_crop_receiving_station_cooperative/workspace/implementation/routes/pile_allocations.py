from flask import Blueprint, request as _req

import db
import response
import serializers
from errors import raise_err
from middleware import check_member_ownership, require_roles
from routes._common import pagination_args, sorted_page

bp = Blueprint("pile_allocations", __name__)


@bp.get("/api/pile-allocations/<allocation_id>")
def get_allocation(allocation_id):
    user_id, role = require_roles(["COOP_ADMIN", "STATION_OPERATOR", "POOL_ACCOUNTANT", "MEMBER"])
    a = db.pile_allocations.get(allocation_id)
    if not a:
        raise_err("ERR_NOT_FOUND", "Pile allocation not found")
    check_member_ownership(user_id, role, a["member_id"])
    return response.success(serializers.pile_allocation(a), 200)


@bp.get("/api/pile-allocations")
def list_allocations():
    user_id, role = require_roles(["COOP_ADMIN", "STATION_OPERATOR", "POOL_ACCOUNTANT", "MEMBER"])
    ticket_id = _req.args.get("ticket_id")
    pile_id = _req.args.get("pile_id")
    member_id = _req.args.get("member_id")
    limit, offset = pagination_args()
    if role == "MEMBER":
        member_id = user_id
    items = list(db.pile_allocations.values())
    if ticket_id is not None:
        items = [a for a in items if a["ticket_id"] == ticket_id]
    if pile_id is not None:
        items = [a for a in items if a["pile_id"] == pile_id]
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    page, total = sorted_page(items, limit, offset)
    return response.success_list([serializers.pile_allocation(a) for a in page], total, limit, offset, 200)
