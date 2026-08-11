from flask import Blueprint

import db
from errors import raise_err
from middleware import get_auth, require_role, actor_member
from response import ok
from services import ser_event

bp = Blueprint("reputation", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


@bp.get("/v1/reputation-events/<event_id>")
def get_event(event_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    ev = db.store.events.get(event_id)
    if ev is None:
        raise_err("ERR_REPUTATION_EVENT_NOT_FOUND", "no reputation event with the given id")
    return ok(ser_event(ev))
