from datetime import date, timedelta

from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_AGREEMENT_HAS_OPEN_DROPS,
                    ERR_CURE_PERIOD_ACTIVE, ERR_DEALER_STATION_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_OVERDUE_INVOICES_EXIST,
                    ERR_RENEWAL_WINDOW_NOT_OPEN, ERR_STALE_VERSION,
                    ERR_STATION_NOT_ACTIVE, ERR_SUPPLY_AGREEMENT_NOT_FOUND,
                    ERR_VALIDATION_FAILED)
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import calc
from validate import (apply_filters, get_body, list_response, parse_date_str,
                      sorted_default, validate_body)

bp = Blueprint('agreements', __name__)

_OPEN_DROP_STATUSES = {'PLANNED', 'SCHEDULED', 'EN_ROUTE'}


@bp.route('/api/supply-agreements', methods=['POST'])
def create_agreement():
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'station_id': {'type': 'str', 'required': True},
        'term_start_date': {'type': 'date', 'required': True},
        'term_end_date': {'type': 'date', 'required': True},
        'committed_gallons': {'type': 'int', 'required': True, 'gt': 0},
        'imaging_allowance_cents': {'type': 'int', 'required': True, 'ge': 0},
        'margin_tc_per_gal': {'type': 'int', 'required': True, 'ge': 0},
        'shortfall_penalty_tc_per_gal': {'type': 'int', 'required': True,
                                         'ge': 0},
        'buyout_method': {'type': 'enum', 'required': True,
                          'enum': ['UNAMORTIZED_DISCOUNT', 'LOST_MARGIN']},
    })
    if not (parse_date_str(body['term_end_date'])
            > parse_date_str(body['term_start_date'])):
        raise err(ERR_VALIDATION_FAILED,
                  'term_end_date must be after term_start_date')
    db.get_or_404('stations', body['station_id'], ERR_DEALER_STATION_NOT_FOUND)
    rec = {
        'id': db.new_id(),
        'station_id': body['station_id'],
        'term_start_date': body['term_start_date'],
        'term_end_date': body['term_end_date'],
        'committed_gallons': body['committed_gallons'],
        'imaging_allowance_cents': body['imaging_allowance_cents'],
        'margin_tc_per_gal': body['margin_tc_per_gal'],
        'shortfall_penalty_tc_per_gal': body['shortfall_penalty_tc_per_gal'],
        'buyout_method': body['buyout_method'],
        'renewal_count': 0,
        'renewal_credit_cents': 0,
        'buyout_settlement_cents': None,
        'status': 'DRAFT',
    }
    db.stamp_new(rec)
    db.STORE['agreements'][rec['id']] = rec
    return ok_object(serializers.agreement(rec), 201)


@bp.route('/api/supply-agreements', methods=['GET'])
def list_agreements():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['agreements'].values())
    items = scoped(items, uid, role, lambda a: a['station_id'])
    items = apply_filters(items, {
        'station_id': request.args.get('station_id'),
        'status': request.args.get('status'),
    })
    return list_response(items, serializers.agreement)


@bp.route('/api/supply-agreements/<aid>', methods=['GET'])
def get_agreement(aid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    dealer_scope_check(uid, role, ag['station_id'])
    return ok_object(serializers.agreement(ag))


@bp.route('/api/supply-agreements/<aid>', methods=['PATCH'])
def amend_agreement(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'expected_agreement_version': {'type': 'int', 'required': True},
        'committed_gallons': {'type': 'int', 'required': False, 'gt': 0},
        'imaging_allowance_cents': {'type': 'int', 'required': False, 'ge': 0},
        'margin_tc_per_gal': {'type': 'int', 'required': False, 'ge': 0},
        'shortfall_penalty_tc_per_gal': {'type': 'int', 'required': False,
                                         'ge': 0},
        'buyout_method': {'type': 'enum', 'required': False,
                          'enum': ['UNAMORTIZED_DISCOUNT', 'LOST_MARGIN']},
    })
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    if ag['status'] not in ('DRAFT', 'ACTIVE'):
        raise err(ERR_INVALID_STATE,
                  'Agreements may be amended only in DRAFT or ACTIVE')
    if body['expected_agreement_version'] != ag['version']:
        raise err(ERR_STALE_VERSION, 'Stale agreement version')
    for f in ('committed_gallons', 'imaging_allowance_cents',
              'margin_tc_per_gal', 'shortfall_penalty_tc_per_gal',
              'buyout_method'):
        if f in body:
            ag[f] = body[f]
    db.touch(ag)
    return ok_object(serializers.agreement(ag))


@bp.route('/api/supply-agreements/<aid>/activate', methods=['POST'])
def activate_agreement(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    if ag['status'] != 'DRAFT':
        raise err(ERR_INVALID_STATE, 'status must be DRAFT')
    station = db.STORE['stations'][ag['station_id']]
    if station['operating_status'] != 'ACTIVE':
        raise err(ERR_STATION_NOT_ACTIVE, 'Station is not ACTIVE')
    ag['status'] = 'ACTIVE'
    db.touch(ag)
    return ok_object(serializers.agreement(ag))


@bp.route('/api/supply-agreements/<aid>/start-renewal', methods=['POST'])
def start_renewal(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    if ag['status'] != 'ACTIVE':
        raise err(ERR_INVALID_STATE, 'status must be ACTIVE')
    term_end = date.fromisoformat(ag['term_end_date'])
    today = db.clock_now().date()
    if not (term_end - timedelta(days=90) <= today <= term_end):
        raise err(ERR_RENEWAL_WINDOW_NOT_OPEN,
                  'Clock date is outside the renewal window')
    ag['status'] = 'RENEWAL_PENDING'
    db.touch(ag)
    return ok_object(serializers.agreement(ag))


@bp.route('/api/supply-agreements/<aid>/renew', methods=['POST'])
def renew_agreement(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'new_term_start_date': {'type': 'date', 'required': True},
        'new_term_end_date': {'type': 'date', 'required': True},
        'new_committed_gallons': {'type': 'int', 'required': False, 'gt': 0},
    })
    if not (parse_date_str(body['new_term_end_date'])
            > parse_date_str(body['new_term_start_date'])):
        raise err(ERR_VALIDATION_FAILED,
                  'new_term_end_date must be after new_term_start_date')
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    if ag['status'] != 'RENEWAL_PENDING':
        raise err(ERR_INVALID_STATE, 'status must be RENEWAL_PENDING')
    station = db.STORE['stations'][ag['station_id']]
    if station['compliance_status'] != 'COMPLIANT':
        raise err(ERR_CURE_PERIOD_ACTIVE,
                  'Station compliance blocks renewal')
    if any(i['station_id'] == station['id'] and i['status'] == 'OVERDUE'
           for i in db.STORE['invoices'].values()):
        raise err(ERR_OVERDUE_INVOICES_EXIST, 'Station has overdue invoices')
    # Volume incentive is evaluated over the ENDING term, before replacement.
    fulfilled = calc.fulfilled_gallons(ag)
    ag['renewal_credit_cents'] = calc.renewal_credit_cents(
        fulfilled, ag['committed_gallons'], ag['imaging_allowance_cents'])
    ag['term_start_date'] = body['new_term_start_date']
    ag['term_end_date'] = body['new_term_end_date']
    if 'new_committed_gallons' in body:
        ag['committed_gallons'] = body['new_committed_gallons']
    ag['renewal_count'] += 1
    ag['status'] = 'ACTIVE'
    db.touch(ag)
    return ok_object(serializers.agreement(ag))


@bp.route('/api/supply-agreements/<aid>/terminate', methods=['POST'])
def terminate_agreement(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    if ag['status'] != 'DEFAULT_NOTICE':
        raise err(ERR_INVALID_STATE, 'status must be DEFAULT_NOTICE')
    if any(d['station_id'] == ag['station_id']
           and d['status'] in _OPEN_DROP_STATUSES
           for d in db.STORE['drops'].values()):
        raise err(ERR_AGREEMENT_HAS_OPEN_DROPS,
                  'Open drops block agreement termination')
    ag['status'] = 'TERMINATED'
    db.touch(ag)
    return ok_object(serializers.agreement(ag))


@bp.route('/api/supply-agreements/<aid>/buyout-quote', methods=['GET'])
def buyout_quote(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin', 'CreditManager'})
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    return ok_object(calc.buyout_figures(ag))


@bp.route('/api/supply-agreements/<aid>/initiate-buyout', methods=['POST'])
def initiate_buyout(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    if ag['status'] != 'ACTIVE':
        raise err(ERR_INVALID_STATE, 'status must be ACTIVE')
    station = db.STORE['stations'][ag['station_id']]
    if station['operating_status'] != 'ACTIVE':
        raise err(ERR_STATION_NOT_ACTIVE, 'Station is not ACTIVE')
    ag['status'] = 'BUYOUT_PENDING'
    db.touch(ag)
    return ok_object(serializers.agreement(ag))


@bp.route('/api/supply-agreements/<aid>/execute-buyout', methods=['POST'])
def execute_buyout(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    if ag['status'] != 'BUYOUT_PENDING':
        raise err(ERR_INVALID_STATE, 'status must be BUYOUT_PENDING')
    figs = calc.buyout_figures(ag)
    ag['buyout_settlement_cents'] = figs['net_settlement_cents']
    ag['status'] = 'BOUGHT_OUT'
    db.touch(ag)
    return ok_object(serializers.agreement(ag))


@bp.route('/api/supply-agreements/<aid>/cancel-buyout', methods=['POST'])
def cancel_buyout(aid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    ag = db.get_or_404('agreements', aid, ERR_SUPPLY_AGREEMENT_NOT_FOUND)
    if ag['status'] != 'BUYOUT_PENDING':
        raise err(ERR_INVALID_STATE, 'status must be BUYOUT_PENDING')
    ag['status'] = 'ACTIVE'
    db.touch(ag)
    return ok_object(serializers.agreement(ag))
