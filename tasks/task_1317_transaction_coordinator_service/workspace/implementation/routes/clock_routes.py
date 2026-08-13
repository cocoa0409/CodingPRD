"""The administrator-controlled logical clock."""
from flask import Blueprint

import errors as E
import middleware as mw
from db import store
from response import ok_object
from services.cascade import sweep_clock
from util import parse_dt, is_dt_str

bp = Blueprint("clock", __name__)


@bp.post("/tc/_clock/set_current_utc")
def set_current_utc():
    uid, role = mw.auth()
    mw.require_roles(role, {"SystemAdmin"})
    data = mw.body()
    if "to_iso8601" not in data or not is_dt_str(data.get("to_iso8601")):
        E.raise_err(E.ERR_INVALID_REQUEST, "to_iso8601 is required and must be ISO 8601")
    store.now = parse_dt(data["to_iso8601"])
    counts = sweep_clock()
    return ok_object(counts)
