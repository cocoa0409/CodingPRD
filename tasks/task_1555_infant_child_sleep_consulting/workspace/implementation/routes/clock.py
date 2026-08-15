from flask import Blueprint

from auth import user_context, require_role
from db import store, fmt_dt, touch
from envelope import ok
from validators import body, req_datetime

bp = Blueprint('clock', __name__)


@bp.post('/_clock/set_current_utc')
def set_clock():
    _, role = user_context()
    require_role(role, 'PracticeAdmin')
    data = body()
    target = req_datetime(data, 'to_iso8601')
    store.clock = target
    # Expiry sweep: ACTIVE packages whose coverage date has passed become
    # EXPIRED (permanently — expiry never reverts on later clock moves).
    today = target.date()
    expired_ids = []
    for pkg in sorted(store.packages.values(), key=lambda p: (p['created_at'], p['_seq'])):
        if pkg['status'] == 'ACTIVE' and today > pkg['expires_on']:
            pkg['status'] = 'EXPIRED'
            touch(pkg)
            expired_ids.append(pkg['id'])
    return ok({'current_utc': fmt_dt(store.clock), 'expired_package_ids': expired_ids})
