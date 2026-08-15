from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_METER_READING_NOT_FOUND,
                    ERR_METER_READING_REGRESSION, ERR_STORAGE_TANK_NOT_FOUND)
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import cascade
from validate import (apply_filters, get_body, parse_dt_str, validate_body,
                      parse_pagination)
from response import ok_list

bp = Blueprint('meters', __name__)


def _tank_of(m):
    tank = db.STORE['tanks'].get(m['tank_id'])
    return tank['station_id'] if tank else None


@bp.route('/api/meter-readings', methods=['POST'])
def create_meter_reading():
    uid, role = auth_context()
    require_role(role, {'DealerOperator'})
    body = validate_body(get_body(), {
        'tank_id': {'type': 'str', 'required': True},
        'reading_at': {'type': 'datetime', 'required': True},
        'totalizer_gallons': {'type': 'int', 'required': True, 'ge': 0},
    })
    tank = db.get_or_404('tanks', body['tank_id'], ERR_STORAGE_TANK_NOT_FOUND)
    dealer_scope_check(uid, role, tank['station_id'])
    reading_at = parse_dt_str(body['reading_at'])
    totalizer = body['totalizer_gallons']
    # Chronological neighbors: ordered by (reading_at, created_at); a fresh
    # insert has the newest created_at, so equal instants sort after existing.
    existing = sorted(
        (m for m in db.STORE['meters'].values() if m['tank_id'] == tank['id']),
        key=lambda m: (m['reading_at'], m['_seq']))
    pred, succ = None, None
    for m in existing:
        if m['reading_at'] <= reading_at:
            pred = m
        else:
            succ = m
            break
    if pred is not None and totalizer < pred['totalizer_gallons']:
        raise err(ERR_METER_READING_REGRESSION,
                  'Totalizer below chronological predecessor')
    if succ is not None and totalizer > succ['totalizer_gallons']:
        raise err(ERR_METER_READING_REGRESSION,
                  'Totalizer above chronological successor')
    rec = {
        'id': db.new_id(),
        'tank_id': tank['id'],
        'reading_at': reading_at,
        'totalizer_gallons': totalizer,
        'metered_gallons': 0,
        'created_at': db.fmt_ts(db.wall_now()),
        '_seq': db.next_seq(),
    }
    db.STORE['meters'][rec['id']] = rec
    # Out-of-order insert recomputes its own delta AND its successor's.
    cascade.recompute_meter_deltas(tank['id'])
    cascade.recompute_book(tank)
    cascade.recompute_open_recon(tank['station_id'])
    return ok_object(serializers.meter(rec), 201)


@bp.route('/api/meter-readings', methods=['GET'])
def list_meter_readings():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted(db.STORE['meters'].values(),
                   key=lambda m: (m['reading_at'], m['_seq']))
    items = scoped(items, uid, role, _tank_of)
    items = apply_filters(items, {'tank_id': request.args.get('tank_id')})
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializers.meter(m) for m in page], limit, offset, total)


@bp.route('/api/meter-readings/<mid>', methods=['GET'])
def get_meter_reading(mid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('meters', mid, ERR_METER_READING_NOT_FOUND)
    dealer_scope_check(uid, role, _tank_of(rec))
    return ok_object(serializers.meter(rec))
