from flask import Blueprint, g

import db
import core
import ser
import find
from core import ApiError

bp = Blueprint("alerts", __name__)


# ---- Wellness checks (read only) ----
@bp.get("/wellness-checks/<wid>")
@core.require_auth(core.ALL_ROLES)
def get_wellness_check(wid):
    w = find.wellness_check(wid)
    return core.ok_object(ser.wellness_check(w))


@bp.get("/wellness-checks")
@core.require_auth(core.ALL_ROLES)
def list_wellness_checks():
    args = core.request.args
    items = list(db.wellness_checks.values())
    for key in ("delivery_id", "client_id", "outcome"):
        val = args.get(key)
        if val is not None:
            items = [w for w in items if w[key] == val]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.wellness_check(w) for w in page], limit, offset, total)


# ---- Welfare alerts ----
@bp.get("/welfare-alerts/<aid>")
@core.require_auth(core.ALL_ROLES)
def get_welfare_alert(aid):
    a = find.welfare_alert(aid)
    return core.ok_object(ser.welfare_alert(a))


@bp.get("/welfare-alerts")
@core.require_auth(core.ALL_ROLES)
def list_welfare_alerts():
    args = core.request.args
    items = list(db.welfare_alerts.values())
    for key in ("client_id", "triggering_wellness_check_id", "status", "severity"):
        val = args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.welfare_alert(a) for a in page], limit, offset, total)


@bp.post("/welfare-alerts/<aid>/acknowledge")
@core.require_auth(["VolunteerDriver", "RouteManager"])
def acknowledge_alert(aid):
    a = find.welfare_alert(aid)
    if a["status"] != "OPEN":
        raise ApiError("ERR_ALERT_INVALID_STATE", 409, "alert must be OPEN to acknowledge")
    a["status"] = "ACKNOWLEDGED"
    a["acknowledged_by"] = g.user_id
    db.touch(a)
    return core.ok_object(ser.welfare_alert(a))


@bp.post("/welfare-alerts/<aid>/escalate")
@core.require_auth(["RouteManager"])
def escalate_alert(aid):
    a = find.welfare_alert(aid)
    if a["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise ApiError("ERR_ALERT_INVALID_STATE", 409, "alert must be OPEN or ACKNOWLEDGED to escalate")
    a["status"] = "ESCALATED"
    db.touch(a)
    return core.ok_object(ser.welfare_alert(a))


@bp.post("/welfare-alerts/<aid>/resolve")
@core.require_auth(["RouteManager", "IntakeCoordinator"])
def resolve_alert(aid):
    a = find.welfare_alert(aid)
    if a["status"] not in ("ACKNOWLEDGED", "ESCALATED"):
        raise ApiError("ERR_ALERT_INVALID_STATE", 409, "alert must be ACKNOWLEDGED or ESCALATED to resolve")
    a["status"] = "RESOLVED"
    db.touch(a)
    return core.ok_object(ser.welfare_alert(a))
