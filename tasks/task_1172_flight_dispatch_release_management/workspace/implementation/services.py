"""Business logic: calculations (Decimal, round-half-up), selectors, cascades."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

from db import store
from errors import err

getcontext().prec = 50

D = lambda x: Decimal(str(x))

# Calculation constants
WEIGHT_STEP_KG = 10000
WEIGHT_STEP_PCT = Decimal('0.01')
WORST_HEADWIND_KTS = 50
MIN_CONTINGENCY_KG = Decimal('100')
CONTINGENCY_PCT = Decimal('0.05')
FINAL_RESERVE_H = Decimal('0.5')
PAX_KG = Decimal('87.5')
BAG_KG = Decimal('12.5')
ARM_OEW = Decimal('18.0')
ARM_PAX = Decimal('17.6')
ARM_BAG = Decimal('18.4')
ARM_CARGO = Decimal('19.5')
ARM_FUEL = Decimal('18.1')
CG_MIN_NORMAL = Decimal('20.0')
CG_MAX_NORMAL = Decimal('31.0')
CG_MIN_CDL = Decimal('22.0')
CG_MAX_CDL = Decimal('30.0')
MAX_ALTERNATE_DISTANCE_NM = 200
DIVERT_MARGIN_KG = 500
ALT_MINIMA_BUMP_CEILING_FT = 200
ALT_MINIMA_BUMP_VIS_M = 500
REST_BUFFER_MIN = 30
DELAY_REVIEW_THRESHOLD_MIN = 60
DEFERRAL_DAYS = {'A': 1, 'B': 3, 'C': 10, 'D': 30}


def rhu(x):
    return int(Decimal(x).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def rhu2(x):
    return float(Decimal(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def new_uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def manifest_for_leg(leg_id):
    for m in store.manifests.values():
        if m['leg_id'] == leg_id:
            return m
    return None


def open_mel_items(aircraft_id):
    return [i for i in store.mel_items.values()
            if i['aircraft_id'] == aircraft_id and i['status'] == 'OPEN']


def expired_mel_exists(aircraft_id):
    return any(i['aircraft_id'] == aircraft_id and i['status'] == 'EXPIRED'
               for i in store.mel_items.values())


def current_plan_for_leg(leg_id):
    """The leg's current non-SUPERSEDED plan (latest created)."""
    cands = [p for p in store.plans.values()
             if p['leg_id'] == leg_id and p['status'] != 'SUPERSEDED']
    if not cands:
        return None
    return max(cands, key=lambda p: (p['created_at'], p['_seq']))


def non_terminal_release_for_leg(leg_id):
    cands = [r for r in store.releases.values()
             if r['leg_id'] == leg_id and r['status'] not in ('CANCELLED', 'CLOSED')]
    if not cands:
        return None
    return max(cands, key=lambda r: (r['created_at'], r['_seq']))


def latest_release_for_leg(leg_id):
    cands = [r for r in store.releases.values() if r['leg_id'] == leg_id]
    if not cands:
        return None
    return max(cands, key=lambda r: (r['created_at'], r['_seq']))


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def write_record(leg_id, release_id, actor_role, actor_id, action,
                 from_status=None, to_status=None, note=None):
    rec = {
        'id': new_uuid(),
        'leg_id': leg_id,
        'release_id': release_id,
        'actor_role': actor_role,
        'actor_id': actor_id,
        'action': action,
        'from_status': from_status,
        'to_status': to_status,
        'note': note,
        'recorded_at_utc': store.clock,
    }
    rec['created_at'] = store.clock
    rec['_seq'] = store.next_seq()
    store.control_records[rec['id']] = rec
    return rec


# ---------------------------------------------------------------------------
# Plan calculations
# ---------------------------------------------------------------------------

def select_alternate(leg, aircraft):
    pool = [s for s in store.stations.values()
            if s['status'] == 'OPEN'
            and s['id'] != leg['dep_station_id']
            and s['id'] != leg['arr_station_id']
            and s['alternate_distance_nm'] <= MAX_ALTERNATE_DISTANCE_NM
            and s['runway_length_m'] >= aircraft['min_runway_m']]
    pool.sort(key=lambda s: (s['alternate_distance_nm'], s['created_at'], s['_seq']))
    if not pool:
        raise err('ERR_NO_SUITABLE_ALTERNATE')
    return pool[0]


def compute_plan_fields(leg, aircraft, distance_nm, forecast_wind_kts,
                        wind_assumption):
    manifest = manifest_for_leg(leg['id'])
    payload = manifest['total_payload_kg'] if manifest else 0
    zfw_ref = aircraft['oew_kg'] + payload
    steps = -(-zfw_ref // WEIGHT_STEP_KG)  # exact ceil
    burn_eff_exact = D(aircraft['burn_kg_per_hour']) * (1 + steps * WEIGHT_STEP_PCT)
    burn_eff_kg_per_hour = rhu(burn_eff_exact)

    wind_eff = forecast_wind_kts if wind_assumption == 'FORECAST' else -WORST_HEADWIND_KTS
    ground_speed_kts = aircraft['cruise_tas_kts'] + wind_eff
    if ground_speed_kts <= 0:
        raise err('ERR_INVALID_REQUEST', 'ground speed must be positive')
    trip_time_min = rhu(D(distance_nm) / D(ground_speed_kts) * 60)
    trip_exact = (D(distance_nm) / D(ground_speed_kts)) * burn_eff_exact
    mel_pct = sum((D(i['fuel_penalty_pct']) for i in open_mel_items(aircraft['id'])),
                  Decimal(0))
    trip_fuel_kg = rhu(trip_exact)
    mel_fuel_penalty_kg = rhu(trip_exact * mel_pct / 100)
    penalized_trip_exact = trip_exact * (1 + mel_pct / 100)

    alternate = select_alternate(leg, aircraft)
    contingency_exact = max(CONTINGENCY_PCT * penalized_trip_exact, MIN_CONTINGENCY_KG)
    contingency_kg = rhu(contingency_exact)
    alternate_exact = (D(alternate['alternate_distance_nm'])
                       / D(aircraft['cruise_tas_kts'])) * burn_eff_exact
    alternate_fuel_kg = rhu(alternate_exact)
    reserve_exact = burn_eff_exact * FINAL_RESERVE_H
    final_reserve_kg = rhu(reserve_exact)
    required_fuel_kg = rhu(penalized_trip_exact + contingency_exact
                           + alternate_exact + reserve_exact)
    return {
        'ground_speed_kts': ground_speed_kts,
        'trip_time_min': trip_time_min,
        'burn_eff_kg_per_hour': burn_eff_kg_per_hour,
        'trip_fuel_kg': trip_fuel_kg,
        'mel_fuel_penalty_kg': mel_fuel_penalty_kg,
        'contingency_kg': contingency_kg,
        'alternate_fuel_kg': alternate_fuel_kg,
        'final_reserve_kg': final_reserve_kg,
        'required_fuel_kg': required_fuel_kg,
        'alternate_station_id': alternate['id'],
    }


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def weather_check(station, sched_arr_utc, aircraft):
    """Returns None or raises ERR_WEATHER_NOT_CURRENT / ERR_WEATHER_BELOW_MINIMA."""
    covering = None
    for p in store.weather_packages.values():
        if (p['station_id'] == station['id'] and p['status'] == 'ACTIVE'
                and p['valid_from_utc'] <= sched_arr_utc < p['valid_to_utc']):
            covering = p
            break
    if covering is None:
        raise err('ERR_WEATHER_NOT_CURRENT')
    bump = any(i['minima_bump'] for i in open_mel_items(aircraft['id']))
    req_ceiling = station['min_ceiling_ft'] + (ALT_MINIMA_BUMP_CEILING_FT if bump else 0)
    req_vis = station['min_visibility_m'] + (ALT_MINIMA_BUMP_VIS_M if bump else 0)
    if covering['ceiling_ft'] < req_ceiling or covering['visibility_m'] < req_vis:
        raise err('ERR_WEATHER_BELOW_MINIMA')


# ---------------------------------------------------------------------------
# Manifest calculations
# ---------------------------------------------------------------------------

def compute_manifest_fields(aircraft, plan, pax_count, bags_count, cargo_kg):
    pax_weight_kg = rhu(D(pax_count) * PAX_KG)
    baggage_kg = rhu(D(bags_count) * BAG_KG)
    cargo_billed_kg = rhu(D(cargo_kg))
    total_payload_kg = pax_weight_kg + baggage_kg + cargo_billed_kg
    zero_fuel_weight_kg = aircraft['oew_kg'] + total_payload_kg
    takeoff_weight_kg = zero_fuel_weight_kg + plan['required_fuel_kg']
    landing_weight_kg = takeoff_weight_kg - (plan['trip_fuel_kg'] + plan['mel_fuel_penalty_kg'])

    mel_payload_penalty = sum(i['payload_penalty_kg'] for i in open_mel_items(aircraft['id']))
    max_payload_kg = min(
        aircraft['mzfw_kg'] - aircraft['oew_kg'],
        aircraft['mtow_kg'] - aircraft['oew_kg'] - plan['required_fuel_kg'],
        aircraft['mlw_kg'] - aircraft['oew_kg']
        - (plan['required_fuel_kg'] - plan['trip_fuel_kg'] - plan['mel_fuel_penalty_kg']),
    ) - mel_payload_penalty

    moment = (D(aircraft['oew_kg']) * ARM_OEW + D(pax_weight_kg) * ARM_PAX
              + D(baggage_kg) * ARM_BAG + D(cargo_billed_kg) * ARM_CARGO
              + D(plan['required_fuel_kg']) * ARM_FUEL)
    arm = moment / D(takeoff_weight_kg)
    cg = ((arm - D(aircraft['lemac_m'])) / D(aircraft['mac_m'])) * 100
    cg_percent_mac = rhu2(cg)

    fields = {
        'pax_weight_kg': pax_weight_kg,
        'baggage_kg': baggage_kg,
        'cargo_billed_kg': cargo_billed_kg,
        'total_payload_kg': total_payload_kg,
        'zero_fuel_weight_kg': zero_fuel_weight_kg,
        'takeoff_weight_kg': takeoff_weight_kg,
        'landing_weight_kg': landing_weight_kg,
        'cg_percent_mac': cg_percent_mac,
        'max_payload_kg': max_payload_kg,
        '_cg_exact': cg,
    }
    return fields


def validate_manifest_fiscal(fields, aircraft):
    if fields['zero_fuel_weight_kg'] > aircraft['mzfw_kg']:
        raise err('ERR_MZFW_EXCEEDED')
    if fields['takeoff_weight_kg'] > aircraft['mtow_kg']:
        raise err('ERR_MTOW_EXCEEDED')
    if fields['landing_weight_kg'] > aircraft['mlw_kg']:
        raise err('ERR_MLW_EXCEEDED')
    cdl = any(i['category'] == 'CDL' for i in open_mel_items(aircraft['id']))
    lo = CG_MIN_CDL if cdl else CG_MIN_NORMAL
    hi = CG_MAX_CDL if cdl else CG_MAX_NORMAL
    cg = fields['_cg_exact']
    if cg < lo or cg > hi:
        raise err('ERR_CG_OUT_OF_ENVELOPE')
    if fields['total_payload_kg'] > fields['max_payload_kg']:
        raise err('ERR_PAYLOAD_EXCEEDS_LIMIT')


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

def auto_select_dispatcher():
    from serializers import workload, shift_status
    cands = []
    for d in store.dispatchers.values():
        has_active = any(s['dispatcher_id'] == d['id'] and shift_status(s) == 'ACTIVE'
                         for s in store.desk_shifts.values())
        if not has_active:
            continue
        count, score = workload(d['id'])
        if count >= d['max_active_legs']:
            continue
        cands.append((count, score, d['_seq'], d))
    if not cands:
        raise err('ERR_NO_DISPATCHER_AVAILABLE')
    cands.sort(key=lambda t: (t[0], t[1], t[2]))
    return cands[0][3]


def auto_select_desk():
    from serializers import workload, desk_active_count, shift_status
    cands = []
    for desk in store.desks.values():
        if desk_active_count(desk['id']) >= desk['max_dispatchers']:
            continue
        active_shifts = [s for s in store.desk_shifts.values()
                         if s['desk_id'] == desk['id'] and shift_status(s) == 'ACTIVE']
        load = sum(workload(s['dispatcher_id'])[1] for s in active_shifts)
        cands.append((load, desk['_seq'], desk))
    if not cands:
        raise err('ERR_NO_DESK_AVAILABLE')
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[0][2]


def check_desk_capacity(desk, new_start, new_end):
    overlapping = [s for s in store.desk_shifts.values()
                   if s['desk_id'] == desk['id']
                   and s['shift_start_utc'] < new_end and new_start < s['shift_end_utc']]
    points = {new_start}
    for s in overlapping:
        points.add(max(s['shift_start_utc'], new_start))
    for p in points:
        concurrent = sum(1 for s in overlapping
                         if s['shift_start_utc'] <= p < s['shift_end_utc']) + 1
        if concurrent > desk['max_dispatchers']:
            raise err('ERR_DESK_OVERLOADED')


# ---------------------------------------------------------------------------
# Release cascade helpers
# ---------------------------------------------------------------------------

def auto_amend_release(release, action='RELEASE_AUTO_AMENDED'):
    """Cascade transition: RELEASED -> UNDER_AMENDMENT, PENDING_SIGNATURES -> DRAFT."""
    old = release['status']
    if old == 'RELEASED':
        release['status'] = 'UNDER_AMENDMENT'
        release['cycle_seq'] += 1
        release['amendment_count'] += 1
    elif old == 'PENDING_SIGNATURES':
        release['status'] = 'DRAFT'
        release['cycle_seq'] += 1
    else:
        return False
    store.touch(release)
    write_record(release['leg_id'], release['id'], 'system', 'system', action,
                 from_status=old, to_status=release['status'])
    return True


def cancel_release_for_leg(leg_id, include_released):
    rel = non_terminal_release_for_leg(leg_id)
    if rel is None:
        return
    if rel['status'] == 'RELEASED' and not include_released:
        return
    old = rel['status']
    rel['status'] = 'CANCELLED'
    store.touch(rel)


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------

def mel_expiry_sweep():
    expiring = [i for i in store.mel_items.values()
                if i['status'] == 'OPEN' and i['repair_deadline_utc'] < store.clock]
    expiring.sort(key=lambda i: (i['repair_deadline_utc'], i['created_at'], i['_seq']))
    for item in expiring:
        item['status'] = 'EXPIRED'
        store.touch(item)
        affected = [l for l in store.legs.values()
                    if l['aircraft_id'] == item['aircraft_id']
                    and l['ops_status'] in ('SCHEDULED', 'DEPARTED')]
        affected.sort(key=lambda l: (l['created_at'], l['_seq']))
        for leg in affected:
            rel = non_terminal_release_for_leg(leg['id'])
            if rel is not None:
                auto_amend_release(rel)
            write_record(leg['id'], None, 'system', 'system', 'MEL_EXPIRED')


# ---------------------------------------------------------------------------
# Weather revalidation cascade
# ---------------------------------------------------------------------------

def weather_revalidation(station_id):
    plans = [p for p in store.plans.values()
             if p['status'] == 'LOCKED'
             and store.legs[p['leg_id']]['arr_station_id'] == station_id]
    plans.sort(key=lambda p: (p['created_at'], p['_seq']))
    for plan in plans:
        leg = store.legs[plan['leg_id']]
        station = store.stations[leg['arr_station_id']]
        aircraft = store.aircraft[leg['aircraft_id']]
        try:
            weather_check(station, leg['sched_arr_utc'], aircraft)
        except Exception:
            pass
        else:
            continue
        # hop 1: plan LOCKED -> COMPUTED with re-derived fields
        old = plan['status']
        plan['status'] = 'COMPUTED'
        recompute_plan_fields(plan)
        store.touch(plan)
        # hop 2/3: release cascade
        for rel in list(store.releases.values()):
            if rel['plan_id'] == plan['id'] and rel['status'] in ('RELEASED', 'PENDING_SIGNATURES'):
                auto_amend_release(rel)


def recompute_plan_fields(plan):
    leg = store.legs[plan['leg_id']]
    aircraft = store.aircraft[leg['aircraft_id']]
    try:
        fields = compute_plan_fields(leg, aircraft, leg['distance_nm'],
                                     plan['forecast_wind_kts'], plan['wind_assumption'])
    except Exception:
        # pool can never shrink below the create-time set; keep old alternate defensively
        fields = None
    if fields is not None:
        plan.update(fields)
    return plan
