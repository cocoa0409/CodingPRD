"""MEL/CDL items, weather packages, and the logical clock."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err
from util import (ok, authenticate, authorize, validate_body, pagination_params,
                  paginate, sorted_created, get_or_404, _MISSING, fmt_dt, parse_dt)
from serializers import ser_mel_item, ser_weather_package
from services import (new_uuid, DEFERRAL_DAYS, mel_expiry_sweep,
                      weather_revalidation)

bp = Blueprint('ops', __name__)

ALL = ['Dispatcher', 'Captain', 'DispatchSupervisor']
SUP = ['DispatchSupervisor']

MEL_SCHEMA = {
    'aircraft_id': ('str', True, _MISSING),
    'item_code': ('str', True, _MISSING),
    'category': ('enum:MEL,CDL', True, _MISSING),
    'deferral_category': ('enum:A,B,C,D', True, _MISSING),
    'repair_deadline_utc': ('dt', True, _MISSING),
    'fuel_penalty_pct': ('nn_num', False, 0),
    'payload_penalty_kg': ('nn_int', False, 0),
    'minima_bump': ('bool', False, False),
}

WEATHER_CREATE_SCHEMA = {
    'station_id': ('str', True, _MISSING),
    'valid_from_utc': ('dt', True, _MISSING),
    'valid_to_utc': ('dt', True, _MISSING),
    'ceiling_ft': ('nn_int', True, _MISSING),
    'visibility_m': ('nn_int', True, _MISSING),
}

WEATHER_REPLACE_SCHEMA = {
    'valid_from_utc': ('dt', True, _MISSING),
    'valid_to_utc': ('dt', True, _MISSING),
    'ceiling_ft': ('nn_int', True, _MISSING),
    'visibility_m': ('nn_int', True, _MISSING),
    'expected_station_version': ('int', True, _MISSING),
}


def _check_weather_overlap(station_id, new_from, new_to, exclude_id=None):
    for p in store.weather_packages.values():
        if p['station_id'] != station_id or p['status'] != 'ACTIVE':
            continue
        if exclude_id is not None and p['id'] == exclude_id:
            continue
        if p['valid_from_utc'] < new_to and new_from < p['valid_to_utc']:
            raise err('ERR_WEATHER_WINDOW_OVERLAP')


# --------------------------------------------------------------- mel items ---

@bp.post('/dispatch/mel-items')
def create_mel_item():
    data = validate_body(MEL_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    get_or_404(store.aircraft, data['aircraft_id'], 'aircraft')
    interval = timedelta(days=DEFERRAL_DAYS[data['deferral_category']])
    if data['repair_deadline_utc'] > store.clock + interval:
        raise err('ERR_REPAIR_WINDOW_EXCEEDED')
    rec = {'id': new_uuid(), 'status': 'OPEN', **data}
    store.mel_items[rec['id']] = store.stamp_new(rec)
    return ok(ser_mel_item(rec), status=201)


@bp.get('/dispatch/mel-items/<itemId>')
def get_mel_item(itemId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.mel_items, itemId, 'mel item')
    return ok(ser_mel_item(rec))


@bp.get('/dispatch/mel-items')
def list_mel_items():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.mel_items.values())
    aircraft_id = request.args.get('aircraft_id')
    status = request.args.get('status')
    if aircraft_id is not None:
        items = [i for i in items if i['aircraft_id'] == aircraft_id]
    if status is not None:
        items = [i for i in items if i['status'] == status]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_mel_item(i) for i in page], is_list=True, pagination=meta)


@bp.post('/dispatch/mel-items/<itemId>/clear')
def clear_mel_item(itemId):
    uid, role = authenticate(); authorize(role, SUP)
    rec = get_or_404(store.mel_items, itemId, 'mel item')
    if rec['status'] != 'OPEN':
        raise err('ERR_INVALID_STATE', 'only an OPEN item can be cleared')
    rec['status'] = 'CLEARED'
    store.touch(rec)
    return ok(ser_mel_item(rec))


# ---------------------------------------------------------- weather packages ---

@bp.post('/dispatch/weather-packages')
def create_weather_package():
    data = validate_body(WEATHER_CREATE_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    station = get_or_404(store.stations, data['station_id'], 'station')
    # uniqueness (overlap) runs before temporal (window shape) per priority order
    _check_weather_overlap(station['id'], data['valid_from_utc'], data['valid_to_utc'])
    if data['valid_to_utc'] <= data['valid_from_utc']:
        raise err('ERR_WINDOW_INVALID')
    rec = {'id': new_uuid(), 'status': 'ACTIVE', **data}
    store.weather_packages[rec['id']] = store.stamp_new(rec)
    store.touch(station)  # publishing increments the station version
    return ok(ser_weather_package(rec), status=201)


@bp.get('/dispatch/weather-packages/<packageId>')
def get_weather_package(packageId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.weather_packages, packageId, 'weather package')
    return ok(ser_weather_package(rec))


@bp.get('/dispatch/weather-packages')
def list_weather_packages():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.weather_packages.values())
    station_id = request.args.get('station_id')
    if station_id is not None:
        items = [p for p in items if p['station_id'] == station_id]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_weather_package(p) for p in page], is_list=True, pagination=meta)


@bp.post('/dispatch/weather-packages/<packageId>/replace')
def replace_weather_package(packageId):
    data = validate_body(WEATHER_REPLACE_SCHEMA)
    uid, role = authenticate(); authorize(role, SUP)
    target = get_or_404(store.weather_packages, packageId, 'weather package')
    station = store.stations[target['station_id']]
    # OCC on the station
    if data['expected_station_version'] != station['version']:
        raise err('ERR_STALE_VERSION')
    # state: only an ACTIVE package can be replaced
    if target['status'] != 'ACTIVE':
        raise err('ERR_INVALID_STATE', 'only an ACTIVE package can be replaced')
    # uniqueness before temporal; replaced package excluded from the check
    _check_weather_overlap(station['id'], data['valid_from_utc'], data['valid_to_utc'],
                           exclude_id=target['id'])
    if data['valid_to_utc'] <= data['valid_from_utc']:
        raise err('ERR_WINDOW_INVALID')
    target['status'] = 'SUPERSEDED'
    store.touch(target)
    rec = {
        'id': new_uuid(),
        'station_id': station['id'],
        'valid_from_utc': data['valid_from_utc'],
        'valid_to_utc': data['valid_to_utc'],
        'ceiling_ft': data['ceiling_ft'],
        'visibility_m': data['visibility_m'],
        'status': 'ACTIVE',
    }
    store.weather_packages[rec['id']] = store.stamp_new(rec)
    store.touch(station)  # replacement increments the station version
    weather_revalidation(station['id'])
    return ok(ser_weather_package(rec), status=201)


# --------------------------------------------------------------------- clock ---

@bp.post('/dispatch/_clock/set_current_utc')
def set_clock():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or 'to_iso8601' not in body:
        raise err('ERR_INVALID_REQUEST', 'missing required field to_iso8601')
    for key in body:
        if key != 'to_iso8601':
            raise err('ERR_INVALID_REQUEST', 'unknown field %r' % key)
    new_clock = parse_dt(body['to_iso8601'])
    uid, role = authenticate(); authorize(role, SUP)
    store.clock = new_clock
    mel_expiry_sweep()
    return ok({'current_utc': fmt_dt(store.clock)})
