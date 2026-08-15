"""Logical clock test-driving endpoint (PRD 2.10)."""
from flask import Blueprint

from auth import roles_allowed
from dates import parse_instant
from domain import apply_time_rules
from envelope import success_object
from errors import ERR_INVALID_REQUEST, raise_err
from store import store

bp = Blueprint('clock', __name__)


@bp.route('/_clock/set_current_utc', methods=['POST'])
@roles_allowed('System')
def set_current_utc():
    from validate import get_body, require
    body = get_body()
    raw = require(body, 'to_iso8601')
    dt = parse_instant(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, 'to_iso8601 must be an ISO 8601 timestamp')
    store.clock = dt
    apply_time_rules()
    return success_object({'current_utc': store.clock.strftime('%Y-%m-%dT%H:%M:%SZ')})
