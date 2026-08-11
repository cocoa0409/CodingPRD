from flask import Blueprint, request

import db
from errors import raise_err
from middleware import get_auth, require_role, actor_member
from response import ok, get_body, paginate, no_body_fields
from services import touch, ser_action, recompute_strike_status

bp = Blueprint("moderation", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


@bp.get("/v1/moderation-actions/<action_id>")
def get_action(action_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    a = db.store.actions.get(action_id)
    if a is None:
        raise_err("ERR_MODERATION_ACTION_NOT_FOUND", "no moderation action with the given id")
    return ok(ser_action(a))


@bp.get("/v1/moderation-actions")
def list_actions():
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    items = list(db.store.actions.values())
    report_id = request.args.get("report_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if report_id is not None:
        items = [a for a in items if a["report_id"] == report_id]
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, meta = paginate(items)
    return ok([ser_action(a) for a in page], response_type="array", pagination=meta)


@bp.post("/v1/moderation-actions/<action_id>/overturn")
def overturn_action(action_id):
    role, _uid = get_auth()
    require_role(role, ("PlatformAdmin",))
    no_body_fields()
    a = db.store.actions.get(action_id)
    if a is None:
        raise_err("ERR_MODERATION_ACTION_NOT_FOUND", "no moderation action with the given id")
    if a["status"] != "ACTIVE":
        raise_err("ERR_ACTION_NOT_OVERTURNABLE", "action is not in ACTIVE")
    a["status"] = "OVERTURNED"
    touch(a)
    subject = db.store.members.get(a["member_id"])
    if subject is not None:
        # Overturn is the only door that can walk a BANNED member back.
        recompute_strike_status(subject, allow_unban=True)
    return ok(ser_action(a))
