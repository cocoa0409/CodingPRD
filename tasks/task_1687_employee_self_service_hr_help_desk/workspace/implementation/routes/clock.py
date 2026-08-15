"""The test-driving logical clock (admin only)."""
from flask import Blueprint

import db
from middleware import authenticate, require_roles
from response import ok_object
from services.clocksvc import advance_clock
from validate import get_body, req_datetime

bp = Blueprint('clock', __name__)


@bp.post('/_clock/set_current_utc')
def set_current_utc():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin')
    body = get_body()
    to_dt = req_datetime(body, 'to_iso8601')
    advance_clock(to_dt)
    return ok_object({'now_utc': db.iso(db.now())})
