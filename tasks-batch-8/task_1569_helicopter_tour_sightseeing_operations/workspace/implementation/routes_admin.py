"""Admin/configuration endpoints: bases, routes, seasons, aircraft, pilots,
duty-days, and the test-driving logical clock."""
from datetime import timedelta

from flask import Blueprint, request

import domain as D
from domain import (
    ser_base, ser_route, ser_season, ser_aircraft, ser_pilot, ser_duty_day,
    sort_created, get_or_404,
)
from envelope import success
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED_ROLE,
    ERR_SEASON_OVERLAP,
    ERR_UNIQUENESS_CONFLICT,
    ERR_ROUTE_QUOTA_STILL_EXCEEDED,
)
from store import db, now, fmt_ts, new_entity, touch, set_clock
from validate import (
    get_body, authenticate, require_role, paginated,
    _str, _int, _num, _bool, _enum, _dt, _date, _list,
)

bp = Blueprint('admin', __name__)

ALL_ROLES = ('OpsAdmin', 'Dispatcher', 'BookingAgent', 'ComplianceOfficer', 'CommunityReporter', 'Pilot')

ROUTE_TIERS = ('SHORT', 'STANDARD', 'GRAND')
NOISE_ZONES = ('VILLAGE', 'RIM', 'AIRPORT')
MIN_NOISE_CLASSES = ('QUIET_ONLY', 'ANY')
AIRCRAFT_NOISE_CLASSES = ('QUIET', 'STANDARD')


# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------

@bp.route('/bases', methods=['POST'])
def create_base():
    body = get_body()
    name = _str(body, 'name', True)
    qh_start = _int(body, 'quiet_hours_start_min_utc', True)
    qh_end = _int(body, 'quiet_hours_end_min_utc', True)
    waiver = _str(body, 'current_waiver_version', True)
    ceil = _int(body, 'weather_ceiling_min_ft', False)
    vis = _int(body, 'weather_visibility_min_sm', False)
    wind = _int(body, 'weather_wind_max_kt', False)
    validity = _int(body, 'weather_validity_min', False)
    quota = _int(body, 'complaint_quota_threshold', False)
    window = _int(body, 'complaint_window_days', False)
    hold = _int(body, 'hold_expire_minutes', False)
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    b = new_entity()
    b.update({
        'name': name,
        'quiet_hours_start_min_utc': qh_start,
        'quiet_hours_end_min_utc': qh_end,
        'weather_ceiling_min_ft': 1000 if ceil is None else ceil,
        'weather_visibility_min_sm': 3 if vis is None else vis,
        'weather_wind_max_kt': 25 if wind is None else wind,
        'weather_validity_min': 60 if validity is None else validity,
        'current_waiver_version': waiver,
        'complaint_quota_threshold': 3 if quota is None else quota,
        'complaint_window_days': 30 if window is None else window,
        'hold_expire_minutes': 30 if hold is None else hold,
        'ops_run_index': 0,
    })
    db.bases[b['id']] = b
    return success(ser_base(b), status=201)


@bp.route('/bases/<bid>', methods=['GET'])
def get_base(bid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    b = get_or_404(db.bases, bid, 'Base')
    return success(ser_base(b))


@bp.route('/bases/<bid>', methods=['PATCH'])
def patch_base(bid):
    body = get_body()
    expected = _int(body, 'expected_base_version', True)
    updates = {}
    for field, fn in (
        ('name', _str),
        ('quiet_hours_start_min_utc', _int),
        ('quiet_hours_end_min_utc', _int),
        ('current_waiver_version', _str),
        ('weather_ceiling_min_ft', _int),
        ('weather_visibility_min_sm', _int),
        ('weather_wind_max_kt', _int),
        ('weather_validity_min', _int),
        ('complaint_quota_threshold', _int),
        ('complaint_window_days', _int),
        ('hold_expire_minutes', _int),
    ):
        v = fn(body, field, False)
        if v is not None:
            updates[field] = v
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    b = get_or_404(db.bases, bid, 'Base')
    if expected != b['version']:
        raise_error(ERR_STALE_VERSION, 'expected_base_version does not match the base version')
    b.update(updates)
    touch(b)
    return success(ser_base(b))


@bp.route('/bases/<bid>/run-ops', methods=['POST'])
def run_ops(bid):
    get_body()
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    b = get_or_404(db.bases, bid, 'Base')
    n = now()
    # Expire HELD bookings whose expires_at is at or before now.
    for bk in list(db.bookings.values()):
        if bk['status'] == 'HELD' and bk['expires_at'] is not None and bk['expires_at'] <= n:
            D.release_applied_credits(bk)
            bk['status'] = 'EXPIRED'
            touch(bk)
    # Expire credits whose expires_at has arrived.
    for c in list(db.credits.values()):
        if c['status'] in ('ISSUED', 'PARTIALLY_REDEEMED') and c['expires_at'] <= n:
            c['status'] = 'EXPIRED'
            touch(c)
    # Close stale duty days; reset fatigue locks for pilots with no OPEN day.
    today = n.date()
    for d in list(db.duty_days.values()):
        if d['status'] == 'OPEN' and d['duty_date'] < today:
            d['status'] = 'CLOSED'
            touch(d)
    for p in list(db.pilots.values()):
        if p['status'] != 'FATIGUE_LOCKED':
            continue
        has_open = any(d['pilot_id'] == p['id'] and d['status'] == 'OPEN' for d in db.duty_days.values())
        if not has_open:
            p['status'] = 'AVAILABLE'
            touch(p)
    b['ops_run_index'] += 1
    touch(b)
    return success(ser_base(b))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/routes', methods=['POST'])
def create_route():
    body = get_body()
    route_code = _str(body, 'route_code', True)
    tier = _enum(body, 'tier', True, ROUTE_TIERS)
    duration = _int(body, 'duration_minutes', True)
    price = _int(body, 'base_seat_price_cents', True)
    fuel = _int(body, 'fuel_required_lb', True)
    min_alt = _int(body, 'min_altitude_ft', True)
    noise_sensitive = _bool(body, 'noise_sensitive', True)
    zones = _list(body, 'noise_zones', True)
    for z in zones:
        if not isinstance(z, str) or z not in NOISE_ZONES:
            raise_error(ERR_INVALID_REQUEST, 'noise_zones entries must be VILLAGE, RIM, or AIRPORT')
    min_class = _enum(body, 'min_aircraft_noise_class', True, MIN_NOISE_CLASSES)
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    for r in db.routes.values():
        if r['route_code'] == route_code:
            raise_error(ERR_UNIQUENESS_CONFLICT, 'route_code already exists')
    r = new_entity()
    r.update({
        'route_code': route_code,
        'tier': tier,
        'duration_minutes': duration,
        'base_seat_price_cents': price,
        'fuel_required_lb': fuel,
        'min_altitude_ft': min_alt,
        'noise_sensitive': noise_sensitive,
        'noise_zones': list(zones),
        'min_aircraft_noise_class': min_class,
        'turn_minutes': D.TURN_BY_TIER[tier],
        'status': 'ACTIVE',
    })
    db.routes[r['id']] = r
    return success(ser_route(r), status=201)


@bp.route('/routes', methods=['GET'])
def list_routes():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sort_created(db.routes.values())
    status = request.args.get('status')
    if status is not None:
        items = [r for r in items if r['status'] == status]
    page, meta = paginated(items)
    return success([ser_route(r) for r in page], response_type='array', pagination=meta)


@bp.route('/routes/<rid>', methods=['GET'])
def get_route(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    r = get_or_404(db.routes, rid, 'Route')
    return success(ser_route(r))


@bp.route('/routes/<rid>/events', methods=['POST'])
def route_events(rid):
    body = get_body()
    event_type = _enum(body, 'event_type', True, ('SUSPEND', 'RESUME'))
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    r = get_or_404(db.routes, rid, 'Route')
    if event_type == 'SUSPEND':
        if r['status'] != 'ACTIVE':
            raise_error(ERR_INVALID_STATE, 'Route is not ACTIVE')
        r['status'] = 'SUSPENDED'
        touch(r)
        D.route_suspension_cascade(r)
    else:  # RESUME
        if r['status'] != 'SUSPENDED':
            raise_error(ERR_INVALID_STATE, 'Route is not SUSPENDED')
        if D.quota_exceeded_bases(r['id']):
            raise_error(ERR_ROUTE_QUOTA_STILL_EXCEEDED, 'Substantiated complaint count still meets the quota')
        r['status'] = 'ACTIVE'
        touch(r)
    return success(ser_route(r))


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------

@bp.route('/seasons', methods=['POST'])
def create_season():
    body = get_body()
    label = _str(body, 'label', True)
    start = _date(body, 'start_date', True)
    end = _date(body, 'end_date', True)
    mult = _int(body, 'multiplier_bps', True)
    if mult < 1 or mult > 30000:
        raise_error(ERR_INVALID_REQUEST, 'multiplier_bps must be between 1 and 30000')
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    if end <= start:
        raise_error(ERR_SEASON_OVERLAP, 'end_date must be after start_date')
    for s in db.seasons.values():
        if s['status'] != 'PUBLISHED':
            continue
        if s['start_date'] < end and start < s['end_date']:
            raise_error(ERR_SEASON_OVERLAP, 'Season window overlaps a PUBLISHED season')
    s = new_entity()
    s.update({'label': label, 'start_date': start, 'end_date': end, 'multiplier_bps': mult, 'status': 'PUBLISHED'})
    db.seasons[s['id']] = s
    return success(ser_season(s), status=201)


@bp.route('/seasons', methods=['GET'])
def list_seasons():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sort_created(db.seasons.values())
    status = request.args.get('status')
    if status is not None:
        items = [s for s in items if s['status'] == status]
    page, meta = paginated(items)
    return success([ser_season(s) for s in page], response_type='array', pagination=meta)


@bp.route('/seasons/<sid>', methods=['GET'])
def get_season(sid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    s = get_or_404(db.seasons, sid, 'Season')
    return success(ser_season(s))


@bp.route('/seasons/<sid>/events', methods=['POST'])
def season_events(sid):
    body = get_body()
    _enum(body, 'event_type', True, ('RETIRE',))
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    s = get_or_404(db.seasons, sid, 'Season')
    if s['status'] != 'PUBLISHED':
        raise_error(ERR_INVALID_STATE, 'Season is not PUBLISHED')
    s['status'] = 'RETIRED'
    touch(s)
    return success(ser_season(s))


# ---------------------------------------------------------------------------
# Aircraft
# ---------------------------------------------------------------------------

@bp.route('/aircraft', methods=['POST'])
def create_aircraft():
    body = get_body()
    tail = _str(body, 'tail_number', True)
    seats = _int(body, 'seat_capacity', True)
    empty_wt = _int(body, 'empty_weight_lb', True)
    empty_moment = _int(body, 'empty_moment_lb_in', True)
    mtow = _int(body, 'max_takeoff_weight_lb', True)
    fuel_arm = _num(body, 'fuel_arm_inches', True)
    seat_arms = _list(body, 'seat_arms_inches', True)
    for a in seat_arms:
        if isinstance(a, bool) or not isinstance(a, (int, float)):
            raise_error(ERR_INVALID_REQUEST, 'seat_arms_inches entries must be numbers')
    cg_fwd = _num(body, 'cg_forward_limit_in', True)
    cg_aft = _num(body, 'cg_aft_limit_in', True)
    noise = _enum(body, 'noise_class', True, AIRCRAFT_NOISE_CLASSES)
    if len(seat_arms) != seats:
        raise_error(ERR_INVALID_REQUEST, 'seat_arms_inches length must equal seat_capacity')
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    for a in db.aircraft.values():
        if a['tail_number'] == tail:
            raise_error(ERR_UNIQUENESS_CONFLICT, 'tail_number already exists')
    a = new_entity()
    a.update({
        'tail_number': tail,
        'seat_capacity': seats,
        'empty_weight_lb': empty_wt,
        'empty_moment_lb_in': empty_moment,
        'max_takeoff_weight_lb': mtow,
        'fuel_arm_inches': fuel_arm,
        'seat_arms_inches': list(seat_arms),
        'cg_forward_limit_in': cg_fwd,
        'cg_aft_limit_in': cg_aft,
        'noise_class': noise,
        'status': 'AVAILABLE',
    })
    db.aircraft[a['id']] = a
    return success(ser_aircraft(a), status=201)


@bp.route('/aircraft', methods=['GET'])
def list_aircraft():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sort_created(db.aircraft.values())
    status = request.args.get('status')
    if status is not None:
        items = [a for a in items if a['status'] == status]
    noise = request.args.get('noise_class')
    if noise is not None:
        items = [a for a in items if a['noise_class'] == noise]
    page, meta = paginated(items)
    return success([ser_aircraft(a) for a in page], response_type='array', pagination=meta)


@bp.route('/aircraft/<aid>', methods=['GET'])
def get_aircraft(aid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    a = get_or_404(db.aircraft, aid, 'Aircraft')
    return success(ser_aircraft(a))


@bp.route('/aircraft/<aid>/events', methods=['POST'])
def aircraft_events(aid):
    body = get_body()
    event_type = _enum(body, 'event_type', True, ('START_MAINTENANCE', 'END_MAINTENANCE', 'GROUND', 'RECERTIFY'))
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    a = get_or_404(db.aircraft, aid, 'Aircraft')
    n = now()
    if event_type == 'START_MAINTENANCE':
        if a['status'] != 'AVAILABLE':
            raise_error(ERR_INVALID_STATE, 'Aircraft is not AVAILABLE')
        blocking = any(
            f['aircraft_id'] == a['id']
            and f['status'] in ('SCHEDULED', 'DELAYED', 'BOARDING', 'MANIFEST_CLOSED')
            and f['scheduled_departure_utc'] >= n
            for f in db.flights.values()
        )
        if blocking:
            raise_error(ERR_INVALID_STATE, 'Aircraft has future active flights')
        a['status'] = 'IN_MAINTENANCE'
    elif event_type == 'END_MAINTENANCE':
        if a['status'] != 'IN_MAINTENANCE':
            raise_error(ERR_INVALID_STATE, 'Aircraft is not IN_MAINTENANCE')
        a['status'] = 'AVAILABLE'
    elif event_type == 'GROUND':
        if a['status'] not in ('AVAILABLE', 'IN_MAINTENANCE'):
            raise_error(ERR_INVALID_STATE, 'Aircraft cannot be grounded from its current state')
        was_available = a['status'] == 'AVAILABLE'
        a['status'] = 'GROUNDED'
        touch(a)
        if was_available:
            D.aircraft_grounding_cascade(a)
        return success(ser_aircraft(a))
    else:  # RECERTIFY
        if a['status'] != 'GROUNDED':
            raise_error(ERR_INVALID_STATE, 'Aircraft is not GROUNDED')
        a['status'] = 'AVAILABLE'
    touch(a)
    return success(ser_aircraft(a))


# ---------------------------------------------------------------------------
# Pilots
# ---------------------------------------------------------------------------

@bp.route('/pilots', methods=['POST'])
def create_pilot():
    body = get_body()
    name = _str(body, 'display_name', True)
    cert = _str(body, 'certificate_no', True)
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    for p in db.pilots.values():
        if p['certificate_no'] == cert:
            raise_error(ERR_UNIQUENESS_CONFLICT, 'certificate_no already exists')
    p = new_entity()
    p.update({'display_name': name, 'certificate_no': cert, 'status': 'AVAILABLE'})
    db.pilots[p['id']] = p
    return success(ser_pilot(p), status=201)


@bp.route('/pilots', methods=['GET'])
def list_pilots():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sort_created(db.pilots.values())
    status = request.args.get('status')
    if status is not None:
        items = [p for p in items if p['status'] == status]
    page, meta = paginated(items)
    return success([ser_pilot(p) for p in page], response_type='array', pagination=meta)


@bp.route('/pilots/<pid>', methods=['GET'])
def get_pilot(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    p = get_or_404(db.pilots, pid, 'Pilot')
    return success(ser_pilot(p))


# ---------------------------------------------------------------------------
# Duty days
# ---------------------------------------------------------------------------

DUTY_READ_ROLES = ('OpsAdmin', 'Dispatcher', 'Pilot')


@bp.route('/duty-days', methods=['GET'])
def list_duty_days():
    uid, role = authenticate()
    require_role(role, DUTY_READ_ROLES)
    pilot_filter = request.args.get('pilot_id')
    if role == 'Pilot':
        # Entity-backed ownership: a pilot may query only their own ledger.
        if pilot_filter != uid:
            raise_error(ERR_UNAUTHORIZED_ROLE, 'Pilot may only query own duty-days')
    items = sort_created(db.duty_days.values())
    if pilot_filter is not None:
        items = [d for d in items if d['pilot_id'] == pilot_filter]
    date_filter = request.args.get('duty_date')
    if date_filter is not None:
        items = [d for d in items if d['duty_date'].isoformat() == date_filter]
    status = request.args.get('status')
    if status is not None:
        items = [d for d in items if d['status'] == status]
    page, meta = paginated(items)
    return success([ser_duty_day(d) for d in page], response_type='array', pagination=meta)


@bp.route('/duty-days/<did>', methods=['GET'])
def get_duty_day(did):
    uid, role = authenticate()
    require_role(role, DUTY_READ_ROLES)
    d = get_or_404(db.duty_days, did, 'DutyDay')
    if role == 'Pilot' and d['pilot_id'] != uid:
        raise_error(ERR_UNAUTHORIZED_ROLE, 'Pilot may only read own duty-days')
    return success(ser_duty_day(d))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_current_utc():
    body = get_body()
    to = _dt(body, 'to_iso8601', True)
    _, role = authenticate()
    require_role(role, ('OpsAdmin',))
    set_clock(to)
    return success({'current_utc': fmt_ts(to)})
