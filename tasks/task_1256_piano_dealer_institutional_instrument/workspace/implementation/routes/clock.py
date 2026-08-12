from flask import Blueprint

import db
from middleware import auth
from response import ok
from util import body, require, parse_dt, fmt_dt

bp = Blueprint('clock', __name__)


@bp.post('/piano-dealer/_clock/set_current_utc')
def set_current_utc():
    auth('PlatformAdmin')
    d = body()
    to = parse_dt(require(d, 'to_iso8601'), 'to_iso8601')
    db.set_clock(to)
    return ok({'current_utc': fmt_dt(db.now())})
