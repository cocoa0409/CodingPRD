import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# In-memory store (fresh on every boot; NO seeding)
# =============================================================================
DB = {
    'clients': {},
    'packages': {},
    'bartenders': {},
    'bar_kits': {},
    'events': {},
    'compliance_reviews': {},
    'assignments': {},
    'kit_reservations': {},
    'inventory_plans': {},
    'menu_items': {},
    'payments': {},
    'breakage_reports': {},
}

_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


ROLES = {'PlatformAdmin', 'Client', 'Coordinator', 'ComplianceOfficer', 'Bartender'}

# =============================================================================
# Helpers: ids, time, rounding
# =============================================================================


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f"{dt.microsecond // 1000:03d}Z"


def D(x):
    return Decimal(str(x))


def rhu(value):
    return int(D(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def dceil(value):
    return int(D(value).quantize(Decimal('1'), rounding=ROUND_CEILING))


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError('ERR_VALIDATION', 400, 'Invalid datetime')
    t = s.strip()
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        raise ApiError('ERR_VALIDATION', 400, 'Invalid datetime format')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# =============================================================================
# Errors and response envelope
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta(extra=None):
    m = {
        'api_request_id': 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=20)),
        'api_request_timestamp': now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, response_type='object', status=200, pagination=None):
    body = {'meta': _meta(pagination), 'response_type': response_type, 'data': data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': err.error_id, 'message': err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {'meta': _meta(), 'response_type': 'error',
            'data': {'error_id': 'ERR_EVENT_NOT_FOUND', 'message': 'Not found'}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {'meta': _meta(), 'response_type': 'error',
            'data': {'error_id': 'ERR_VALIDATION', 'message': 'Method not allowed'}}
    return jsonify(body), 405


# =============================================================================
# Auth / RBAC
# =============================================================================


def require_auth():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401, 'Missing or unknown authentication headers')
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'Role not permitted for this operation')


def body_json():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError('ERR_VALIDATION', 400, 'Request body must be a JSON object')
    return data


# =============================================================================
# Field extraction / validation helpers
# =============================================================================


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == '':
        raise ApiError('ERR_VALIDATION', 400, f'Missing or invalid field: {key}')
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise ApiError('ERR_VALIDATION', 400, f'Invalid field: {key}')
    return v


def req_enum(body, key, members):
    v = req_str(body, key)
    if v not in members:
        raise ApiError('ERR_VALIDATION', 400, f'Invalid enum value for {key}')
    return v


def opt_enum(body, key, members, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if v not in members:
        raise ApiError('ERR_VALIDATION', 400, f'Invalid enum value for {key}')
    return v


def req_int(body, key, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        raise ApiError('ERR_VALIDATION', 400, f'Missing field: {key}')
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError('ERR_VALIDATION', 400, f'Invalid integer for {key}')
    if minimum is not None and v < minimum:
        raise ApiError('ERR_VALIDATION', 400, f'{key} below minimum')
    if maximum is not None and v > maximum:
        raise ApiError('ERR_VALIDATION', 400, f'{key} above maximum')
    return v


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key, minimum, maximum)


def req_num(body, key, minimum=None, strictly_positive=False):
    if key not in body or body[key] is None:
        raise ApiError('ERR_VALIDATION', 400, f'Missing field: {key}')
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError('ERR_VALIDATION', 400, f'Invalid number for {key}')
    if strictly_positive and not v > 0:
        raise ApiError('ERR_VALIDATION', 400, f'{key} must be positive')
    if minimum is not None and v < minimum:
        raise ApiError('ERR_VALIDATION', 400, f'{key} below minimum')
    return v


def opt_bool(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise ApiError('ERR_VALIDATION', 400, f'Invalid boolean for {key}')
    return v


def req_bool(body, key):
    if key not in body or body[key] is None:
        raise ApiError('ERR_VALIDATION', 400, f'Missing field: {key}')
    v = body[key]
    if not isinstance(v, bool):
        raise ApiError('ERR_VALIDATION', 400, f'Invalid boolean for {key}')
    return v


def req_datetime(body, key):
    v = req_str(body, key)
    parse_dt(v)  # validates
    return v


def valid_state_code(body, key):
    v = req_str(body, key)
    if len(v) != 2 or not v.isalpha() or v != v.upper():
        raise ApiError('ERR_VALIDATION', 400, f'{key} must be a 2-letter uppercase state code')
    return v


def get_pagination():
    limit = 10
    offset = 0
    ls = request.args.get('limit')
    os_ = request.args.get('offset')
    if ls is not None:
        try:
            limit = int(ls)
        except Exception:
            raise ApiError('ERR_VALIDATION', 400, 'Invalid limit')
        if limit < 1 or limit > 100:
            raise ApiError('ERR_VALIDATION', 400, 'limit out of range')
    if os_ is not None:
        try:
            offset = int(os_)
        except Exception:
            raise ApiError('ERR_VALIDATION', 400, 'Invalid offset')
        if offset < 0:
            raise ApiError('ERR_VALIDATION', 400, 'offset out of range')
    return limit, offset


def paginate_response(items, serialize):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda r: (r['created_at'], r['_seq']))
    total = len(items)
    page = items[offset:offset + limit]
    data = [serialize(x) for x in page]
    pag = {'limit': limit, 'offset': offset, 'total_count': total,
           'has_more': (offset + len(page)) < total}
    return success(data, 'array', 200, pag)


# =============================================================================
# Common resource helpers
# =============================================================================


def base_record(with_version=True):
    rec = {'id': new_id(), 'created_at': now_iso(), '_seq': next_seq()}
    if with_version:
        rec['updated_at'] = rec['created_at']
        rec['version'] = 1
    return rec


def touch(rec):
    rec['version'] += 1
    rec['updated_at'] = now_iso()


def clean(rec):
    return {k: v for k, v in rec.items() if not k.startswith('_')}


# =============================================================================
# Serializers
# =============================================================================


def ser_event(ev):
    d = clean(ev)
    d['amount_paid_cents'] = amount_paid(ev)
    d['balance_due_cents'] = balance_due(ev)
    return d


def ser_bartender(b):
    d = clean(b)
    strict, lenient = reliability(b['id'])
    d['reliability_score_strict'] = strict
    d['reliability_score_lenient'] = lenient
    d['upcoming_assignment_count'] = upcoming_count(b['id'])
    return d


def ser(rec):
    return clean(rec)


# =============================================================================
# Financial helpers
# =============================================================================


def event_payments(eid):
    return [p for p in DB['payments'].values() if p['event_id'] == eid]


def amount_paid(ev):
    s = 0
    for p in event_payments(ev['id']):
        if p['payment_type'] in ('DEPOSIT', 'BALANCE'):
            s += p['amount_cents']
        elif p['payment_type'] == 'REFUND':
            s -= p['amount_cents']
    return s


def balance_due(ev):
    if ev['booking_status'] == 'CANCELLED':
        return 0
    extra = sum(p['amount_cents'] for p in event_payments(ev['id'])
                if p['payment_type'] in ('BREAKAGE_CHARGE', 'CANCELLATION_FEE'))
    return ev['final_grand_total_cents'] + extra - amount_paid(ev)


def recompute_payment_status(ev):
    if ev['booking_status'] == 'CANCELLED':
        return
    ap = amount_paid(ev)
    bal = balance_due(ev)
    if ap <= 0:
        ev['payment_status'] = 'UNPAID'
    elif bal <= 0:
        ev['payment_status'] = 'PAID_IN_FULL'
    else:
        ev['payment_status'] = 'DEPOSIT_PAID'


def create_payment(eid, ptype, amount, method):
    rec = {
        'id': new_id(),
        'created_at': now_iso(),
        '_seq': next_seq(),
        'event_id': eid,
        'payment_type': ptype,
        'amount_cents': amount,
        'method': method,
    }
    DB['payments'][rec['id']] = rec
    return rec


# =============================================================================
# Calculation helpers
# =============================================================================


def compute_event_pricing(ev, pkg):
    start = parse_dt(ev['event_start'])
    end = parse_dt(ev['event_end'])
    secs = (end - start).total_seconds()
    billable = dceil(D(secs) / D(3600))
    guests = ev['guest_count']
    required = dceil(D(guests) / D(pkg['guests_per_bartender']))

    overage_guests = max(0, guests - pkg['included_guest_count'])
    overage_hours_final = max(0, billable - pkg['included_hours'])
    guest_over_cost = overage_guests * pkg['per_guest_overage_cents']
    subtotal_final = pkg['base_price_cents'] + guest_over_cost + \
        overage_hours_final * pkg['per_hour_overage_cents']
    subtotal_prov = pkg['base_price_cents'] + guest_over_cost  # overage_hours = 0

    if guests <= 50:
        pct = Decimal('0.20')
    elif guests <= 150:
        pct = Decimal('0.18')
    else:
        pct = Decimal('0.15')

    def service_fee(sub):
        f = rhu(D(sub) * pct)
        return min(max(f, 25000), 200000)

    def gratuity(sub):
        return rhu(D(sub) * Decimal('0.18'))

    sf_final = service_fee(subtotal_final)
    grat_final = gratuity(subtotal_final)
    final_total = subtotal_final + sf_final + grat_final

    sf_prov = service_fee(subtotal_prov)
    grat_prov = gratuity(subtotal_prov)
    prov_total = subtotal_prov + sf_prov + grat_prov

    deposit = rhu(D(prov_total) * Decimal('0.5'))

    ev['billable_hours'] = billable
    ev['required_bartender_count'] = required
    ev['subtotal_cents'] = subtotal_final
    ev['service_fee_cents'] = sf_final
    ev['gratuity_cents'] = grat_final
    ev['provisional_grand_total_cents'] = prov_total
    ev['final_grand_total_cents'] = final_total
    ev['deposit_due_cents'] = deposit


def compute_inventory(ev, pkg):
    total = dceil(D(ev['guest_count']) * D(ev['billable_hours']) * D(pkg['drinks_per_guest_per_hour']))
    beer_s = rhu(D(total) * Decimal('0.40'))
    wine_s = rhu(D(total) * Decimal('0.30'))
    spirit_s = total - beer_s - wine_s
    beer_units = dceil(D(beer_s) / D(1))
    wine_bottles = dceil(D(wine_s) / D(5))
    spirit_bottles = dceil(D(spirit_s) / D(16))
    ice = dceil(D(ev['guest_count']) * Decimal('1.5'))
    glass = dceil(D(ev['guest_count']) * Decimal('2.5'))
    return {
        'total_servings': total,
        'beer_units': beer_units,
        'wine_bottles': wine_bottles,
        'spirit_bottles': spirit_bottles,
        'ice_lbs': ice,
        'glassware_needed': glass,
    }


def compute_shift(a, bartender):
    s = parse_dt(a['shift_start'])
    e = parse_dt(a['shift_end'])
    secs = (e - s).total_seconds()
    hours = D(secs) / D(3600)
    quarters = dceil(hours * 4)
    shift_hours = D(quarters) / D(4)
    reg = min(shift_hours, D(8))
    ot = max(D(0), shift_hours - D(8))
    rate = D(bartender['hourly_rate_cents'])
    cost = rhu(reg * rate + ot * rate * Decimal('1.5'))
    a['shift_hours'] = float(shift_hours)
    a['labor_cost_cents'] = cost


def reliability(bid):
    asn = [a for a in DB['assignments'].values() if a['bartender_id'] == bid]
    completed = sum(1 for a in asn if a['status'] == 'COMPLETED')
    no_shows = sum(1 for a in asn if a['status'] == 'NO_SHOW')
    cancels = sum(1 for a in asn if a['status'] == 'CANCELLED' and a.get('cancelled_by') == 'BARTENDER')
    total = completed + no_shows + cancels
    if total == 0:
        return 100, 100
    strict = max(0, rhu(D(100) * D(completed) / D(total) - D(no_shows) * 15 - D(cancels) * 5))
    lenient = max(0, rhu(D(100) * (D(completed) + D(cancels) * Decimal('0.5')) / D(total) - D(no_shows) * 8))
    return strict, lenient


def upcoming_count(bid):
    return sum(1 for a in DB['assignments'].values()
               if a['bartender_id'] == bid and a['status'] in ('PROPOSED', 'CONFIRMED', 'CHECKED_IN'))


# =============================================================================
# Lookup helpers (existence)
# =============================================================================


def get_event(eid):
    ev = DB['events'].get(eid)
    if ev is None:
        raise ApiError('ERR_EVENT_NOT_FOUND', 404, 'Event not found')
    return ev


def get_bartender(bid):
    b = DB['bartenders'].get(bid)
    if b is None:
        raise ApiError('ERR_BARTENDER_NOT_FOUND', 404, 'Bartender not found')
    return b


def get_assignment(aid):
    a = DB['assignments'].get(aid)
    if a is None:
        raise ApiError('ERR_ASSIGNMENT_NOT_FOUND', 404, 'Assignment not found')
    return a


def get_review(rid):
    r = DB['compliance_reviews'].get(rid)
    if r is None:
        raise ApiError('ERR_COMPLIANCE_REVIEW_NOT_FOUND', 404, 'Compliance review not found')
    return r


def get_reservation(kid):
    r = DB['kit_reservations'].get(kid)
    if r is None:
        raise ApiError('ERR_KIT_RESERVATION_NOT_FOUND', 404, 'Kit reservation not found')
    return r


def get_breakage(bid):
    r = DB['breakage_reports'].get(bid)
    if r is None:
        raise ApiError('ERR_BREAKAGE_REPORT_NOT_FOUND', 404, 'Breakage report not found')
    return r


def check_event_owner(role, uid, ev):
    if role == 'Client' and ev['client_id'] != uid:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'Client does not own this event')


def assignments_of(eid):
    return [a for a in DB['assignments'].values() if a['event_id'] == eid]


def touch_bartender_by_id(bid):
    b = DB['bartenders'].get(bid)
    if b:
        touch(b)


# =============================================================================
# Config endpoints: Package, Bartender, BarKit, Client
# =============================================================================


@app.route('/packages', methods=['POST'])
def create_package():
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin'})
    body = body_json()
    rec = base_record()
    rec['tier'] = req_enum(body, 'tier', {'BEER_WINE', 'CLASSIC', 'PREMIUM', 'LUXURY'})
    rec['name'] = req_str(body, 'name')
    rec['base_price_cents'] = req_int(body, 'base_price_cents', minimum=0)
    rec['included_guest_count'] = req_int(body, 'included_guest_count', minimum=1)
    rec['per_guest_overage_cents'] = req_int(body, 'per_guest_overage_cents', minimum=0)
    rec['included_hours'] = req_int(body, 'included_hours', minimum=1)
    rec['min_hours'] = req_int(body, 'min_hours', minimum=1)
    rec['per_hour_overage_cents'] = req_int(body, 'per_hour_overage_cents', minimum=0)
    rec['drinks_per_guest_per_hour'] = req_num(body, 'drinks_per_guest_per_hour', strictly_positive=True)
    rec['guests_per_bartender'] = req_int(body, 'guests_per_bartender', minimum=1)
    rec['is_active'] = opt_bool(body, 'is_active', True)
    DB['packages'][rec['id']] = rec
    return success(ser(rec), 'object', 201)


@app.route('/bartenders', methods=['POST'])
def create_bartender():
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin'})
    body = body_json()
    rec = base_record()
    rec['full_name'] = req_str(body, 'full_name')
    rec['email'] = req_str(body, 'email')
    rec['certification_expiry'] = req_datetime(body, 'certification_expiry')
    rec['hourly_rate_cents'] = req_int(body, 'hourly_rate_cents', minimum=0)
    rec['home_state_code'] = valid_state_code(body, 'home_state_code')
    rec['availability_status'] = 'AVAILABLE'
    # reliability + upcoming are computed dynamically at serialization time.
    DB['bartenders'][rec['id']] = rec
    return success(ser_bartender(rec), 'object', 201)


@app.route('/bartenders/<bid>', methods=['GET'])
def read_bartender(bid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'Bartender'})
    b = get_bartender(bid)
    return success(ser_bartender(b), 'object', 200)


@app.route('/bartenders/<bid>/deactivate', methods=['POST'])
def deactivate_bartender(bid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin'})
    b = get_bartender(bid)
    b['availability_status'] = 'INACTIVE'
    touch(b)
    return success(ser_bartender(b), 'object', 200)


@app.route('/bar-kits', methods=['POST'])
def create_bar_kit():
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin'})
    body = body_json()
    rec = base_record()
    rec['kit_name'] = req_str(body, 'kit_name')
    rec['station_type'] = req_enum(body, 'station_type', {'BEER_WINE', 'FULL_BAR', 'MOBILE_CART'})
    rec['glassware_count'] = req_int(body, 'glassware_count', minimum=0)
    rec['status'] = 'AVAILABLE'
    DB['bar_kits'][rec['id']] = rec
    return success(ser(rec), 'object', 201)


@app.route('/clients', methods=['POST'])
def create_client():
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin'})
    body = body_json()
    rec = base_record()
    rec['full_name'] = req_str(body, 'full_name')
    rec['email'] = req_str(body, 'email')
    rec['phone'] = req_str(body, 'phone')
    rec['home_state_code'] = valid_state_code(body, 'home_state_code')
    DB['clients'][rec['id']] = rec
    return success(ser(rec), 'object', 201)


# =============================================================================
# Event core
# =============================================================================


@app.route('/events', methods=['POST'])
def create_event():
    uid, role = require_auth()
    require_role(role, {'Client'})
    body = body_json()

    # Authorization / ownership: a client books for itself.
    client_id = body.get('client_id')
    if client_id is not None and client_id != uid:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'Client may only book its own events')

    # Existence (path/body FK) before body well-formedness.
    if client_id is not None and client_id not in DB['clients']:
        raise ApiError('ERR_CLIENT_NOT_FOUND', 404, 'Client not found')
    package_id = body.get('package_id')
    if package_id is not None and package_id not in DB['packages']:
        raise ApiError('ERR_PACKAGE_NOT_FOUND', 404, 'Package not found')

    # Body well-formedness.
    client_id = req_str(body, 'client_id')
    package_id = req_str(body, 'package_id')
    title = req_str(body, 'title')
    venue_state_code = valid_state_code(body, 'venue_state_code')
    venue_type = req_enum(body, 'venue_type', {'INDOOR', 'OUTDOOR', 'MIXED'})
    event_start = req_datetime(body, 'event_start')
    event_end = req_datetime(body, 'event_end')
    guest_count = req_int(body, 'guest_count', minimum=1)
    byob = opt_bool(body, 'byob_host_model', True)
    if not parse_dt(event_end) > parse_dt(event_start):
        raise ApiError('ERR_VALIDATION', 400, 'event_end must be strictly after event_start')

    rec = base_record()
    rec.update({
        'client_id': client_id,
        'package_id': package_id,
        'title': title,
        'venue_state_code': venue_state_code,
        'venue_type': venue_type,
        'event_start': event_start,
        'event_end': event_end,
        'guest_count': guest_count,
        'byob_host_model': byob,
        'booking_status': 'DRAFT',
        'payment_status': 'UNPAID',
        'compliance_posture': 'PENDING',
        'cancelled_by': None,
    })
    compute_event_pricing(rec, DB['packages'][package_id])
    DB['events'][rec['id']] = rec
    return success(ser_event(rec), 'object', 201)


@app.route('/events', methods=['GET'])
def list_events():
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'ComplianceOfficer', 'Client'})
    items = list(DB['events'].values())
    if role == 'Client':
        items = [e for e in items if e['client_id'] == uid]
    cid = request.args.get('client_id')
    if cid is not None:
        items = [e for e in items if e['client_id'] == cid]
    pid = request.args.get('package_id')
    if pid is not None:
        items = [e for e in items if e['package_id'] == pid]
    bs = request.args.get('booking_status')
    if bs is not None:
        items = [e for e in items if e['booking_status'] == bs]
    return paginate_response(items, ser_event)


@app.route('/events/<eid>', methods=['GET'])
def read_event(eid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'ComplianceOfficer', 'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    return success(ser_event(ev), 'object', 200)


@app.route('/events/<eid>', methods=['PATCH'])
def edit_event(eid):
    uid, role = require_auth()
    require_role(role, {'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    body = body_json()

    expected = req_int(body, 'expected_event_version')

    new_guest = opt_int(body, 'guest_count', minimum=1, default=None)
    new_start = opt_str(body, 'event_start', default=None)
    new_end = opt_str(body, 'event_end', default=None)
    new_venue_type = None
    if 'venue_type' in body and body['venue_type'] is not None:
        new_venue_type = req_enum(body, 'venue_type', {'INDOOR', 'OUTDOOR', 'MIXED'})

    start_val = new_start if new_start is not None else ev['event_start']
    end_val = new_end if new_end is not None else ev['event_end']
    if new_start is not None:
        parse_dt(new_start)
    if new_end is not None:
        parse_dt(new_end)
    if not parse_dt(end_val) > parse_dt(start_val):
        raise ApiError('ERR_VALIDATION', 400, 'event_end must be strictly after event_start')

    # OCC
    if expected != ev['version']:
        raise ApiError('ERR_STALE_EVENT_VERSION', 412, 'Stale event version')

    if new_guest is not None:
        ev['guest_count'] = new_guest
    if new_start is not None:
        ev['event_start'] = new_start
    if new_end is not None:
        ev['event_end'] = new_end
    if new_venue_type is not None:
        ev['venue_type'] = new_venue_type

    compute_event_pricing(ev, DB['packages'][ev['package_id']])

    # Mark inventory plan STALE
    for plan in DB['inventory_plans'].values():
        if plan['event_id'] == eid:
            plan['status'] = 'STALE'
            touch(plan)

    touch(ev)
    return success(ser_event(ev), 'object', 200)


@app.route('/events/<eid>/confirm', methods=['POST'])
def confirm_event(eid):
    uid, role = require_auth()
    require_role(role, {'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    if ev['booking_status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Event not in DRAFT')
    if ev['compliance_posture'] != 'CLEARED':
        raise ApiError('ERR_COMPLIANCE_NOT_CLEARED', 409, 'Compliance not cleared')
    if ev['payment_status'] not in ('DEPOSIT_PAID', 'PAID_IN_FULL'):
        raise ApiError('ERR_DEPOSIT_NOT_PAID', 409, 'Deposit not paid')
    ev['booking_status'] = 'CONFIRMED'
    touch(ev)
    return success(ser_event(ev), 'object', 200)


@app.route('/events/<eid>/cancel', methods=['POST'])
def cancel_event(eid):
    uid, role = require_auth()
    require_role(role, {'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    from_status = ev['booking_status']
    if from_status not in ('DRAFT', 'CONFIRMED'):
        raise ApiError('ERR_INVALID_STATE', 409, 'Event cannot be cancelled from its current state')

    ap = amount_paid(ev)
    ev['booking_status'] = 'CANCELLED'
    ev['cancelled_by'] = 'CLIENT'

    if ap > 0:
        fee = rhu(D(ap) * Decimal('0.5'))
        refund = ap - fee
        create_payment(eid, 'CANCELLATION_FEE', fee, 'SYSTEM')
        if refund > 0:
            create_payment(eid, 'REFUND', refund, 'SYSTEM')
        ev['payment_status'] = 'SETTLED'

    if from_status == 'CONFIRMED':
        for a in assignments_of(eid):
            if a['status'] in ('PROPOSED', 'CONFIRMED'):
                a['status'] = 'CANCELLED'
                a['cancelled_by'] = 'SYSTEM'
                touch(a)
                touch_bartender_by_id(a['bartender_id'])

    touch(ev)
    return success(ser_event(ev), 'object', 200)


@app.route('/events/<eid>/start', methods=['POST'])
def start_event(eid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    ev = get_event(eid)
    if ev['booking_status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Event not in CONFIRMED')
    has_lead = any(a['status'] == 'CHECKED_IN' and a['role_on_event'] == 'LEAD'
                   for a in assignments_of(eid))
    if not has_lead:
        raise ApiError('ERR_NO_CHECKED_IN_STAFF', 409, 'No checked-in LEAD assignment')
    ev['booking_status'] = 'IN_PROGRESS'
    touch(ev)
    return success(ser_event(ev), 'object', 200)


@app.route('/events/<eid>/complete', methods=['POST'])
def complete_event(eid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    ev = get_event(eid)
    if ev['booking_status'] != 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 409, 'Event not in IN_PROGRESS')
    ev['booking_status'] = 'COMPLETED'
    for a in assignments_of(eid):
        if a['status'] == 'CHECKED_IN':
            a['status'] = 'COMPLETED'
            touch(a)
            touch_bartender_by_id(a['bartender_id'])
    touch(ev)
    return success(ser_event(ev), 'object', 200)


@app.route('/events/<eid>/close', methods=['POST'])
def close_event(eid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    ev = get_event(eid)
    if ev['booking_status'] != 'COMPLETED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Event not in COMPLETED')
    for r in DB['kit_reservations'].values():
        if r['event_id'] == eid and r['status'] not in ('RETURNED', 'RELEASED'):
            raise ApiError('ERR_INVALID_STATE', 409, 'Kit reservation not returned/released')
    for br in DB['breakage_reports'].values():
        if br['event_id'] == eid and br['status'] != 'SETTLED':
            raise ApiError('ERR_INVALID_STATE', 409, 'Breakage report not settled')
    ev['booking_status'] = 'CLOSED'
    touch(ev)
    return success(ser_event(ev), 'object', 200)


# =============================================================================
# Payments
# =============================================================================


@app.route('/events/<eid>/payments', methods=['POST'])
def post_payment(eid):
    uid, role = require_auth()
    require_role(role, {'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    body = body_json()
    ptype = req_enum(body, 'payment_type', {'DEPOSIT', 'BALANCE'})
    amount = req_int(body, 'amount_cents', minimum=1)
    method = opt_enum(body, 'method', {'CARD', 'ACH', 'CASH', 'SYSTEM'}, 'SYSTEM')

    if ptype == 'DEPOSIT':
        if ev['payment_status'] != 'UNPAID':
            raise ApiError('ERR_PAYMENT_EXCEEDS_BALANCE', 422, 'Deposit already recorded')
    else:  # BALANCE
        if amount > balance_due(ev):
            raise ApiError('ERR_PAYMENT_EXCEEDS_BALANCE', 422, 'Payment exceeds balance due')

    rec = create_payment(eid, ptype, amount, method)

    if ptype == 'DEPOSIT' and ev['payment_status'] == 'UNPAID':
        ev['payment_status'] = 'DEPOSIT_PAID'
    if balance_due(ev) <= 0 and amount_paid(ev) > 0:
        ev['payment_status'] = 'PAID_IN_FULL'
    touch(ev)
    return success(ser(rec), 'object', 201)


@app.route('/events/<eid>/payments', methods=['GET'])
def list_payments(eid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    items = event_payments(eid)
    return paginate_response(items, ser)


# =============================================================================
# Compliance
# =============================================================================


@app.route('/events/<eid>/compliance-review', methods=['POST'])
def create_compliance_review(eid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    ev = get_event(eid)
    body = body_json()
    rec = base_record()
    rec['event_id'] = eid
    rec['abc_model'] = req_enum(body, 'abc_model', {'HOST_NO_SALE', 'CASH_BAR', 'NONE'})
    rec['liquor_liability_insurance_verified'] = req_bool(body, 'liquor_liability_insurance_verified')
    rec['host_alcohol_ownership_attested'] = req_bool(body, 'host_alcohol_ownership_attested')
    rec['server_certification_verified'] = req_bool(body, 'server_certification_verified')
    rec['revision_round'] = 0
    rec['reviewer_notes'] = opt_str(body, 'reviewer_notes', None)
    rec['status'] = 'DRAFT'
    DB['compliance_reviews'][rec['id']] = rec
    return success(ser(rec), 'object', 201)


@app.route('/events/<eid>/compliance-review', methods=['GET'])
def list_compliance_review(eid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'ComplianceOfficer', 'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    items = [r for r in DB['compliance_reviews'].values() if r['event_id'] == eid]
    return paginate_response(items, ser)


@app.route('/compliance-reviews/<rid>/submit', methods=['POST'])
def submit_review(rid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    r = get_review(rid)
    body = body_json()
    # optional attestation corrections
    if 'abc_model' in body and body['abc_model'] is not None:
        r['abc_model'] = req_enum(body, 'abc_model', {'HOST_NO_SALE', 'CASH_BAR', 'NONE'})
    if 'liquor_liability_insurance_verified' in body and body['liquor_liability_insurance_verified'] is not None:
        r['liquor_liability_insurance_verified'] = req_bool(body, 'liquor_liability_insurance_verified')
    if 'host_alcohol_ownership_attested' in body and body['host_alcohol_ownership_attested'] is not None:
        r['host_alcohol_ownership_attested'] = req_bool(body, 'host_alcohol_ownership_attested')
    if 'server_certification_verified' in body and body['server_certification_verified'] is not None:
        r['server_certification_verified'] = req_bool(body, 'server_certification_verified')

    if r['status'] not in ('DRAFT', 'CHANGES_REQUESTED'):
        raise ApiError('ERR_INVALID_STATE', 409, 'Review cannot be submitted from its current state')
    resubmit = r['status'] == 'CHANGES_REQUESTED'
    r['status'] = 'SUBMITTED'
    if resubmit:
        r['revision_round'] += 1
    touch(r)
    return success(ser(r), 'object', 200)


@app.route('/compliance-reviews/<rid>/clear', methods=['POST'])
def clear_review(rid):
    uid, role = require_auth()
    require_role(role, {'ComplianceOfficer'})
    r = get_review(rid)
    body = body_json()
    if 'reviewer_notes' in body and body['reviewer_notes'] is not None:
        r['reviewer_notes'] = opt_str(body, 'reviewer_notes', r['reviewer_notes'])
    if r['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Review not in SUBMITTED')
    if r['abc_model'] != 'HOST_NO_SALE':
        raise ApiError('ERR_ABC_MODEL_INVALID', 422, 'ABC model must be HOST_NO_SALE')
    if not r['liquor_liability_insurance_verified']:
        raise ApiError('ERR_INSURANCE_NOT_VERIFIED', 422, 'Insurance not verified')
    if not r['host_alcohol_ownership_attested'] or not r['server_certification_verified']:
        raise ApiError('ERR_HOST_ATTESTATION_MISSING', 422, 'Host/server attestation missing')

    r['status'] = 'CLEARED'
    touch(r)
    ev = DB['events'].get(r['event_id'])
    if ev:
        ev['compliance_posture'] = 'CLEARED'
        touch(ev)
    return success(ser(r), 'object', 200)


@app.route('/compliance-reviews/<rid>/request-changes', methods=['POST'])
def request_changes_review(rid):
    uid, role = require_auth()
    require_role(role, {'ComplianceOfficer'})
    r = get_review(rid)
    body = body_json()
    reviewer_notes = req_str(body, 'reviewer_notes')
    if r['status'] not in ('SUBMITTED', 'CLEARED'):
        raise ApiError('ERR_INVALID_STATE', 409, 'Review cannot request changes from its current state')

    r['reviewer_notes'] = reviewer_notes
    r['status'] = 'CHANGES_REQUESTED'
    touch(r)

    ev = DB['events'].get(r['event_id'])
    if ev:
        ev['compliance_posture'] = 'BLOCKED'
        for a in assignments_of(ev['id']):
            if a['status'] == 'CONFIRMED':
                a['status'] = 'PROPOSED'
                touch(a)
                touch_bartender_by_id(a['bartender_id'])
        touch(ev)
    return success(ser(r), 'object', 200)


# =============================================================================
# Assignments
# =============================================================================


@app.route('/events/<eid>/assignments', methods=['POST'])
def create_assignment(eid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    ev = get_event(eid)
    body = body_json()

    # Existence: bartender FK
    bartender_id = body.get('bartender_id')
    if bartender_id is not None and bartender_id not in DB['bartenders']:
        raise ApiError('ERR_BARTENDER_NOT_FOUND', 404, 'Bartender not found')

    # Body well-formedness
    bartender_id = req_str(body, 'bartender_id')
    shift_start = req_datetime(body, 'shift_start')
    shift_end = req_datetime(body, 'shift_end')
    role_on_event = req_enum(body, 'role_on_event', {'LEAD', 'BACK'})
    expected = req_int(body, 'expected_event_version')
    if not parse_dt(shift_end) > parse_dt(shift_start):
        raise ApiError('ERR_VALIDATION', 400, 'shift_end must be strictly after shift_start')

    # OCC
    if expected != ev['version']:
        raise ApiError('ERR_STALE_EVENT_VERSION', 412, 'Stale event version')

    bartender = DB['bartenders'][bartender_id]

    # Business-safety checks (priority order)
    if not parse_dt(bartender['certification_expiry']) > parse_dt(ev['event_start']):
        raise ApiError('ERR_BARTENDER_CERT_EXPIRED', 422, 'Bartender certification expired')
    if bartender['home_state_code'] != ev['venue_state_code']:
        raise ApiError('ERR_JURISDICTION_MISMATCH', 422, 'Bartender jurisdiction mismatch')

    # Double-booking with 90-min travel buffer on both sides
    ns = parse_dt(shift_start)
    ne = parse_dt(shift_end)
    buffer = 90 * 60
    dstart = ns.timestamp() - buffer
    dend = ne.timestamp() + buffer
    for other in DB['assignments'].values():
        if other['bartender_id'] != bartender_id:
            continue
        if other['status'] in ('COMPLETED', 'CANCELLED', 'NO_SHOW'):
            continue
        os_ = parse_dt(other['shift_start']).timestamp()
        oe = parse_dt(other['shift_end']).timestamp()
        if not (oe <= dstart or dend <= os_):
            raise ApiError('ERR_BARTENDER_DOUBLE_BOOKED', 409, 'Bartender double-booked')

    if bartender['availability_status'] == 'INACTIVE':
        raise ApiError('ERR_BARTENDER_UNAVAILABLE', 409, 'Bartender unavailable')

    if role_on_event == 'LEAD':
        strict, _ = reliability(bartender_id)
        if strict < 70:
            raise ApiError('ERR_INSUFFICIENT_RELIABILITY', 422, 'Insufficient reliability for LEAD')

    rec = base_record()
    rec.update({
        'event_id': eid,
        'bartender_id': bartender_id,
        'shift_start': shift_start,
        'shift_end': shift_end,
        'role_on_event': role_on_event,
        'cancelled_by': None,
        'status': 'PROPOSED',
    })
    compute_shift(rec, bartender)
    DB['assignments'][rec['id']] = rec

    bartender['availability_status'] = 'ENGAGED'
    touch(bartender)
    touch(ev)  # staffing view changed; advances Event.version

    return success(ser(rec), 'object', 201)


@app.route('/assignments', methods=['GET'])
def list_assignments():
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'Bartender'})
    items = list(DB['assignments'].values())
    bid = request.args.get('bartender_id')
    if bid is not None:
        items = [a for a in items if a['bartender_id'] == bid]
    ev_id = request.args.get('event_id')
    if ev_id is not None:
        items = [a for a in items if a['event_id'] == ev_id]
    st = request.args.get('status')
    if st is not None:
        items = [a for a in items if a['status'] == st]
    return paginate_response(items, ser)


@app.route('/assignments/<aid>', methods=['GET'])
def read_assignment(aid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'Bartender'})
    a = get_assignment(aid)
    return success(ser(a), 'object', 200)


@app.route('/assignments/<aid>/confirm', methods=['POST'])
def confirm_assignment(aid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    a = get_assignment(aid)
    if a['status'] != 'PROPOSED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Assignment not in PROPOSED')
    ev = DB['events'].get(a['event_id'])
    if not ev or ev['compliance_posture'] != 'CLEARED':
        raise ApiError('ERR_COMPLIANCE_NOT_CLEARED', 409, 'Compliance not cleared')
    a['status'] = 'CONFIRMED'
    touch(a)
    return success(ser(a), 'object', 200)


@app.route('/assignments/<aid>/check-in', methods=['POST'])
def checkin_assignment(aid):
    uid, role = require_auth()
    require_role(role, {'Bartender'})
    a = get_assignment(aid)
    if a['bartender_id'] != uid:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'Not the assigned bartender')
    if a['status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Assignment not in CONFIRMED')
    a['status'] = 'CHECKED_IN'
    touch(a)
    return success(ser(a), 'object', 200)


@app.route('/assignments/<aid>/cancel', methods=['POST'])
def cancel_assignment(aid):
    uid, role = require_auth()
    require_role(role, {'Coordinator', 'Bartender'})
    a = get_assignment(aid)
    if role == 'Bartender' and a['bartender_id'] != uid:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'Not the assigned bartender')
    if a['status'] not in ('PROPOSED', 'CONFIRMED'):
        raise ApiError('ERR_INVALID_STATE', 409, 'Assignment cannot be cancelled from its current state')
    a['status'] = 'CANCELLED'
    a['cancelled_by'] = 'COORDINATOR' if role == 'Coordinator' else 'BARTENDER'
    touch(a)
    touch_bartender_by_id(a['bartender_id'])
    return success(ser(a), 'object', 200)


@app.route('/assignments/<aid>/no-show', methods=['POST'])
def noshow_assignment(aid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    a = get_assignment(aid)
    if a['status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Assignment not in CONFIRMED')
    a['status'] = 'NO_SHOW'
    a['cancelled_by'] = 'SYSTEM'
    touch(a)
    touch_bartender_by_id(a['bartender_id'])
    return success(ser(a), 'object', 200)


# =============================================================================
# Kit reservations
# =============================================================================


@app.route('/events/<eid>/kit-reservations', methods=['POST'])
def create_kit_reservation(eid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    ev = get_event(eid)
    body = body_json()

    kit_id = body.get('kit_id')
    if kit_id is not None and kit_id not in DB['bar_kits']:
        raise ApiError('ERR_BARKIT_NOT_FOUND', 404, 'Bar kit not found')

    kit_id = req_str(body, 'kit_id')
    reserve_start = req_datetime(body, 'reserve_start')
    reserve_end = req_datetime(body, 'reserve_end')
    if not parse_dt(reserve_end) > parse_dt(reserve_start):
        raise ApiError('ERR_VALIDATION', 400, 'reserve_end must be strictly after reserve_start')

    # No-buffer half-open overlap check for the same kit
    ns = parse_dt(reserve_start).timestamp()
    ne = parse_dt(reserve_end).timestamp()
    for other in DB['kit_reservations'].values():
        if other['kit_id'] != kit_id:
            continue
        if other['status'] in ('RETURNED', 'RELEASED'):
            continue
        os_ = parse_dt(other['reserve_start']).timestamp()
        oe = parse_dt(other['reserve_end']).timestamp()
        if ns < oe and os_ < ne:
            raise ApiError('ERR_KIT_DOUBLE_BOOKED', 409, 'Bar kit double-booked')

    rec = base_record()
    rec.update({
        'event_id': eid,
        'kit_id': kit_id,
        'reserve_start': reserve_start,
        'reserve_end': reserve_end,
        'items_checked_out': 0,
        'status': 'RESERVED',
    })
    DB['kit_reservations'][rec['id']] = rec
    return success(ser(rec), 'object', 201)


@app.route('/kit-reservations', methods=['GET'])
def list_kit_reservations():
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator'})
    items = list(DB['kit_reservations'].values())
    kid = request.args.get('kit_id')
    if kid is not None:
        items = [r for r in items if r['kit_id'] == kid]
    ev_id = request.args.get('event_id')
    if ev_id is not None:
        items = [r for r in items if r['event_id'] == ev_id]
    st = request.args.get('status')
    if st is not None:
        items = [r for r in items if r['status'] == st]
    return paginate_response(items, ser)


@app.route('/kit-reservations/<kid>', methods=['GET'])
def read_kit_reservation(kid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator'})
    r = get_reservation(kid)
    return success(ser(r), 'object', 200)


@app.route('/kit-reservations/<kid>/deploy', methods=['POST'])
def deploy_kit(kid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    r = get_reservation(kid)
    if r['status'] != 'RESERVED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Reservation not in RESERVED')
    ev = DB['events'].get(r['event_id'])
    if not ev or ev['booking_status'] != 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 409, 'Event not IN_PROGRESS')
    kit = DB['bar_kits'].get(r['kit_id'])
    r['items_checked_out'] = kit['glassware_count'] if kit else 0
    r['status'] = 'DEPLOYED'
    touch(r)
    return success(ser(r), 'object', 200)


@app.route('/kit-reservations/<kid>/return', methods=['POST'])
def return_kit(kid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    r = get_reservation(kid)
    if r['status'] != 'DEPLOYED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Reservation not in DEPLOYED')
    r['status'] = 'RETURNED'
    touch(r)
    return success(ser(r), 'object', 200)


@app.route('/kit-reservations/<kid>/release', methods=['POST'])
def release_kit(kid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    r = get_reservation(kid)
    if r['status'] != 'RESERVED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Reservation not in RESERVED')
    r['status'] = 'RELEASED'
    touch(r)
    return success(ser(r), 'object', 200)


# =============================================================================
# Inventory plan
# =============================================================================


@app.route('/events/<eid>/inventory-plan', methods=['POST'])
def generate_inventory_plan(eid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    ev = get_event(eid)
    pkg = DB['packages'][ev['package_id']]
    values = compute_inventory(ev, pkg)

    existing = None
    for plan in DB['inventory_plans'].values():
        if plan['event_id'] == eid:
            existing = plan
            break

    if existing is not None:
        existing.update(values)
        existing['status'] = 'GENERATED'
        touch(existing)
        rec = existing
    else:
        rec = base_record()
        rec['event_id'] = eid
        rec.update(values)
        rec['status'] = 'GENERATED'
        DB['inventory_plans'][rec['id']] = rec

    return success(ser(rec), 'object', 201)


@app.route('/events/<eid>/inventory-plan', methods=['GET'])
def list_inventory_plan(eid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    items = [p for p in DB['inventory_plans'].values() if p['event_id'] == eid]
    return paginate_response(items, ser)


# =============================================================================
# Menu items
# =============================================================================


@app.route('/events/<eid>/menu-items', methods=['POST'])
def create_menu_item(eid):
    uid, role = require_auth()
    require_role(role, {'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    body = body_json()
    rec = base_record()
    rec['event_id'] = eid
    rec['name'] = req_str(body, 'name')
    rec['drink_type'] = req_enum(body, 'drink_type', {'BEER', 'WINE', 'COCKTAIL', 'MOCKTAIL'})
    rec['spirit_base'] = opt_enum(body, 'spirit_base',
                                  {'VODKA', 'GIN', 'WHISKEY', 'RUM', 'TEQUILA', 'NONE'}, 'NONE')
    rec['is_signature'] = opt_bool(body, 'is_signature', False)
    rec['abv_pct'] = req_num(body, 'abv_pct', minimum=0)
    DB['menu_items'][rec['id']] = rec
    return success(ser(rec), 'object', 201)


@app.route('/events/<eid>/menu-items', methods=['GET'])
def list_menu_items(eid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator', 'Client'})
    ev = get_event(eid)
    check_event_owner(role, uid, ev)
    items = [m for m in DB['menu_items'].values() if m['event_id'] == eid]
    return paginate_response(items, ser)


# =============================================================================
# Breakage reports
# =============================================================================


@app.route('/events/<eid>/breakage-reports', methods=['POST'])
def create_breakage_report(eid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    ev = get_event(eid)
    body = body_json()

    kit_id = body.get('kit_id')
    if kit_id is not None and kit_id not in DB['bar_kits']:
        raise ApiError('ERR_BARKIT_NOT_FOUND', 404, 'Bar kit not found')

    kit_id = req_str(body, 'kit_id')
    items_broken = req_int(body, 'items_broken', minimum=0)
    items_returned = req_int(body, 'items_returned', minimum=0)

    # Requires a RETURNED KitReservation for (event_id, kit_id)
    returned_res = None
    for r in DB['kit_reservations'].values():
        if r['event_id'] == eid and r['kit_id'] == kit_id and r['status'] == 'RETURNED':
            returned_res = r
            break
    if returned_res is None:
        raise ApiError('ERR_KIT_NOT_RETURNED', 409, 'No returned kit reservation for this event/kit')

    baseline = returned_res['items_checked_out']
    if items_broken + items_returned != baseline:
        raise ApiError('ERR_BREAKAGE_COUNT_MISMATCH', 422, 'Glassware counts do not conserve')

    rec = base_record()
    rec.update({
        'event_id': eid,
        'kit_id': kit_id,
        'items_broken': items_broken,
        'items_returned': items_returned,
        'items_checked_out': baseline,
        'breakage_fee_cents': None,
        'deposit_refund_cents': None,
        'status': 'DRAFT',
    })
    DB['breakage_reports'][rec['id']] = rec
    return success(ser(rec), 'object', 201)


@app.route('/breakage-reports', methods=['GET'])
def list_breakage_reports():
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator'})
    items = list(DB['breakage_reports'].values())
    kid = request.args.get('kit_id')
    if kid is not None:
        items = [r for r in items if r['kit_id'] == kid]
    ev_id = request.args.get('event_id')
    if ev_id is not None:
        items = [r for r in items if r['event_id'] == ev_id]
    return paginate_response(items, ser)


@app.route('/breakage-reports/<bid>', methods=['GET'])
def read_breakage_report(bid):
    uid, role = require_auth()
    require_role(role, {'PlatformAdmin', 'Coordinator'})
    r = get_breakage(bid)
    return success(ser(r), 'object', 200)


@app.route('/breakage-reports/<bid>/settle', methods=['POST'])
def settle_breakage_report(bid):
    uid, role = require_auth()
    require_role(role, {'Coordinator'})
    r = get_breakage(bid)
    if r['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Breakage report not in DRAFT')

    baseline = r['items_checked_out']
    free_allowance = dceil(D(baseline) * Decimal('0.02'))
    chargeable = max(0, r['items_broken'] - free_allowance)
    fee = chargeable * 500

    ev = DB['events'].get(r['event_id'])
    deposit_due = ev['deposit_due_cents'] if ev else 0
    deposit_refund = max(0, deposit_due - fee)

    r['breakage_fee_cents'] = fee
    r['deposit_refund_cents'] = deposit_refund
    r['status'] = 'SETTLED'
    touch(r)

    if fee > 0 and ev:
        create_payment(ev['id'], 'BREAKAGE_CHARGE', fee, 'SYSTEM')
        recompute_payment_status(ev)
        touch(ev)

    return success(ser(r), 'object', 200)


# =============================================================================
# Entry point
# =============================================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, threaded=True)
