"""Logical clock test-driving endpoint. The clock-setting call itself must NOT
trigger lazy sweeps (PRD 2.4) — sweeps are deferred to the next read or
transition."""
from flask import Blueprint

import clock
from middleware import authenticate, authorize
from response import success
from utils import StructErrors, check_unknown_fields, get_datetime
from routes.common import body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"to_iso8601"}, struct)
    target = get_datetime(data, "to_iso8601", struct)
    struct.raise_if_bad()
    current = clock.set_clock(target)
    from utils import iso
    return success({"current_utc": iso(current)})
