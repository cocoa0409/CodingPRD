"""Household endpoints: register, read, list, reinstate, reverse-reachable sublists."""
from flask import Blueprint

import db
import response
import serializers
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_DETERMINATION_INCONSISTENT)
from middleware import (body_json, is_int, require_own_household, require_roles)
from services import calc

bp = Blueprint('households', __name__)


def _get_household(hid):
    h = db.households.get(hid)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, f'Household {hid} not found', 404)
    return h


@bp.route('/curbside/households', methods=['POST'])
def create_household():
    require_roles('Dispatcher')
    body = body_json()
    street_address = body.get('street_address')
    service_zone = body.get('service_zone')
    allowance = body.get('annual_allowance_items', 4)
    if not isinstance(street_address, str) or not street_address.strip():
        raise ApiError(ERR_INVALID_REQUEST, 'street_address is required', 400)
    if service_zone not in calc.ZONES:
        raise ApiError(ERR_INVALID_REQUEST, 'service_zone must be one of ZONE_NORTH, ZONE_SOUTH, ZONE_EAST, ZONE_WEST', 400)
    if not is_int(allowance) or allowance < 0:
        raise ApiError(ERR_INVALID_REQUEST, 'annual_allowance_items must be a non-negative integer', 400)
    now = db.wall_now()
    h = {
        'id': db.new_id(),
        'street_address': street_address,
        'service_zone': service_zone,
        'status': 'ACTIVE',
        'annual_allowance_items': allowance,
        'suspension_reason': None,
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    db.households[h['id']] = h
    return response.ok(serializers.household(h), status=201)


@bp.route('/curbside/households/<hid>', methods=['GET'])
def get_household(hid):
    uid, role = require_roles('Dispatcher', 'Inspector', 'Resident')
    if role == 'Resident':
        # Ownership computable from the path id directly (priority 2 before 3).
        require_own_household(uid, hid)
    return response.ok(serializers.household(_get_household(hid)))


@bp.route('/curbside/households', methods=['GET'])
def list_households():
    require_roles('Dispatcher', 'Inspector')
    from flask import request
    zone = request.args.get('service_zone')
    status = request.args.get('status')
    rows = list(db.households.values())
    if zone is not None:
        rows = [h for h in rows if h['service_zone'] == zone]
    if status is not None:
        rows = [h for h in rows if h['status'] == status]
    rows.sort(key=lambda h: h['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.household(h) for h in page], total, limit, offset)


@bp.route('/curbside/households/<hid>/reinstate', methods=['POST'])
def reinstate_household(hid):
    require_roles('Inspector')
    h = _get_household(hid)
    if h['status'] != 'SUSPENDED':
        raise ApiError(ERR_INVALID_STATE, 'Household is not SUSPENDED', 409)
    for a in db.assessments.values():
        if (a['household_id'] == hid and a['kind'] == 'ILLEGAL_DUMPING_FINE'
                and a['status'] not in ('SETTLED', 'WAIVED')):
            raise ApiError(ERR_DETERMINATION_INCONSISTENT,
                           'Reinstate requires all ILLEGAL_DUMPING_FINE assessments settled or waived', 422)
    h['status'] = 'ACTIVE'
    h['suspension_reason'] = None
    calc.touch(h)
    return response.ok(serializers.household(h))


def _sublist(hid, roles, rows_fn, ser_fn):
    uid, role = require_roles(*roles)
    if role == 'Resident':
        require_own_household(uid, hid)
    _get_household(hid)
    rows = rows_fn(hid)
    rows.sort(key=lambda r: r['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([ser_fn(r) for r in page], total, limit, offset)


@bp.route('/curbside/households/<hid>/allowances', methods=['GET'])
def household_allowances(hid):
    return _sublist(hid, ('Dispatcher', 'Inspector', 'Resident'),
                    lambda h: [a for a in db.allowances.values() if a['household_id'] == h],
                    serializers.allowance)


@bp.route('/curbside/households/<hid>/pickup-requests', methods=['GET'])
def household_pickup_requests(hid):
    return _sublist(hid, ('Dispatcher', 'Inspector', 'Resident'),
                    lambda h: [r for r in db.pickup_requests.values() if r['household_id'] == h],
                    serializers.pickup_request)


@bp.route('/curbside/households/<hid>/dumping-reports', methods=['GET'])
def household_dumping_reports(hid):
    return _sublist(hid, ('Dispatcher', 'Inspector'),
                    lambda h: [r for r in db.reports.values() if r['household_id'] == h],
                    serializers.dumping_report)


@bp.route('/curbside/households/<hid>/fee-assessments', methods=['GET'])
def household_fee_assessments(hid):
    return _sublist(hid, ('Dispatcher', 'Inspector', 'Resident'),
                    lambda h: [a for a in db.assessments.values() if a['household_id'] == h],
                    serializers.fee_assessment)
