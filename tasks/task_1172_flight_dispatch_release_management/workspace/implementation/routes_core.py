"""Reference data + desk staffing endpoints."""
from flask import Blueprint, request

from db import store
from errors import err
from util import (ok, authenticate, authorize, validate_body, pagination_params,
                  paginate, sorted_created, get_or_404, _MISSING)
from serializers import (ser_station, ser_aircraft, ser_dispatcher, ser_captain,
                         ser_desk, ser_desk_shift)
from services import (new_uuid, auto_select_desk, check_desk_capacity,
                      REST_BUFFER_MIN)
from datetime import timedelta

bp = Blueprint('core', __name__)

ALL = ['Dispatcher', 'Captain', 'DispatchSupervisor']
SUP = ['DispatchSupervisor']

STATION_SCHEMA = {
    'iata_code': ('str', True, _MISSING),
    'runway_length_m': ('pos_int', True, _MISSING),
    'alternate_distance_nm': ('pos_int', True, _MISSING),
    'min_ceiling_ft': ('nn_int', True, _MISSING),
    'min_visibility_m': ('nn_int', True, _MISSING),
    'status': ('enum:OPEN,CLOSED', False, 'OPEN'),
}

AIRCRAFT_SCHEMA = {
    'tail_no': ('str', True, _MISSING),
    'type_code': ('str', True, _MISSING),
    'oew_kg': ('pos_int', True, _MISSING),
    'mzfw_kg': ('pos_int', True, _MISSING),
    'mtow_kg': ('pos_int', True, _MISSING),
    'mlw_kg': ('pos_int', True, _MISSING),
    'fuel_capacity_kg': ('pos_int', True, _MISSING),
    'cruise_tas_kts': ('pos_int', True, _MISSING),
    'burn_kg_per_hour': ('pos_int', True, _MISSING),
    'min_runway_m': ('pos_int', True, _MISSING),
    'lemac_m': ('pos_num', True, _MISSING),
    'mac_m': ('pos_num', True, _MISSING),
}

DISPATCHER_SCHEMA = {
    'name': ('str', True, _MISSING),
    'license_no': ('str', True, _MISSING),
    'max_active_legs': ('pos_int', False, 6),
}

CAPTAIN_SCHEMA = {
    'name': ('str', True, _MISSING),
    'license_no': ('str', True, _MISSING),
    'qualified_type_codes': ('str_list', True, _MISSING),
}

DESK_SCHEMA = {
    'code': ('str', True, _MISSING),
    'region': ('str', True, _MISSING),
    'max_dispatchers': ('pos_int', True, _MISSING),
}

DESK_SHIFT_SCHEMA = {
    'dispatcher_id': ('str', True, _MISSING),
    'desk_id': ('str', False, _MISSING),
    'shift_start_utc': ('dt', True, _MISSING),
    'shift_end_utc': ('dt', True, _MISSING),
}


# ---------------------------------------------------------------- stations ---

@bp.post('/dispatch/stations')
def create_station():
    data = validate_body(STATION_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    if any(s['iata_code'] == data['iata_code'] for s in store.stations.values()):
        raise err('ERR_DUPLICATE_RESOURCE', 'iata_code already exists')
    rec = {'id': new_uuid(), **data}
    store.stations[rec['id']] = store.stamp_new(rec)
    return ok(ser_station(rec), status=201)


@bp.get('/dispatch/stations/<stationId>')
def get_station(stationId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.stations, stationId, 'station')
    return ok(ser_station(rec))


@bp.get('/dispatch/stations')
def list_stations():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.stations.values())
    status = request.args.get('status')
    if status is not None:
        items = [s for s in items if s['status'] == status]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_station(s) for s in page], is_list=True, pagination=meta)


# --------------------------------------------------------------- aircraft ---

@bp.post('/dispatch/aircraft')
def create_aircraft():
    data = validate_body(AIRCRAFT_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    if any(a['tail_no'] == data['tail_no'] for a in store.aircraft.values()):
        raise err('ERR_DUPLICATE_RESOURCE', 'tail_no already exists')
    rec = {'id': new_uuid(), **data}
    store.aircraft[rec['id']] = store.stamp_new(rec)
    return ok(ser_aircraft(rec), status=201)


@bp.get('/dispatch/aircraft/<aircraftId>')
def get_aircraft(aircraftId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.aircraft, aircraftId, 'aircraft')
    return ok(ser_aircraft(rec))


# ------------------------------------------------------------ dispatchers ---

@bp.post('/dispatch/dispatchers')
def create_dispatcher():
    data = validate_body(DISPATCHER_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    if any(d['license_no'] == data['license_no'] for d in store.dispatchers.values()):
        raise err('ERR_DUPLICATE_RESOURCE', 'license_no already exists')
    rec = {'id': new_uuid(), **data}
    store.dispatchers[rec['id']] = store.stamp_new(rec)
    return ok(ser_dispatcher(rec), status=201)


@bp.get('/dispatch/dispatchers/<dispatcherId>')
def get_dispatcher(dispatcherId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.dispatchers, dispatcherId, 'dispatcher')
    return ok(ser_dispatcher(rec))


# ---------------------------------------------------------------- captains ---

@bp.post('/dispatch/captains')
def create_captain():
    data = validate_body(CAPTAIN_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    if any(c['license_no'] == data['license_no'] for c in store.captains.values()):
        raise err('ERR_DUPLICATE_RESOURCE', 'license_no already exists')
    rec = {'id': new_uuid(), **data}
    store.captains[rec['id']] = store.stamp_new(rec)
    return ok(ser_captain(rec), status=201)


@bp.get('/dispatch/captains/<captainId>')
def get_captain(captainId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.captains, captainId, 'captain')
    return ok(ser_captain(rec))


# ------------------------------------------------------------------- desks ---

@bp.post('/dispatch/desks')
def create_desk():
    data = validate_body(DESK_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    if any(d['code'] == data['code'] for d in store.desks.values()):
        raise err('ERR_DUPLICATE_RESOURCE', 'code already exists')
    rec = {'id': new_uuid(), **data}
    store.desks[rec['id']] = store.stamp_new(rec)
    return ok(ser_desk(rec), status=201)


@bp.get('/dispatch/desks/<deskId>')
def get_desk(deskId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.desks, deskId, 'desk')
    return ok(ser_desk(rec))


# ------------------------------------------------------------- desk shifts ---

@bp.post('/dispatch/desk-shifts')
def create_desk_shift():
    data = validate_body(DESK_SHIFT_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    dispatcher = get_or_404(store.dispatchers, data['dispatcher_id'], 'dispatcher')
    desk = None
    if 'desk_id' in data:
        desk = get_or_404(store.desks, data['desk_id'], 'desk')
    start, end = data['shift_start_utc'], data['shift_end_utc']

    # business safety: rest buffer (before uniqueness per priority order)
    rest_bad = False
    overlap_bad = False
    for s in store.desk_shifts.values():
        if s['dispatcher_id'] != dispatcher['id']:
            continue
        if s['shift_start_utc'] < end and start < s['shift_end_utc']:
            overlap_bad = True
        else:
            if s['shift_end_utc'] <= start:
                gap = start - s['shift_end_utc']
            elif end <= s['shift_start_utc']:
                gap = s['shift_start_utc'] - end
            else:
                continue
            if gap < timedelta(minutes=REST_BUFFER_MIN):
                rest_bad = True
    if rest_bad:
        raise err('ERR_REST_VIOLATION')
    if overlap_bad:
        raise err('ERR_SHIFT_OVERLAP')

    # temporal: window shape
    if end <= start:
        raise err('ERR_WINDOW_INVALID')

    # fiscal: desk selection + capacity
    if desk is None:
        desk = auto_select_desk()
    check_desk_capacity(desk, start, end)

    rec = {
        'id': new_uuid(),
        'dispatcher_id': dispatcher['id'],
        'desk_id': desk['id'],
        'shift_start_utc': start,
        'shift_end_utc': end,
    }
    store.desk_shifts[rec['id']] = store.stamp_new(rec)
    return ok(ser_desk_shift(rec), status=201)


@bp.get('/dispatch/desk-shifts/<shiftId>')
def get_desk_shift(shiftId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.desk_shifts, shiftId, 'desk shift')
    return ok(ser_desk_shift(rec))


@bp.get('/dispatch/desk-shifts')
def list_desk_shifts():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.desk_shifts.values())
    dispatcher_id = request.args.get('dispatcher_id')
    desk_id = request.args.get('desk_id')
    if dispatcher_id is not None:
        items = [s for s in items if s['dispatcher_id'] == dispatcher_id]
    if desk_id is not None:
        items = [s for s in items if s['desk_id'] == desk_id]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_desk_shift(s) for s in page], is_list=True, pagination=meta)
