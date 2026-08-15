"""Logical clock test-driving endpoint (PRD section 2.4)."""
from datetime import datetime, timezone

from flask import Blueprint

from db import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles, body_json, req_str
from response import ok
from services.core import run_clock_sweeps

bp = Blueprint('clock', __name__)


def _parse_iso8601(s):
    text = s.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_clock(dt):
    if dt.microsecond:
        return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{0:06d}Z'.format(dt.microsecond)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_current_utc():
    require_roles('AirportAdmin')
    body = body_json()
    raw = req_str(body, 'to_iso8601')
    dt = _parse_iso8601(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'to_iso8601 must be a valid ISO 8601 instant')
    db.clock = dt
    # Advancing the clock is not passive: the lease expiry sweep and the
    # settlement overdue sweep run against the new time in the same request.
    run_clock_sweeps()
    return ok({'current_utc': _format_clock(db.clock)})
