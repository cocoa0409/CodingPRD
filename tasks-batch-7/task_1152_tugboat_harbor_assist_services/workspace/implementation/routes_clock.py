"""Administrative logical clock (PRD §2.4)."""
from flask import Blueprint

from db import store
from util import (
    authenticate, require_roles, ok_object, json_body, Check, get_dt, fmt_dt,
)

bp = Blueprint('clock', __name__)


@bp.route('/api/_clock/set_current_utc', methods=['POST'])
def set_current_utc():
    _, role = authenticate()
    require_roles(role, ('PortAdmin',))
    body = json_body()
    c = Check()
    target = get_dt(body, 'to_iso8601', c)
    c.raise_deferred()
    store.clock = target
    return ok_object({'current_utc': fmt_dt(store.clock)})
