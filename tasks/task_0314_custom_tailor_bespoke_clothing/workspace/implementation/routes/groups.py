"""Group orders (PRD §3.9)."""
from flask import Blueprint, request

import errors
import serializers as S
import validation as V
from db import db, stamp_create, touch
from errors import fail
from lookups import get_group
from middleware import get_user_context, require_role, get_json_body
from response import success, list_response
from services import calculations as calc
from services import orders as osvc

bp = Blueprint("groups", __name__)


@bp.post("/group-orders")
def create_group():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate"})
    body = get_json_body()
    event_name = V.req_str(body, "event_name")
    event_date = V.req_str(body, "event_date")
    rec = stamp_create()
    rec.update({
        "event_name": event_name,
        "event_date": event_date,
        "lead_order_id": None,
        "member_order_count": 0,
        "group_total_cents": 0,
        "status": "FORMING",
    })
    db.group_orders[rec["id"]] = rec
    return success(S.group_order(rec), status=201)


@bp.get("/group-orders/<gid>")
def get_group_route(gid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    g = get_group(gid)
    return success(S.group_order(g))


@bp.get("/group-orders")
def list_groups():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate"})
    limit, offset = V.parse_pagination()
    status = request.args.get("status")
    lead_order_id = request.args.get("lead_order_id")

    def pred(g):
        if status is not None and g["status"] != status:
            return False
        if lead_order_id is not None and g["lead_order_id"] != lead_order_id:
            return False
        return True

    items = [g for g in db.group_orders.values() if pred(g)]
    items.sort(key=lambda g: g["created_at"])
    page = V.paginate(items, limit, offset)
    return list_response([S.group_order(g) for g in page], len(items), limit, offset)


@bp.get("/group-orders/<gid>/orders")
def list_group_orders(gid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    get_group(gid)
    limit, offset = V.parse_pagination()
    items = [o for o in db.garment_orders.values() if o["group_order_id"] == gid]
    items.sort(key=lambda o: o["created_at"])
    page = V.paginate(items, limit, offset)
    return list_response([S.garment_order(o) for o in page], len(items), limit, offset)


@bp.post("/group-orders/<gid>/lock")
def lock_group(gid):
    _, role = get_user_context()
    require_role(role, {"ShopManager"})
    g = get_group(gid)
    body = get_json_body()
    expected_version = V.req_int(body, "expected_group_order_version")

    # state (priority 7): must be FORMING
    if g["status"] != "FORMING":
        fail(errors.ERR_ORDER_INVALID_STATE, "Group is not FORMING")

    members = osvc.group_members(gid)  # non-cancelled
    # member count >= GROUP_MIN_MEMBERS
    if len(members) < calc.GROUP_MIN_MEMBERS:
        fail(errors.ERR_GROUP_TOO_SMALL, "Group does not meet the minimum member count")

    # "Group has draft members" is gated on the members that count toward the
    # locked-in set (the qualifying CONFIRMED+ states). A still-DRAFT member that
    # was attached but never confirmed is simply excluded from the lock — it does
    # not block it (it cannot confirm afterward, since the group is no longer
    # FORMING). This matches the lock/confirm cross-entity contract: the lock
    # freezes over the qualifying members, and the leftover draft is left behind.
    qualifying = osvc.group_total_members(gid)
    if len(qualifying) < calc.GROUP_MIN_MEMBERS:
        fail(errors.ERR_GROUP_HAS_DRAFT_MEMBERS, "Group has too few non-draft members")

    # OCC (priority 17)
    if expected_version != g["version"]:
        fail(errors.ERR_STALE_VERSION, "Group version is stale")

    g["status"] = "LOCKED"
    # recompute group_total over the locked-in member set
    total_members = osvc.group_total_members(gid)
    g["member_order_count"] = len(members)
    g["group_total_cents"] = calc.group_order_total(
        [m["locked_total_cents"] for m in total_members]
    )
    touch(g)
    return success(S.group_order(g))


@bp.post("/group-orders/<gid>/cancel")
def cancel_group(gid):
    _, role = get_user_context()
    require_role(role, {"ShopManager"})
    g = get_group(gid)
    body = get_json_body()
    expected_version = V.req_int(body, "expected_group_order_version")

    # valid from-states: FORMING, LOCKED
    if g["status"] not in ("FORMING", "LOCKED"):
        fail(errors.ERR_ORDER_INVALID_STATE, "Group cannot be cancelled from its current state")

    # OCC (priority 17)
    if expected_version != g["version"]:
        fail(errors.ERR_STALE_VERSION, "Group version is stale")

    g["status"] = "CANCELLED"
    touch(g)

    # cascade-cancel each non-terminal member order (DRAFT/CONFIRMED/IN_FITTING/REMAKE/READY)
    member_orders = [o for o in db.garment_orders.values() if o["group_order_id"] == gid]
    for o in member_orders:
        if o["status"] in ("DRAFT", "CONFIRMED", "IN_FITTING", "REMAKE", "READY"):
            osvc.cancel_order(o)

    return success(S.group_order(g))
