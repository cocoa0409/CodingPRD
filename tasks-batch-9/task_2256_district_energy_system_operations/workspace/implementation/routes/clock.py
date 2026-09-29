"""The logical clock endpoint, mounted at the server root (PRD 2.10)."""

from flask import Blueprint

from db import fmt_ts, store
from middleware import endpoint
from validators import get_dt, json_body

bp = Blueprint("clock", __name__)


@endpoint(bp, "/_clock/set_current_utc", ["POST"], ["SystemController"])
def set_current_utc():
    body = json_body()
    raw, moment = get_dt(body, "to_iso8601", required=True)
    del raw
    store.clock = moment
    return {"current_utc": fmt_ts(store.clock)}
