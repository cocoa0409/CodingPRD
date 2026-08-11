from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import authenticate, authorize, check_order_scope, ALL_ROLES
from response import ok
from services import calc
from services.lifecycle import elected_coverage_for, order_tariff
from services.store import new_entity, touch, estimate_view, coverage_view
from util import get_body, check_body, get_path, apply_list, now

bp = Blueprint('estimates', __name__)


# ---------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------

@bp.post('/orders/<oid>/estimates')
def create_estimate(oid):
    auth = authenticate()
    authorize(auth, ['BookingAgent'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    vals = check_body(get_body(), [
        ('estimate_kind', 'enum', True, ('BINDING', 'NON_BINDING')),
        ('estimated_weight_lbs', 'int', True, (1, None)),
        ('packing_services_cents', 'int', False, (0, None)),
        ('expected_order_version', 'int', True, None),
    ])
    if order['status'] != 'REGISTERED':
        raise ApiError('ERR_ORDER_NOT_REGISTERED', 409, 'order is not REGISTERED')
    if vals['expected_order_version'] != order['version']:
        raise ApiError('ERR_STALE_ORDER_VERSION', 412,
                       'expected_order_version does not match the current order version')
    if vals['estimate_kind'] != order['pricing_mode']:
        raise ApiError('ERR_ESTIMATE_KIND_MISMATCH', 422,
                       'estimate_kind must equal the order pricing_mode')

    prior = [e for e in db.estimates.values()
             if e['order_id'] == oid and e['status'] in ('ISSUED', 'ACCEPTED')]
    prior.sort(key=lambda e: (e['created_at'], e['id']))
    prior_est = prior[-1] if prior else None
    if prior_est is not None:
        was_accepted = prior_est['status'] == 'ACCEPTED'
        prior_est['status'] = 'SUPERSEDED'
        touch(prior_est)
        if was_accepted:
            order['estimated_weight_lbs'] = None

    tariff = order_tariff(order)
    packing = vals.get('packing_services_cents', 0)
    line = calc.linehaul_cents(tariff, order['mileage'], vals['estimated_weight_lbs'])
    fuel = calc.fuel_cents(line, tariff)
    elected = elected_coverage_for(order)
    premium = elected['premium_cents'] if elected else 0
    issued = now()
    est = new_entity()
    est.update({
        'order_id': oid,
        'supersedes_estimate_id': prior_est['id'] if prior_est else None,
        'estimate_kind': vals['estimate_kind'],
        'estimated_weight_lbs': vals['estimated_weight_lbs'],
        'packing_services_cents': packing,
        'linehaul_cents': line,
        'fuel_surcharge_cents': fuel,
        'valuation_premium_cents': premium,
        'estimated_charges_cents': line + fuel + premium + packing,
        'revision_number': (prior_est['revision_number'] + 1) if prior_est else 1,
        'issued_at': issued,
        'expires_at': issued + timedelta(days=calc.ESTIMATE_VALIDITY_DAYS),
        'status': 'ISSUED',
    })
    db.estimates[est['id']] = est
    touch(order)
    return ok(estimate_view(est), 201)


@bp.get('/estimates')
def list_estimates():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'supersedes_estimate_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda e, p=param, v=v: e[p] == v)
    return apply_list(db.estimates, filters, estimate_view)


@bp.get('/estimates/<eid>')
def get_estimate(eid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(estimate_view(get_path(db.estimates, eid)))


@bp.post('/estimates/<eid>/accept')
def accept_estimate(eid):
    auth = authenticate()
    authorize(auth, ['Customer'])
    est = get_path(db.estimates, eid)
    check_order_scope(auth, est['order_id'])
    check_body(get_body(), [])
    if est['status'] != 'ISSUED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'estimate is not ISSUED')
    order = db.orders[est['order_id']]
    if order['status'] != 'REGISTERED':
        raise ApiError('ERR_ORDER_NOT_REGISTERED', 409, 'order is not REGISTERED')
    if now() > est['expires_at']:
        est['status'] = 'EXPIRED'
        touch(est)
        raise ApiError('ERR_ESTIMATE_EXPIRED', 422, 'estimate has expired')
    est['status'] = 'ACCEPTED'
    touch(est)
    order['estimated_weight_lbs'] = est['estimated_weight_lbs']
    touch(order)
    return ok(estimate_view(est))


@bp.post('/estimates/<eid>/decline')
def decline_estimate(eid):
    auth = authenticate()
    authorize(auth, ['Customer'])
    est = get_path(db.estimates, eid)
    check_order_scope(auth, est['order_id'])
    check_body(get_body(), [])
    if est['status'] != 'ISSUED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'estimate is not ISSUED')
    est['status'] = 'DECLINED'
    touch(est)
    return ok(estimate_view(est))


# ---------------------------------------------------------------------------
# Valuation coverages
# ---------------------------------------------------------------------------

@bp.post('/orders/<oid>/valuation-coverages')
def create_coverage(oid):
    auth = authenticate()
    authorize(auth, ['BookingAgent', 'Customer'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    vals = check_body(get_body(), [
        ('coverage_type', 'enum', True, ('RELEASED_VALUE', 'FULL_VALUE_PROTECTION')),
        ('declared_value_cents', 'int', False, (0, None)),
        ('deductible_cents', 'enum_int', False, (0, 25000, 50000)),
        ('expected_order_version', 'int', True, None),
    ])
    declared = vals.get('declared_value_cents', 0)
    deductible = vals.get('deductible_cents', 0)
    if vals['coverage_type'] == 'FULL_VALUE_PROTECTION':
        if declared <= 0:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'declared_value_cents must be > 0 for FULL_VALUE_PROTECTION')
    else:
        declared = 0
    if order['status'] != 'REGISTERED':
        raise ApiError('ERR_ORDER_NOT_REGISTERED', 409, 'order is not REGISTERED')
    if vals['expected_order_version'] != order['version']:
        raise ApiError('ERR_STALE_ORDER_VERSION', 412,
                       'expected_order_version does not match the current order version')
    for c in db.coverages.values():
        if c['order_id'] == oid and c['status'] == 'ELECTED':
            c['status'] = 'SUPERSEDED'
            touch(c)
    premium = calc.valuation_premium(vals['coverage_type'], declared, deductible)
    cov = new_entity()
    cov.update({
        'order_id': oid,
        'coverage_type': vals['coverage_type'],
        'declared_value_cents': declared,
        'deductible_cents': deductible,
        'premium_cents': premium,
        'status': 'ELECTED',
    })
    db.coverages[cov['id']] = cov
    touch(order)
    return ok(coverage_view(cov), 201)


@bp.get('/valuation-coverages')
def list_coverages():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda c, p=param, v=v: c[p] == v)
    return apply_list(db.coverages, filters, coverage_view)


@bp.get('/valuation-coverages/<cid>')
def get_coverage(cid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(coverage_view(get_path(db.coverages, cid)))
