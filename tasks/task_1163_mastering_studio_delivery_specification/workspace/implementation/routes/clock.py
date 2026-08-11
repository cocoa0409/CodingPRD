from flask import Blueprint

import db
from middleware import auth, require_roles, body, req_field, as_datetime
from response import success

bp = Blueprint('clock', __name__)


@bp.post('/studio/_clock/set_current_utc')
def set_current_utc():
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    data = body()
    to_iso8601 = as_datetime(req_field(data, 'to_iso8601'), 'to_iso8601')
    db.CLOCK.set(to_iso8601)
    return success({}, 200)
