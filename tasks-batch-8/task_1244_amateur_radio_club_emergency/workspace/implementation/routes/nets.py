"""Net session and check-in endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_ALREADY_CHECKED_IN, ERR_FORBIDDEN, ERR_INVALID_STATE,
    ERR_INVALID_TRAFFIC_COUNT, ERR_LICENSE_CLASS_INSUFFICIENT,
    ERR_LICENSE_EXPIRED, ERR_MEMBERSHIP_NOT_ACTIVE, ERR_NET_NOT_OPEN,
    ERR_NET_TIME_CONFLICT, ERR_NET_WINDOW_NOT_STARTED,
    ERR_REPEATER_NOT_OPERATIONAL, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    LICENSE_CLASSES, as_bool, as_dt, as_enum, as_int, as_str, body_json, need,
    opt, reject_unknown_fields,
)

bp = Blueprint("nets", __name__)

NET_STATUSES = {"SCHEDULED", "OPEN", "CLOSED", "CANCELLED"}
WRITE_ROLES = {"NetControl", "ClubAdmin"}
READ_ROLES = {"ClubAdmin", "NetControl", "Member"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


def _net_time_conflict(repeater_id, start, end):
    """Half-open [start, end) overlap vs nets in {SCHEDULED, OPEN} on the same
    repeater; back-to-back nets (end == start) are allowed."""
    for o in db.STORE["net_sessions"].values():
        if o["repeater_id"] != repeater_id:
            continue
        if o["status"] not in ("SCHEDULED", "OPEN"):
            continue
        if start < o["scheduled_end"] and o["scheduled_start"] < end:
            return True
    return False


def _owns_net(user_id, role, net):
    """Caller must be the net's control operator or a ClubAdmin."""
    if role == "ClubAdmin":
        return
    if net["net_control_member_id"] is not None and net["net_control_member_id"] == user_id:
        return
    raise ApiError(ERR_FORBIDDEN, 403,
                   "caller is not the net control operator for this net")


@bp.post("/net-sessions")
def create_net():
    user_id, role = _auth(WRITE_ROLES)
    body = body_json(request)
    reject_unknown_fields(body, {"name", "repeater_id", "scheduled_start",
                                 "scheduled_end", "min_license_class",
                                 "net_control_member_id"})
    name = as_str(need(body, "name"), "name")
    repeater_id = as_str(need(body, "repeater_id"), "repeater_id")
    repeater = svc.get_repeater(repeater_id)  # body FK existence
    scheduled_start = as_dt(need(body, "scheduled_start"), "scheduled_start")
    scheduled_end = as_dt(need(body, "scheduled_end"), "scheduled_end")
    min_license_class = as_enum(opt(body, "min_license_class", "TECHNICIAN"),
                                "min_license_class", LICENSE_CLASSES)
    if role == "NetControl":
        # NetControl callers always run the net themselves.
        control_id = user_id
    else:
        control_id = opt(body, "net_control_member_id")
        if control_id is not None:
            control_id = as_str(control_id, "net_control_member_id")
    control = None
    if control_id is not None:
        control = svc.get_member(control_id)  # body FK existence
    if control is not None and not svc.license_at_least(control, min_license_class):
        raise ApiError(ERR_LICENSE_CLASS_INSUFFICIENT, 422,
                       "net control license_class below min_license_class")
    if _net_time_conflict(repeater["id"], scheduled_start, scheduled_end):
        raise ApiError(ERR_NET_TIME_CONFLICT, 409,
                       "net window overlaps another net on this repeater")
    net = {
        "name": name,
        "repeater_id": repeater["id"],
        "net_control_member_id": control_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "min_license_class": min_license_class,
        "status": "SCHEDULED",
    }
    svc.stamp_new(net)
    db.STORE["net_sessions"][net["id"]] = net
    return success(svc.ser_net(net), "object", 201)


@bp.get("/net-sessions")
def list_nets():
    _auth(READ_ROLES)
    repeater_id = request.args.get("repeater_id")
    control_id = request.args.get("net_control_member_id")
    status = request.args.get("status")
    items = []
    for n in svc.sorted_records("net_sessions"):
        if repeater_id is not None and n["repeater_id"] != repeater_id:
            continue
        if control_id is not None and n["net_control_member_id"] != control_id:
            continue
        if status is not None and n["status"] != status:
            continue
        items.append(svc.ser_net(n))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/net-sessions/<nid>")
def get_net(nid):
    _auth(READ_ROLES)
    return success(svc.ser_net(svc.get_net(nid)), "object", 200)


@bp.post("/net-sessions/<nid>/set-status")
def set_net_status(nid):
    user_id, role = _auth(WRITE_ROLES)
    net = svc.get_net(nid)
    _owns_net(user_id, role, net)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", NET_STATUSES)
    current = net["status"]
    now = db.now()
    if to == "OPEN":
        if current != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot open a net in status %s" % current)
        if not (net["scheduled_start"] <= now < net["scheduled_end"]):
            raise ApiError(ERR_NET_WINDOW_NOT_STARTED, 409,
                           "net may be opened only within [scheduled_start, scheduled_end)")
        repeater = svc.get_repeater(net["repeater_id"])
        if repeater["status"] != "OPERATIONAL":
            raise ApiError(ERR_REPEATER_NOT_OPERATIONAL, 409,
                           "net open requires repeater status OPERATIONAL")
        net["status"] = "OPEN"
        svc.touch(net)
    elif to == "CLOSED":
        if current != "OPEN":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot close a net in status %s" % current)
        net["status"] = "CLOSED"
        svc.touch(net)
    elif to == "CANCELLED":
        # Manual cancel only from SCHEDULED; OPEN -> CANCELLED is cascade-only.
        if current != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot cancel a net in status %s" % current)
        svc.cancel_net_cascade(net)
    else:  # SCHEDULED is never a manual target
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move a net from %s to %s" % (current, to))
    return success(svc.ser_net(net), "object", 200)


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------

@bp.post("/check-ins")
def create_checkin():
    user_id, role = _auth({"Member"})
    body = body_json(request)
    reject_unknown_fields(body, {"net_session_id", "has_traffic",
                                 "traffic_count"})
    net_session_id = as_str(need(body, "net_session_id"), "net_session_id")
    net = svc.get_net(net_session_id)  # body FK existence
    has_traffic = as_bool(opt(body, "has_traffic", False), "has_traffic")
    traffic_count = as_int(opt(body, "traffic_count", 0), "traffic_count")
    member = svc.get_member(user_id)
    # State (p4): target net must be OPEN.
    if net["status"] != "OPEN":
        raise ApiError(ERR_NET_NOT_OPEN, 409, "check-in target net is not OPEN")
    # Field-domain (p6): license class ordinal, then licence expiry.
    if not svc.license_at_least(member, net["min_license_class"]):
        raise ApiError(ERR_LICENSE_CLASS_INSUFFICIENT, 422,
                       "license_class below the net's min_license_class")
    if member["license_expires_at"] <= db.now():
        raise ApiError(ERR_LICENSE_EXPIRED, 422, "license has expired")
    if has_traffic != (traffic_count >= 1):
        raise ApiError(ERR_INVALID_TRAFFIC_COUNT, 422,
                       "has_traffic must agree with traffic_count")
    for c in db.STORE["check_ins"].values():
        if c["net_session_id"] == net["id"] and c["member_id"] == member["id"]:
            raise ApiError(ERR_ALREADY_CHECKED_IN, 409,
                           "member already checked in to this net")
    # Referenced-entity state (p8): membership must be ACTIVE.
    if member["membership_status"] != "ACTIVE":
        raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                       "membership_status is not ACTIVE")
    checkin = {
        "net_session_id": net["id"],
        "member_id": member["id"],
        "has_traffic": has_traffic,
        "traffic_count": traffic_count,
        "checked_in_at": db.now(),
    }
    # CheckIn: common_fields false — only id + created_at (PRD §2.4).
    checkin["id"] = svc.new_id()
    checkin["created_at"] = db.now()
    checkin["_seq"] = db.next_seq()
    db.STORE["check_ins"][checkin["id"]] = checkin
    return success(svc.ser_checkin(checkin), "object", 201)


@bp.get("/check-ins")
def list_checkins():
    _auth(READ_ROLES)
    net_session_id = request.args.get("net_session_id")
    member_id = request.args.get("member_id")
    items = []
    for c in svc.sorted_records("check_ins"):
        if net_session_id is not None and c["net_session_id"] != net_session_id:
            continue
        if member_id is not None and c["member_id"] != member_id:
            continue
        items.append(svc.ser_checkin(c))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/check-ins/<cid>")
def get_checkin(cid):
    _auth(READ_ROLES)
    return success(svc.ser_checkin(svc.get_checkin(cid)), "object", 200)
