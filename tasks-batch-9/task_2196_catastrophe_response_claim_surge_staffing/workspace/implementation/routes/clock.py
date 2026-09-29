"""The server-owned logical clock (PRD 2.6)."""
from flask import Blueprint

import store
import sync
import validate
from envelope import ok
from routes.common import begin

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    begin()
    payload = validate.body()
    moment = validate.req_datetime(payload, "to_iso8601")
    store.set_clock(moment)
    # Re-evaluate every time-driven transition at the new instant.
    sync.sync_all()
    for event in list(store.events.values()):
        sync.recompute_event_deadlines(event["id"])
    return ok({})
