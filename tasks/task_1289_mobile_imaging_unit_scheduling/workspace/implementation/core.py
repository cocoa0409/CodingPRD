"""Core primitives: logical clock, in-memory store, response envelope, errors,
auth, field validation, pagination. All names follow SCAFFOLD.yaml / PRD.md."""
import re
import uuid
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------- logical clock
# Startup default is exactly 2026-08-01T00:00:00Z (never wall clock).
_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _CLOCK


def set_clock(dt):
    global _CLOCK
    _CLOCK = dt


def clock_date():
    return _CLOCK.date()


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{:03d}Z'.format(dt.microsecond // 1000)


def now_iso():
    return fmt_dt(_CLOCK)


# ---------------------------------------------------------------- errors
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def invalid_request(msg):
    fail('ERR_INVALID_REQUEST', 400, msg)


# ---------------------------------------------------------------- store
COLLECTIONS = [
    'facilities', 'units', 'contracts', 'route_plans', 'site_days',
    'appointments', 'technologists', 'staffing', 'legs', 'checklists',
    'breakdowns', 'dose_records', 'accreditations', 'statements', 'studies',
]
DB = {c: {} for c in COLLECTIONS}
_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_entity(coll, fields, common=True):
    e = dict(fields)
    e['id'] = str(uuid.uuid4())
    e['created_at'] = now_iso()
    if common:
        e['updated_at'] = e['created_at']
        e['version'] = 1
    e['_seq'] = next_seq()
    DB[coll][e['id']] = e
    return e


def touch(e):
    e['updated_at'] = now_iso()
    e['version'] = e.get('version', 1) + 1


def get(coll, rid, error_id):
    e = DB[coll].get(rid)
    if e is None:
        fail(error_id, 404, 'Resource not found: {}'.format(rid))
    return e


def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith('_')}


def sorted_items(coll):
    return sorted(DB[coll].values(), key=lambda e: (e['created_at'], e['_seq']))


# ---------------------------------------------------------------- envelope
def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex[:24],
        'api_request_timestamp': now_iso(),
    }


def ok_object(data, code=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), code


def ok_list(items, serializer=None):
    serializer = serializer or serialize
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    m = _meta()
    m['limit'] = limit
    m['offset'] = offset
    m['total_count'] = total
    m['has_more'] = (offset + len(page)) < total
    return jsonify({'meta': m, 'response_type': 'array',
                    'data': [serializer(e) for e in page]}), 200


def error_response(e):
    return jsonify({
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': e.error_id, 'message': e.message},
    }), e.http_status


# ---------------------------------------------------------------- pagination
_INT_RE = re.compile(r'^-?\d+$')


def pagination_params():
    args = request.args
    raw_limit = args.get('limit')
    raw_offset = args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        if not _INT_RE.match(raw_limit):
            invalid_request('limit must be an integer')
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            invalid_request('limit must be between 1 and 100')
    if raw_offset is None:
        offset = 0
    else:
        if not _INT_RE.match(raw_offset):
            invalid_request('offset must be an integer')
        offset = int(raw_offset)
        if offset < 0:
            invalid_request('offset must be >= 0')
    return limit, offset


def apply_filters(items, mapping):
    """mapping: query param -> entity field. Exact match; 'null' matches None."""
    out = []
    for e in items:
        keep = True
        for qp, field in mapping.items():
            val = request.args.get(qp)
            if val is None:
                continue
            cur = e.get(field)
            if cur is None:
                if val != 'null':
                    keep = False
                    break
            elif str(cur) != val:
                keep = False
                break
        if keep:
            out.append(e)
    return out


# ---------------------------------------------------------------- auth
ROLES = {'OperationsDirector', 'FacilityCoordinator', 'Technologist',
         'ReadingRadiologist', 'ComplianceOfficer'}


def auth(allowed=None):
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        fail('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 400,
             'X-User-ID and X-User-Role headers must be present and role declared')
    if allowed is not None and role not in allowed:
        fail('ERR_INSUFFICIENT_PERMISSIONS', 403,
             'Role {} is not permitted for this endpoint'.format(role))
    return uid, role


# ---------------------------------------------------------------- body & fields
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid_request('request body must be a JSON object')
    return data


def _present(d, k):
    return k in d and d[k] is not None


def f_str(d, k, required=True, default=None):
    if not _present(d, k):
        if required:
            invalid_request('missing required field: ' + k)
        return default
    if not isinstance(d[k], str):
        invalid_request('field {} must be a string'.format(k))
    return d[k]


def f_int(d, k, required=True, default=None):
    if not _present(d, k):
        if required:
            invalid_request('missing required field: ' + k)
        return default
    v = d[k]
    if isinstance(v, bool) or not isinstance(v, int):
        invalid_request('field {} must be an integer'.format(k))
    return v


def f_num(d, k, required=True, default=None):
    if not _present(d, k):
        if required:
            invalid_request('missing required field: ' + k)
        return default
    v = d[k]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid_request('field {} must be a number'.format(k))
    return v


def f_bool(d, k, required=True, default=None):
    if not _present(d, k):
        if required:
            invalid_request('missing required field: ' + k)
        return default
    if not isinstance(d[k], bool):
        invalid_request('field {} must be a boolean'.format(k))
    return d[k]


def f_enum(d, k, allowed, required=True, default=None):
    v = f_str(d, k, required=required, default=default)
    if v is None:
        return None
    if v not in allowed:
        invalid_request('field {} must be one of {}'.format(k, sorted(allowed)))
    return v


def f_enum_array(d, k, allowed, required=True, default=None):
    if not _present(d, k):
        if required:
            invalid_request('missing required field: ' + k)
        return default
    v = d[k]
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        invalid_request('field {} must be an array of strings'.format(k))
    for x in v:
        if x not in allowed:
            invalid_request('field {} contains value outside the declared set'.format(k))
    return v


_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def f_date(d, k, required=True, default=None):
    v = f_str(d, k, required=required, default=default)
    if v is None:
        return None
    if not _DATE_RE.match(v):
        invalid_request('field {} must be YYYY-MM-DD'.format(k))
    try:
        date.fromisoformat(v)
    except ValueError:
        invalid_request('field {} is not a valid calendar date'.format(k))
    return v


_TIME_RE = re.compile(r'^([01][0-9]|2[0-3]):[0-5][0-9]$')


def f_time(d, k, required=True, default=None):
    v = f_str(d, k, required=required, default=default)
    if v is None:
        return None
    if not _TIME_RE.match(v):
        invalid_request('field {} must be HH:MM 24h'.format(k))
    return v


# ---------------------------------------------------------------- misc helpers
def to_minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def parse_iso_dt(s):
    if not isinstance(s, str):
        invalid_request('to_iso8601 must be an ISO 8601 string')
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        invalid_request('to_iso8601 is not a valid ISO 8601 datetime')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu_cents(dec):
    """Round half-up to whole cents (integer)."""
    return int(dec.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def dec(v):
    return Decimal(str(v))
