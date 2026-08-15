"""POST /escrow/_clock/set_current_utc — logical clock test-driving."""

from db import store, fmt_dt
from helpers import get_body, check_allowed_fields, req_datetime
from middleware import authenticate, authorize
from response import success

from . import bp


@bp.post("/escrow/_clock/set_current_utc")
def set_current_utc():
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    data = get_body()
    check_allowed_fields(data, {"to_iso8601"})
    target = req_datetime(data, "to_iso8601")
    store.clock = target
    return success({"current_utc": fmt_dt(store.clock)}, response_type="object", status=200)
