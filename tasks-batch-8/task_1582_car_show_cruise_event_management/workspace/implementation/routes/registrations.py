"""Registration routes: create, payments, check-in, withdraw, refund-decision."""
from flask import Blueprint, request

from db import STORE, new_id, now_iso, CLOCK
from errors import raise_err
from middleware import require_roles, check_participant_owns
from response import success_object, success_list
from util import body, get_field, get_int, get_pagination, paginate, parse_dt
from services import domain, calculations
from services.serializers import registration_json, payment_json

bp = Blueprint('registrations', __name__)


def _get_registration_or_404(reg_id):
    reg = STORE.registrations.get(reg_id)
    if reg is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Registration not found')
    return reg


def _participant_check_list(user_id, role, items):
    if role == 'Participant':
        return [r for r in items if r['registrant_id'] == user_id]
    return items


@bp.route('/registrations', methods=['POST'])
def create_registration():
    user_id, role = require_roles('Participant', 'RegistrationDesk')
    data = body()
    event_id = get_field(data, 'event_id', type_=str)
    registrant_id = get_field(data, 'registrant_id', type_=str)
    vehicle_id = get_field(data, 'vehicle_id', type_=str)
    class_id = get_field(data, 'class_id', type_=str)
    check_participant_owns(user_id, role, registrant_id)

    # Existence: body FK targets left to right
    ev = STORE.events.get(event_id)
    if ev is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Event not found')
    registrant = STORE.registrants.get(registrant_id)
    if registrant is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Registrant not found')
    vehicle = STORE.vehicles.get(vehicle_id)
    if vehicle is None or vehicle['registrant_id'] != registrant_id:
        raise_err(('ERR_NOT_FOUND', 404), 'Vehicle not found')
    cls = STORE.classes.get(class_id)
    if cls is None or cls['event_id'] != event_id:
        raise_err(('ERR_NOT_FOUND', 404), 'Class not found')

    # Eligibility guards (PRD 3.2)
    if not (cls['min_year'] <= vehicle['year'] <= cls['max_year']):
        raise_err(('ERR_VEHICLE_CLASS_INELIGIBLE', 422),
                  'Vehicle year outside the class eligibility band')
    for r in STORE.registrations.values():
        if (r['event_id'] == event_id and r['vehicle_id'] == vehicle_id
                and r['status'] in domain.NON_TERMINAL_REG_STATUSES):
            raise_err(('ERR_DUPLICATE_REGISTRATION', 409),
                      'Vehicle already has a non-terminal registration for the event')
    if domain.compute_class_confirmed_count(class_id) >= cls['capacity']:
        raise_err(('ERR_CLASS_FULL', 409), 'Class is at capacity')

    tier, fee_cents = calculations.compute_entry_fee(ev, cls, registrant)
    now = now_iso()
    reg = {
        'id': new_id(),
        'event_id': event_id,
        'registrant_id': registrant_id,
        'vehicle_id': vehicle_id,
        'class_id': class_id,
        'pricing_tier': tier,
        'fee_cents': fee_cents,
        'status': 'PENDING_PAYMENT',
        'paid_cents': 0,
        'refunded_cents': 0,
        'assigned_zone_id': None,
        'spot_number': None,
        'checked_in_at': None,
        'withdrawn_at': None,
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.registrations[reg['id']] = reg
    return success_object(registration_json(reg), status=201)


@bp.route('/registrations', methods=['GET'])
def list_registrations():
    user_id, role = require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge')
    limit, offset = get_pagination()
    items = domain.sorted_created(list(STORE.registrations.values()))
    items = _participant_check_list(user_id, role, items)
    for param in ('event_id', 'registrant_id', 'vehicle_id', 'class_id',
                  'assigned_zone_id', 'status'):
        val = request.args.get(param)
        if val:
            items = [r for r in items if str(r.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([registration_json(r) for r in page], limit, offset, total)


@bp.route('/registrations/<reg_id>', methods=['GET'])
def get_registration(reg_id):
    user_id, role = require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge')
    reg = _get_registration_or_404(reg_id)
    check_participant_owns(user_id, role, reg['registrant_id'])
    return success_object(registration_json(reg))


@bp.route('/registrations/<reg_id>/payments', methods=['POST'])
def record_entry_payment(reg_id):
    user_id, role = require_roles('Participant', 'RegistrationDesk')
    reg = _get_registration_or_404(reg_id)
    check_participant_owns(user_id, role, reg['registrant_id'])
    data = body()
    amount_cents = get_int(data, 'amount_cents')
    method = get_field(data, 'method', type_=str)
    if method not in ('CASH', 'CARD', 'CHECK'):
        raise_err(('ERR_VALIDATION', 400), 'method must be CASH, CARD, or CHECK')

    # Target entity state before cross-entity state (PRD 2.9 level 6)
    if reg['status'] != 'PENDING_PAYMENT':
        raise_err(('ERR_INVALID_REGISTRATION_STATE', 409),
                  'Registration is not in PENDING_PAYMENT')
    ev = STORE.events[reg['event_id']]
    if ev['lifecycle_status'] != 'REGISTRATION_OPEN' or \
            ev['weather_posture'] not in ('NORMAL', 'WATCH'):
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Entry-fee payment requires REGISTRATION_OPEN and weather NORMAL/WATCH')
    if amount_cents != reg['fee_cents']:
        raise_err(('ERR_PAYMENT_AMOUNT_MISMATCH', 422),
                  'amount_cents must equal the frozen fee_cents')

    pay = domain.create_payment(reg['id'], None, 'ENTRY_FEE', amount_cents,
                                method, user_id)
    reg['status'] = 'CONFIRMED'
    domain.touch_entity(reg)
    return success_object(payment_json(pay), status=201)


@bp.route('/registrations/<reg_id>/payments', methods=['GET'])
def list_registration_payments(reg_id):
    user_id, role = require_roles('Organizer', 'RegistrationDesk', 'Participant')
    reg = _get_registration_or_404(reg_id)
    check_participant_owns(user_id, role, reg['registrant_id'])
    limit, offset = get_pagination()
    items = domain.sorted_created([p for p in STORE.payments.values()
                                   if p.get('registration_id') == reg_id])
    page, total = paginate(items, limit, offset)
    return success_list([payment_json(p) for p in page], limit, offset, total)


@bp.route('/registrations/<reg_id>/check-in', methods=['POST'])
def check_in(reg_id):
    user_id, role = require_roles('RegistrationDesk')
    reg = _get_registration_or_404(reg_id)
    data = body()
    zone_id = get_field(data, 'zone_id', type_=str)

    # Level 6: registration's own state first
    if reg['status'] != 'CONFIRMED':
        raise_err(('ERR_INVALID_REGISTRATION_STATE', 409),
                  'Registration must be CONFIRMED to check in')
    # Cross-entity event state
    ev = STORE.events[reg['event_id']]
    if ev['lifecycle_status'] not in ('REGISTRATION_OPEN', 'REGISTRATION_LOCKED') \
            or ev['weather_posture'] == 'CANCELLED':
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Check-in requires REGISTRATION_OPEN/LOCKED and weather not CANCELLED')
    # Level 7: waiver safety
    waiver = None
    for w in STORE.waivers.values():
        if w['event_id'] == reg['event_id'] and w['registrant_id'] == reg['registrant_id']:
            waiver = w
            break
    if waiver is None:
        raise_err(('ERR_WAIVER_NOT_SIGNED', 422),
                  'No waiver exists for this registrant and event')
    registrant = STORE.registrants[reg['registrant_id']]
    if registrant.get('is_minor') and not waiver.get('guardian_name'):
        raise_err(('ERR_GUARDIAN_SIGNATURE_REQUIRED', 422),
                  'Minor registrant waiver lacks guardian_name')

    # Zone existence (body FK)
    zone = STORE.zones.get(zone_id)
    if zone is None or zone['event_id'] != reg['event_id']:
        raise_err(('ERR_NOT_FOUND', 404), 'Zone not found')

    # Level 8: arrival window
    if zone.get('arrival_window_start') is not None and \
            zone.get('arrival_window_end') is not None:
        now_dt = parse_dt(CLOCK.now())
        if not (parse_dt(zone['arrival_window_start']) <= now_dt
                < parse_dt(zone['arrival_window_end'])):
            raise_err(('ERR_OUTSIDE_ARRIVAL_WINDOW', 422),
                      'Check-in is outside the zone arrival window')

    # Level 9: zone type then capacity
    if zone['zone_type'] not in ('SHOW_FIELD', 'OVERFLOW'):
        raise_err(('ERR_ZONE_TYPE_INELIGIBLE', 422),
                  'Vehicles may check in only into SHOW_FIELD or OVERFLOW zones')
    if domain.compute_zone_assigned_count(zone_id) >= zone['capacity']:
        raise_err(('ERR_ZONE_FULL', 409), 'Zone is at capacity')

    # Lowest free spot 1..capacity
    taken = {r['spot_number'] for r in STORE.registrations.values()
             if r.get('assigned_zone_id') == zone_id and r['status'] == 'CHECKED_IN'
             and r.get('spot_number') is not None}
    spot = None
    for n in range(1, zone['capacity'] + 1):
        if n not in taken:
            spot = n
            break
    reg['assigned_zone_id'] = zone_id
    reg['spot_number'] = spot
    reg['checked_in_at'] = CLOCK.now()
    reg['status'] = 'CHECKED_IN'
    domain.touch_entity(reg)
    return success_object(registration_json(reg))


@bp.route('/registrations/<reg_id>/withdraw', methods=['POST'])
def withdraw(reg_id):
    user_id, role = require_roles('Participant', 'RegistrationDesk')
    reg = _get_registration_or_404(reg_id)
    check_participant_owns(user_id, role, reg['registrant_id'])
    body()  # optional reason
    ev = STORE.events[reg['event_id']]
    status = reg['status']

    if status == 'PENDING_PAYMENT':
        reg['withdrawn_at'] = CLOCK.now()
        reg['status'] = 'WITHDRAWN'
        domain.touch_entity(reg)
        return success_object(registration_json(reg))

    if status == 'CONFIRMED':
        if ev['weather_posture'] == 'CANCELLED':
            raise_err(('ERR_INVALID_EVENT_STATE', 409),
                      'Weather CANCELLED; refunds route through the weather cascade')
        pct = calculations.withdrawal_refund_pct(ev, CLOCK.now())
        reg['withdrawn_at'] = CLOCK.now()
        if pct > 0:
            reg['status'] = 'REFUND_REQUESTED'
            reg['_refund_pct'] = str(pct)
        else:
            reg['status'] = 'WITHDRAWN'
            domain.void_ballots_for(reg['id'])
        domain.touch_entity(reg)
        return success_object(registration_json(reg))

    if status == 'CHECKED_IN':
        # Day-of pull-out: never refundable; frees spot, voids ballots, reverts awards
        domain.release_spot(reg)
        reg['status'] = 'WITHDRAWN'
        reg['withdrawn_at'] = CLOCK.now()
        domain.touch_entity(reg)
        domain.void_ballots_for(reg['id'])
        domain.revert_awards_won_by(reg['id'])
        return success_object(registration_json(reg))

    raise_err(('ERR_INVALID_REGISTRATION_STATE', 409),
              f'Registration in {status} cannot be withdrawn')


@bp.route('/registrations/<reg_id>/refund-decision', methods=['POST'])
def refund_decision(reg_id):
    user_id, role = require_roles('Organizer')
    reg = _get_registration_or_404(reg_id)
    data = body()
    decision = get_field(data, 'decision', type_=str)
    if decision not in ('APPROVE', 'DENY'):
        raise_err(('ERR_VALIDATION', 400), 'decision must be APPROVE or DENY')
    get_field(data, 'note', required=False, default=None)
    amount_cents = data.get('amount_cents')
    if amount_cents is not None:
        if not isinstance(amount_cents, int) or isinstance(amount_cents, bool):
            raise_err(('ERR_VALIDATION', 400), 'amount_cents must be an integer')

    if reg['status'] != 'REFUND_REQUESTED':
        raise_err(('ERR_INVALID_REGISTRATION_STATE', 409),
                  'Registration is not in REFUND_REQUESTED')

    if decision == 'DENY':
        reg['status'] = 'CONFIRMED'
        reg['withdrawn_at'] = None
        reg.pop('_refund_pct', None)
        domain.touch_entity(reg)
        return success_object(registration_json(reg))

    # APPROVE
    ev = STORE.events[reg['event_id']]
    net_paid = reg['paid_cents'] - reg['refunded_cents']
    if amount_cents is not None:
        amount = amount_cents
    else:
        from decimal import Decimal
        pct = Decimal(reg.get('_refund_pct', '0'))
        amount = calculations.withdrawal_refund_amount(reg, pct)
    if amount > net_paid:
        raise_err(('ERR_REFUND_EXCEEDS_PAID', 422),
                  'Approved refund exceeds net paid')
    if amount > 0:
        domain.create_payment(reg['id'], None, 'REFUND', amount, 'CASH', user_id)
    reg['status'] = 'REFUNDED'
    reg.pop('_refund_pct', None)
    domain.touch_entity(reg)
    domain.void_ballots_for(reg['id'])
    domain.revert_awards_won_by(reg['id'])
    return success_object(registration_json(reg))
