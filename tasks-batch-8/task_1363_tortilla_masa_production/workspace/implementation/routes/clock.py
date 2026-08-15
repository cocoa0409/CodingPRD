from flask import Blueprint

from db import store, fmt_dt
from middleware import authorize
from response import ok
from validate import body, parse_dt_value

bp = Blueprint("clock", __name__)


@bp.post("/plant/_clock/set_current_utc")
def set_current_utc():
    authorize(["PlantManager"])
    b = body()
    dt = parse_dt_value(b.get("to_iso8601"), "to_iso8601")
    store.clock = dt
    return ok({"current_utc": fmt_dt(store.clock)})
