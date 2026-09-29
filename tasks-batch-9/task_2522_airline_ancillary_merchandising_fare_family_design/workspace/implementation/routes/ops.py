"""Flights, the seat map, the demand feed and irregular-operations waivers."""
from flask import Blueprint

import calc
import envelope as env
import ser
import svc
import validate as v
from errors import fail
from store import by_created, common_fields, db, now, touch

bp = Blueprint('ops', __name__)

SALES_PHASE = ('PRESALE', 'CHECKIN_OPEN', 'BOARDING', 'DEPARTED')
IROPS_STATE = ('NORMAL', 'IRREGULAR', 'RECOVERED')
ZONE = ('FWD', 'MID', 'AFT', 'EXIT_ROW', 'BULKHEAD')
SEGMENT_STATE = ('OPEN', 'CLOSED')
EVENT_TYPE = ('DELAY', 'CANCELLATION', 'DIVERSION')
WAIVER_STATE = ('ACTIVE', 'RESCINDED', 'EXPIRED')


@bp.post('/flights')
def create_flight():
    v.ctx(('OperationsController',))
    data = v.fields(v.body(), [
        ('flight_no', True, lambda x: v.v_str(x)),
        ('origin', True, lambda x: v.v_str(x, v.RE_AIRPORT)),
        ('destination', True, lambda x: v.v_str(x, v.RE_AIRPORT)),
        ('scheduled_departure_utc', True, v.v_datetime),
        ('cabin_seat_total', True, lambda x: v.v_int(x, 1)),
    ])
    if data['origin'] == data['destination']:
        fail('ERR_INVALID_REQUEST')
    record = common_fields()
    record.update({
        'flight_no': data['flight_no'], 'origin': data['origin'],
        'destination': data['destination'],
        'scheduled_departure_utc': data['scheduled_departure_utc'],
        'cabin_seat_total': data['cabin_seat_total'],
        'sales_phase': 'PRESALE', 'irops_state': 'NORMAL',
        'booked_load_factor_pct': 0, 'demand_index_bp': 0,
        'demand_tier': 'LOW', 'active_waiver_count': 0,
        'ticketed_booking_count': 0,
    })
    db.flights[record['id']] = record
    return env.created(ser.flight(record))


@bp.get('/flights/<id>')
def read_flight(id):
    v.ctx(v.ALL_ROLES)
    return env.obj(ser.flight(svc.flight_or_404(id)))


@bp.get('/flights')
def list_flights():
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    phase = v.q_enum('sales_phase', SALES_PHASE)
    irops = v.q_enum('irops_state', IROPS_STATE)
    rows = [f for f in db.flights.values()
            if (phase is None or f['sales_phase'] == phase)
            and (irops is None or f['irops_state'] == irops)]
    return env.page(by_created(rows), ser.flight, limit, offset)


@bp.post('/flights/<id>/phase-advance')
def phase_advance(id):
    v.ctx(('OperationsController',))
    data = v.fields(v.body(), [
        ('target_phase', True, lambda x: v.v_enum(x, SALES_PHASE)),
    ])
    flight = svc.flight_or_404(id)
    current = SALES_PHASE.index(flight['sales_phase'])
    target = data['target_phase']
    if current + 1 >= len(SALES_PHASE) or SALES_PHASE[current + 1] != target:
        fail('ERR_PHASE_TRANSITION_INVALID')
    flight['sales_phase'] = target
    if target == 'CHECKIN_OPEN':
        svc.expire_flight_offers(flight, ('BOOKING',))
    elif target == 'BOARDING':
        svc.expire_flight_offers(flight, ('CHECKIN',))
    else:
        svc.depart_flight(flight)
    touch(flight)
    return env.obj(ser.flight(flight))


@bp.post('/flights/<id>/demand-snapshot')
def demand_snapshot(id):
    v.ctx(('OperationsController',))
    data = v.fields(v.body(), [
        ('booked_load_factor_pct', True, lambda x: v.v_int(x, 0, 100)),
        ('demand_index_bp', True, lambda x: v.v_int(x, -5000, 5000)),
    ])
    flight = svc.flight_or_404(id)
    if flight['sales_phase'] == 'DEPARTED':
        fail('ERR_FLIGHT_ALREADY_DEPARTED')
    flight['booked_load_factor_pct'] = data['booked_load_factor_pct']
    flight['demand_index_bp'] = data['demand_index_bp']
    flight['demand_tier'] = calc.demand_tier(data['booked_load_factor_pct'])
    svc.reprice_flight_segments(flight)
    touch(flight)
    return env.obj(ser.flight(flight))


# --------------------------------------------------------------------------
# seat inventory segments
# --------------------------------------------------------------------------
def seat_letters_validator(value):
    return v.v_enum_array(value, v.SEAT_LETTERS, min_len=1, max_len=6,
                          distinct=True)


@bp.post('/seat-segments')
def create_segment():
    v.ctx(('OperationsController',))
    data = v.fields(v.body(), [
        ('flight_id', True, v.v_id),
        ('ancillary_product_id', True, v.v_id),
        ('zone', True, lambda x: v.v_enum(x, ZONE)),
        ('row_start', True, lambda x: v.v_int(x, 1)),
        ('row_end', True, lambda x: v.v_int(x, 1)),
        ('seat_letters', True, seat_letters_validator),
        ('base_price_cents', True, lambda x: v.v_int(x, 0)),
    ])
    if data['row_end'] < data['row_start']:
        fail('ERR_INVALID_REQUEST')
    flight = svc.flight_or_404(data['flight_id'])
    product = svc.product_or_404(data['ancillary_product_id'])
    if flight['sales_phase'] == 'DEPARTED':
        fail('ERR_FLIGHT_ALREADY_DEPARTED')
    if product['category'] != 'SEAT':
        fail('ERR_SEAT_PRODUCT_CATEGORY_INVALID')
    new_seats = set()
    for row in range(data['row_start'], data['row_end'] + 1):
        for letter in data['seat_letters']:
            new_seats.add((row, letter))
    existing = svc.segments_of_flight(flight['id'])
    for segment in existing:
        if segment['segment_state'] != 'OPEN':
            continue
        for row in range(segment['row_start'], segment['row_end'] + 1):
            for letter in segment['seat_letters']:
                if (row, letter) in new_seats:
                    fail('ERR_SEAT_SEGMENT_ROW_OVERLAP')
    total_seats = ((data['row_end'] - data['row_start'] + 1)
                   * len(data['seat_letters']))
    if sum(s['total_seats'] for s in existing) + total_seats > flight['cabin_seat_total']:
        fail('ERR_SEGMENT_EXCEEDS_CABIN')
    record = common_fields()
    record.update({
        'flight_id': flight['id'], 'ancillary_product_id': product['id'],
        'zone': data['zone'], 'row_start': data['row_start'],
        'row_end': data['row_end'], 'seat_letters': list(data['seat_letters']),
        'base_price_cents': data['base_price_cents'],
        'total_seats': total_seats, 'held_seats': 0, 'sold_seats': 0,
        'available_seats': total_seats, 'zone_multiplier_bp': 0,
        'effective_price_cents': 0, 'segment_state': 'OPEN',
    })
    svc.price_segment(record, flight)
    db.segments[record['id']] = record
    return env.created(ser.segment(record))


@bp.get('/seat-segments/<id>')
def read_segment(id):
    v.ctx(v.ALL_ROLES)
    return env.obj(ser.segment(svc.segment_or_404(id)))


@bp.get('/seat-segments')
def list_segments():
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    flight_id = v.q_str('flight_id')
    product_id = v.q_str('ancillary_product_id')
    zone = v.q_enum('zone', ZONE)
    state = v.q_enum('segment_state', SEGMENT_STATE)
    rows = [s for s in db.segments.values()
            if (flight_id is None or s['flight_id'] == flight_id)
            and (product_id is None or s['ancillary_product_id'] == product_id)
            and (zone is None or s['zone'] == zone)
            and (state is None or s['segment_state'] == state)]
    return env.page(by_created(rows), ser.segment, limit, offset)


# --------------------------------------------------------------------------
# irregular-operations waivers
# --------------------------------------------------------------------------
@bp.post('/flights/<id>/irops-waivers')
def declare_waiver(id):
    v.ctx(('OperationsController',))
    data = v.fields(v.body(), [
        ('event_type', True, lambda x: v.v_enum(x, EVENT_TYPE)),
        ('delay_minutes', True, lambda x: v.v_int(x, 0, 1440)),
        ('waiver_scope', True, lambda x: v.v_enum_array(x, v.CATEGORIES,
                                                        min_len=1)),
    ])
    flight = svc.flight_or_404(id)
    if flight['sales_phase'] == 'DEPARTED':
        fail('ERR_FLIGHT_ALREADY_DEPARTED')
    if (data['event_type'] == 'DELAY' and 'CHANGE' in data['waiver_scope']
            and data['delay_minutes'] < calc.IROPS_CHANGE_WAIVER_MIN_DELAY_MINUTES):
        fail('ERR_DELAY_THRESHOLD_NOT_MET')
    record = common_fields()
    record.update({
        'flight_id': flight['id'], 'event_type': data['event_type'],
        'delay_minutes': data['delay_minutes'],
        'waiver_scope': list(data['waiver_scope']),
        'declared_at': now(), 'waiver_state': 'ACTIVE',
        'credited_bookings_count': 0, 'credited_amount_cents': 0,
        'rescind_reason': None,
    })
    db.waivers[record['id']] = record
    svc.declare_waiver(flight, record)
    return env.created(ser.waiver(record))


@bp.get('/irops-waivers/<id>')
def read_waiver(id):
    v.ctx(v.ALL_ROLES)
    return env.obj(ser.waiver(svc.waiver_or_404(id)))


@bp.get('/irops-waivers')
def list_waivers():
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    flight_id = v.q_str('flight_id')
    state = v.q_enum('waiver_state', WAIVER_STATE)
    event_type = v.q_enum('event_type', EVENT_TYPE)
    rows = [w for w in db.waivers.values()
            if (flight_id is None or w['flight_id'] == flight_id)
            and (state is None or w['waiver_state'] == state)
            and (event_type is None or w['event_type'] == event_type)]
    return env.page(by_created(rows), ser.waiver, limit, offset)


@bp.get('/flights/<id>/irops-waivers')
def list_flight_waivers(id):
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    state = v.q_enum('waiver_state', WAIVER_STATE)
    flight = svc.flight_or_404(id)
    rows = [w for w in svc.waivers_of_flight(flight['id'])
            if state is None or w['waiver_state'] == state]
    return env.page(rows, ser.waiver, limit, offset)


@bp.post('/irops-waivers/<id>/rescind')
def rescind_waiver(id):
    v.ctx(('OperationsController',))
    data = v.fields(v.body(), [
        ('rescind_reason', True, lambda x: v.v_str(x)),
    ])
    waiver = svc.waiver_or_404(id)
    if waiver['waiver_state'] != 'ACTIVE':
        fail('ERR_WAIVER_STATE_INVALID')
    flight = db.flights[waiver['flight_id']]
    if flight['sales_phase'] == 'DEPARTED':
        fail('ERR_FLIGHT_ALREADY_DEPARTED')
    waiver['rescind_reason'] = data['rescind_reason']
    svc.rescind_waiver(flight, waiver)
    return env.obj(ser.waiver(waiver))
