"""Logical clock endpoint (PRD 2.4). Dispatcher only."""
from flask import Blueprint

import db
import response
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import body_json, parse_datetime, require_roles

bp = Blueprint('clock', __name__)


@bp.route('/curbside/_clock/set_current_utc', methods=['POST'])
def set_current_utc():
    require_roles('Dispatcher')
    body = body_json()
    to_iso = body.get('to_iso8601')
    dt = parse_datetime(to_iso)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 'to_iso8601 must be a valid ISO 8601 datetime', 400)
    db.set_clock(dt)
    return response.ok({'current_utc': db.fmt_instant(db.get_clock())})
