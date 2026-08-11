"""Test-driving logical clock (PRD §2.8)."""
from flask import Blueprint

from db import store
from middleware import require
from response import ok
from util import body_json, fmt_dt, v_dt

bp = Blueprint("clock", __name__)


@bp.post("/petting-zoo/_clock/set_current_utc")
def set_current_utc():
    require({"Operator"})
    body = body_json()
    store.clock = v_dt(body, "to_iso8601")
    return ok({"current_utc": fmt_dt(store.clock)})
