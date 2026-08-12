"""Shared foundation: in-memory store, logical clock, response envelope,
errors, auth, pagination, and small helpers."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_FLOOR

from flask import request, jsonify

# ---------------------------------------------------------------- errors
ERROR_HTTP = {
    'ERR_UNAUTHENTICATED': 401,
    'ERR_FORBIDDEN': 403,
    'ERR_NOT_FOUND': 404,
    'ERR_INVALID_REQUEST': 400,
    'ERR_INVALID_STATE': 409,
    'ERR_STALE_MEMBER_VERSION': 412,
    'ERR_STALE_FISCAL_YEAR_VERSION': 412,
    'ERR_STALE_CERTIFICATE_VERSION': 412,
    'ERR_COMPLIANCE_GATE': 422,
    'ERR_TEMPORAL_WINDOW': 422,
    'ERR_REFERENTIAL': 422,
    'ERR_CONSTRAINT_VIOLATION': 409,
    'ERR_FISCAL': 422,
    'ERR_FISCAL_BOUNDARY': 422,
    'ERR_DELIVERY_ALREADY_SETTLED': 409,
    'ERR_CYCLE_OVERLAP': 409,
    'ERR_CYCLE_BUDGET_EXCEEDED': 422,
    'ERR_APPOINTMENT_CONFLICT': 409,
    'ERR_ESTATE_WINDOW_NOT_ELAPSED': 422,
    'ERR_CERTIFICATE_FROZEN': 422,
    'ERR_CERTIFICATE_NOT_REDEEMABLE': 422,
    'ERR_DELEGATE_CAP_REACHED': 409,
    'ERR_QUORUM_NOT_MET': 422,
    'ERR_CERTIFICATE_OWNERSHIP': 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = ERROR_HTTP[error_id]


def err(error_id, message):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------- logical clock
_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# ---------------------------------------------------------------- time utils
def iso(dt):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{0:03d}Z'.format(dt.microsecond // 1000)


def parse_dt(value):
    if not isinstance(value, str):
        raise ValueError('not a string')
    s = value.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


GREGORIAN_YEAR_SECONDS = 31556952  # 365.2425 * 86400
MIN_HOLDING_YEARS = 1
APPOINTMENT_SLOT_SECONDS = 1800
ESTATE_CLAIM_WINDOW_DAYS = 90
ESTATE_LAPSE_DAYS = 365
APPEAL_WINDOW_DAYS = 30


def gregorian_years(years):
    return timedelta(seconds=int(Decimal(str(years)) * GREGORIAN_YEAR_SECONDS))


# ---------------------------------------------------------------- ids / meta
def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=20))


def wall_iso():
    return iso(datetime.now(timezone.utc))


# ---------------------------------------------------------------- in-memory store
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


class _DB(object):
    pass


db = _DB()
db.members = {}
db.districts = {}
db.delegates = {}
db.fiscal_years = {}
db.deliveries = {}
db.allocations = {}
db.certificates = {}
db.cycles = {}
db.resolutions = {}
db.redemption_requests = {}
db.estate_claims = {}
db.lots = {}
db.tax_forms = {}
db.disbursements = []  # {certificate_id, member_id, fiscal_year_id, equity_class, amount_cents, at}


def base_fields():
    t = iso(now())
    return {'id': new_id(), 'created_at': t, 'updated_at': t, 'version': 1, '_seq': next_seq()}


def touch(ent):
    ent['updated_at'] = iso(now())
    ent['version'] += 1


def public(ent):
    return {k: v for k, v in ent.items() if not k.startswith('_')}


# ---------------------------------------------------------------- envelope
def success(data, status=200, page=None):
    meta = {'api_request_id': new_request_id(), 'api_request_timestamp': wall_iso()}
    payload = {'meta': meta}
    if page is not None:
        meta.update(page)
        payload['response_type'] = 'array'
    else:
        payload['response_type'] = 'object'
    payload['data'] = data
    return jsonify(payload), status


def error_response(e):
    return jsonify({
        'meta': {'api_request_id': new_request_id(), 'api_request_timestamp': wall_iso()},
        'response_type': 'error',
        'data': {'error_id': e.error_id, 'message': e.message},
    }), e.http_status


# ---------------------------------------------------------------- pagination
def paginate(items):
    items = sorted(items, key=lambda e: (e['created_at'], e['_seq']))
    try:
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        err('ERR_INVALID_REQUEST', 'limit and offset must be integers')
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page_items = items[offset:offset + limit]
    return [public(i) for i in page_items], {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + limit) < total,
    }


# ---------------------------------------------------------------- auth
ROLES = ['CoopAdmin', 'CoopRegistrar', 'CoopAccountant', 'ExternalAuditor',
         'ElevatorOperator', 'CoopTreasurer', 'BoardSecretary', 'Member']


def authn(allowed):
    role = request.headers.get('X-User-Role')
    uid = request.headers.get('X-User-ID')
    if not role or role not in ROLES:
        err('ERR_UNAUTHENTICATED', 'X-User-Role header missing or not a declared role')
    if not uid:
        err('ERR_UNAUTHENTICATED', 'X-User-ID header missing')
    if role == 'Member' and uid not in db.members:
        err('ERR_UNAUTHENTICATED', 'X-User-ID does not reference an existing member')
    if role not in allowed:
        err('ERR_FORBIDDEN', 'Role {0} is not permitted for this endpoint'.format(role))
    return role, uid


def require_own_member(role, uid, member_id):
    if role == 'Member' and uid != member_id:
        err('ERR_FORBIDDEN', 'Members may only access their own resources')


# ---------------------------------------------------------------- request body
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err('ERR_INVALID_REQUEST', 'JSON body must be an object')
    return data


def require(data, *fields):
    for f in fields:
        if f not in data or data[f] is None:
            err('ERR_INVALID_REQUEST', 'Missing required field: {0}'.format(f))


def as_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        err('ERR_INVALID_REQUEST', 'Field {0} must be an integer'.format(field))
    return v


def as_number(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err('ERR_INVALID_REQUEST', 'Field {0} must be a number'.format(field))
    return v


def as_str(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        err('ERR_INVALID_REQUEST', 'Field {0} must be a string'.format(field))
    return v


def as_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        err('ERR_INVALID_REQUEST', 'Field {0} must be a boolean'.format(field))
    return v


def as_dt(data, field):
    v = data.get(field)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        err('ERR_INVALID_REQUEST', 'Field {0} must be an ISO 8601 datetime'.format(field))


# ---------------------------------------------------------------- decimal helpers
def D(x):
    return Decimal(str(x))


def cents_half_up(x):
    return int(x.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- lazy system sweeps
def run_sweeps():
    """Deterministic clock-driven transitions evaluated lazily per request."""
    n = now()
    for c in db.estate_claims.values():
        if c['status'] == 'FILED' and n > parse_dt(c['filed_at']) + timedelta(days=ESTATE_LAPSE_DAYS):
            c['status'] = 'LAPSED'
            touch(c)
    for lot in db.lots.values():
        if lot['status'] == 'NOTIFIED' and n >= parse_dt(lot['escheat_eligible_at']):
            lot['status'] = 'ESCHEAT_PENDING'
            touch(lot)
