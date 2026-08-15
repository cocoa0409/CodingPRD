"""Flight endpoints: scheduling, assignment (OCC), event transitions,
manifest close (OCC). Gate ordering follows PRD 3.3 / 3.7 and the global
validation ladder of PRD 2.9."""
from datetime import timedelta

from flask import Blueprint, request

import domain as D
from domain import ser_flight, sort_created, get_or_404
from envelope import success
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_WEATHER_HOLD_ACTIVE,
    ERR_PILOT_NOT_AVAILABLE,
    ERR_AIRCRAFT_NOT_AVAILABLE,
    ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT,
    ERR_DEPARTURE_IN_PAST,
    ERR_ROUTE_SUSPENDED,
    ERR_SEGREGATION_OF_DUTY,
    ERR_PILOT_MISMATCH,
    ERR_PILOT_ACK_REQUIRED,
)
from store import db, now, new_entity, touch
from validate import get_body, authenticate, require_role, paginated, _str, _int, _enum, _dt

bp = Blueprint('flights', __name__)

FLIGHT_READ_ROLES = ('OpsAdmin', 'Dispatcher', 'BookingAgent', 'ComplianceOfficer', 'CommunityReporter', 'Pilot')
DISPATCHER_EVENTS = ('DELAY', 'ACCEPT_DELAY', 'OPEN_BOARDING', 'DISPATCH', 'COMPLETE', 'CANCEL_WEATHER', 'CANCEL_OPS')
ALL_FLIGHT_EVENTS = DISPATCHER_EVENTS + ('PILOT_ACK',)


def _flight_gates_for_new_slot(base, route, aircraft, pilot, dep, arr, exclude_id=None,
                               check_quiet=True, check_departure_past=True, check_route_active=True):
    """Safety/temporal/constraint gates for flight create (PRD 3.3 order).
    Order: pilot availability, flight time, duty span, aircraft availability,
    noise class, quiet hours, departure-in-past, aircraft turn, pilot overlap,
    route status."""
    if pilot['status'] != 'AVAILABLE':
        raise_error(ERR_PILOT_NOT_AVAILABLE, 'Pilot is not AVAILABLE')
    D.pilot_duty_gate(pilot, dep.date(), route['duration_minutes'], dep, arr, exclude_id=exclude_id)
    if aircraft['status'] != 'AVAILABLE':
        raise_error(ERR_AIRCRAFT_NOT_AVAILABLE, 'Aircraft is not AVAILABLE')
    if route['min_aircraft_noise_class'] == 'QUIET_ONLY' and aircraft['noise_class'] != 'QUIET':
        raise_error(ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT, 'Route requires QUIET_ONLY aircraft')
    if check_quiet:
        D.quiet_hours_gate(base, route, aircraft, dep)
    if check_departure_past and dep <= now():
        raise_error(ERR_DEPARTURE_IN_PAST, 'Departure must be strictly in the future')
    D.turn_window_gates(route, aircraft, pilot, dep, arr, exclude_id=exclude_id)
    if check_route_active and route['status'] != 'ACTIVE':
        raise_error(ERR_ROUTE_SUSPENDED, 'Route is SUSPENDED')


@bp.route('/flights', methods=['POST'])
def create_flight():
    body = get_body()
    base_id = _str(body, 'base_id', True)
    route_id = _str(body, 'route_id', True)
    aircraft_id = _str(body, 'aircraft_id', True)
    pilot_id = _str(body, 'pilot_id', True)
    dep = _dt(body, 'scheduled_departure_utc', True)
    uid, role = authenticate()
    require_role(role, ('Dispatcher',))
    # Body foreign keys validated left to right.
    base = get_or_404(db.bases, base_id, 'Base')
    route = get_or_404(db.routes, route_id, 'Route')
    aircraft = get_or_404(db.aircraft, aircraft_id, 'Aircraft')
    pilot = get_or_404(db.pilots, pilot_id, 'Pilot')
    arr = dep + timedelta(minutes=route['duration_minutes'])
    _flight_gates_for_new_slot(base, route, aircraft, pilot, dep, arr)
    f = new_entity()
    f.update({
        'base_id': base['id'],
        'route_id': route['id'],
        'aircraft_id': aircraft['id'],
        'pilot_id': pilot['id'],
        'scheduled_departure_utc': dep,
        'scheduled_arrival_utc': arr,
        'rotation_seq': None,
        'status': 'SCHEDULED',
        'pilot_acknowledged': False,
        'created_by_user_id': uid,
        'dispatched_by_user_id': None,
        'actual_departure_utc': None,
        'actual_arrival_utc': None,
        'cancel_reason': None,
        'manifested_passenger_count': None,
        'manifested_fuel_lb': None,
        'actual_gross_weight_lb': None,
        'actual_cg_in': None,
    })
    db.flights[f['id']] = f
    D.recompute_rotation(aircraft['id'], dep.date())
    D.get_or_create_duty_day(pilot['id'], dep.date())
    return success(ser_flight(f), status=201)


@bp.route('/flights', methods=['GET'])
def list_flights():
    _, role = authenticate()
    require_role(role, FLIGHT_READ_ROLES)
    items = sort_created(db.flights.values())
    for param in ('base_id', 'route_id', 'aircraft_id', 'pilot_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f[param] == v]
    page, meta = paginated(items)
    return success([ser_flight(f) for f in page], response_type='array', pagination=meta)


@bp.route('/flights/<fid>', methods=['GET'])
def get_flight(fid):
    _, role = authenticate()
    require_role(role, FLIGHT_READ_ROLES)
    f = get_or_404(db.flights, fid, 'Flight')
    return success(ser_flight(f))


@bp.route('/flights/<fid>/assignment', methods=['PATCH'])
def patch_assignment(fid):
    body = get_body()
    expected = _int(body, 'expected_flight_version', True)
    new_pilot_id = _str(body, 'pilot_id', False)
    new_aircraft_id = _str(body, 'aircraft_id', False)
    _, role = authenticate()
    require_role(role, ('Dispatcher',))
    f = get_or_404(db.flights, fid, 'Flight')
    new_pilot = get_or_404(db.pilots, new_pilot_id, 'Pilot') if new_pilot_id else None
    new_aircraft = get_or_404(db.aircraft, new_aircraft_id, 'Aircraft') if new_aircraft_id else None
    if expected != f['version']:
        raise_error(ERR_STALE_VERSION, 'expected_flight_version does not match the flight version')
    if f['status'] not in ('SCHEDULED', 'DELAYED'):
        raise_error(ERR_INVALID_STATE, 'Reassignment requires SCHEDULED or DELAYED')
    pilot = new_pilot or db.pilots[f['pilot_id']]
    aircraft = new_aircraft or db.aircraft[f['aircraft_id']]
    route = db.routes[f['route_id']]
    base = db.bases[f['base_id']]
    dep = f['scheduled_departure_utc']
    arr = f['scheduled_arrival_utc']
    # Re-run the crew-dependent gates for the new crew (PRD 3.3): availability,
    # duty, noise, turn. Quiet-hours and departure-in-past are not re-checked
    # on reassignment (the slot did not move).
    if pilot['status'] != 'AVAILABLE':
        raise_error(ERR_PILOT_NOT_AVAILABLE, 'Pilot is not AVAILABLE')
    D.pilot_duty_gate(pilot, dep.date(), route['duration_minutes'], dep, arr, exclude_id=f['id'])
    if aircraft['status'] != 'AVAILABLE':
        raise_error(ERR_AIRCRAFT_NOT_AVAILABLE, 'Aircraft is not AVAILABLE')
    if route['min_aircraft_noise_class'] == 'QUIET_ONLY' and aircraft['noise_class'] != 'QUIET':
        raise_error(ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT, 'Route requires QUIET_ONLY aircraft')
    D.turn_window_gates(route, aircraft, pilot, dep, arr, exclude_id=f['id'])
    old_aircraft_id = f['aircraft_id']
    f['pilot_id'] = pilot['id']
    f['aircraft_id'] = aircraft['id']
    touch(f)
    D.recompute_rotation(old_aircraft_id, dep.date())
    if aircraft['id'] != old_aircraft_id:
        D.recompute_rotation(aircraft['id'], dep.date())
    D.get_or_create_duty_day(pilot['id'], dep.date())
    return success(ser_flight(f))


def _do_delay(f, new_dep):
    route = db.routes[f['route_id']]
    aircraft = db.aircraft[f['aircraft_id']]
    pilot = db.pilots[f['pilot_id']]
    base = db.bases[f['base_id']]
    new_arr = new_dep + timedelta(minutes=route['duration_minutes'])
    old_date = f['scheduled_departure_utc'].date()
    # Gates in PRD/priority order: flight time, duty span, noise class,
    # quiet hours, departure-in-past, aircraft turn, pilot overlap.
    D.pilot_duty_gate(pilot, new_dep.date(), route['duration_minutes'], new_dep, new_arr, exclude_id=f['id'])
    if route['min_aircraft_noise_class'] == 'QUIET_ONLY' and aircraft['noise_class'] != 'QUIET':
        raise_error(ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT, 'Route requires QUIET_ONLY aircraft')
    D.quiet_hours_gate(base, route, aircraft, new_dep)
    if new_dep <= now():
        raise_error(ERR_DEPARTURE_IN_PAST, 'New departure must be strictly in the future')
    D.turn_window_gates(route, aircraft, pilot, new_dep, new_arr, exclude_id=f['id'])
    f['scheduled_departure_utc'] = new_dep
    f['scheduled_arrival_utc'] = new_arr
    f['status'] = 'DELAYED'
    touch(f)
    D.recompute_rotation(f['aircraft_id'], old_date)
    if new_dep.date() != old_date:
        D.recompute_rotation(f['aircraft_id'], new_dep.date())
    D.get_or_create_duty_day(pilot['id'], new_dep.date())


def _do_dispatch(f, uid):
    base = db.bases[f['base_id']]
    if D.compute_posture(base) != 'NORMAL':
        raise_error(ERR_WEATHER_HOLD_ACTIVE, 'Base posture is WEATHER_HOLD')
    if uid == f['created_by_user_id']:
        raise_error(ERR_SEGREGATION_OF_DUTY, 'Flight creator may not dispatch the same flight')
    if not f['pilot_acknowledged']:
        raise_error(ERR_PILOT_ACK_REQUIRED, 'Assigned pilot has not acknowledged')
    f['status'] = 'DISPATCHED'
    f['actual_departure_utc'] = now()
    f['dispatched_by_user_id'] = uid
    touch(f)
    for b in D.bookings_of_flight(f['id']):
        if b['status'] == 'CONFIRMED':
            b['status'] = 'NO_SHOW'
            b['retained_fee_cents'] = b['paid_cents']
            touch(b)
        elif b['status'] == 'HELD':
            D.release_applied_credits(b)
            b['status'] = 'EXPIRED'
            touch(b)


def _do_complete(f):
    if not (now() > f['actual_departure_utc']):
        raise_error(ERR_INVALID_STATE, 'Completion requires now after actual departure')
    f['status'] = 'COMPLETED'
    f['actual_arrival_utc'] = now()
    touch(f)
    duty = D.get_or_create_duty_day(f['pilot_id'], f['scheduled_departure_utc'].date())
    _, actual, _ = D.duty_day_values(duty)
    if actual >= D.FLIGHT_LIMIT_MIN:
        pilot = db.pilots[f['pilot_id']]
        if pilot['status'] == 'AVAILABLE':
            pilot['status'] = 'FATIGUE_LOCKED'
            touch(pilot)
    for b in D.bookings_of_flight(f['id']):
        if b['status'] == 'MANIFESTED':
            b['status'] = 'FLOWN'
            touch(b)


@bp.route('/flights/<fid>/events', methods=['POST'])
def flight_events(fid):
    body = get_body()
    event_type = _enum(body, 'event_type', True, ALL_FLIGHT_EVENTS)
    new_departure = None
    if event_type == 'DELAY':
        new_departure = _dt(body, 'new_departure_utc', True)
    uid, role = authenticate()
    require_role(role, ('Dispatcher', 'Pilot'))
    f = get_or_404(db.flights, fid, 'Flight')
    return _flight_event_impl(f, event_type, new_departure, uid, role)


def _flight_event_impl(f, event_type, new_departure, uid, role):
    if event_type == 'PILOT_ACK':
        if role != 'Pilot':
            raise_error(ERR_PILOT_MISMATCH, 'PILOT_ACK requires the Pilot role')
        if f['status'] not in ('SCHEDULED', 'DELAYED'):
            raise_error(ERR_INVALID_STATE, 'PILOT_ACK requires SCHEDULED or DELAYED')
        if uid != f['pilot_id']:
            raise_error(ERR_PILOT_MISMATCH, 'PILOT_ACK by a pilot other than the assigned pilot')
        f['pilot_acknowledged'] = True
        touch(f)
        return success(ser_flight(f))
    # All remaining events are Dispatcher-only.
    if role != 'Dispatcher':
        from errors import ERR_UNAUTHORIZED_ROLE
        raise_error(ERR_UNAUTHORIZED_ROLE, 'Role not permitted for this event')
    if event_type == 'DELAY':
        if f['status'] != 'SCHEDULED':
            raise_error(ERR_INVALID_STATE, 'DELAY requires SCHEDULED')
        _do_delay(f, new_departure)
    elif event_type == 'ACCEPT_DELAY':
        if f['status'] != 'DELAYED':
            raise_error(ERR_INVALID_STATE, 'ACCEPT_DELAY requires DELAYED')
        f['status'] = 'SCHEDULED'
        touch(f)
    elif event_type == 'OPEN_BOARDING':
        if f['status'] not in ('SCHEDULED', 'DELAYED'):
            raise_error(ERR_INVALID_STATE, 'OPEN_BOARDING requires SCHEDULED or DELAYED')
        base = db.bases[f['base_id']]
        if D.compute_posture(base) != 'NORMAL':
            raise_error(ERR_WEATHER_HOLD_ACTIVE, 'Base posture is WEATHER_HOLD')
        f['status'] = 'BOARDING'
        touch(f)
    elif event_type == 'DISPATCH':
        if f['status'] != 'MANIFEST_CLOSED':
            raise_error(ERR_INVALID_STATE, 'DISPATCH requires MANIFEST_CLOSED')
        _do_dispatch(f, uid)
    elif event_type == 'COMPLETE':
        if f['status'] != 'DISPATCHED':
            raise_error(ERR_INVALID_STATE, 'COMPLETE requires DISPATCHED')
        _do_complete(f)
    elif event_type == 'CANCEL_WEATHER':
        if f['status'] not in ('SCHEDULED', 'DELAYED', 'BOARDING', 'MANIFEST_CLOSED'):
            raise_error(ERR_INVALID_STATE, 'CANCEL_WEATHER not permitted from current state')
        D.cancel_flight(f, 'CANCELLED_WEATHER', 'WEATHER')
    elif event_type == 'CANCEL_OPS':
        if f['status'] not in ('SCHEDULED', 'DELAYED', 'BOARDING', 'MANIFEST_CLOSED'):
            raise_error(ERR_INVALID_STATE, 'CANCEL_OPS not permitted from current state')
        D.cancel_flight(f, 'CANCELLED_OPS', 'OPS_MANUAL')
    return success(ser_flight(f))


@bp.route('/flights/<fid>/close-manifest', methods=['POST'])
def close_manifest(fid):
    body = get_body()
    expected = _int(body, 'expected_flight_version', True)
    _, role = authenticate()
    require_role(role, ('Dispatcher',))
    f = get_or_404(db.flights, fid, 'Flight')
    if expected != f['version']:
        raise_error(ERR_STALE_VERSION, 'expected_flight_version does not match the flight version')
    if f['status'] != 'BOARDING':
        raise_error(ERR_INVALID_STATE, 'close-manifest requires BOARDING')
    D.close_manifest_wb(f)  # also transitions the flight (touch) and manifests bookings
    f['status'] = 'MANIFEST_CLOSED'
    return success(ser_flight(f))
