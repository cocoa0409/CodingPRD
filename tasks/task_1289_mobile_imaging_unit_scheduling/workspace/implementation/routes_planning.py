"""Planning resources: route plans, site day assignments, transport legs."""
from datetime import date, timedelta

from flask import Blueprint

from core import (DB, auth, body, ok_object, ok_list, serialize, sorted_items,
                  apply_filters, new_entity, touch, get, fail, clock_date,
                  f_str, f_int, f_num, f_bool, f_date, f_time, to_minutes)
import logic

bp = Blueprint('planning', __name__)

OD = ('OperationsDirector',)
ALL = None


def serialize_plan(p):
    out = serialize(p)
    out['site_day_count'] = len(logic.days_of_plan(p['id']))
    out['total_travel_stipend_cents'] = logic.plan_total_stipend(p['id'])
    return out


# ---------------------------------------------------------------- route plans
@bp.post('/api/route-plans')
def create_route_plan():
    auth(OD)
    d = body()
    unit_id = f_str(d, 'unit_id')
    week_start = f_date(d, 'week_start_date')
    expected_unit_version = f_int(d, 'expected_unit_version')
    if date.fromisoformat(week_start).weekday() != 0:
        fail('ERR_INVALID_REQUEST', 400, 'week_start_date must be a Monday')
    unit = get('units', unit_id, 'ERR_UNIT_NOT_FOUND')
    # OCC (priority 4): before state/business rules
    if expected_unit_version != unit['version']:
        fail('ERR_STALE_UNIT_VERSION', 412,
             'expected_unit_version does not match unit.version')
    supersedes = None
    for p in DB['route_plans'].values():
        if (p['unit_id'] == unit_id and p['week_start_date'] == week_start
                and p['status'] != 'SUPERSEDED'):
            if p['status'] == 'DRAFT':
                supersedes = p
            elif p['status'] in ('PUBLISHED', 'LOCKED'):
                fail('ERR_PLAN_WEEK_CONFLICT', 409,
                     'A PUBLISHED or LOCKED plan exists for this unit and week')
    if supersedes is not None:
        supersedes['status'] = 'SUPERSEDED'
        touch(supersedes)
    plan = new_entity('route_plans', {
        'unit_id': unit_id,
        'week_start_date': week_start,
        'status': 'DRAFT',
        'supersedes_plan_id': supersedes['id'] if supersedes else None,
    })
    touch(unit)  # plan creation increments unit version by 1
    return ok_object(serialize_plan(plan), 201)


@bp.get('/api/route-plans')
def list_route_plans():
    auth(ALL)
    items = apply_filters(sorted_items('route_plans'),
                          {'unit_id': 'unit_id', 'status': 'status',
                           'supersedes_plan_id': 'supersedes_plan_id'})
    return ok_list(items, serialize_plan)


@bp.get('/api/route-plans/<pid>')
def get_route_plan(pid):
    auth(ALL)
    return ok_object(serialize_plan(get('route_plans', pid,
                                        'ERR_ROUTE_PLAN_NOT_FOUND')))


@bp.post('/api/route-plans/<pid>/publish')
def publish_plan(pid):
    auth(OD)
    plan = get('route_plans', pid, 'ERR_ROUTE_PLAN_NOT_FOUND')
    if plan['status'] != 'DRAFT':
        fail('ERR_PLAN_NOT_PUBLISHED', 409, 'Plan must be DRAFT to publish')
    if len(logic.days_of_plan(pid)) < 1:
        fail('ERR_EMPTY_ROUTE_PLAN', 409, 'Publish requires at least one site day')
    plan['status'] = 'PUBLISHED'
    touch(plan)
    return ok_object(serialize_plan(plan))


@bp.post('/api/route-plans/<pid>/unpublish')
def unpublish_plan(pid):
    auth(OD)
    plan = get('route_plans', pid, 'ERR_ROUTE_PLAN_NOT_FOUND')
    if plan['status'] != 'PUBLISHED':
        fail('ERR_PLAN_NOT_PUBLISHED', 409, 'Plan must be PUBLISHED to unpublish')
    for day in logic.days_of_plan(pid):
        if day['status'] not in ('SCHEDULED', 'CANCELLED'):
            fail('ERR_PLAN_HAS_ACTIVE_DAYS', 409,
                 'Unpublish blocked by days past scheduling')
    plan['status'] = 'DRAFT'
    touch(plan)
    return ok_object(serialize_plan(plan))


@bp.post('/api/route-plans/<pid>/lock')
def lock_plan(pid):
    auth(OD)
    plan = get('route_plans', pid, 'ERR_ROUTE_PLAN_NOT_FOUND')
    if plan['status'] != 'PUBLISHED':
        fail('ERR_PLAN_NOT_PUBLISHED', 409, 'Plan must be PUBLISHED to lock')
    plan['status'] = 'LOCKED'
    touch(plan)
    return ok_object(serialize_plan(plan))


@bp.post('/api/route-plans/<pid>/close')
def close_plan(pid):
    auth(OD)
    plan = get('route_plans', pid, 'ERR_ROUTE_PLAN_NOT_FOUND')
    if plan['status'] != 'LOCKED':
        fail('ERR_PLAN_NOT_LOCKED', 409, 'Plan must be LOCKED to close')
    for day in logic.days_of_plan(pid):
        if day['status'] not in ('COMPLETED', 'CANCELLED', 'RESCHEDULED'):
            fail('ERR_PLAN_HAS_ACTIVE_DAYS', 409,
                 'Close blocked by non-terminal days')
    plan['status'] = 'CLOSED'
    touch(plan)
    return ok_object(serialize_plan(plan))


# ---------------------------------------------------------------- site days
def _validate_window(unit, arrival, first, last, departure):
    if to_minutes(first) < to_minutes(arrival) + unit['setup_minutes']:
        fail('ERR_WINDOW_TOO_SHORT', 422,
             'first_patient_time must be >= arrival_time + setup_minutes')
    if to_minutes(departure) < to_minutes(last) + unit['teardown_minutes']:
        fail('ERR_WINDOW_TOO_SHORT', 422,
             'departure_time must be >= last_patient_time + teardown_minutes')


def _validate_temporal(plan, service_date):
    if date.fromisoformat(service_date) < clock_date():
        fail('ERR_SERVICE_DATE_IN_PAST', 422,
             'service_date precedes the logical clock date')
    ws = date.fromisoformat(plan['week_start_date'])
    sd = date.fromisoformat(service_date)
    if sd < ws or sd > ws + timedelta(days=6):
        fail('ERR_SERVICE_DATE_OUTSIDE_PLAN_WEEK', 422,
             'service_date outside the plan week')


@bp.post('/api/site-days')
def create_site_day():
    auth(OD)
    d = body()
    route_plan_id = f_str(d, 'route_plan_id')
    facility_id = f_str(d, 'facility_id')
    contract_id = f_str(d, 'contract_id')
    service_date = f_date(d, 'service_date')
    arrival = f_time(d, 'arrival_time')
    first = f_time(d, 'first_patient_time')
    last = f_time(d, 'last_patient_time')
    departure = f_time(d, 'departure_time')
    # existence (priority 3) in declared FK order
    plan = get('route_plans', route_plan_id, 'ERR_ROUTE_PLAN_NOT_FOUND')
    facility = get('facilities', facility_id, 'ERR_FACILITY_NOT_FOUND')
    contract = get('contracts', contract_id, 'ERR_CONTRACT_NOT_FOUND')
    # state (5)
    if plan['status'] not in ('DRAFT', 'PUBLISHED'):
        fail('ERR_PLAN_NOT_PUBLISHED', 409,
             'Site days may be added only to DRAFT or PUBLISHED plans')
    unit = DB['units'][plan['unit_id']]
    # pad power (7)
    if (facility['pad_amps_available'] < unit['power_required_amps']
            or facility['pad_voltage'] != unit['voltage_required']):
        fail('ERR_PAD_POWER_INSUFFICIENT', 422,
             'Pad amperage/voltage does not meet unit requirements')
    # credential linkage (9)
    if unit['modality'] not in facility['supported_modalities']:
        fail('ERR_MODALITY_NOT_SUPPORTED', 422,
             'Facility does not host the unit modality')
    if contract['facility_id'] != facility_id:
        fail('ERR_CONTRACT_FACILITY_MISMATCH', 422,
             'contract.facility_id must equal the site day facility_id')
    # temporal (10)
    _validate_temporal(plan, service_date)
    _validate_window(unit, arrival, first, last, departure)
    # resource conflicts (11): unit day exclusivity
    if logic.unit_day_booked(unit['id'], service_date):
        fail('ERR_UNIT_DAY_DOUBLE_BOOKED', 409,
             'Unit already has a live site day on that service_date')
    # accreditation (12)
    if not logic.accreditation_valid(unit):
        fail('ERR_ACCREDITATION_NOT_VALID', 422,
             'Governing accreditation is not ACTIVE or EXPIRING_SOON')
    day = new_entity('site_days', {
        'route_plan_id': route_plan_id,
        'unit_id': plan['unit_id'],
        'facility_id': facility_id,
        'contract_id': contract_id,
        'service_date': service_date,
        'arrival_time': arrival,
        'first_patient_time': first,
        'last_patient_time': last,
        'departure_time': departure,
        'status': 'SCHEDULED',
        'cancel_reason': None,
        'interrupt_reason': None,
        'delivered_service_minutes': 0,
        'rescheduled_from_id': None,
        'rescheduled_to_id': None,
        '_reached_ready': False,
        '_cancel_late': False,
    })
    touch(plan)  # site-day create increments plan version by 1
    return ok_object(serialize(day), 201)


@bp.get('/api/site-days')
def list_site_days():
    auth(ALL)
    items = apply_filters(sorted_items('site_days'), {
        'route_plan_id': 'route_plan_id', 'unit_id': 'unit_id',
        'facility_id': 'facility_id', 'contract_id': 'contract_id',
        'status': 'status', 'service_date': 'service_date',
        'rescheduled_from_id': 'rescheduled_from_id',
        'rescheduled_to_id': 'rescheduled_to_id'})
    return ok_list(items)


@bp.get('/api/site-days/<sid>')
def get_site_day(sid):
    auth(ALL)
    return ok_object(serialize(get('site_days', sid, 'ERR_SITE_DAY_NOT_FOUND')))


def _day(sid):
    return get('site_days', sid, 'ERR_SITE_DAY_NOT_FOUND')


@bp.post('/api/site-days/<sid>/depart')
def depart_day(sid):
    auth(OD)
    day = _day(sid)
    if day['status'] != 'SCHEDULED':
        fail('ERR_INVALID_STATE', 409, 'Day must be SCHEDULED to depart')
    unit = DB['units'][day['unit_id']]
    if not logic.accreditation_valid(unit):
        fail('ERR_ACCREDITATION_NOT_VALID', 422,
             'Governing accreditation is not valid')
    day['status'] = 'EN_ROUTE'
    touch(day)
    for leg in logic.legs_of_day(sid):
        if leg['status'] == 'PLANNED':
            leg['status'] = 'DISPATCHED'
            touch(leg)
    return ok_object(serialize(day))


@bp.post('/api/site-days/<sid>/begin-setup')
def begin_setup(sid):
    auth(OD)
    day = _day(sid)
    if day['status'] != 'EN_ROUTE':
        fail('ERR_INVALID_STATE', 409, 'Day must be EN_ROUTE to begin setup')
    for leg in logic.legs_of_day(sid):
        if leg['status'] != 'ARRIVED':
            fail('ERR_TRANSPORT_NOT_ARRIVED', 409,
                 'Every transport leg must be ARRIVED')
    day['status'] = 'SETTING_UP'
    touch(day)
    return ok_object(serialize(day))


@bp.post('/api/site-days/<sid>/mark-ready')
def mark_ready(sid):
    auth(OD)
    day = _day(sid)
    if day['status'] != 'SETTING_UP':
        fail('ERR_INVALID_STATE', 409, 'Day must be SETTING_UP to mark ready')
    checklist = logic.checklist_of_day(sid)
    if checklist is None or checklist['status'] != 'ALL_PASSED':
        fail('ERR_CHECKLIST_INCOMPLETE', 409,
             'Checklist must exist with status ALL_PASSED')
    unit = DB['units'][day['unit_id']]
    if checklist['measured_amps'] < unit['power_required_amps']:
        fail('ERR_PAD_POWER_INSUFFICIENT', 422,
             'Measured amperage below unit requirement')
    if not logic.accreditation_valid(unit):
        fail('ERR_ACCREDITATION_NOT_VALID', 422,
             'Governing accreditation is not valid')
    day['status'] = 'READY'
    day['_reached_ready'] = True
    touch(day)
    return ok_object(serialize(day))


@bp.post('/api/site-days/<sid>/start-service')
def start_service(sid):
    auth(OD)
    day = _day(sid)
    if day['status'] != 'READY':
        fail('ERR_INVALID_STATE', 409, 'Day must be READY to start service')
    if not any(s['status'] == 'ASSIGNED' for s in logic.staffing_of_day(sid)):
        fail('ERR_NO_STAFF_ASSIGNED', 409,
             'At least one ASSIGNED staffing assignment is required')
    day['status'] = 'IN_SERVICE'
    touch(day)
    return ok_object(serialize(day))


@bp.post('/api/site-days/<sid>/complete')
def complete(sid):
    auth(OD)
    day = _day(sid)
    if day['status'] != 'IN_SERVICE':
        fail('ERR_INVALID_STATE', 409, 'Day must be IN_SERVICE to complete')
    for a in logic.appointments_of_day(sid):
        if a['status'] not in ('COMPLETED', 'CANCELLED', 'NO_SHOW'):
            fail('ERR_OPEN_APPOINTMENTS', 409,
                 'All appointments must be terminal to complete the day')
    logic.complete_day(day)
    return ok_object(serialize(day))


@bp.post('/api/site-days/<sid>/cancel')
def cancel(sid):
    auth(('OperationsDirector', 'FacilityCoordinator'))
    day = _day(sid)
    d = body()
    notice_hours = f_num(d, 'notice_hours')
    if day['status'] not in ('SCHEDULED', 'EN_ROUTE'):
        fail('ERR_INVALID_STATE', 409,
             'Day must be SCHEDULED or EN_ROUTE to cancel')
    logic.cancel_day_manual(day, notice_hours)
    return ok_object(serialize(day))


@bp.post('/api/site-days/<sid>/interrupt')
def interrupt(sid):
    auth(OD)
    day = _day(sid)
    d = body()
    reason = f_str(d, 'reason')
    if reason not in ('BREAKDOWN', 'OPERATOR_INTERRUPT'):
        fail('ERR_INVALID_REQUEST', 400,
             'reason must be BREAKDOWN or OPERATOR_INTERRUPT')
    if day['status'] not in ('SETTING_UP', 'READY', 'IN_SERVICE'):
        fail('ERR_INVALID_STATE', 409,
             'Day must be SETTING_UP, READY, or IN_SERVICE to interrupt')
    logic.interrupt_day(day, reason)
    return ok_object(serialize(day))


@bp.post('/api/site-days/<sid>/reschedule')
def reschedule(sid):
    auth(OD)
    day = _day(sid)
    d = body()
    target_route_plan_id = f_str(d, 'target_route_plan_id')
    expected_route_plan_version = f_int(d, 'expected_route_plan_version')
    new_service_date = f_date(d, 'new_service_date')
    new_arrival = f_time(d, 'new_arrival_time')
    new_first = f_time(d, 'new_first_patient_time')
    new_last = f_time(d, 'new_last_patient_time')
    new_departure = f_time(d, 'new_departure_time')
    plan = get('route_plans', target_route_plan_id, 'ERR_ROUTE_PLAN_NOT_FOUND')
    # OCC (4) before state/business
    if expected_route_plan_version != plan['version']:
        fail('ERR_STALE_ROUTE_PLAN_VERSION', 412,
             'expected_route_plan_version does not match target plan version')
    # state (5)
    if day['status'] != 'INTERRUPTED':
        fail('ERR_RESCHEDULE_SOURCE_INVALID', 409,
             'Source day must be INTERRUPTED')
    if plan['status'] != 'PUBLISHED' or plan['unit_id'] != day['unit_id']:
        fail('ERR_RESCHEDULE_TARGET_INVALID', 409,
             'Target plan must be PUBLISHED and belong to the same unit')
    # temporal (10)
    _validate_temporal(plan, new_service_date)
    unit = DB['units'][day['unit_id']]
    _validate_window(unit, new_arrival, new_first, new_last, new_departure)
    # conflicts (11): unit day exclusivity
    if logic.unit_day_booked(day['unit_id'], new_service_date):
        fail('ERR_UNIT_DAY_DOUBLE_BOOKED', 409,
             'Unit already has a live site day on that service_date')
    replacement = new_entity('site_days', {
        'route_plan_id': plan['id'],
        'unit_id': day['unit_id'],
        'facility_id': day['facility_id'],
        'contract_id': day['contract_id'],
        'service_date': new_service_date,
        'arrival_time': new_arrival,
        'first_patient_time': new_first,
        'last_patient_time': new_last,
        'departure_time': new_departure,
        'status': 'SCHEDULED',
        'cancel_reason': None,
        'interrupt_reason': None,
        'delivered_service_minutes': 0,
        'rescheduled_from_id': day['id'],
        'rescheduled_to_id': None,
        '_reached_ready': False,
        '_cancel_late': False,
    })
    day['status'] = 'RESCHEDULED'
    day['rescheduled_to_id'] = replacement['id']
    touch(day)
    touch(plan)  # reschedule increments target plan version by 1
    return ok_object(serialize(replacement))


# ---------------------------------------------------------------- transport legs
@bp.post('/api/transport-legs')
def create_leg():
    auth(OD)
    d = body()
    site_day_id = f_str(d, 'site_day_id')
    origin_name = f_str(d, 'origin_name')
    destination_name = f_str(d, 'destination_name')
    distance_miles = f_num(d, 'distance_miles')
    drive_minutes = f_int(d, 'drive_minutes')
    overnight = f_bool(d, 'overnight', required=False, default=False)
    get('site_days', site_day_id, 'ERR_SITE_DAY_NOT_FOUND')
    leg = new_entity('legs', {
        'site_day_id': site_day_id,
        'origin_name': origin_name,
        'destination_name': destination_name,
        'distance_miles': distance_miles,
        'drive_minutes': drive_minutes,
        'overnight': overnight,
        'stipend_cents': logic.leg_stipend_cents(distance_miles, overnight),
        'status': 'PLANNED',
    })
    day = DB['site_days'][site_day_id]
    plan = DB['route_plans'].get(day['route_plan_id'])
    if plan is not None:
        touch(plan)  # total_travel_stipend_cents recomputed -> derived-field bump
    return ok_object(serialize(leg), 201)


@bp.get('/api/transport-legs')
def list_legs():
    auth(ALL)
    items = apply_filters(sorted_items('legs'),
                          {'site_day_id': 'site_day_id', 'status': 'status'})
    return ok_list(items)


@bp.get('/api/transport-legs/<lid>')
def get_leg(lid):
    auth(ALL)
    return ok_object(serialize(get('legs', lid, 'ERR_TRANSPORT_LEG_NOT_FOUND')))


@bp.post('/api/transport-legs/<lid>/arrive')
def arrive_leg(lid):
    auth(('Technologist', 'OperationsDirector'))
    leg = get('legs', lid, 'ERR_TRANSPORT_LEG_NOT_FOUND')
    if leg['status'] != 'DISPATCHED':
        fail('ERR_INVALID_STATE', 409, 'Leg must be DISPATCHED to arrive')
    leg['status'] = 'ARRIVED'
    touch(leg)
    return ok_object(serialize(leg))
