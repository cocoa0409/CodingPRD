"""Booking, passenger, and credit endpoints (PRD 3.5, 3.6, 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import domain as D
from domain import (
    ser_booking, ser_passenger, ser_credit, sort_created, get_or_404,
    passengers_of, bookings_of_flight,
)
from envelope import success
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_BOOKING_HOLD_EXPIRED,
    ERR_SEAT_CAPACITY_EXCEEDED,
    ERR_DUPLICATE_PASSENGER,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_CREDIT_NOT_REDEEMABLE,
    ERR_WAIVER_VERSION_STALE,
    ERR_WAIVER_NOT_SIGNED,
    ERR_BRIEFING_INCOMPLETE,
    ERR_SEAT_NUMBER_TAKEN,
)
from store import db, now, new_entity, touch
from validate import get_body, authenticate, require_role, paginated, _str, _int, _enum, _list

bp = Blueprint('bookings', __name__)

BOOKING_READ_ROLES = ('OpsAdmin', 'Dispatcher', 'BookingAgent', 'ComplianceOfficer')
AGENT = ('BookingAgent',)


@bp.route('/bookings', methods=['POST'])
def create_booking():
    body = get_body()
    flight_id = _str(body, 'flight_id', True)
    contact_name = _str(body, 'contact_name', True)
    contact_email = _str(body, 'contact_email', True)
    passengers = _list(body, 'passengers', True)
    parsed_pax = []
    for entry in passengers:
        if not isinstance(entry, dict):
            raise_error(ERR_INVALID_REQUEST, 'passengers entries must be objects')
        full_name = entry.get('full_name')
        declared = entry.get('declared_weight_lb')
        if not isinstance(full_name, str) or full_name is None:
            raise_error(ERR_INVALID_REQUEST, 'passenger full_name is required')
        if isinstance(declared, bool) or not isinstance(declared, int):
            raise_error(ERR_INVALID_REQUEST, 'passenger declared_weight_lb must be an integer')
        parsed_pax.append((full_name, declared))
    _, role = authenticate()
    require_role(role, AGENT)
    flight = get_or_404(db.flights, flight_id, 'Flight')
    aircraft = db.aircraft[flight['aircraft_id']]
    base = db.bases[flight['base_id']]
    # Gates in order (PRD 3.5): provisional weight estimate, then capacity,
    # then duplicate-passenger constraint.
    D.estimate_gate(flight, [w for _, w in parsed_pax])
    seat_count = len(parsed_pax)
    seats_available = aircraft['seat_capacity'] - D.seats_booked(flight)
    if seat_count > seats_available:
        raise_error(ERR_SEAT_CAPACITY_EXCEEDED, 'seat_count exceeds flight seats_available')
    names = [n for n, _ in parsed_pax]
    if len(set(names)) != len(names):
        raise_error(ERR_DUPLICATE_PASSENGER, 'Two passengers share a full_name in one booking')
    per_seat, total, season_id = D.seat_price_quote(flight, seat_count)
    created = now()
    b = new_entity()
    b.update({
        'flight_id': flight['id'],
        'contact_name': contact_name,
        'contact_email': contact_email,
        'status': 'HELD',
        'seat_count': seat_count,
        'quoted_per_seat_cents': per_seat,
        'quoted_total_cents': total,
        'season_id': season_id,
        'credits_applied_cents': 0,
        'paid_cents': 0,
        'refunded_card_cents': 0,
        'credited_cents': 0,
        'retained_fee_cents': 0,
        'waiver_version_pinned': base['current_waiver_version'],
        'expires_at': created + timedelta(minutes=base['hold_expire_minutes']),
    })
    db.bookings[b['id']] = b
    for idx, (full_name, declared) in enumerate(parsed_pax):
        p = new_entity()
        p.update({
            'booking_id': b['id'],
            'pax_index': idx,
            'full_name': full_name,
            'declared_weight_lb': declared,
            'waiver_signed': False,
            'waiver_version_signed': None,
            'briefing_completed': False,
            'checked_in': False,
            'actual_weight_lb': None,
            'seat_number': None,
        })
        db.passengers[p['id']] = p
    return success(ser_booking(b), status=201)


@bp.route('/bookings', methods=['GET'])
def list_bookings():
    _, role = authenticate()
    require_role(role, BOOKING_READ_ROLES)
    items = sort_created(db.bookings.values())
    for param in ('flight_id', 'status', 'contact_email'):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b[param] == v]
    page, meta = paginated(items)
    return success([ser_booking(b) for b in page], response_type='array', pagination=meta)


@bp.route('/bookings/<bid>', methods=['GET'])
def get_booking(bid):
    _, role = authenticate()
    require_role(role, BOOKING_READ_ROLES)
    b = get_or_404(db.bookings, bid, 'Booking')
    return success(ser_booking(b))


def _hold_live_or_fail(booking):
    if booking['expires_at'] is not None and now() >= booking['expires_at']:
        raise_error(ERR_BOOKING_HOLD_EXPIRED, 'Booking hold has expired')


@bp.route('/bookings/<bid>/apply-credit', methods=['POST'])
def apply_credit(bid):
    body = get_body()
    credit_id = _str(body, 'credit_id', True)
    _, role = authenticate()
    require_role(role, AGENT)
    b = get_or_404(db.bookings, bid, 'Booking')
    credit = get_or_404(db.credits, credit_id, 'RebookingCredit')
    if b['status'] != 'HELD':
        raise_error(ERR_INVALID_STATE, 'apply-credit requires a HELD booking')
    _hold_live_or_fail(b)
    if D.credit_effective_status(credit) not in ('ISSUED', 'PARTIALLY_REDEEMED') \
            or credit['amount_cents'] - credit['redeemed_cents'] <= 0:
        raise_error(ERR_CREDIT_NOT_REDEEMABLE, 'Credit is not redeemable')
    balance_due = b['quoted_total_cents'] - b['credits_applied_cents']
    consume = min(credit['amount_cents'] - credit['redeemed_cents'], balance_due)
    if consume > 0:
        credit['redeemed_cents'] += consume
        b['credits_applied_cents'] += consume
        db.credit_applications.append({
            'booking_id': b['id'],
            'credit_id': credit['id'],
            'amount_cents': consume,
        })
        if credit['redeemed_cents'] >= credit['amount_cents']:
            credit['status'] = 'REDEEMED'
        else:
            credit['status'] = 'PARTIALLY_REDEEMED'
        touch(credit)
        touch(b)
    return success(ser_booking(b))


@bp.route('/bookings/<bid>/confirm', methods=['POST'])
def confirm_booking(bid):
    body = get_body()
    card_amount = _int(body, 'card_amount_cents', True)
    _, role = authenticate()
    require_role(role, AGENT)
    b = get_or_404(db.bookings, bid, 'Booking')
    if b['status'] != 'HELD':
        raise_error(ERR_INVALID_STATE, 'confirm requires a HELD booking')
    _hold_live_or_fail(b)
    flight = db.flights[b['flight_id']]
    if flight['status'] not in ('SCHEDULED', 'DELAYED'):
        raise_error(ERR_INVALID_STATE, 'Flight no longer accepts confirmations')
    if card_amount != b['quoted_total_cents'] - b['credits_applied_cents']:
        raise_error(ERR_PAYMENT_AMOUNT_MISMATCH, 'card_amount_cents must equal the exact balance due')
    b['status'] = 'CONFIRMED'
    b['paid_cents'] = card_amount
    b['expires_at'] = None
    touch(b)
    return success(ser_booking(b))


@bp.route('/bookings/<bid>/events', methods=['POST'])
def booking_events(bid):
    body = get_body()
    _enum(body, 'event_type', True, ('CANCEL',))
    _, role = authenticate()
    require_role(role, AGENT)
    b = get_or_404(db.bookings, bid, 'Booking')
    if b['status'] not in ('HELD', 'CONFIRMED', 'CHECKED_IN'):
        raise_error(ERR_INVALID_STATE, 'Booking state does not permit CANCEL')
    if b['status'] == 'HELD':
        D.release_applied_credits(b)
        b['status'] = 'CANCELLED'
        touch(b)
        return success(ser_booking(b))
    # Voluntary cancellation settlement tiers (PRD 3.8).
    flight = db.flights[b['flight_id']]
    minutes_until = int((flight['scheduled_departure_utc'] - now()).total_seconds() // 60)
    paid = b['paid_cents']
    if minutes_until >= D.REFUND_FULL_MIN:
        refunded, retained, credited = paid, 0, 0
    elif minutes_until >= D.REFUND_PARTIAL_MIN:
        retained = D.rhu_div(paid * D.PARTIAL_FEE_BPS, 10000)
        refunded, credited = paid - retained, 0
    else:
        credited = D.rhu_div(paid * D.CREDIT_ONLY_BPS, 10000)
        retained, refunded = paid - credited, 0
    b['refunded_card_cents'] += refunded
    b['retained_fee_cents'] += retained
    b['credited_cents'] += credited
    if credited > 0:
        D.mint_credit(b, credited)
    # Consumed credits are re-minted in full as a fresh credit.
    if b['credits_applied_cents'] > 0:
        D.mint_credit(b, b['credits_applied_cents'])
    b['status'] = 'CANCELLED'
    touch(b)
    return success(ser_booking(b))


@bp.route('/bookings/<bid>/move', methods=['POST'])
def move_booking(bid):
    body = get_body()
    new_flight_id = _str(body, 'new_flight_id', True)
    expected = _int(body, 'expected_booking_version', True)
    additional_card = _int(body, 'additional_card_cents', False)
    _, role = authenticate()
    require_role(role, AGENT)
    b = get_or_404(db.bookings, bid, 'Booking')
    new_flight = get_or_404(db.flights, new_flight_id, 'Flight')
    if expected != b['version']:
        raise_error(ERR_STALE_VERSION, 'expected_booking_version does not match the booking version')
    if b['status'] != 'CONFIRMED':
        raise_error(ERR_INVALID_STATE, 'move requires a CONFIRMED booking')
    if any(p['checked_in'] for p in passengers_of(b['id'])):
        raise_error(ERR_INVALID_STATE, 'Cannot move a booking with checked-in passengers')
    if new_flight['status'] not in ('SCHEDULED', 'DELAYED'):
        raise_error(ERR_INVALID_STATE, 'Target flight must be SCHEDULED or DELAYED')
    # Weight before capacity (PRD 3.8).
    D.estimate_gate(new_flight, [p['declared_weight_lb'] for p in passengers_of(b['id'])])
    new_aircraft = db.aircraft[new_flight['aircraft_id']]
    if b['seat_count'] > new_aircraft['seat_capacity'] - D.seats_booked(new_flight):
        raise_error(ERR_SEAT_CAPACITY_EXCEEDED, 'seat_count exceeds target flight seats_available')
    per_seat, total, season_id = D.seat_price_quote(new_flight, b['seat_count'])
    delta = total - b['quoted_total_cents']
    if delta > 0:
        if additional_card != delta:
            raise_error(ERR_PAYMENT_AMOUNT_MISMATCH, 'additional_card_cents must equal the positive delta')
        b['paid_cents'] += delta
    elif delta < 0:
        # PRD 3.8: card refund is min(|delta|, paid_cents); paid_cents itself
        # does NOT decrease — it stays as the historical amount paid so that
        # credits_applied_cents = new quoted_total - paid_cents is the
        # recomposition required by the relock rule.
        refund = min(-delta, b['paid_cents'])
        b['refunded_card_cents'] += refund
        excess = -delta - refund
        if excess > 0:
            D.mint_credit(b, excess)
    b['flight_id'] = new_flight['id']
    b['quoted_per_seat_cents'] = per_seat
    b['quoted_total_cents'] = total
    b['season_id'] = season_id
    b['credits_applied_cents'] = total - b['paid_cents']
    touch(b)
    return success(ser_booking(b))


# ---------------------------------------------------------------------------
# Passengers
# ---------------------------------------------------------------------------

@bp.route('/passengers', methods=['GET'])
def list_passengers():
    _, role = authenticate()
    require_role(role, BOOKING_READ_ROLES)
    items = list(db.passengers.values())
    booking_filter = request.args.get('booking_id')
    if booking_filter is not None:
        items = [p for p in items if p['booking_id'] == booking_filter]

    def sort_key(p):
        booking = db.bookings.get(p['booking_id'])
        anchor = (booking['created_at'], booking['_seq']) if booking else (p['created_at'], p['_seq'])
        return (anchor, p['pax_index'])

    items.sort(key=sort_key)
    page, meta = paginated(items)
    return success([ser_passenger(p) for p in page], response_type='array', pagination=meta)


@bp.route('/passengers/<pid>', methods=['GET'])
def get_passenger(pid):
    _, role = authenticate()
    require_role(role, BOOKING_READ_ROLES)
    p = get_or_404(db.passengers, pid, 'Passenger')
    return success(ser_passenger(p))


@bp.route('/passengers/<pid>/events', methods=['POST'])
def passenger_events(pid):
    body = get_body()
    event_type = _enum(body, 'event_type', True, ('SIGN_WAIVER', 'COMPLETE_BRIEFING', 'CHECK_IN', 'UNCHECK'))
    waiver_version = None
    actual_weight = None
    seat_number = None
    if event_type == 'SIGN_WAIVER':
        waiver_version = _str(body, 'waiver_version', True)
    if event_type == 'CHECK_IN':
        actual_weight = _int(body, 'actual_weight_lb', True)
        seat_number = _int(body, 'seat_number', True)
    _, role = authenticate()
    require_role(role, AGENT)
    p = get_or_404(db.passengers, pid, 'Passenger')
    booking = db.bookings[p['booking_id']]
    if event_type == 'SIGN_WAIVER':
        if waiver_version != booking['waiver_version_pinned']:
            raise_error(ERR_WAIVER_VERSION_STALE, 'waiver_version does not match the pinned version')
        p['waiver_signed'] = True
        p['waiver_version_signed'] = waiver_version
        touch(p)
    elif event_type == 'COMPLETE_BRIEFING':
        p['briefing_completed'] = True
        touch(p)
    elif event_type == 'CHECK_IN':
        if p['checked_in']:
            raise_error(ERR_INVALID_STATE, 'Passenger is already checked in')
        if booking['status'] not in ('CONFIRMED', 'CHECKED_IN'):
            raise_error(ERR_INVALID_STATE, 'Booking state does not permit check-in')
        if not p['waiver_signed']:
            raise_error(ERR_WAIVER_NOT_SIGNED, 'Waiver must be signed before check-in')
        if not p['briefing_completed']:
            raise_error(ERR_BRIEFING_INCOMPLETE, 'Briefing must be completed before check-in')
        flight = db.flights[booking['flight_id']]
        aircraft = db.aircraft[flight['aircraft_id']]
        if seat_number < 0 or seat_number >= aircraft['seat_capacity']:
            raise_error(ERR_SEAT_NUMBER_TAKEN, 'seat_number outside the aircraft seat range')
        for other_b in bookings_of_flight(flight['id']):
            for other_p in passengers_of(other_b['id']):
                if other_p['id'] != p['id'] and other_p['checked_in'] and other_p['seat_number'] == seat_number:
                    raise_error(ERR_SEAT_NUMBER_TAKEN, 'seat_number already held on this flight')
        p['actual_weight_lb'] = actual_weight
        p['seat_number'] = seat_number
        p['checked_in'] = True
        touch(p)
        if all(x['checked_in'] for x in passengers_of(booking['id'])):
            if booking['status'] == 'CONFIRMED':
                booking['status'] = 'CHECKED_IN'
                touch(booking)
    else:  # UNCHECK
        if not p['checked_in']:
            raise_error(ERR_INVALID_STATE, 'Passenger is not checked in')
        if booking['status'] not in ('CHECKED_IN', 'CONFIRMED'):
            raise_error(ERR_INVALID_STATE, 'Booking state does not permit uncheck')
        p['actual_weight_lb'] = None
        p['seat_number'] = None
        p['checked_in'] = False
        touch(p)
        if booking['status'] == 'CHECKED_IN':
            booking['status'] = 'CONFIRMED'
            touch(booking)
    return success(ser_passenger(p))


# ---------------------------------------------------------------------------
# Rebooking credits
# ---------------------------------------------------------------------------

@bp.route('/credits', methods=['GET'])
def list_credits():
    _, role = authenticate()
    require_role(role, BOOKING_READ_ROLES)
    items = sort_created(db.credits.values())
    booking_filter = request.args.get('booking_id')
    if booking_filter is not None:
        items = [c for c in items if c['booking_id'] == booking_filter]
    status = request.args.get('status')
    if status is not None:
        items = [c for c in items if D.credit_effective_status(c) == status]
    page, meta = paginated(items)
    return success([ser_credit(c) for c in page], response_type='array', pagination=meta)


@bp.route('/credits/<cid>', methods=['GET'])
def get_credit(cid):
    _, role = authenticate()
    require_role(role, BOOKING_READ_ROLES)
    c = get_or_404(db.credits, cid, 'RebookingCredit')
    return success(ser_credit(c))
