"""Dispatch releases, signatures, monitoring events, control records."""
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import err
from util import (ok, authenticate, authorize, validate_body, pagination_params,
                  paginate, sorted_created, get_or_404, _MISSING)
from serializers import (ser_release, ser_signature, ser_monitoring_event,
                         ser_control_record)
from services import (new_uuid, write_record, manifest_for_leg, open_mel_items,
                      expired_mel_exists, current_plan_for_leg,
                      non_terminal_release_for_leg, latest_release_for_leg,
                      compute_manifest_fields, validate_manifest_fiscal,
                      weather_check, rhu, D, DIVERT_MARGIN_KG,
                      ALT_MINIMA_BUMP_CEILING_FT, ALT_MINIMA_BUMP_VIS_M)

bp = Blueprint('releases', __name__)

ALL = ['Dispatcher', 'Captain', 'DispatchSupervisor']
DISP = ['Dispatcher']

RELEASE_SCHEMA = {
    'leg_id': ('str', True, _MISSING),
}

SIGN_SCHEMA = {
    'statement': ('str', False, _MISSING),
}

EVENT_SCHEMA = {
    'leg_id': ('str', True, _MISSING),
    'fuel_remaining_kg': ('nn_int', True, _MISSING),
    'eta_destination_utc': ('dt', True, _MISSING),
    'dest_ceiling_ft': ('nn_int', False, _MISSING),
    'dest_visibility_m': ('nn_int', False, _MISSING),
}


def _release_dispatcher_gate(rel, uid):
    if rel['dispatcher_id'] != uid:
        raise err('ERR_NOT_ASSIGNED_DISPATCHER')


# ---------------------------------------------------------------- releases ---

@bp.post('/dispatch/releases')
def create_release():
    data = validate_body(RELEASE_SCHEMA)
    uid, role = authenticate(); authorize(role, DISP)
    leg = get_or_404(store.legs, data['leg_id'], 'leg')
    # uniqueness before referential per priority order
    if non_terminal_release_for_leg(leg['id']) is not None:
        raise err('ERR_RELEASE_EXISTS')
    plan = current_plan_for_leg(leg['id'])
    if plan is None or plan['status'] != 'LOCKED':
        raise err('ERR_PLAN_NOT_LOCKED')
    if manifest_for_leg(leg['id']) is None:
        raise err('ERR_MANIFEST_MISSING')
    rec = {
        'id': new_uuid(),
        'leg_id': leg['id'],
        'plan_id': plan['id'],
        'dispatcher_id': leg['dispatcher_id'],
        'captain_id': leg['captain_id'],
        'status': 'DRAFT',
        'cycle_seq': 1,
        'amendment_count': 0,
    }
    store.releases[rec['id']] = store.stamp_new(rec)
    write_record(leg['id'], rec['id'], role, uid, 'RELEASE_CREATED',
                 from_status=None, to_status='DRAFT')
    return ok(ser_release(rec), status=201)


@bp.get('/dispatch/releases/<releaseId>')
def get_release(releaseId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.releases, releaseId, 'release')
    return ok(ser_release(rec))


@bp.get('/dispatch/releases')
def list_releases():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.releases.values())
    for f in ('leg_id', 'plan_id', 'dispatcher_id', 'captain_id'):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_release(r) for r in page], is_list=True, pagination=meta)


@bp.post('/dispatch/releases/<releaseId>/submit')
def submit_release(releaseId):
    uid, role = authenticate(); authorize(role, DISP)
    rel = get_or_404(store.releases, releaseId, 'release')
    _release_dispatcher_gate(rel, uid)
    if rel['status'] not in ('DRAFT', 'UNDER_AMENDMENT'):
        raise err('ERR_INVALID_STATE', 'only DRAFT or UNDER_AMENDMENT can be submitted')
    leg = store.legs[rel['leg_id']]
    aircraft = store.aircraft[leg['aircraft_id']]
    # safety
    if expired_mel_exists(leg['aircraft_id']):
        raise err('ERR_MEL_ITEM_EXPIRED')
    captain = store.captains[leg['captain_id']]
    if aircraft['type_code'] not in captain['qualified_type_codes']:
        raise err('ERR_CAPTAIN_NOT_QUALIFIED')
    # referential
    plan = store.plans.get(rel['plan_id'])
    if plan is None or plan['status'] != 'LOCKED':
        raise err('ERR_PLAN_NOT_LOCKED')
    manifest = manifest_for_leg(leg['id'])
    if manifest is None:
        raise err('ERR_MANIFEST_MISSING')
    # fiscal: weight/CG re-checked against the pinned plan
    fields = compute_manifest_fields(aircraft, plan, manifest['pax_count'],
                                     manifest['bags_count'], manifest['cargo_kg'])
    validate_manifest_fiscal(fields, aircraft)
    # weather currency at the arrival station
    station = store.stations[leg['arr_station_id']]
    weather_check(station, leg['sched_arr_utc'], aircraft)
    if plan['required_fuel_kg'] > aircraft['fuel_capacity_kg']:
        raise err('ERR_FUEL_EXCEEDS_CAPACITY')
    old = rel['status']
    rel['status'] = 'PENDING_SIGNATURES'
    store.touch(rel)
    write_record(leg['id'], rel['id'], role, uid, 'RELEASE_SUBMITTED',
                 from_status=old, to_status='PENDING_SIGNATURES')
    return ok(ser_release(rel))


@bp.post('/dispatch/releases/<releaseId>/sign')
def sign_release(releaseId):
    data = validate_body(SIGN_SCHEMA)
    uid, role = authenticate(); authorize(role, ['Dispatcher', 'Captain'])
    rel = get_or_404(store.releases, releaseId, 'release')
    if role == 'Dispatcher':
        if rel['dispatcher_id'] != uid:
            raise err('ERR_NOT_ASSIGNED_DISPATCHER')
        slot = 'DISPATCHER'
    else:
        if rel['captain_id'] != uid:
            raise err('ERR_NOT_ASSIGNED_CAPTAIN')
        slot = 'CAPTAIN'
    if rel['status'] != 'PENDING_SIGNATURES':
        raise err('ERR_RELEASE_NOT_PENDING')
    leg = store.legs[rel['leg_id']]
    if expired_mel_exists(leg['aircraft_id']):
        raise err('ERR_MEL_ITEM_EXPIRED')
    # duplicate: a valid signature for this slot in the current cycle
    for s in store.signatures.values():
        if (s['release_id'] == rel['id'] and s['signer_role'] == slot
                and s['cycle_seq'] == rel['cycle_seq']):
            raise err('ERR_DUPLICATE_SIGNATURE')
    sig = {
        'id': new_uuid(),
        'release_id': rel['id'],
        'signer_role': slot,
        'signer_id': uid,
        'cycle_seq': rel['cycle_seq'],
        'signed_at_utc': store.clock,
    }
    sig['created_at'] = store.clock
    sig['_seq'] = store.next_seq()
    store.signatures[sig['id']] = sig
    old = rel['status']
    slots = {s['signer_role'] for s in store.signatures.values()
             if s['release_id'] == rel['id'] and s['cycle_seq'] == rel['cycle_seq']}
    if 'DISPATCHER' in slots and 'CAPTAIN' in slots:
        rel['status'] = 'RELEASED'
        store.touch(rel)
    write_record(leg['id'], rel['id'], role, uid, 'SIGNATURE_RECORDED',
                 from_status=old, to_status=rel['status'])
    return ok(ser_release(rel))


@bp.post('/dispatch/releases/<releaseId>/recall')
def recall_release(releaseId):
    uid, role = authenticate(); authorize(role, DISP)
    rel = get_or_404(store.releases, releaseId, 'release')
    _release_dispatcher_gate(rel, uid)
    if rel['status'] != 'PENDING_SIGNATURES':
        raise err('ERR_INVALID_STATE', 'only PENDING_SIGNATURES can be recalled')
    old = rel['status']
    rel['status'] = 'DRAFT'
    rel['cycle_seq'] += 1
    store.touch(rel)
    write_record(rel['leg_id'], rel['id'], role, uid, 'RELEASE_RECALLED',
                 from_status=old, to_status='DRAFT')
    return ok(ser_release(rel))


@bp.post('/dispatch/releases/<releaseId>/amend')
def amend_release(releaseId):
    uid, role = authenticate(); authorize(role, DISP)
    rel = get_or_404(store.releases, releaseId, 'release')
    _release_dispatcher_gate(rel, uid)
    if rel['status'] != 'RELEASED':
        raise err('ERR_INVALID_STATE', 'only RELEASED can be amended')
    old = rel['status']
    rel['status'] = 'UNDER_AMENDMENT'
    rel['cycle_seq'] += 1
    rel['amendment_count'] += 1
    store.touch(rel)
    write_record(rel['leg_id'], rel['id'], role, uid, 'RELEASE_AMENDED',
                 from_status=old, to_status='UNDER_AMENDMENT')
    return ok(ser_release(rel))


@bp.get('/dispatch/releases/<releaseId>/signatures')
def list_signatures(releaseId):
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    rel = get_or_404(store.releases, releaseId, 'release')
    items = [s for s in store.signatures.values() if s['release_id'] == rel['id']]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_signature(s) for s in page], is_list=True, pagination=meta)


# --------------------------------------------------------- monitoring events ---

@bp.post('/dispatch/monitoring-events')
def create_monitoring_event():
    data = validate_body(EVENT_SCHEMA)
    uid, role = authenticate(); authorize(role, DISP)
    leg = get_or_404(store.legs, data['leg_id'], 'leg')
    if leg['dispatcher_id'] != uid:
        raise err('ERR_NOT_ASSIGNED_DISPATCHER')
    if leg['ops_status'] != 'DEPARTED':
        raise err('ERR_LEG_NOT_IN_FLIGHT')
    rel = non_terminal_release_for_leg(leg['id']) or latest_release_for_leg(leg['id'])
    if rel is None:
        raise err('ERR_INVALID_STATE', 'no release exists for the leg')
    plan = store.plans.get(rel['plan_id'])
    if plan is None:
        raise err('ERR_INVALID_STATE', 'release has no pinned plan')
    hours = Decimal(str((data['eta_destination_utc'] - store.clock).total_seconds())) / Decimal('3600')
    remaining_estimate = hours * D(plan['burn_eff_kg_per_hour'])
    projected = rhu(D(data['fuel_remaining_kg']) - remaining_estimate)
    margin = projected - plan['final_reserve_kg']
    if margin >= DIVERT_MARGIN_KG:
        fuel_rec = 'NONE'
    elif margin >= 0:
        fuel_rec = 'CONSIDER_DIVERT'
    else:
        fuel_rec = 'RECOMMEND_DIVERT'
    station = store.stations[leg['arr_station_id']]
    bump = any(i['minima_bump'] for i in open_mel_items(leg['aircraft_id']))
    req_ceiling = station['min_ceiling_ft'] + (ALT_MINIMA_BUMP_CEILING_FT if bump else 0)
    req_vis = station['min_visibility_m'] + (ALT_MINIMA_BUMP_VIS_M if bump else 0)
    weather_rec = 'NONE'
    if 'dest_ceiling_ft' in data and data['dest_ceiling_ft'] < req_ceiling:
        weather_rec = 'RECOMMEND_DIVERT'
    if 'dest_visibility_m' in data and data['dest_visibility_m'] < req_vis:
        weather_rec = 'RECOMMEND_DIVERT'
    severity = {'NONE': 0, 'CONSIDER_DIVERT': 1, 'RECOMMEND_DIVERT': 2}
    recommendation = fuel_rec if severity[fuel_rec] >= severity[weather_rec] else weather_rec

    rec = {
        'id': new_uuid(),
        'leg_id': leg['id'],
        'fuel_remaining_kg': data['fuel_remaining_kg'],
        'eta_destination_utc': data['eta_destination_utc'],
        'dest_ceiling_ft': data.get('dest_ceiling_ft'),
        'dest_visibility_m': data.get('dest_visibility_m'),
        'projected_arrival_fuel_kg': projected,
        'fuel_margin_kg': margin,
        'recommendation': recommendation,
        'status': 'OPEN',
    }
    store.monitoring_events[rec['id']] = store.stamp_new(rec)
    if recommendation in ('CONSIDER_DIVERT', 'RECOMMEND_DIVERT'):
        if leg['monitor_status'] == 'MONITORING':
            leg['monitor_status'] = 'ALERTED'
            store.touch(leg)
    if recommendation == 'RECOMMEND_DIVERT':
        write_record(leg['id'], None, role, uid, 'DIVERT_RECOMMENDED',
                     from_status='MONITORING', to_status='ALERTED')
    return ok(ser_monitoring_event(rec), status=201)


@bp.get('/dispatch/monitoring-events/<eventId>')
def get_monitoring_event(eventId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.monitoring_events, eventId, 'monitoring event')
    return ok(ser_monitoring_event(rec))


@bp.get('/dispatch/monitoring-events')
def list_monitoring_events():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.monitoring_events.values())
    leg_id = request.args.get('leg_id')
    if leg_id is not None:
        items = [e for e in items if e['leg_id'] == leg_id]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_monitoring_event(e) for e in page], is_list=True, pagination=meta)


@bp.post('/dispatch/monitoring-events/<eventId>/acknowledge')
def acknowledge_monitoring_event(eventId):
    uid, role = authenticate(); authorize(role, DISP)
    rec = get_or_404(store.monitoring_events, eventId, 'monitoring event')
    leg = store.legs[rec['leg_id']]
    if leg['dispatcher_id'] != uid:
        raise err('ERR_NOT_ASSIGNED_DISPATCHER')
    if rec['status'] != 'OPEN':
        raise err('ERR_INVALID_STATE', 'only an OPEN event can be acknowledged')
    rec['status'] = 'ACKNOWLEDGED'
    store.touch(rec)
    if leg['monitor_status'] == 'ALERTED':
        remaining = [e for e in store.monitoring_events.values()
                     if e['leg_id'] == leg['id'] and e['status'] == 'OPEN'
                     and e['recommendation'] != 'NONE']
        if not remaining:
            leg['monitor_status'] = 'MONITORING'
            store.touch(leg)
    return ok(ser_monitoring_event(rec))


# ----------------------------------------------------------- control records ---

@bp.get('/dispatch/legs/<legId>/control-records')
def list_control_records(legId):
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    leg = get_or_404(store.legs, legId, 'leg')
    items = [r for r in store.control_records.values() if r['leg_id'] == leg['id']]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_control_record(r) for r in page], is_list=True, pagination=meta)
