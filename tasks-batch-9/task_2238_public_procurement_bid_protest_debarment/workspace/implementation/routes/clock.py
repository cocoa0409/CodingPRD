"""The administrative logical-clock capability (PRD §2.4)."""

from flask import Blueprint

import store
import validation as v
from util import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@v.endpoint(["SystemAdmin"])
def set_current_utc():
    data = v.body()
    instant = v.req_dt(data, "to_iso8601")
    store.set_clock(instant)
    return ("raw", {"current_utc": fmt_dt(instant)}, 200)
