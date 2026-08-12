"""Flight leg endpoints: create/list/get, delay, cancel, depart, arrive, divert."""
from flask import Blueprint, request

from db import store
from errors import err
from util import (ok, authenticate, authorize, validate_body, pagination_params,
                  paginate, sorted_created, get_or_404, _MISSING)
from serializers import ser_leg, workload, shift_status
from services import (new_uuid, write_record, non_terminal_release_for_leg,
                      auto_select_dispatcher, cancel_release_for_leg,
                      expired_mel_exists, DELAY_REVIEW_THRESHOLD_MIN)

bp = Blueprint('legs', __name__)

ALL = ['Dispatcher', 'Captain', 'DispatchSupervisor']
DISP = ['Dispatcher']

LEG_SCHEMA = {
    'flight_no': ('str', True, _MISSING),
    'dep_station_id': ('str', True, _MISSING),
    'arr_station_id': ('str', True, _MISSING),
    'aircraft_id': ('str', True, _MISSING),
    'captain_id': ('str', True, _MISSING),
    'dispatcher_id': ('str', False, _MISSING),
    'distance_nm': ('pos_int', True, _MISSING),
    'sched_dep_utc': ('dt', True, _MISSING),
    'sched_arr_utc': ('dt', True, _MISSING),
}

DELAY_SCHEMA = {
    'new_dep_utc': ('dt', True, _MISSING),
    'new_arr_utc': ('dt', True, _MISSING),
    'reason_code': ('str', True, _MISSING),
}

CANCEL_SCHEMA = {
    'reason_code': ('str', True, _MISSING),
}

DIVERT_SCHEMA = {
    'divert_station_id': ('str', True, _MISSING),
    'distance_nm': ('pos_int', True, _MISSING),
    'sched_dep_utc': ('dt', True, _MISSING),
    'sched_arr_utc': ('dt', True, _MISSING),
    'reason_code': ('str', True, _MISSING),
}


def _own_leg(leg, uid):
    if leg['dispatcher_id'] != uid:
        raise err('ERR_NOT_ASSIGNED_DISPATCHER')


@bp.post('/dispatch/legs')
def create_leg():
    data = validate_body(LEG_SCHEMA)
    uid, role = authenticate(); authorize(role, DISP)
    # ownership: explicit dispatcher_id must equal the caller
    if 'dispatcher_id' in data and data['dispatcher_id'] != uid:
        raise err('ERR_NOT_ASSIGNED_DISPATCHER')
    # body FK existence (input order)
    get_or_404(store.stations, data['dep_station_id'], 'departure station')
    get_or_404(store.stations, data['arr_station_id'], 'arrival station')
    aircraft = get_or_404(store.aircraft, data['aircraft_id'], 'aircraft')
    captain = get_or_404(store.captains, data['captain_id'], 'captain')
    explicit = None
    if 'dispatcher_id' in data:
        explicit = get_or_404(store.dispatchers, data['dispatcher_id'], 'dispatcher')

    # safety: captain qualification
    if aircraft['type_code'] not in captain['qualified_type_codes']:
        raise err('ERR_CAPTAIN_NOT_QUALIFIED')

    # resolve dispatcher + capacity / auto-select (fiscal)
    if explicit is not None:
        dispatcher = explicit
        count, _ = workload(dispatcher['id'])
        if count >= dispatcher['max_active_legs']:
            raise err('ERR_DISPATCHER_OVERLOADED')
    else:
        dispatcher = auto_select_dispatcher()

    # safety: segregation of duties
    if captain['license_no'] == dispatcher['license_no']:
        raise err('ERR_DUAL_ROLE_ASSIGNMENT')

    rec = {
        'id': new_uuid(),
        'flight_no': data['flight_no'],
        'dep_station_id': data['dep_station_id'],
        'arr_station_id': data['arr_station_id'],
        'aircraft_id': data['aircraft_id'],
        'captain_id': data['captain_id'],
        'dispatcher_id': dispatcher['id'],
        'diverted_from_leg_id': None,
        'distance_nm': data['distance_nm'],
        'sched_dep_utc': data['sched_dep_utc'],
        'sched_arr_utc': data['sched_arr_utc'],
        'actual_dep_utc': None,
        'ops_status': 'SCHEDULED',
        'monitor_status': 'UNMONITORED',
        'delay_count': 0,
    }
    store.legs[rec['id']] = store.stamp_new(rec)
    write_record(rec['id'], None, role, uid, 'LEG_CREATED',
                 from_status=None, to_status='SCHEDULED')
    return ok(ser_leg(rec), status=201)


@bp.get('/dispatch/legs/<legId>')
def get_leg(legId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.legs, legId, 'leg')
    return ok(ser_leg(rec))


@bp.get('/dispatch/legs')
def list_legs():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.legs.values())
    for f in ('dep_station_id', 'arr_station_id', 'aircraft_id', 'captain_id',
              'dispatcher_id', 'diverted_from_leg_id', 'ops_status'):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_leg(l) for l in page], is_list=True, pagination=meta)


@bp.post('/dispatch/legs/<legId>/delay')
def delay_leg(legId):
    data = validate_body(DELAY_SCHEMA)
    uid, role = authenticate(); authorize(role, DISP)
    leg = get_or_404(store.legs, legId, 'leg')
    _own_leg(leg, uid)
    if leg['ops_status'] in ('ARRIVED', 'DIVERTED', 'CANCELLED'):
        raise err('ERR_INVALID_STATE', 'terminal leg admits no delay')
    new_dep, new_arr = data['new_dep_utc'], data['new_arr_utc']
    if not (new_dep > leg['sched_dep_utc']) or not (new_arr > new_dep):
        raise err('ERR_DELAY_INVALID_TIME')
    old_dep = leg['sched_dep_utc']
    leg['sched_dep_utc'] = new_dep
    leg['sched_arr_utc'] = new_arr
    leg['delay_count'] += 1
    store.touch(leg)
    write_record(leg['id'], None, role, uid, 'DELAY_DECISION',
                 note=data['reason_code'])
    # delay_auto_amend cascade
    delay_minutes = int((new_dep - old_dep).total_seconds() // 60)
    if delay_minutes >= DELAY_REVIEW_THRESHOLD_MIN:
        rel = non_terminal_release_for_leg(leg['id'])
        if rel is not None and rel['status'] == 'RELEASED':
            from services import auto_amend_release
            auto_amend_release(rel)
    return ok(ser_leg(leg))


@bp.post('/dispatch/legs/<legId>/cancel')
def cancel_leg(legId):
    data = validate_body(CANCEL_SCHEMA)
    uid, role = authenticate(); authorize(role, DISP)
    leg = get_or_404(store.legs, legId, 'leg')
    _own_leg(leg, uid)
    if leg['ops_status'] != 'SCHEDULED':
        raise err('ERR_INVALID_STATE', 'only a SCHEDULED leg can be cancelled')
    old = leg['ops_status']
    leg['ops_status'] = 'CANCELLED'
    store.touch(leg)
    # PRD: cancel cascades DRAFT / PENDING_SIGNATURES / UNDER_AMENDMENT (not RELEASED)
    cancel_release_for_leg(leg['id'], include_released=False)
    write_record(leg['id'], None, role, uid, 'CANCEL_DECISION',
                 from_status=old, to_status='CANCELLED', note=data['reason_code'])
    return ok(ser_leg(leg))


@bp.post('/dispatch/legs/<legId>/depart')
def depart_leg(legId):
    uid, role = authenticate(); authorize(role, DISP)
    leg = get_or_404(store.legs, legId, 'leg')
    _own_leg(leg, uid)
    # state: SCHEDULED + a RELEASED release exists
    if leg['ops_status'] != 'SCHEDULED':
        raise err('ERR_INVALID_STATE', 'only a SCHEDULED leg can depart')
    rel = non_terminal_release_for_leg(leg['id'])
    if rel is None or rel['status'] != 'RELEASED':
        raise err('ERR_INVALID_STATE', 'a RELEASED release is required for departure')
    # safety: no EXPIRED mel item
    if expired_mel_exists(leg['aircraft_id']):
        raise err('ERR_MEL_ITEM_EXPIRED')
    # temporal: active shift for the assigned dispatcher
    has_shift = any(s['dispatcher_id'] == leg['dispatcher_id']
                    and shift_status(s) == 'ACTIVE'
                    for s in store.desk_shifts.values())
    if not has_shift:
        raise err('ERR_NO_ACTIVE_SHIFT')
    old = leg['ops_status']
    leg['ops_status'] = 'DEPARTED'
    leg['monitor_status'] = 'MONITORING'
    leg['actual_dep_utc'] = store.clock
    store.touch(leg)
    write_record(leg['id'], None, role, uid, 'DEPARTURE',
                 from_status=old, to_status='DEPARTED')
    return ok(ser_leg(leg))


@bp.post('/dispatch/legs/<legId>/arrive')
def arrive_leg(legId):
    uid, role = authenticate(); authorize(role, DISP)
    leg = get_or_404(store.legs, legId, 'leg')
    _own_leg(leg, uid)
    if leg['ops_status'] != 'DEPARTED':
        raise err('ERR_INVALID_STATE', 'only a DEPARTED leg can arrive')
    old = leg['ops_status']
    leg['ops_status'] = 'ARRIVED'
    leg['monitor_status'] = 'CLOSED'
    store.touch(leg)
    rel = non_terminal_release_for_leg(leg['id'])
    if rel is not None:
        if rel['status'] == 'RELEASED':
            rel['status'] = 'CLOSED'
        else:
            rel['status'] = 'CANCELLED'
        store.touch(rel)
    write_record(leg['id'], None, role, uid, 'ARRIVAL',
                 from_status=old, to_status='ARRIVED')
    return ok(ser_leg(leg))


@bp.post('/dispatch/legs/<legId>/divert')
def divert_leg(legId):
    data = validate_body(DIVERT_SCHEMA)
    uid, role = authenticate(); authorize(role, ['Dispatcher', 'Captain'])
    leg = get_or_404(store.legs, legId, 'leg')
    # ownership depends on caller role
    if role == 'Dispatcher':
        if leg['dispatcher_id'] != uid:
            raise err('ERR_NOT_ASSIGNED_DISPATCHER')
    else:
        if leg['captain_id'] != uid:
            raise err('ERR_NOT_ASSIGNED_CAPTAIN')
    target_id = data['divert_station_id']
    if target_id == leg['arr_station_id'] or target_id == leg['dep_station_id']:
        raise err('ERR_INVALID_REQUEST',
                  'divert target must differ from departure and arrival stations')
    target = get_or_404(store.stations, target_id, 'divert station')
    if leg['ops_status'] != 'DEPARTED':
        raise err('ERR_INVALID_STATE', 'only a DEPARTED leg can be diverted')
    if target['status'] != 'OPEN':
        raise err('ERR_INVALID_STATE', 'divert target station is not OPEN')

    old = leg['ops_status']
    leg['ops_status'] = 'DIVERTED'
    leg['monitor_status'] = 'CLOSED'
    store.touch(leg)
    cancel_release_for_leg(leg['id'], include_released=True)

    cont = {
        'id': new_uuid(),
        'flight_no': leg['flight_no'],
        'dep_station_id': target['id'],
        'arr_station_id': leg['arr_station_id'],
        'aircraft_id': leg['aircraft_id'],
        'captain_id': leg['captain_id'],
        'dispatcher_id': leg['dispatcher_id'],
        'diverted_from_leg_id': leg['id'],
        'distance_nm': data['distance_nm'],
        'sched_dep_utc': data['sched_dep_utc'],
        'sched_arr_utc': data['sched_arr_utc'],
        'actual_dep_utc': None,
        'ops_status': 'SCHEDULED',
        'monitor_status': 'UNMONITORED',
        'delay_count': 0,
    }
    store.legs[cont['id']] = store.stamp_new(cont)
    write_record(leg['id'], None, role, uid, 'DIVERSION',
                 from_status=old, to_status='DIVERTED', note=data['reason_code'])
    write_record(cont['id'], None, role, uid, 'DIVERSION',
                 from_status=None, to_status='SCHEDULED', note=data['reason_code'])
    return ok(ser_leg(cont), status=201)
