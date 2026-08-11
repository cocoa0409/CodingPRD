from flask import Blueprint

import db
from errors import raise_err
from middleware import (
    get_auth, require_role, actor_member, validate, v_str, v_email,
)
from response import ok, get_body, paginate
from services import new_entity, add_event, ser_member, ser_event

bp = Blueprint("members", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


@bp.post("/v1/members")
def create_member():
    role, _uid = get_auth()
    require_role(role, ("Anonymous",))
    body = get_body()
    fields = validate(body, {
        "email": (True, v_email),
        "display_name": (True, v_str),
    })
    email = fields["email"]
    for m in db.store.members.values():
        if m["email"].lower() == email.lower():
            raise_err("ERR_VALIDATION", "email is already registered")
    member = new_entity()
    member.update({
        "email": email,
        "display_name": fields["display_name"],
        "status": "ACTIVE",
        "suspension_ends_at": None,
    })
    db.store.members[member["id"]] = member
    add_event(member["id"], "WELCOME_BONUS", 5)
    return ok(ser_member(member), status=201)


@bp.get("/v1/members/<member_id>")
def get_member(member_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    member = db.store.members.get(member_id)
    if member is None:
        raise_err("ERR_MEMBER_NOT_FOUND", "no member with the given id")
    return ok(ser_member(member))


@bp.get("/v1/members/<member_id>/reputation-events")
def list_member_reputation_events(member_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    member = db.store.members.get(member_id)
    if member is None:
        raise_err("ERR_MEMBER_NOT_FOUND", "no member with the given id")
    events = [ev for ev in db.store.events.values() if ev["member_id"] == member_id]
    status = _status_filter(("PENDING", "SETTLED"))
    if status is not None:
        events = [ev for ev in events if ev["status"] == status]
    events.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(events)
    return ok([ser_event(ev) for ev in page], response_type="array", pagination=meta)


def _status_filter(allowed):
    from flask import request
    raw = request.args.get("status")
    if raw is None:
        return None
    return raw
