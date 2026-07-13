from flask import Blueprint, request

import store
from auth import authenticate, require_role
from util import ApiError, object_response, array_response, paginate, apply_list, serialize
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("connections", __name__)

HAZARD_CLASSES = {"HIGH_HAZARD", "LOW_HAZARD"}
POSTURES = {"COMPLIANT", "AT_RISK", "NON_COMPLIANT", "SHUTOFF"}


@bp.post("/service-connections")
def create_connection():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    body = v.json_object()
    account = v.req_nonempty_str(body, "account_number")
    # duplicate before full validation (ladder: duplicate 13 < validation 14)
    if any(c["account_number"] == account for c in store.connections.values()):
        raise ApiError("ERR_DUPLICATE_VALUE", 409, "account_number already exists")
    address = v.req_str(body, "address")
    owner_user_id = v.req_nonempty_str(body, "owner_user_id")
    hazard_class = v.req_enum(body, "hazard_class", HAZARD_CLASSES)

    conn = {
        "account_number": account,
        "address": address,
        "owner_user_id": owner_user_id,
        "hazard_class": hazard_class,
        "compliance_posture": "COMPLIANT",
        "risk_tier": "LOW",
        "water_service_active": True,
        "protected_device_count": 0,
        "overdue_device_count": 0,
        "open_notice_count": 0,
        "total_penalty_cents": 0,
    }
    svc.stamp_new(conn)
    store.connections[conn["id"]] = conn
    return object_response(serialize(conn), 201)


@bp.get("/service-connections")
def list_connections():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    limit, offset = paginate(request.args)

    owner_filter = request.args.get("owner_user_id")
    posture_filter = request.args.get("compliance_posture")
    hazard_filter = request.args.get("hazard_class")

    pool = list(store.connections.values())
    if role == "PremisesOwner":
        pool = [c for c in pool if c["owner_user_id"] == user_id]
    elif owner_filter is not None:
        pool = [c for c in pool if c["owner_user_id"] == owner_filter]

    for c in pool:
        svc.read_recompute(c)

    if posture_filter is not None:
        pool = [c for c in pool if c["compliance_posture"] == posture_filter]
    if hazard_filter is not None:
        pool = [c for c in pool if c["hazard_class"] == hazard_filter]

    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/service-connections/<cid>")
def get_connection(cid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    conn = lk.get_connection(cid)
    lk.ensure_owner_conn(conn, role, user_id)
    svc.read_recompute(conn)
    return object_response(serialize(conn))


@bp.post("/service-connections/<cid>/restore")
def restore_connection(cid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    conn = lk.get_connection(cid)
    svc.read_recompute(conn)
    if conn["compliance_posture"] != "SHUTOFF":
        raise ApiError("ERR_NOT_SHUTOFF", 409, "connection is not in SHUTOFF")
    # cure requirements
    if (conn["overdue_device_count"] != 0 or svc.has_needs_repair_device(conn)
            or conn["open_notice_count"] != 0):
        raise ApiError("ERR_NOT_SHUTOFF", 409, "connection has not fully cured")

    before = svc.begin(conn)
    conn["water_service_active"] = True
    svc.finish(conn, before)
    return object_response(serialize(conn))
