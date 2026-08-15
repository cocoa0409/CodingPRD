"""Weather observation and community complaint endpoints (PRD 3.2, 3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import domain as D
from domain import ser_weather_observation, ser_complaint, sort_created, get_or_404
from envelope import success
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_COMPLAINT_FLIGHT_MISMATCH,
)
from store import db, now, new_entity, touch, next_seq, new_id
from validate import get_body, authenticate, require_role, paginated, _str, _int, _enum, _dt

bp = Blueprint('weather_complaints', __name__)

WEATHER_READ_ROLES = ('OpsAdmin', 'Dispatcher', 'BookingAgent', 'ComplianceOfficer', 'CommunityReporter', 'Pilot')
COMPLAINT_READ_ROLES = ('OpsAdmin', 'Dispatcher', 'ComplianceOfficer', 'CommunityReporter')
COMPLAINT_ZONES = ('VILLAGE', 'RIM', 'AIRPORT')
COMPLAINT_EVENTS = ('REVIEW', 'LINK_FLIGHT', 'SUBSTANTIATE', 'DISMISS', 'CLOSE', 'REOPEN')


# ---------------------------------------------------------------------------
# Weather observations
# ---------------------------------------------------------------------------

@bp.route('/weather-observations', methods=['POST'])
def create_observation():
    body = get_body()
    base_id = _str(body, 'base_id', True)
    observed_at = _dt(body, 'observed_at', True)
    ceiling = _int(body, 'ceiling_ft', True)
    visibility = _int(body, 'visibility_sm', True)
    wind = _int(body, 'wind_kt', True)
    _, role = authenticate()
    require_role(role, ('Dispatcher',))
    base = get_or_404(db.bases, base_id, 'Base')
    values = {'ceiling_ft': ceiling, 'visibility_sm': visibility, 'wind_kt': wind}
    adverse = D.observation_adverse(values, base)
    o = {
        'id': new_id(),
        'created_at': now(),
        '_seq': next_seq(),
        'base_id': base['id'],
        'observed_at': observed_at,
        'ceiling_ft': ceiling,
        'visibility_sm': visibility,
        'wind_kt': wind,
        'adverse': adverse,
        'validity_until': observed_at + timedelta(minutes=base['weather_validity_min']),
    }
    db.weather_observations[o['id']] = o
    # Fire the cascade when this newly posted adverse observation becomes
    # governing (PRD 3.2). "Governing" here is evaluated against the new
    # observation's own observed_at window: an observation whose observed_at
    # is in the future still governs flights inside [observed_at,
    # validity_until) — that is the only way the cascade can ever reach
    # flights departing between observed_at and validity_until. A stale
    # observation (one that does not surpass the current governing
    # observation's observed_at) does not fire.
    if adverse:
        prior = [
            x for x in db.weather_observations.values()
            if x['base_id'] == base['id'] and x['id'] != o['id']
        ]
        prior_latest = max(prior, key=lambda x: (x['observed_at'], x['_seq'])) if prior else None
        if prior_latest is None or (o['observed_at'], o['_seq']) >= (prior_latest['observed_at'], prior_latest['_seq']):
            D.weather_cascade(base, o)
    return success(ser_weather_observation(o), status=201)


@bp.route('/weather-observations', methods=['GET'])
def list_observations():
    _, role = authenticate()
    require_role(role, WEATHER_READ_ROLES)
    items = sort_created(db.weather_observations.values())
    base_filter = request.args.get('base_id')
    if base_filter is not None:
        items = [o for o in items if o['base_id'] == base_filter]
    page, meta = paginated(items)
    return success([ser_weather_observation(o) for o in page], response_type='array', pagination=meta)


@bp.route('/weather-observations/<oid>', methods=['GET'])
def get_observation(oid):
    _, role = authenticate()
    require_role(role, WEATHER_READ_ROLES)
    o = get_or_404(db.weather_observations, oid, 'WeatherObservation')
    return success(ser_weather_observation(o))


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

@bp.route('/complaints', methods=['POST'])
def create_complaint():
    body = get_body()
    base_id = _str(body, 'base_id', True)
    zone = _enum(body, 'zone', True, COMPLAINT_ZONES)
    observed_at = _dt(body, 'observed_at', True)
    description = _str(body, 'description', True)
    reporter_ref = _str(body, 'reporter_ref', True)
    _, role = authenticate()
    require_role(role, ('CommunityReporter',))
    base = get_or_404(db.bases, base_id, 'Base')
    c = new_entity()
    c.update({
        'base_id': base['id'],
        'zone': zone,
        'observed_at': observed_at,
        'description': description,
        'reporter_ref': reporter_ref,
        'status': 'LOGGED',
        'match_status': 'UNMATCHED',
        'matched_flight_id': None,
        'matched_route_id': None,
        'resolution_note': None,
    })
    db.complaints[c['id']] = c
    match = D.auto_match_complaint(c)
    if match is not None:
        c['match_status'] = 'MATCHED'
        c['matched_flight_id'] = match['id']
        c['matched_route_id'] = match['route_id']
    return success(ser_complaint(c), status=201)


@bp.route('/complaints', methods=['GET'])
def list_complaints():
    _, role = authenticate()
    require_role(role, COMPLAINT_READ_ROLES)
    items = sort_created(db.complaints.values())
    for param in ('base_id', 'status', 'matched_route_id'):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    page, meta = paginated(items)
    return success([ser_complaint(c) for c in page], response_type='array', pagination=meta)


@bp.route('/complaints/<cid>', methods=['GET'])
def get_complaint(cid):
    _, role = authenticate()
    require_role(role, COMPLAINT_READ_ROLES)
    c = get_or_404(db.complaints, cid, 'Complaint')
    return success(ser_complaint(c))


@bp.route('/complaints/<cid>/events', methods=['POST'])
def complaint_events(cid):
    body = get_body()
    event_type = _enum(body, 'event_type', True, COMPLAINT_EVENTS)
    flight_id = None
    resolution_note = None
    if event_type == 'LINK_FLIGHT':
        flight_id = _str(body, 'flight_id', True)
    if event_type == 'CLOSE':
        resolution_note = _str(body, 'resolution_note', False)
    _, role = authenticate()
    require_role(role, ('ComplianceOfficer',))
    c = get_or_404(db.complaints, cid, 'Complaint')
    if event_type == 'REVIEW':
        if c['status'] != 'LOGGED':
            raise_error(ERR_INVALID_STATE, 'REVIEW requires LOGGED')
        c['status'] = 'UNDER_REVIEW'
        touch(c)
    elif event_type == 'LINK_FLIGHT':
        flight = get_or_404(db.flights, flight_id, 'Flight')
        route = db.routes[flight['route_id']]
        if c['zone'] not in route['noise_zones']:
            raise_error(ERR_COMPLAINT_FLIGHT_MISMATCH, 'Flight route does not overfly the complaint zone')
        c['match_status'] = 'MATCHED'
        c['matched_flight_id'] = flight['id']
        c['matched_route_id'] = flight['route_id']
        touch(c)
    elif event_type == 'SUBSTANTIATE':
        if c['status'] != 'UNDER_REVIEW':
            raise_error(ERR_INVALID_STATE, 'SUBSTANTIATE requires UNDER_REVIEW')
        flight = db.flights.get(c['matched_flight_id']) if c['matched_flight_id'] else None
        if flight is None or flight['status'] not in ('DISPATCHED', 'COMPLETED'):
            raise_error(ERR_COMPLAINT_FLIGHT_MISMATCH, 'Matched flight must be DISPATCHED or COMPLETED')
        c['status'] = 'SUBSTANTIATED'
        touch(c)
        # Quota check against the complaint's base; suspension cascade fires.
        base = db.bases[c['base_id']]
        route = db.routes.get(c['matched_route_id'])
        if route is not None and route['status'] == 'ACTIVE':
            if D.complaint_count_for_route(route['id'], base['id']) >= base['complaint_quota_threshold']:
                route['status'] = 'SUSPENDED'
                touch(route)
                D.route_suspension_cascade(route)
    elif event_type == 'DISMISS':
        if c['status'] not in ('LOGGED', 'UNDER_REVIEW'):
            raise_error(ERR_INVALID_STATE, 'DISMISS requires LOGGED or UNDER_REVIEW')
        c['status'] = 'DISMISSED'
        touch(c)
    elif event_type == 'CLOSE':
        if c['status'] not in ('SUBSTANTIATED', 'DISMISSED'):
            raise_error(ERR_INVALID_STATE, 'CLOSE requires SUBSTANTIATED or DISMISSED')
        c['status'] = 'CLOSED'
        if resolution_note is not None:
            c['resolution_note'] = resolution_note
        touch(c)
    else:  # REOPEN
        if c['status'] != 'CLOSED':
            raise_error(ERR_INVALID_STATE, 'REOPEN requires CLOSED')
        c['status'] = 'UNDER_REVIEW'
        touch(c)
    return success(ser_complaint(c))
