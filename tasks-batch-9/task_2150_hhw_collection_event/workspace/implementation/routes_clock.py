"""The logical clock (PRD §2.9) — a test-driving affordance, not a business
operation: it mutates no entity and increments no row's version."""

from flask import Blueprint

from envelope import ok
from store import store
from validation import authorize, body, context, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/hhw/_clock/set_current_utc")
def set_current_utc():
    user_id, role = context()
    authorize(role, ["ProgramAdmin"])
    payload = body()
    moment = req_dt(payload, "to_iso8601")
    store.clock_dt = moment
    store.clock_raw = payload["to_iso8601"]
    return ok({"current_utc": store.clock_raw})
