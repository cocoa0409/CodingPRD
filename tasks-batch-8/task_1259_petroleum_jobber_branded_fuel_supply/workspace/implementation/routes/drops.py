from datetime import timedelta

from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_AGREEMENT_NOT_ACTIVE, ERR_CREDIT_LIMIT_EXCEEDED,
                    ERR_DEALER_STATION_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_PRICE_NOT_POSTED, ERR_PRODUCT_NOT_FOUND,
                    ERR_SAFE_FILL_EXCEEDED, ERR_STALE_VERSION,
                    ERR_STATION_NOT_ACTIVE, ERR_STORAGE_TANK_NOT_FOUND,
                    ERR_TANK_SETTLE_WINDOW, ERR_TRANSPORT_DROP_NOT_FOUND,
                    ERR_TRUCK_CAPACITY_EXCEEDED, ERR_TRUCK_NOT_FOUND,
                    ERR_TRUCK_WINDOW_CONFLICT, ERR_VALIDATION_FAILED)
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import calc, cascade
from validate import (apply_filters, get_body, list_response, parse_dt_str,
                      sorted_default, validate_body)

bp = Blueprint('drops', __name__)

_OPEN_STATUSES = {'PLANNED', 'SCHEDULED', 'EN_ROUTE'}
_SETTLE_GAP = timedelta(hours=4)


def _check_truck_capacity(planned_gallons, truck):
    if planned_gallons > truck['capacity_gallons']:
        raise err(ERR_TRUCK_CAPACITY_EXCEEDED,
                  'planned_gallons exceeds truck capacity')


def _check_safe_fill(planned_gallons, tank):
    ceiling = calc.D(tank['capacity_gallons']) * calc.D(tank['safe_fill_pct'])
    if calc.D(planned_gallons) + calc.D(tank['physical_gallons']) > ceiling:
        raise err(ERR_SAFE_FILL_EXCEEDED, 'Safe fill ceiling exceeded')


def _check_truck_window(truck_id, ws, we):
    for d in db.STORE['drops'].values():
        if d['truck_id'] != truck_id or d['status'] not in _OPEN_STATUSES:
            continue
        # Half-open overlap: [ws, we) vs [d.ws, d.we); adjacency allowed.
        if ws < d['window_end'] and d['window_start'] < we:
            raise err(ERR_TRUCK_WINDOW_CONFLICT,
                      'Truck window overlaps an existing drop')


def _check_tank_settle(tank_id, ws, we):
    for d in db.STORE['drops'].values():
        if d['tank_id'] != tank_id or d['status'] not in _OPEN_STATUSES:
            continue
        if ws >= d['window_end']:
            gap = (ws - d['window_end']).total_seconds()
        elif d['window_start'] >= we:
            gap = (d['window_start'] - we).total_seconds()
        else:
            gap = -1.0  # overlapping windows never leave a settle buffer
        if gap < _SETTLE_GAP.total_seconds():
            raise err(ERR_TANK_SETTLE_WINDOW,
                      'Same-tank drops require a 4h settle buffer')


def _resolve_price_or_422(station, product_id, on_date_str):
    posting = calc.resolve_posted_posting(station['home_terminal_code'],
                                          product_id, on_date_str)
    if posting is None:
        raise err(ERR_PRICE_NOT_POSTED,
                  'No POSTED price resolvable for this drop')
    return posting


def _estimate_and_credit_check(station, product, planned_gallons):
    posting = _resolve_price_or_422(station, product['id'],
                                    db.clock_date_str())
    amounts = calc.invoice_amounts(planned_gallons,
                                   posting['price_tc_per_gal'], product,
                                   station)
    estimate = amounts['total_cents']
    projected = station['current_exposure_cents'] + estimate
    if projected > station['credit_limit_cents']:
        raise err(ERR_CREDIT_LIMIT_EXCEEDED,
                  'Projected exposure exceeds credit limit')
    return estimate


def _run_planning_gates(station, tank, truck, product, planned_gallons,
                        ws, we):
    """Safety (7) -> temporal (8) -> price (9) -> credit (10)."""
    _check_truck_capacity(planned_gallons, truck)
    _check_safe_fill(planned_gallons, tank)
    _check_truck_window(truck['id'], ws, we)
    _check_tank_settle(tank['id'], ws, we)
    return _estimate_and_credit_check(station, product, planned_gallons)


@bp.route('/api/transport-drops', methods=['POST'])
def create_drop():
    uid, role = auth_context()
    require_role(role, {'Dispatcher'})
    body = validate_body(get_body(), {
        'station_id': {'type': 'str', 'required': True},
        'tank_id': {'type': 'str', 'required': True},
        'truck_id': {'type': 'str', 'required': True},
        'product_id': {'type': 'str', 'required': True},
        'planned_gallons': {'type': 'int', 'required': True, 'gt': 0},
        'window_start': {'type': 'datetime', 'required': True},
        'window_end': {'type': 'datetime', 'required': True},
    })
    ws = parse_dt_str(body['window_start'])
    we = parse_dt_str(body['window_end'])
    if not ws < we:
        raise err(ERR_VALIDATION_FAILED,
                  'window_start must be before window_end')
    # Body FK existence, in declared order.
    station = db.get_or_404('stations', body['station_id'],
                            ERR_DEALER_STATION_NOT_FOUND)
    tank = db.get_or_404('tanks', body['tank_id'], ERR_STORAGE_TANK_NOT_FOUND)
    truck = db.get_or_404('trucks', body['truck_id'], ERR_TRUCK_NOT_FOUND)
    product = db.get_or_404('products', body['product_id'],
                            ERR_PRODUCT_NOT_FOUND)
    # Referential integrity of the receiving tank.
    if tank['station_id'] != station['id']:
        raise err(ERR_VALIDATION_FAILED,
                  'tank does not belong to the station')
    if tank['product_id'] != product['id']:
        raise err(ERR_VALIDATION_FAILED,
                  'product_id must equal the tank product')
    # Cross-entity state gates.
    if station['operating_status'] != 'ACTIVE':
        raise err(ERR_STATION_NOT_ACTIVE, 'Station is not ACTIVE')
    if not any(a['station_id'] == station['id'] and a['status'] == 'ACTIVE'
               for a in db.STORE['agreements'].values()):
        raise err(ERR_AGREEMENT_NOT_ACTIVE,
                  'Station has no ACTIVE supply agreement')
    estimate = _run_planning_gates(station, tank, truck, product,
                                   body['planned_gallons'], ws, we)
    rec = {
        'id': db.new_id(),
        'station_id': station['id'],
        'tank_id': tank['id'],
        'truck_id': truck['id'],
        'product_id': product['id'],
        'planned_gallons': body['planned_gallons'],
        'window_start': ws,
        'window_end': we,
        'delivered_gallons': None,
        'delivered_at': None,
        'estimated_amount_cents': estimate,
        'invoice_id': None,
        'failure_count': 0,
        'failure_reason': None,
        'status': 'PLANNED',
    }
    db.stamp_new(rec)
    db.STORE['drops'][rec['id']] = rec
    return ok_object(serializers.drop(rec), 201)


@bp.route('/api/transport-drops', methods=['GET'])
def list_drops():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['drops'].values())
    items = scoped(items, uid, role, lambda d: d['station_id'])
    items = apply_filters(items, {
        'station_id': request.args.get('station_id'),
        'tank_id': request.args.get('tank_id'),
        'truck_id': request.args.get('truck_id'),
        'product_id': request.args.get('product_id'),
        'invoice_id': request.args.get('invoice_id'),
        'status': request.args.get('status'),
    })
    return list_response(items, serializers.drop)


@bp.route('/api/transport-drops/<did>', methods=['GET'])
def get_drop(did):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('drops', did, ERR_TRANSPORT_DROP_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    return ok_object(serializers.drop(rec))


def _drop_action(did, from_status, to_status):
    uid, role = auth_context()
    require_role(role, {'Dispatcher'})
    rec = db.get_or_404('drops', did, ERR_TRANSPORT_DROP_NOT_FOUND)
    if rec['status'] != from_status:
        raise err(ERR_INVALID_STATE,
                  'status must be {}'.format(from_status))
    rec['status'] = to_status
    db.touch(rec)
    return ok_object(serializers.drop(rec))


@bp.route('/api/transport-drops/<did>/schedule', methods=['POST'])
def schedule_drop(did):
    return _drop_action(did, 'PLANNED', 'SCHEDULED')


@bp.route('/api/transport-drops/<did>/dispatch', methods=['POST'])
def dispatch_drop(did):
    return _drop_action(did, 'SCHEDULED', 'EN_ROUTE')


@bp.route('/api/transport-drops/<did>/deliver', methods=['POST'])
def deliver_drop(did):
    uid, role = auth_context()
    require_role(role, {'Dispatcher'})
    body = validate_body(get_body(), {
        'delivered_gallons': {'type': 'int', 'required': True, 'gt': 0},
    })
    rec = db.get_or_404('drops', did, ERR_TRANSPORT_DROP_NOT_FOUND)
    if rec['status'] != 'EN_ROUTE':
        raise err(ERR_INVALID_STATE, 'status must be EN_ROUTE')
    station = db.STORE['stations'][rec['station_id']]
    product = db.STORE['products'][rec['product_id']]
    posting = _resolve_price_or_422(station, product['id'],
                                    db.clock_date_str())
    gallons = body['delivered_gallons']
    amounts = calc.invoice_amounts(gallons, posting['price_tc_per_gal'],
                                   product, station)
    invoice_date = db.clock_date_str()
    due = (db.clock_now().date()
           + timedelta(days=station['credit_terms_days'])).isoformat()
    invoice = {
        'id': db.new_id(),
        'station_id': station['id'],
        'drop_id': rec['id'],
        'product_id': product['id'],
        'gallons_delivered': gallons,
        'price_tc_per_gal': posting['price_tc_per_gal'],
        'fuel_amount_cents': amounts['fuel_amount_cents'],
        'freight_amount_cents': amounts['freight_amount_cents'],
        'tax_amount_cents': amounts['tax_amount_cents'],
        'total_cents': amounts['total_cents'],
        'invoice_date': invoice_date,
        'due_date': due,
        'status': 'ISSUED',
    }
    db.stamp_new(invoice)
    db.STORE['invoices'][invoice['id']] = invoice
    rec['delivered_gallons'] = gallons
    rec['delivered_at'] = db.clock_now()
    rec['invoice_id'] = invoice['id']
    rec['status'] = 'DELIVERED'
    db.touch(rec)
    cascade.recompute_exposure(station)
    return ok_object(serializers.drop(rec))


@bp.route('/api/transport-drops/<did>/fail', methods=['POST'])
def fail_drop(did):
    uid, role = auth_context()
    require_role(role, {'Dispatcher'})
    body = validate_body(get_body(), {
        'reason': {'type': 'str', 'required': True},
    })
    rec = db.get_or_404('drops', did, ERR_TRANSPORT_DROP_NOT_FOUND)
    if rec['status'] != 'EN_ROUTE':
        raise err(ERR_INVALID_STATE, 'status must be EN_ROUTE')
    rec['status'] = 'DELIVERY_FAILED'
    rec['failure_count'] += 1
    rec['failure_reason'] = body['reason']
    db.touch(rec)
    return ok_object(serializers.drop(rec))


@bp.route('/api/transport-drops/<did>/replan', methods=['POST'])
def replan_drop(did):
    uid, role = auth_context()
    require_role(role, {'Dispatcher'})
    body = validate_body(get_body(), {
        'expected_drop_version': {'type': 'int', 'required': True},
        'window_start': {'type': 'datetime', 'required': True},
        'window_end': {'type': 'datetime', 'required': True},
        'truck_id': {'type': 'str', 'required': True},
    })
    ws = parse_dt_str(body['window_start'])
    we = parse_dt_str(body['window_end'])
    if not ws < we:
        raise err(ERR_VALIDATION_FAILED,
                  'window_start must be before window_end')
    rec = db.get_or_404('drops', did, ERR_TRANSPORT_DROP_NOT_FOUND)
    truck = db.get_or_404('trucks', body['truck_id'], ERR_TRUCK_NOT_FOUND)
    if rec['status'] != 'DELIVERY_FAILED':
        raise err(ERR_INVALID_STATE, 'status must be DELIVERY_FAILED')
    if body['expected_drop_version'] != rec['version']:
        raise err(ERR_STALE_VERSION, 'Stale drop version')
    station = db.STORE['stations'][rec['station_id']]
    tank = db.STORE['tanks'][rec['tank_id']]
    product = db.STORE['products'][rec['product_id']]
    estimate = _run_planning_gates(station, tank, truck, product,
                                   rec['planned_gallons'], ws, we)
    rec['window_start'] = ws
    rec['window_end'] = we
    rec['truck_id'] = truck['id']
    rec['estimated_amount_cents'] = estimate
    rec['status'] = 'PLANNED'
    db.touch(rec)
    return ok_object(serializers.drop(rec))


@bp.route('/api/transport-drops/<did>/reconcile', methods=['POST'])
def reconcile_drop(did):
    uid, role = auth_context()
    require_role(role, {'Dispatcher'})
    rec = db.get_or_404('drops', did, ERR_TRANSPORT_DROP_NOT_FOUND)
    if rec['status'] != 'DELIVERED':
        raise err(ERR_INVALID_STATE, 'status must be DELIVERED')
    rec['status'] = 'RECONCILED'
    db.touch(rec)
    tank = db.STORE['tanks'][rec['tank_id']]
    cascade.recompute_book(tank)          # cascade hop 1
    cascade.recompute_open_recon(rec['station_id'])  # hops 2-4
    return ok_object(serializers.drop(rec))


@bp.route('/api/transport-drops/<did>/cancel', methods=['POST'])
def cancel_drop(did):
    uid, role = auth_context()
    require_role(role, {'Dispatcher'})
    rec = db.get_or_404('drops', did, ERR_TRANSPORT_DROP_NOT_FOUND)
    if rec['status'] not in ('PLANNED', 'SCHEDULED'):
        raise err(ERR_INVALID_STATE,
                  'status must be PLANNED or SCHEDULED')
    rec['status'] = 'CANCELLED'
    db.touch(rec)
    return ok_object(serializers.drop(rec))
