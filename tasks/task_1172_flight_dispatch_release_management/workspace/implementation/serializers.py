"""Entity -> JSON dict serialization. Computed/derived fields resolved here."""
from db import store
from util import fmt_ts, fmt_dt

DT_FIELDS = {
    'shift_start_utc', 'shift_end_utc', 'sched_dep_utc', 'sched_arr_utc',
    'actual_dep_utc', 'repair_deadline_utc', 'valid_from_utc', 'valid_to_utc',
    'eta_destination_utc', 'signed_at_utc', 'recorded_at_utc',
}


def _base(rec, fields):
    out = {'id': rec['id']}
    for f in fields:
        v = rec.get(f)
        if f in DT_FIELDS:
            out[f] = fmt_dt(v)
        else:
            out[f] = v
    out['created_at'] = fmt_ts(rec['created_at'])
    out['updated_at'] = fmt_ts(rec['updated_at'])
    out['version'] = rec['version']
    return out


def _append_only(rec, fields):
    out = {'id': rec['id']}
    for f in fields:
        v = rec.get(f)
        out[f] = fmt_dt(v) if f in DT_FIELDS else v
    out['created_at'] = fmt_ts(rec['created_at'])
    return out


def shift_status(shift):
    now = store.clock
    if now < shift['shift_start_utc']:
        return 'PLANNED'
    if now < shift['shift_end_utc']:
        return 'ACTIVE'
    return 'ENDED'


def workload(dispatcher_id):
    """Returns (workload_leg_count, weighted_load_score) at the current clock."""
    legs = [l for l in store.legs.values()
            if l['dispatcher_id'] == dispatcher_id
            and l['ops_status'] in ('SCHEDULED', 'DEPARTED')]
    count = len(legs)
    score = 0
    now = store.clock
    for l in legs:
        hours = (l['sched_dep_utc'] - now).total_seconds() / 3600.0
        if hours <= 2:
            score += 3
        elif hours <= 6:
            score += 2
        else:
            score += 1
    return count, score


def desk_active_count(desk_id):
    now = store.clock
    return sum(1 for s in store.desk_shifts.values()
               if s['desk_id'] == desk_id
               and s['shift_start_utc'] <= now < s['shift_end_utc'])


def ser_station(r):
    return _base(r, ['iata_code', 'runway_length_m', 'alternate_distance_nm',
                     'min_ceiling_ft', 'min_visibility_m', 'status'])


def ser_aircraft(r):
    return _base(r, ['tail_no', 'type_code', 'oew_kg', 'mzfw_kg', 'mtow_kg',
                     'mlw_kg', 'fuel_capacity_kg', 'cruise_tas_kts',
                     'burn_kg_per_hour', 'min_runway_m', 'lemac_m', 'mac_m'])


def ser_dispatcher(r):
    count, score = workload(r['id'])
    out = _base(r, ['name', 'license_no', 'max_active_legs'])
    out['workload_leg_count'] = count
    out['weighted_load_score'] = score
    return out


def ser_captain(r):
    return _base(r, ['name', 'license_no', 'qualified_type_codes'])


def ser_desk(r):
    active = desk_active_count(r['id'])
    out = _base(r, ['code', 'region', 'max_dispatchers'])
    out['active_shift_count'] = active
    out['free_slots'] = r['max_dispatchers'] - active
    return out


def ser_desk_shift(r):
    out = _base(r, ['dispatcher_id', 'desk_id', 'shift_start_utc', 'shift_end_utc'])
    out['status'] = shift_status(r)
    return out


def ser_leg(r):
    return _base(r, ['flight_no', 'dep_station_id', 'arr_station_id', 'aircraft_id',
                     'captain_id', 'dispatcher_id', 'diverted_from_leg_id',
                     'distance_nm', 'sched_dep_utc', 'sched_arr_utc',
                     'actual_dep_utc', 'ops_status', 'monitor_status', 'delay_count'])


def ser_plan(r):
    return _base(r, ['leg_id', 'plan_seq', 'route_code', 'cruise_altitude_ft',
                     'forecast_wind_kts', 'wind_assumption', 'status',
                     'ground_speed_kts', 'trip_time_min', 'burn_eff_kg_per_hour',
                     'trip_fuel_kg', 'mel_fuel_penalty_kg', 'contingency_kg',
                     'alternate_fuel_kg', 'final_reserve_kg', 'required_fuel_kg',
                     'alternate_station_id'])


def ser_manifest(r):
    return _base(r, ['leg_id', 'plan_id', 'pax_count', 'bags_count', 'cargo_kg',
                     'pax_weight_kg', 'baggage_kg', 'cargo_billed_kg',
                     'total_payload_kg', 'zero_fuel_weight_kg',
                     'takeoff_weight_kg', 'landing_weight_kg',
                     'cg_percent_mac', 'max_payload_kg'])


def ser_mel_item(r):
    return _base(r, ['aircraft_id', 'item_code', 'category', 'deferral_category',
                     'fuel_penalty_pct', 'payload_penalty_kg', 'minima_bump',
                     'repair_deadline_utc', 'status'])


def ser_weather_package(r):
    return _base(r, ['station_id', 'valid_from_utc', 'valid_to_utc',
                     'ceiling_ft', 'visibility_m', 'status'])


def ser_release(r):
    return _base(r, ['leg_id', 'plan_id', 'dispatcher_id', 'captain_id',
                     'status', 'cycle_seq', 'amendment_count'])


def ser_signature(r):
    return _append_only(r, ['release_id', 'signer_role', 'signer_id',
                            'cycle_seq', 'signed_at_utc'])


def ser_control_record(r):
    return _append_only(r, ['leg_id', 'release_id', 'actor_role', 'actor_id',
                            'action', 'from_status', 'to_status', 'note',
                            'recorded_at_utc'])


def ser_monitoring_event(r):
    return _base(r, ['leg_id', 'fuel_remaining_kg', 'eta_destination_utc',
                     'dest_ceiling_ft', 'dest_visibility_m',
                     'projected_arrival_fuel_kg', 'fuel_margin_kg',
                     'recommendation', 'status'])
