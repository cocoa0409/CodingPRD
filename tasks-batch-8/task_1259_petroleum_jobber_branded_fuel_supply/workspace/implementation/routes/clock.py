from flask import Blueprint

import db
from middleware import auth_context, require_role
from response import ok_object
from services import cascade
from validate import get_body, parse_dt_str, validate_body

bp = Blueprint('clock', __name__)


@bp.route('/api/_clock/set_current_utc', methods=['POST'])
def set_current_utc():
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'to_iso8601': {'type': 'datetime', 'required': True},
    })
    db.set_clock(parse_dt_str(body['to_iso8601']))
    # Setting the clock is never silent: evaluate every time-based
    # auto-transition as part of this request.
    cascade.evaluate_clock_transitions()
    return ok_object({'current_utc': db.fmt_clock(db.clock_now())})
