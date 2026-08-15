from flask import Blueprint

from db import clock
from middleware import require
from response import fmt_dt, ok
from validate import Shape, get_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require("DealershipAdmin")
def set_current_utc(actor_id, actor_role):
    shape = Shape(get_body())
    shape.req_dt("to_iso8601")
    shape.raise_if_errors()
    clock.set(shape.value("to_iso8601"))
    return ok({"current_utc": fmt_dt(clock.now())})
