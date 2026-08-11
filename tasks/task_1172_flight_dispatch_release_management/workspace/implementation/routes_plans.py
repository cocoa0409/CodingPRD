"""Flight plan and payload manifest endpoints."""
from flask import Blueprint, request

from db import store
from errors import err
from util import (ok, authenticate, authorize, validate_body, pagination_params,
                  paginate, sorted_created, get_or_404, _MISSING)
from serializers import ser_plan, ser_manifest
from services import (new_uuid, compute_plan_fields, recompute_plan_fields,
                      weather_check, manifest_for_leg, current_plan_for_leg,
                      compute_manifest_fields, validate_manifest_fiscal)

bp = Blueprint('plans', __name__)

ALL = ['Dispatcher', 'Captain', 'DispatchSupervisor']
DISP = ['Dispatcher']

PLAN_SCHEMA = {
    'leg_id': ('str', True, _MISSING),
    'route_code': ('str', True, _MISSING),
    'cruise_altitude_ft': ('pos_int', True, _MISSING),
    'forecast_wind_kts': ('int', True, _MISSING),
    'wind_assumption': ('enum:FORECAST,WORST_CASE', True, _MISSING),
    'expected_leg_version': ('int', True, _MISSING),
}

MANIFEST_CREATE_SCHEMA = {
    'leg_id': ('str', True, _MISSING),
    'pax_count': ('nn_int', True, _MISSING),
    'bags_count': ('nn_int', True, _MISSING),
    'cargo_kg': ('nn_num', True, _MISSING),
}

MANIFEST_UPDATE_SCHEMA = {
    'pax_count': ('nn_int', False, _MISSING),
    'bags_count': ('nn_int', False, _MISSING),
    'cargo_kg': ('nn_num', False, _MISSING),
}


def _plan_owner(plan, uid):
    leg = store.legs[plan['leg_id']]
    if leg['dispatcher_id'] != uid:
        raise err('ERR_NOT_ASSIGNED_DISPATCHER')
    return leg


@bp.post('/dispatch/plans')
def create_plan():
    data = validate_body(PLAN_SCHEMA)
    uid, role = authenticate(); authorize(role, DISP)
    leg = get_or_404(store.legs, data['leg_id'], 'leg')
    # OCC on the leg
    if data['expected_leg_version'] != leg['version']:
        raise err('ERR_STALE_VERSION')
    aircraft = store.aircraft[leg['aircraft_id']]
    # safety: worst-case wind mandate
    from services import open_mel_items
    if data['wind_assumption'] == 'FORECAST':
        if any(i['fuel_penalty_pct'] > 0 for i in open_mel_items(aircraft['id'])):
            raise err('ERR_WORST_CASE_REQUIRED')
    # uniqueness: plan-in-use gate
    for rel in store.releases.values():
        if rel['leg_id'] == leg['id'] and rel['status'] not in ('CANCELLED', 'CLOSED'):
            pinned = store.plans.get(rel['plan_id'])
            if pinned is not None and pinned['status'] == 'LOCKED':
                raise err('ERR_PLAN_IN_USE')
    # compute (alternate selection raises ERR_NO_SUITABLE_ALTERNATE)
    fields = compute_plan_fields(leg, aircraft, leg['distance_nm'],
                                 data['forecast_wind_kts'], data['wind_assumption'])
    # supersede prior non-SUPERSEDED plans of the leg
    for p in store.plans.values():
        if p['leg_id'] == leg['id'] and p['status'] in ('COMPUTED', 'LOCKED'):
            p['status'] = 'SUPERSEDED'
            store.touch(p)
    prior_seqs = [p['plan_seq'] for p in store.plans.values() if p['leg_id'] == leg['id']]
    rec = {
        'id': new_uuid(),
        'leg_id': leg['id'],
        'plan_seq': (max(prior_seqs) if prior_seqs else 0) + 1,
        'route_code': data['route_code'],
        'cruise_altitude_ft': data['cruise_altitude_ft'],
        'forecast_wind_kts': data['forecast_wind_kts'],
        'wind_assumption': data['wind_assumption'],
        'status': 'COMPUTED',
        **fields,
    }
    store.plans[rec['id']] = store.stamp_new(rec)
    store.touch(leg)  # plan creation increments the leg version
    return ok(ser_plan(rec), status=201)


@bp.get('/dispatch/plans/<planId>')
def get_plan(planId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.plans, planId, 'plan')
    return ok(ser_plan(rec))


@bp.get('/dispatch/plans')
def list_plans():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.plans.values())
    leg_id = request.args.get('leg_id')
    alt_id = request.args.get('alternate_station_id')
    if leg_id is not None:
        items = [p for p in items if p['leg_id'] == leg_id]
    if alt_id is not None:
        items = [p for p in items if p['alternate_station_id'] == alt_id]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_plan(p) for p in page], is_list=True, pagination=meta)


@bp.post('/dispatch/plans/<planId>/lock')
def lock_plan(planId):
    uid, role = authenticate(); authorize(role, DISP)
    plan = get_or_404(store.plans, planId, 'plan')
    leg = _plan_owner(plan, uid)
    if plan['status'] != 'COMPUTED':
        raise err('ERR_INVALID_STATE', 'only a COMPUTED plan can be locked')
    station = store.stations[leg['arr_station_id']]
    aircraft = store.aircraft[leg['aircraft_id']]
    weather_check(station, leg['sched_arr_utc'], aircraft)
    if plan['required_fuel_kg'] > aircraft['fuel_capacity_kg']:
        raise err('ERR_FUEL_EXCEEDS_CAPACITY')
    plan['status'] = 'LOCKED'
    store.touch(plan)
    return ok(ser_plan(plan))


@bp.post('/dispatch/plans/<planId>/recompute')
def recompute_plan(planId):
    uid, role = authenticate(); authorize(role, DISP)
    plan = get_or_404(store.plans, planId, 'plan')
    _plan_owner(plan, uid)
    if plan['status'] != 'LOCKED':
        raise err('ERR_INVALID_STATE', 'only a LOCKED plan can be recomputed')
    plan['status'] = 'COMPUTED'
    recompute_plan_fields(plan)
    store.touch(plan)
    return ok(ser_plan(plan))


# --------------------------------------------------------------- manifests ---

def _locked_plan_or_409(leg):
    plan = current_plan_for_leg(leg['id'])
    if plan is None or plan['status'] != 'LOCKED':
        raise err('ERR_PLAN_NOT_LOCKED')
    return plan


@bp.post('/dispatch/manifests')
def create_manifest():
    data = validate_body(MANIFEST_CREATE_SCHEMA)
    uid, role = authenticate(); authorize(role, DISP)
    leg = get_or_404(store.legs, data['leg_id'], 'leg')
    # uniqueness before referential per priority order
    if manifest_for_leg(leg['id']) is not None:
        raise err('ERR_MANIFEST_EXISTS')
    plan = _locked_plan_or_409(leg)
    aircraft = store.aircraft[leg['aircraft_id']]
    fields = compute_manifest_fields(aircraft, plan, data['pax_count'],
                                     data['bags_count'], data['cargo_kg'])
    validate_manifest_fiscal(fields, aircraft)
    fields.pop('_cg_exact')
    rec = {
        'id': new_uuid(),
        'leg_id': leg['id'],
        'plan_id': plan['id'],
        'pax_count': data['pax_count'],
        'bags_count': data['bags_count'],
        'cargo_kg': data['cargo_kg'],
        **fields,
    }
    store.manifests[rec['id']] = store.stamp_new(rec)
    return ok(ser_manifest(rec), status=201)


@bp.get('/dispatch/manifests/<manifestId>')
def get_manifest(manifestId):
    uid, role = authenticate(); authorize(role, ALL)
    rec = get_or_404(store.manifests, manifestId, 'manifest')
    return ok(ser_manifest(rec))


@bp.get('/dispatch/manifests')
def list_manifests():
    limit, offset = pagination_params()
    uid, role = authenticate(); authorize(role, ALL)
    items = list(store.manifests.values())
    leg_id = request.args.get('leg_id')
    plan_id = request.args.get('plan_id')
    if leg_id is not None:
        items = [m for m in items if m['leg_id'] == leg_id]
    if plan_id is not None:
        items = [m for m in items if m['plan_id'] == plan_id]
    page, meta = paginate(sorted_created(items), limit, offset)
    return ok([ser_manifest(m) for m in page], is_list=True, pagination=meta)


@bp.put('/dispatch/manifests/<manifestId>')
def update_manifest(manifestId):
    data = validate_body(MANIFEST_UPDATE_SCHEMA)
    uid, role = authenticate(); authorize(role, DISP)
    rec = get_or_404(store.manifests, manifestId, 'manifest')
    leg = store.legs[rec['leg_id']]
    plan = _locked_plan_or_409(leg)
    aircraft = store.aircraft[leg['aircraft_id']]
    pax = data.get('pax_count', rec['pax_count'])
    bags = data.get('bags_count', rec['bags_count'])
    cargo = data.get('cargo_kg', rec['cargo_kg'])
    fields = compute_manifest_fields(aircraft, plan, pax, bags, cargo)
    validate_manifest_fiscal(fields, aircraft)
    fields.pop('_cg_exact')
    rec['pax_count'] = pax
    rec['bags_count'] = bags
    rec['cargo_kg'] = cargo
    rec['plan_id'] = plan['id']  # re-pin to the current LOCKED plan
    rec.update(fields)
    store.touch(rec)
    return ok(ser_manifest(rec))
