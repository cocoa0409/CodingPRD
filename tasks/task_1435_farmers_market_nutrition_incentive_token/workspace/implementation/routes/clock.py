"""POST /_clock/set_current_utc — test-driving endpoint for the logical clock."""

from flask import Blueprint

from logical_clock import CLOCK, _parse_iso
from middleware import ensure_valid_json, req_datetime
from response import success_object
from routes.common import Pipeline

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    pipe = Pipeline(["ProgramAdmin"], is_write=True)
    ensure_valid_json(pipe.body)
    to_dt = req_datetime(pipe.body, "to_iso8601")
    CLOCK.set(to_dt)
    resp_body = {"current_utc": CLOCK.now_iso()}
    env, status = success_object(resp_body, 200)
    pipe.commit(status, env.get_json())
    return env, status
