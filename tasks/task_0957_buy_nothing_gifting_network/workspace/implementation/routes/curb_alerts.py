from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    get_auth, require_role, actor_member, require_active, is_moderator,
    validate, v_str, v_datetime,
)
from response import ok, get_body, paginate, no_body_fields
from services import new_entity, touch, ser_alert, curb_zone_overlap_count

bp = Blueprint("curb_alerts", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


@bp.post("/v1/curb-alerts")
def create_alert():
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {
        "group_id": (True, v_str),
        "zone": (True, v_str),
        "starts_at": (True, v_datetime),
        "ends_at": (True, v_datetime),
    })
    member = actor_member(role, uid)
    group = db.store.groups.get(fields["group_id"])
    if group is None:
        raise_err("ERR_GROUP_NOT_FOUND", "no group with the given id")
    require_active(member)
    if fields["ends_at"] <= fields["starts_at"]:
        raise_err("ERR_INVALID_TIME_RANGE", "ends_at must be strictly after starts_at")
    if curb_zone_overlap_count(group["id"], fields["zone"], fields["starts_at"], fields["ends_at"]) >= 3:
        raise_err("ERR_CURB_ALERT_CAPACITY", "the zone already has 3 overlapping live alerts")
    a = new_entity()
    a.update({
        "group_id": group["id"],
        "creator_id": member["id"],
        "zone": fields["zone"],
        "starts_at": fields["starts_at"],
        "ends_at": fields["ends_at"],
        "status": "SCHEDULED",
    })
    db.store.alerts[a["id"]] = a
    return ok(ser_alert(a), status=201)


@bp.get("/v1/curb-alerts/<alert_id>")
def get_alert(alert_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    a = db.store.alerts.get(alert_id)
    if a is None:
        raise_err("ERR_CURB_ALERT_NOT_FOUND", "no curb alert with the given id")
    return ok(ser_alert(a))


@bp.get("/v1/curb-alerts")
def list_alerts():
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    items = list(db.store.alerts.values())
    group_id = request.args.get("group_id")
    creator_id = request.args.get("creator_id")
    zone = request.args.get("zone")
    status = request.args.get("status")
    if group_id is not None:
        items = [a for a in items if a["group_id"] == group_id]
    if creator_id is not None:
        items = [a for a in items if a["creator_id"] == creator_id]
    if zone is not None:
        items = [a for a in items if a["zone"] == zone]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, meta = paginate(items)
    return ok([ser_alert(a) for a in page], response_type="array", pagination=meta)


@bp.post("/v1/curb-alerts/<alert_id>/cancel")
def cancel_alert(alert_id):
    role, uid = get_auth()
    require_role(role, ("Member", "GroupModerator"))
    no_body_fields()
    actor_member(role, uid)
    a = db.store.alerts.get(alert_id)
    if a is None:
        raise_err("ERR_CURB_ALERT_NOT_FOUND", "no curb alert with the given id")
    # Actor qualifier on the role: creator, or a moderator of the group.
    if role == "Member" and a["creator_id"] != uid:
        raise_err("ERR_UNAUTHORIZED", "only the creator or a group moderator may cancel the alert")
    if role == "GroupModerator" and not is_moderator(uid, a["group_id"]):
        raise_err("ERR_UNAUTHORIZED", "actor does not moderate the alert's group")
    if a["status"] not in ("SCHEDULED", "ACTIVE"):
        raise_err("ERR_CURB_ALERT_NOT_CANCELLABLE", "alert is already ENDED or CANCELLED")
    a["status"] = "CANCELLED"
    touch(a)
    return ok(ser_alert(a))
