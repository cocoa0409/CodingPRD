"""Domain logic: serializers, calculations, gates, cascades.

Every rule here traces to PRD.md section 3 (business logic) and section 2
(global semantics). Monetary math uses Decimal with ROUND_HALF_UP.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_PILOT_FLIGHT_TIME_EXCEEDED,
    ERR_PILOT_DUTY_LIMIT_EXCEEDED,
    ERR_QUIET_HOURS_VIOLATION,
    ERR_AIRCRAFT_TURN_CONFLICT,
    ERR_PILOT_SCHEDULE_OVERLAP,
    ERR_GROSS_WEIGHT_EXCEEDED,
    ERR_FUEL_BELOW_MINIMUM,
    ERR_CG_OUT_OF_ENVELOPE,
)
from store import db, now, fmt_ts, new_entity, touch

# ---- calculation constants (PRD section 3) ----
TURN_BY_TIER = {'SHORT': 15, 'STANDARD': 25, 'GRAND': 40}
PAX_ALLOWANCE_LB = 5
FLIGHT_LIMIT_MIN = 480
DUTY_LIMIT_MIN = 840
REPORT_OFFSET_MIN = 45
DEBRIEF_OFFSET_MIN = 15
MIN_FUEL_RATIO_BPS = 6000
REFUND_FULL_MIN = 1440
REFUND_PARTIAL_MIN = 120
PARTIAL_FEE_BPS = 1000
CREDIT_ONLY_BPS = 7500
CREDIT_VALIDITY_DAYS = 365
OVERFLIGHT_PAD_MIN = 30
LOAD_TIER2_PCT = 50
LOAD_TIER2_BPS = 11000
LOAD_TIER3_PCT = 80
LOAD_TIER3_BPS = 12500
WEEKEND_BPS = 11000
DEFAULT_BPS = 10000

ACTIVE_FLIGHT_STATUSES = ('SCHEDULED', 'DELAYED', 'BOARDING', 'MANIFEST_CLOSED', 'DISPATCHED')
CANCELLED_STATUSES = ('CANCELLED_WEATHER', 'CANCELLED_OPS')
SEAT_HOLDING_BOOKING_STATUSES = ('HELD', 'CONFIRMED', 'CHECKED_IN', 'MANIFESTED')
ESTIMATE_BOOKING_STATUSES = ('HELD', 'CONFIRMED', 'CHECKED_IN')


def rhu_div(numer, denom):
    """round_half_up(numer / denom) to an integer, exact arithmetic."""
    return int((Decimal(int(numer)) / Decimal(int(denom))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def get_or_404(collection, entity_id, what='Resource'):
    ent = collection.get(entity_id)
    if ent is None:
        raise_error(ERR_NOT_FOUND, f'{what} not found: {entity_id}')
    return ent


def passengers_of(booking_id):
    return sorted(
        (p for p in db.passengers.values() if p['booking_id'] == booking_id),
        key=lambda p: p['pax_index'],
    )


def bookings_of_flight(flight_id):
    return [b for b in db.bookings.values() if b['flight_id'] == flight_id]


# ---------------------------------------------------------------------------
# Weather posture (PRD 3.2)
# ---------------------------------------------------------------------------

def observation_adverse(obs_values, base):
    return (
        obs_values['ceiling_ft'] < base['weather_ceiling_min_ft']
        or obs_values['visibility_sm'] < base['weather_visibility_min_sm']
        or obs_values['wind_kt'] > base['weather_wind_max_kt']
    )


def governing_observation(base_id):
    n = now()
    candidates = [
        o for o in db.weather_observations.values()
        if o['base_id'] == base_id and o['observed_at'] <= n
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda o: (o['observed_at'], o['_seq']))


def compute_posture(base):
    latest = governing_observation(base['id'])
    if latest is not None and latest['adverse'] and now() < latest['validity_until']:
        return 'WEATHER_HOLD'
    return 'NORMAL'


# ---------------------------------------------------------------------------
# Complaint quota rollup (PRD 3.9)
# ---------------------------------------------------------------------------

def complaint_count_for_route(route_id, base_id=None):
    """SUBSTANTIATED complaints matched to the route whose observed_at lies in
    [now - complaint_window_days, now], both bounds inclusive. The window comes
    from each complaint's own base (or a specific base when base_id given)."""
    n = now()
    count = 0
    for c in db.complaints.values():
        if c['status'] != 'SUBSTANTIATED':
            continue
        if c['matched_route_id'] != route_id:
            continue
        if base_id is not None and c['base_id'] != base_id:
            continue
        base = db.bases.get(c['base_id'])
        window_days = base['complaint_window_days'] if base else 30
        if n - timedelta(days=window_days) <= c['observed_at'] <= n:
            count += 1
    return count


def quota_exceeded_bases(route_id):
    """Bases for which this route's substantiated count meets/exceeds threshold."""
    exceeded = []
    for base in db.bases.values():
        if complaint_count_for_route(route_id, base['id']) >= base['complaint_quota_threshold']:
            exceeded.append(base)
    return exceeded


# ---------------------------------------------------------------------------
# Flight computed figures (PRD 3.3 / 3.5)
# ---------------------------------------------------------------------------

def seats_booked(flight):
    return sum(
        b['seat_count'] for b in bookings_of_flight(flight['id'])
        if b['status'] in SEAT_HOLDING_BOOKING_STATUSES
    )


def estimated_gross_weight(flight):
    aircraft = db.aircraft.get(flight['aircraft_id'])
    route = db.routes.get(flight['route_id'])
    if aircraft is None or route is None:
        return None
    total = aircraft['empty_weight_lb'] + route['fuel_required_lb']
    for b in bookings_of_flight(flight['id']):
        if b['status'] in ESTIMATE_BOOKING_STATUSES:
            for p in passengers_of(b['id']):
                total += p['declared_weight_lb'] + PAX_ALLOWANCE_LB
    return total


def estimate_gate(flight, extra_declared_weights):
    """Provisional W&B gate: full planned fuel, declared+5 per passenger,
    equality at MTOW allowed (PRD 3.5)."""
    aircraft = db.aircraft[flight['aircraft_id']]
    total = estimated_gross_weight(flight)
    total += sum(w + PAX_ALLOWANCE_LB for w in extra_declared_weights)
    if total > aircraft['max_takeoff_weight_lb']:
        raise_error(ERR_GROSS_WEIGHT_EXCEEDED, 'Estimated gross weight exceeds max_takeoff_weight_lb')


# ---------------------------------------------------------------------------
# Seat price quote (PRD 3.5): pinned rounding order, round half-up per step
# ---------------------------------------------------------------------------

def season_for_date(dep_date):
    for s in db.seasons.values():
        if s['status'] == 'PUBLISHED' and s['start_date'] <= dep_date < s['end_date']:
            return s
    return None


def seat_price_quote(flight, seat_count):
    route = db.routes[flight['route_id']]
    aircraft = db.aircraft[flight['aircraft_id']]
    dep = flight['scheduled_departure_utc']
    season = season_for_date(dep.date())
    season_bps = season['multiplier_bps'] if season else DEFAULT_BPS
    season_id = season['id'] if season else None
    cap = aircraft['seat_capacity']
    load_pct = (seats_booked(flight) * 100) // cap if cap else 0
    if load_pct < LOAD_TIER2_PCT:
        load_bps = DEFAULT_BPS
    elif load_pct < LOAD_TIER3_PCT:
        load_bps = LOAD_TIER2_BPS
    else:
        load_bps = LOAD_TIER3_BPS
    weekend_bps = WEEKEND_BPS if dep.weekday() >= 5 else DEFAULT_BPS
    step1 = rhu_div(route['base_seat_price_cents'] * season_bps, 10000)
    step2 = rhu_div(step1 * load_bps, 10000)
    step3 = rhu_div(step2 * weekend_bps, 10000)
    return step3, step3 * seat_count, season_id


# ---------------------------------------------------------------------------
# Duty ledger (PRD 3.4)
# ---------------------------------------------------------------------------

def duty_flights(pilot_id, duty_date, exclude_id=None):
    return [
        f for f in db.flights.values()
        if f['pilot_id'] == pilot_id
        and f['scheduled_departure_utc'].date() == duty_date
        and f['status'] not in CANCELLED_STATUSES
        and f['id'] != exclude_id
    ]


def get_or_create_duty_day(pilot_id, duty_date):
    for d in db.duty_days.values():
        if d['pilot_id'] == pilot_id and d['duty_date'] == duty_date:
            return d
    d = new_entity()
    d.update({'pilot_id': pilot_id, 'duty_date': duty_date, 'status': 'OPEN'})
    db.duty_days[d['id']] = d
    return d


def duty_day_values(duty_day):
    flights = duty_flights(duty_day['pilot_id'], duty_day['duty_date'])
    scheduled = sum(db.routes[f['route_id']]['duration_minutes'] for f in flights)
    actual = 0
    for f in flights:
        if f['status'] == 'COMPLETED' and f['actual_departure_utc'] and f['actual_arrival_utc']:
            secs = (f['actual_arrival_utc'] - f['actual_departure_utc']).total_seconds()
            actual += int(secs // 60)
    if flights:
        lo = min(f['scheduled_departure_utc'] for f in flights) - timedelta(minutes=REPORT_OFFSET_MIN)
        hi = max(f['scheduled_arrival_utc'] for f in flights) + timedelta(minutes=DEBRIEF_OFFSET_MIN)
        projected = int((hi - lo).total_seconds() // 60)
    else:
        projected = 0
    return scheduled, actual, projected


def pilot_duty_gate(pilot, duty_date, cand_duration, cand_dep, cand_arr, exclude_id=None):
    """Scheduled-projection variant: flight minutes <= 480, duty span <= 840,
    equality allowed (PRD 3.4)."""
    flights = duty_flights(pilot['id'], duty_date, exclude_id=exclude_id)
    total = sum(db.routes[f['route_id']]['duration_minutes'] for f in flights) + cand_duration
    if total > FLIGHT_LIMIT_MIN:
        raise_error(ERR_PILOT_FLIGHT_TIME_EXCEEDED, 'Pilot flight minutes would exceed 480 for the day')
    deps = [f['scheduled_departure_utc'] for f in flights] + [cand_dep]
    arrs = [f['scheduled_arrival_utc'] for f in flights] + [cand_arr]
    span = (max(arrs) + timedelta(minutes=DEBRIEF_OFFSET_MIN)) - (min(deps) - timedelta(minutes=REPORT_OFFSET_MIN))
    if span.total_seconds() / 60 > DUTY_LIMIT_MIN:
        raise_error(ERR_PILOT_DUTY_LIMIT_EXCEEDED, 'Projected duty span would exceed 840 minutes')


# ---------------------------------------------------------------------------
# Turn-window / schedule-overlap gates (PRD 3.3)
# ---------------------------------------------------------------------------

def turn_window_gates(route, aircraft, pilot, dep, arr, exclude_id=None):
    """Aircraft interval is buffer-extended half-open; pilot interval is plain
    half-open. Aircraft conflicts surface before pilot conflicts."""
    date = dep.date()
    cand_end = arr + timedelta(minutes=route['turn_minutes'])
    peers = [
        f for f in db.flights.values()
        if f['id'] != exclude_id
        and f['status'] in ACTIVE_FLIGHT_STATUSES
        and f['scheduled_departure_utc'].date() == date
    ]
    for f in peers:
        if f['aircraft_id'] != aircraft['id']:
            continue
        f_route = db.routes[f['route_id']]
        f_end = f['scheduled_arrival_utc'] + timedelta(minutes=f_route['turn_minutes'])
        if dep < f_end and f['scheduled_departure_utc'] < cand_end:
            raise_error(ERR_AIRCRAFT_TURN_CONFLICT, 'Aircraft turnaround-buffered interval conflict')
    for f in peers:
        if f['pilot_id'] != pilot['id']:
            continue
        if dep < f['scheduled_arrival_utc'] and f['scheduled_departure_utc'] < arr:
            raise_error(ERR_PILOT_SCHEDULE_OVERLAP, 'Pilot block interval overlap')


def quiet_hours_gate(base, route, aircraft, dep):
    if route['noise_sensitive'] and aircraft['noise_class'] != 'QUIET':
        minute = dep.hour * 60 + dep.minute
        start = base['quiet_hours_start_min_utc']
        end = base['quiet_hours_end_min_utc']
        if start <= end:
            inside = start <= minute < end
        else:
            # Window wraps midnight (e.g. 22:00 -> 06:00).
            inside = minute >= start or minute < end
        if inside:
            raise_error(ERR_QUIET_HOURS_VIOLATION, 'Departure minute falls inside the base quiet-hours window')


# ---------------------------------------------------------------------------
# Rotation sequence (PRD 3.3): per aircraft per UTC date, departures ascending
# ---------------------------------------------------------------------------

def recompute_rotation(aircraft_id, date):
    flights = [
        f for f in db.flights.values()
        if f['aircraft_id'] == aircraft_id
        and f['scheduled_departure_utc'].date() == date
        and f['status'] not in CANCELLED_STATUSES
    ]
    flights.sort(key=lambda f: (f['scheduled_departure_utc'], f['_seq']))
    for idx, f in enumerate(flights, start=1):
        if f.get('rotation_seq') != idx:
            f['rotation_seq'] = idx
            touch(f)


# ---------------------------------------------------------------------------
# Credit ledger (PRD 3.8)
# ---------------------------------------------------------------------------

def mint_credit(booking, amount_cents):
    c = new_entity()
    issued = now()
    c.update({
        'booking_id': booking['id'],
        'amount_cents': amount_cents,
        'redeemed_cents': 0,
        'issued_at': issued,
        'expires_at': issued + timedelta(days=CREDIT_VALIDITY_DAYS),
        'status': 'ISSUED',
    })
    db.credits[c['id']] = c
    return c


def credit_effective_status(credit):
    if credit['status'] in ('ISSUED', 'PARTIALLY_REDEEMED') and credit['expires_at'] <= now():
        return 'EXPIRED'
    return credit['status']


def release_applied_credits(booking):
    """HELD cancellation/expiry: each applied credit gets its contribution back."""
    remaining = []
    for app in db.credit_applications:
        if app['booking_id'] != booking['id']:
            remaining.append(app)
            continue
        credit = db.credits.get(app['credit_id'])
        if credit is not None:
            credit['redeemed_cents'] -= app['amount_cents']
            if credit['status'] != 'EXPIRED':
                if credit['redeemed_cents'] <= 0:
                    credit['redeemed_cents'] = 0
                    credit['status'] = 'ISSUED'
                elif credit['redeemed_cents'] >= credit['amount_cents']:
                    credit['status'] = 'REDEEMED'
                else:
                    credit['status'] = 'PARTIALLY_REDEEMED'
            touch(credit)
    db.credit_applications = remaining
    booking['credits_applied_cents'] = 0


# ---------------------------------------------------------------------------
# Involuntary cancellation cascade (PRD 3.8)
# ---------------------------------------------------------------------------

def cascade_bookings(flight):
    for b in bookings_of_flight(flight['id']):
        if b['status'] == 'HELD':
            release_applied_credits(b)
            b['status'] = 'EXPIRED'
            touch(b)
        elif b['status'] in ('CONFIRMED', 'CHECKED_IN', 'MANIFESTED'):
            b['credited_cents'] = b['paid_cents']
            amount = b['paid_cents'] + b['credits_applied_cents']
            b['status'] = 'CREDITED'
            touch(b)
            if amount > 0:
                mint_credit(b, amount)


def cancel_flight(flight, new_status, cancel_reason):
    flight['status'] = new_status
    flight['cancel_reason'] = cancel_reason
    touch(flight)
    cascade_bookings(flight)
    recompute_rotation(flight['aircraft_id'], flight['scheduled_departure_utc'].date())


def weather_cascade(base, obs):
    window_start = obs['observed_at']
    window_end = obs['validity_until']
    for f in list(db.flights.values()):
        if f['base_id'] != base['id']:
            continue
        if f['status'] not in ('SCHEDULED', 'DELAYED', 'BOARDING', 'MANIFEST_CLOSED'):
            continue
        if window_start <= f['scheduled_departure_utc'] < window_end:
            cancel_flight(f, 'CANCELLED_WEATHER', 'WEATHER')


def route_suspension_cascade(route):
    n = now()
    for f in list(db.flights.values()):
        if f['route_id'] != route['id']:
            continue
        if f['status'] not in ('SCHEDULED', 'DELAYED', 'BOARDING'):
            continue
        if f['scheduled_departure_utc'] >= n:
            cancel_flight(f, 'CANCELLED_OPS', 'ROUTE_SUSPENDED')


def aircraft_grounding_cascade(aircraft):
    n = now()
    for f in list(db.flights.values()):
        if f['aircraft_id'] != aircraft['id']:
            continue
        if f['status'] not in ('SCHEDULED', 'DELAYED', 'BOARDING', 'MANIFEST_CLOSED'):
            continue
        if f['scheduled_departure_utc'] >= n:
            cancel_flight(f, 'CANCELLED_OPS', 'AIRCRAFT_GROUNDED')


# ---------------------------------------------------------------------------
# Manifest final weight & balance (PRD 3.7): pinned evaluation order
# ---------------------------------------------------------------------------

def close_manifest_wb(flight):
    aircraft = db.aircraft[flight['aircraft_id']]
    route = db.routes[flight['route_id']]
    pax = []
    for b in bookings_of_flight(flight['id']):
        if b['status'] != 'CHECKED_IN':
            continue
        for p in passengers_of(b['id']):
            if p['checked_in']:
                pax.append(p)
    pax_weight = sum(p['actual_weight_lb'] for p in pax)
    fuel_budget = aircraft['max_takeoff_weight_lb'] - aircraft['empty_weight_lb'] - pax_weight
    manifested_fuel = min(route['fuel_required_lb'], fuel_budget)
    min_fuel = rhu_div(route['fuel_required_lb'] * MIN_FUEL_RATIO_BPS, 10000)
    if manifested_fuel < min_fuel:
        raise_error(ERR_FUEL_BELOW_MINIMUM, 'Trimmed fuel below 60% of route fuel_required_lb')
    gross = aircraft['empty_weight_lb'] + pax_weight + manifested_fuel
    if gross > aircraft['max_takeoff_weight_lb']:
        raise_error(ERR_GROSS_WEIGHT_EXCEEDED, 'Final gross weight exceeds max_takeoff_weight_lb')
    moment = Decimal(aircraft['empty_moment_lb_in'])
    for p in pax:
        arm = Decimal(str(aircraft['seat_arms_inches'][p['seat_number']]))
        moment += Decimal(p['actual_weight_lb']) * arm
    moment += Decimal(manifested_fuel) * Decimal(str(aircraft['fuel_arm_inches']))
    cg = (moment / Decimal(gross)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    fwd = Decimal(str(aircraft['cg_forward_limit_in']))
    aft = Decimal(str(aircraft['cg_aft_limit_in']))
    if not (fwd <= cg <= aft):
        raise_error(ERR_CG_OUT_OF_ENVELOPE, 'Final CG outside the inclusive envelope')
    flight['manifested_fuel_lb'] = manifested_fuel
    flight['actual_gross_weight_lb'] = gross
    flight['actual_cg_in'] = float(cg)
    flight['manifested_passenger_count'] = len(pax)
    for b in bookings_of_flight(flight['id']):
        if b['status'] == 'CHECKED_IN':
            b['status'] = 'MANIFESTED'
            touch(b)
    touch(flight)


# ---------------------------------------------------------------------------
# Complaint auto-match (PRD 3.9)
# ---------------------------------------------------------------------------

def auto_match_complaint(complaint):
    obs = complaint['observed_at']
    candidates = []
    for f in db.flights.values():
        if f['base_id'] != complaint['base_id']:
            continue
        if f['status'] not in ('DISPATCHED', 'COMPLETED'):
            continue
        route = db.routes.get(f['route_id'])
        if route is None or complaint['zone'] not in route['noise_zones']:
            continue
        window_end = f['scheduled_arrival_utc'] + timedelta(minutes=OVERFLIGHT_PAD_MIN)
        if f['scheduled_departure_utc'] <= obs < window_end:
            candidates.append(f)
    if not candidates:
        return None

    def rank(f):
        dist_secs = abs((obs - f['scheduled_departure_utc']).total_seconds())
        return (int(dist_secs // 60), f['scheduled_departure_utc'], f['_seq'])

    candidates.sort(key=rank)
    return candidates[0]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_base(b):
    return {
        'id': b['id'],
        'name': b['name'],
        'quiet_hours_start_min_utc': b['quiet_hours_start_min_utc'],
        'quiet_hours_end_min_utc': b['quiet_hours_end_min_utc'],
        'weather_ceiling_min_ft': b['weather_ceiling_min_ft'],
        'weather_visibility_min_sm': b['weather_visibility_min_sm'],
        'weather_wind_max_kt': b['weather_wind_max_kt'],
        'weather_validity_min': b['weather_validity_min'],
        'current_waiver_version': b['current_waiver_version'],
        'complaint_quota_threshold': b['complaint_quota_threshold'],
        'complaint_window_days': b['complaint_window_days'],
        'hold_expire_minutes': b['hold_expire_minutes'],
        'posture': compute_posture(b),
        'ops_run_index': b['ops_run_index'],
        'created_at': fmt_ts(b['created_at']),
        'updated_at': fmt_ts(b['updated_at']),
        'version': b['version'],
    }


def ser_route(r):
    return {
        'id': r['id'],
        'route_code': r['route_code'],
        'tier': r['tier'],
        'duration_minutes': r['duration_minutes'],
        'base_seat_price_cents': r['base_seat_price_cents'],
        'fuel_required_lb': r['fuel_required_lb'],
        'min_altitude_ft': r['min_altitude_ft'],
        'noise_sensitive': r['noise_sensitive'],
        'noise_zones': r['noise_zones'],
        'min_aircraft_noise_class': r['min_aircraft_noise_class'],
        'turn_minutes': r['turn_minutes'],
        'status': r['status'],
        'substantiated_complaints_30d': complaint_count_for_route(r['id']),
        'created_at': fmt_ts(r['created_at']),
        'updated_at': fmt_ts(r['updated_at']),
        'version': r['version'],
    }


def ser_season(s):
    return {
        'id': s['id'],
        'label': s['label'],
        'start_date': s['start_date'].isoformat(),
        'end_date': s['end_date'].isoformat(),
        'multiplier_bps': s['multiplier_bps'],
        'status': s['status'],
        'created_at': fmt_ts(s['created_at']),
        'updated_at': fmt_ts(s['updated_at']),
        'version': s['version'],
    }


def ser_aircraft(a):
    return {
        'id': a['id'],
        'tail_number': a['tail_number'],
        'seat_capacity': a['seat_capacity'],
        'empty_weight_lb': a['empty_weight_lb'],
        'empty_moment_lb_in': a['empty_moment_lb_in'],
        'max_takeoff_weight_lb': a['max_takeoff_weight_lb'],
        'fuel_arm_inches': a['fuel_arm_inches'],
        'seat_arms_inches': a['seat_arms_inches'],
        'cg_forward_limit_in': a['cg_forward_limit_in'],
        'cg_aft_limit_in': a['cg_aft_limit_in'],
        'noise_class': a['noise_class'],
        'status': a['status'],
        'created_at': fmt_ts(a['created_at']),
        'updated_at': fmt_ts(a['updated_at']),
        'version': a['version'],
    }


def ser_pilot(p):
    return {
        'id': p['id'],
        'display_name': p['display_name'],
        'certificate_no': p['certificate_no'],
        'status': p['status'],
        'created_at': fmt_ts(p['created_at']),
        'updated_at': fmt_ts(p['updated_at']),
        'version': p['version'],
    }


def ser_duty_day(d):
    scheduled, actual, projected = duty_day_values(d)
    return {
        'id': d['id'],
        'pilot_id': d['pilot_id'],
        'duty_date': d['duty_date'].isoformat(),
        'flight_minutes_scheduled': scheduled,
        'flight_minutes_actual': actual,
        'duty_minutes_projected': projected,
        'status': d['status'],
        'created_at': fmt_ts(d['created_at']),
        'updated_at': fmt_ts(d['updated_at']),
        'version': d['version'],
    }


def ser_flight(f):
    aircraft = db.aircraft.get(f['aircraft_id'])
    booked = seats_booked(f)
    capacity = aircraft['seat_capacity'] if aircraft else 0
    return {
        'id': f['id'],
        'base_id': f['base_id'],
        'route_id': f['route_id'],
        'aircraft_id': f['aircraft_id'],
        'pilot_id': f['pilot_id'],
        'scheduled_departure_utc': fmt_ts(f['scheduled_departure_utc']),
        'scheduled_arrival_utc': fmt_ts(f['scheduled_arrival_utc']),
        'rotation_seq': f['rotation_seq'],
        'status': f['status'],
        'pilot_acknowledged': f['pilot_acknowledged'],
        'created_by_user_id': f['created_by_user_id'],
        'dispatched_by_user_id': f['dispatched_by_user_id'],
        'actual_departure_utc': fmt_ts(f['actual_departure_utc']),
        'actual_arrival_utc': fmt_ts(f['actual_arrival_utc']),
        'cancel_reason': f['cancel_reason'],
        'seats_booked': booked,
        'seats_available': capacity - booked,
        'estimated_gross_weight_lb': estimated_gross_weight(f),
        'manifested_passenger_count': f['manifested_passenger_count'],
        'manifested_fuel_lb': f['manifested_fuel_lb'],
        'actual_gross_weight_lb': f['actual_gross_weight_lb'],
        'actual_cg_in': f['actual_cg_in'],
        'created_at': fmt_ts(f['created_at']),
        'updated_at': fmt_ts(f['updated_at']),
        'version': f['version'],
    }


def ser_booking(b):
    return {
        'id': b['id'],
        'flight_id': b['flight_id'],
        'contact_name': b['contact_name'],
        'contact_email': b['contact_email'],
        'status': b['status'],
        'seat_count': b['seat_count'],
        'quoted_per_seat_cents': b['quoted_per_seat_cents'],
        'quoted_total_cents': b['quoted_total_cents'],
        'season_id': b['season_id'],
        'credits_applied_cents': b['credits_applied_cents'],
        'paid_cents': b['paid_cents'],
        'refunded_card_cents': b['refunded_card_cents'],
        'credited_cents': b['credited_cents'],
        'retained_fee_cents': b['retained_fee_cents'],
        'waiver_version_pinned': b['waiver_version_pinned'],
        'expires_at': fmt_ts(b['expires_at']),
        'created_at': fmt_ts(b['created_at']),
        'updated_at': fmt_ts(b['updated_at']),
        'version': b['version'],
    }


def ser_passenger(p):
    return {
        'id': p['id'],
        'booking_id': p['booking_id'],
        'pax_index': p['pax_index'],
        'full_name': p['full_name'],
        'declared_weight_lb': p['declared_weight_lb'],
        'waiver_signed': p['waiver_signed'],
        'waiver_version_signed': p['waiver_version_signed'],
        'briefing_completed': p['briefing_completed'],
        'checked_in': p['checked_in'],
        'actual_weight_lb': p['actual_weight_lb'],
        'seat_number': p['seat_number'],
        'created_at': fmt_ts(p['created_at']),
        'updated_at': fmt_ts(p['updated_at']),
        'version': p['version'],
    }


def ser_credit(c):
    return {
        'id': c['id'],
        'booking_id': c['booking_id'],
        'amount_cents': c['amount_cents'],
        'redeemed_cents': c['redeemed_cents'],
        'remaining_cents': c['amount_cents'] - c['redeemed_cents'],
        'issued_at': fmt_ts(c['issued_at']),
        'expires_at': fmt_ts(c['expires_at']),
        'status': credit_effective_status(c),
        'created_at': fmt_ts(c['created_at']),
        'updated_at': fmt_ts(c['updated_at']),
        'version': c['version'],
    }


def ser_weather_observation(o):
    # Observations are immutable: no updated_at, no version.
    return {
        'id': o['id'],
        'base_id': o['base_id'],
        'observed_at': fmt_ts(o['observed_at']),
        'ceiling_ft': o['ceiling_ft'],
        'visibility_sm': o['visibility_sm'],
        'wind_kt': o['wind_kt'],
        'adverse': o['adverse'],
        'validity_until': fmt_ts(o['validity_until']),
        'created_at': fmt_ts(o['created_at']),
    }


def ser_complaint(c):
    return {
        'id': c['id'],
        'base_id': c['base_id'],
        'zone': c['zone'],
        'observed_at': fmt_ts(c['observed_at']),
        'description': c['description'],
        'reporter_ref': c['reporter_ref'],
        'status': c['status'],
        'match_status': c['match_status'],
        'matched_flight_id': c['matched_flight_id'],
        'matched_route_id': c['matched_route_id'],
        'resolution_note': c['resolution_note'],
        'created_at': fmt_ts(c['created_at']),
        'updated_at': fmt_ts(c['updated_at']),
        'version': c['version'],
    }


def sort_created(items):
    return sorted(items, key=lambda e: (e['created_at'], e['_seq']))
