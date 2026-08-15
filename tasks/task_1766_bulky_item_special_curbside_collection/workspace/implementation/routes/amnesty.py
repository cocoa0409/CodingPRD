"""Amnesty window endpoints (PRD 3.6): half-open [starts_at, ends_at), non-intersecting."""
from flask import Blueprint, request

import db
import response
import serializers
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_TEMPORAL_CONFLICT
from middleware import body_json, parse_datetime, require_roles

bp = Blueprint('amnesty', __name__)


def _get_window(wid):
    w = db.amnesty_windows.get(wid)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, f'AmnestyWindow {wid} not found', 404)
    return w


@bp.route('/curbside/amnesty-windows', methods=['POST'])
def create_window():
    require_roles('Dispatcher')
    body = body_json()
    label = body.get('label')
    starts_at = parse_datetime(body.get('starts_at'))
    ends_at = parse_datetime(body.get('ends_at'))
    if not isinstance(label, str) or not label.strip():
        raise ApiError(ERR_INVALID_REQUEST, 'label is required', 400)
    if starts_at is None or ends_at is None:
        raise ApiError(ERR_INVALID_REQUEST, 'starts_at and ends_at must be valid ISO 8601 datetimes', 400)
    if not (starts_at < ends_at):
        raise ApiError(ERR_TEMPORAL_CONFLICT, 'Amnesty window requires starts_at < ends_at', 422)
    for w in db.amnesty_windows.values():
        if w['status'] != 'ACTIVE':
            continue
        # Half-open intersection: touching endpoints allowed.
        if starts_at < w['ends_at'] and w['starts_at'] < ends_at:
            raise ApiError(ERR_TEMPORAL_CONFLICT,
                           'Amnesty window intersects an existing ACTIVE window', 422)
    now = db.wall_now()
    w = {
        'id': db.new_id(),
        'label': label,
        'starts_at': starts_at,
        'ends_at': ends_at,
        'status': 'ACTIVE',
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    db.amnesty_windows[w['id']] = w
    return response.ok(serializers.amnesty_window(w), status=201)


@bp.route('/curbside/amnesty-windows/<wid>', methods=['GET'])
def get_window(wid):
    require_roles('Dispatcher', 'Inspector', 'Resident', 'Driver')
    return response.ok(serializers.amnesty_window(_get_window(wid)))


@bp.route('/curbside/amnesty-windows', methods=['GET'])
def list_windows():
    require_roles('Dispatcher', 'Inspector', 'Resident', 'Driver')
    status = request.args.get('status')
    rows = list(db.amnesty_windows.values())
    if status is not None:
        rows = [w for w in rows if w['status'] == status]
    rows.sort(key=lambda w: w['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.amnesty_window(w) for w in page], total, limit, offset)


@bp.route('/curbside/amnesty-windows/<wid>/cancel', methods=['POST'])
def cancel_window(wid):
    require_roles('Dispatcher')
    w = _get_window(wid)
    if w['status'] != 'ACTIVE':
        raise ApiError(ERR_INVALID_STATE, 'AmnestyWindow is not ACTIVE', 409)
    w['status'] = 'CANCELLED'
    from services import calc
    calc.touch(w)
    return response.ok(serializers.amnesty_window(w))
