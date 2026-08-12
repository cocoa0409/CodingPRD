from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_DEALER_STATION_NOT_FOUND, ERR_INVALID_STATE)
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import calc, cascade
from validate import (apply_filters, get_body, list_response, sorted_default,
                      validate_body)

bp = Blueprint('stations', __name__)

_AGREEMENT_BLOCKING_STATUSES = {'DRAFT', 'ACTIVE', 'RENEWAL_PENDING',
                                'DEFAULT_NOTICE', 'BUYOUT_PENDING'}


@bp.route('/api/dealer-stations', methods=['POST'])
def create_station():
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'station_name': {'type': 'str', 'required': True},
        'state_code': {'type': 'str', 'required': True},
        'home_terminal_code': {'type': 'str', 'required': True},
        'state_excise_tc_per_gal': {'type': 'int', 'required': True},
        'local_option_tc_per_gal': {'type': 'int', 'required': False},
        'credit_limit_cents': {'type': 'int', 'required': True, 'ge': 0},
        'credit_terms_days': {'type': 'int', 'required': False, 'ge': 1},
    })
    rec = {
        'id': db.new_id(),
        'station_name': body['station_name'],
        'state_code': body['state_code'],
        'home_terminal_code': body['home_terminal_code'],
        'state_excise_tc_per_gal': body['state_excise_tc_per_gal'],
        'local_option_tc_per_gal': body.get('local_option_tc_per_gal', 0),
        'credit_limit_cents': body['credit_limit_cents'],
        'credit_terms_days': body.get('credit_terms_days', 10),
        'current_exposure_cents': 0,
        'operating_status': 'ONBOARDING',
        'credit_status': 'GOOD_STANDING',
        'compliance_status': 'COMPLIANT',
        'cure_started_at': None,
    }
    db.stamp_new(rec)
    db.STORE['stations'][rec['id']] = rec
    return ok_object(serializers.station(rec), 201)


@bp.route('/api/dealer-stations', methods=['GET'])
def list_stations():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['stations'].values())
    items = scoped(items, uid, role, lambda s: s['id'])
    items = apply_filters(items, {
        'operating_status': request.args.get('operating_status'),
        'credit_status': request.args.get('credit_status'),
        'compliance_status': request.args.get('compliance_status'),
        'state_code': request.args.get('state_code'),
    })
    return list_response(items, serializers.station)


@bp.route('/api/dealer-stations/<sid>', methods=['GET'])
def get_station(sid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    st = db.get_or_404('stations', sid, ERR_DEALER_STATION_NOT_FOUND)
    dealer_scope_check(uid, role, st['id'])
    return ok_object(serializers.station(st))


@bp.route('/api/dealer-stations/<sid>', methods=['PATCH'])
def patch_station(sid):
    uid, role = auth_context()
    require_role(role, {'CreditManager'})
    body = validate_body(get_body(), {
        'credit_limit_cents': {'type': 'int', 'required': False, 'ge': 0},
        'credit_terms_days': {'type': 'int', 'required': False, 'ge': 1},
    })
    st = db.get_or_404('stations', sid, ERR_DEALER_STATION_NOT_FOUND)
    limit_changed = ('credit_limit_cents' in body
                     and body['credit_limit_cents'] != st['credit_limit_cents'])
    if 'credit_limit_cents' in body:
        st['credit_limit_cents'] = body['credit_limit_cents']
    if 'credit_terms_days' in body:
        st['credit_terms_days'] = body['credit_terms_days']
    db.touch(st)
    if limit_changed:
        # Band re-evaluated when the limit changed (never enters/exits HOLD).
        cascade.apply_credit_band(st)
    return ok_object(serializers.station(st))


def _station_action(sid, from_status, to_status):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    st = db.get_or_404('stations', sid, ERR_DEALER_STATION_NOT_FOUND)
    if st['operating_status'] != from_status:
        raise err(ERR_INVALID_STATE,
                  'operating_status must be {}'.format(from_status))
    st['operating_status'] = to_status
    db.touch(st)
    return ok_object(serializers.station(st))


@bp.route('/api/dealer-stations/<sid>/activate', methods=['POST'])
def activate_station(sid):
    return _station_action(sid, 'ONBOARDING', 'ACTIVE')


@bp.route('/api/dealer-stations/<sid>/suspend', methods=['POST'])
def suspend_station(sid):
    return _station_action(sid, 'ACTIVE', 'SUSPENDED')


@bp.route('/api/dealer-stations/<sid>/reactivate', methods=['POST'])
def reactivate_station(sid):
    return _station_action(sid, 'SUSPENDED', 'ACTIVE')


@bp.route('/api/dealer-stations/<sid>/terminate', methods=['POST'])
def terminate_station(sid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    st = db.get_or_404('stations', sid, ERR_DEALER_STATION_NOT_FOUND)
    if st['operating_status'] not in ('ACTIVE', 'SUSPENDED'):
        raise err(ERR_INVALID_STATE,
                  'operating_status must be ACTIVE or SUSPENDED')
    for ag in db.STORE['agreements'].values():
        if (ag['station_id'] == st['id']
                and ag['status'] in _AGREEMENT_BLOCKING_STATUSES):
            raise err(ERR_INVALID_STATE,
                      'A live supply agreement blocks termination')
    st['operating_status'] = 'TERMINATED'
    db.touch(st)
    return ok_object(serializers.station(st))


@bp.route('/api/dealer-stations/<sid>/restore-credit', methods=['POST'])
def restore_credit(sid):
    uid, role = auth_context()
    require_role(role, {'CreditManager'})
    st = db.get_or_404('stations', sid, ERR_DEALER_STATION_NOT_FOUND)
    if st['credit_status'] != 'HOLD':
        raise err(ERR_INVALID_STATE, 'credit_status must be HOLD')
    # Apply the exposure band: below 80% -> GOOD_STANDING, else WATCH.
    st['credit_status'] = calc.credit_band_for(st['current_exposure_cents'],
                                               st['credit_limit_cents'])
    db.touch(st)
    return ok_object(serializers.station(st))
