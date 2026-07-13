from flask import Blueprint, request

import store
from auth import authenticate, require_role
from util import ApiError, object_response, array_response, paginate, apply_list, serialize
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("notices", __name__)

REASONS = {"OVERDUE_TEST", "FAILED_TEST", "UNREPAIRED_DEVICE"}


@bp.post("/shutoff-notices")
def issue_notice():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    body = v.json_object()

    raw_scid = body.get("service_connection_id")
    conn = lk.get_connection(raw_scid) if isinstance(raw_scid, str) and raw_scid else None

    scid = v.req_nonempty_str(body, "service_connection_id")
    reason = v.req_enum(body, "reason", REASONS)
    if conn is None:
        conn = lk.get_connection(scid)

    before = svc.begin(conn)
    notice = svc.create_notice(conn, reason)
    svc.finish(conn, before)
    return object_response(serialize(notice), 201)


@bp.get("/shutoff-notices")
def list_notices():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    limit, offset = paginate(request.args)

    scid = request.args.get("service_connection_id")
    status = request.args.get("status")

    pool = list(store.notices.values())
    if scid is not None:
        pool = [n for n in pool if n["service_connection_id"] == scid]
    if status is not None:
        pool = [n for n in pool if n["status"] == status]
    if role == "PremisesOwner":
        pool = [n for n in pool
                if lk.owns_connection(store.connections.get(n["service_connection_id"]), user_id)]

    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/shutoff-notices/<nid>")
def get_notice(nid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    notice = lk.get_notice(nid)
    if role == "PremisesOwner":
        lk.ensure_owner_conn(store.connections.get(notice["service_connection_id"]), role, user_id)
    return object_response(serialize(notice))


@bp.post("/shutoff-notices/<nid>/rescind")
def rescind_notice(nid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    notice = lk.get_notice(nid)
    if notice["status"] != "ISSUED":
        raise ApiError("ERR_NOTICE_NOT_ISSUED", 409, "notice is not ISSUED")
    conn = store.connections[notice["service_connection_id"]]
    if svc.has_needs_repair_device(conn) or svc.overdue_count(conn) > 0:
        raise ApiError("ERR_NOTICE_RESCIND_BLOCKED", 409, "connection has not cured")

    before = svc.begin(conn)
    notice["status"] = "RESCINDED"
    svc.touch(notice)
    svc.finish(conn, before)
    return object_response(serialize(notice))


@bp.post("/shutoff-notices/<nid>/enforce")
def enforce_notice(nid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    notice = lk.get_notice(nid)
    if notice["status"] != "ISSUED":
        raise ApiError("ERR_NOTICE_NOT_ISSUED", 409, "notice is not ISSUED")
    if store.current_utc() < notice["enforcement_due_date"]:
        raise ApiError("ERR_ENFORCEMENT_NOT_DUE", 409, "enforcement date not reached")
    conn = store.connections[notice["service_connection_id"]]

    before = svc.begin(conn)
    notice["status"] = "ENFORCED"
    svc.touch(notice)
    conn["water_service_active"] = False
    svc.finish(conn, before)
    return object_response(serialize(notice))
