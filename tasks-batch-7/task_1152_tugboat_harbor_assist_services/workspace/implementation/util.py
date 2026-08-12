"""Envelope, auth, datetime, field-extraction and pagination helpers."""
import math
import random
import re
import string
from datetime import datetime, timezone

from flask import jsonify, request

from db import store, now
from errors import ApiError

ROLES = {
    "PortAdmin", "VesselAgent", "PortDispatcher", "Pilot",
    "TugCaptain", "MarineSurveyor", "ClaimsAdjuster",
}

_DT_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?'
    r'(Z|z|[+-]\d{2}:?\d{2})?$'
)


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    date, tm, frac, tz = m.groups()
    frac = (frac[:6].ljust(6, '0')) if frac else '000000'
    if tz in (None, 'Z', 'z'):
        off = '+00:00'
    else:
        t = tz.replace(':', '')
        off = t[:3] + ':' + t[3:]
    try:
        dt = datetime.fromisoformat(f'{date}T{tm}.{frac}{off}')
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def fmt_opt(dt):
    return None if dt is None else fmt_dt(dt)


def half_open_overlap(a_start, a_end, b_start, b_end):
    """True iff [a_start,a_end) and [b_start,b_end) share an instant."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------- envelope

def _meta():
    rid = 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=20))
    return {'api_request_id': rid, 'api_request_timestamp': fmt_dt(now())}


def ok_object(obj, status=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': obj}), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total_count
    meta['has_more'] = (offset + len(items)) < total_count
    return jsonify({'meta': meta, 'response_type': 'array', 'data': items}), 200


def error_response(e):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': e.error_id, 'message': e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------- auth

def authenticate():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401,
                       'X-User-ID / X-User-Role header missing or role not recognized')
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError('ERR_FORBIDDEN', 403,
                       f'Role {role} is not authorized for this operation')


def not_found(what='resource'):
    raise ApiError('ERR_NOT_FOUND', 404, f'{what} not found')


# ---------------------------------------------------------------- body checks

class Check:
    """Collects deferred shape errors (PRD §2.8 stages 27/28 run last)."""

    def __init__(self):
        self.bad_request = False
        self.bad_enum = False

    def raise_deferred(self):
        if self.bad_request:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'Required input field missing or mistyped')
        if self.bad_enum:
            raise ApiError('ERR_INVALID_ENUM', 400,
                           'Enum field carries a value outside its declared set')


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {'__non_dict__': True}
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))))


def get_str(body, key, c, required=True):
    if key not in body or body[key] is None:
        if required:
            c.bad_request = True
        return None
    if not isinstance(body[key], str):
        c.bad_request = True
        return None
    return body[key]


def get_int(body, key, c, required=True, lo=None, lo_exclusive=False):
    if key not in body or body[key] is None:
        if required:
            c.bad_request = True
        return None
    v = body[key]
    if not is_int(v):
        c.bad_request = True
        return None
    if lo is not None:
        if lo_exclusive and v <= lo:
            c.bad_request = True
            return None
        if not lo_exclusive and v < lo:
            c.bad_request = True
            return None
    return v


def get_num(body, key, c, required=True, lo=None, lo_exclusive=False):
    if key not in body or body[key] is None:
        if required:
            c.bad_request = True
        return None
    v = body[key]
    if not is_num(v):
        c.bad_request = True
        return None
    v = float(v)
    if lo is not None:
        if lo_exclusive and v <= lo:
            c.bad_request = True
            return None
        if not lo_exclusive and v < lo:
            c.bad_request = True
            return None
    return v


def get_dt(body, key, c, required=True):
    if key not in body or body[key] is None:
        if required:
            c.bad_request = True
        return None
    dt = parse_dt(body[key])
    if dt is None:
        c.bad_request = True
    return dt


def get_bool(body, key, c, required=True):
    if key not in body or body[key] is None:
        if required:
            c.bad_request = True
        return None
    if not isinstance(body[key], bool):
        c.bad_request = True
        return None
    return body[key]


def get_enum(body, key, allowed, c, required=True):
    if key not in body or body[key] is None:
        if required:
            c.bad_request = True
        return None
    v = body[key]
    if not isinstance(v, str):
        c.bad_request = True
        return None
    if v not in allowed:
        c.bad_enum = True
        return None
    return v


def get_occ(body, key, current_version, c):
    """OCC guard (stage 5): missing/mistyped defers to shape stage; mismatch 412."""
    if key not in body or body[key] is None or not is_int(body[key]):
        c.bad_request = True
        return
    if body[key] != current_version:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'Stale version: the resource has been modified since it was read')


# ---------------------------------------------------------------- pagination

def parse_pagination(c):
    limit, offset = 10, 0
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            c.bad_request = True
        else:
            if limit < 1 or limit > 100:
                c.bad_request = True
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            c.bad_request = True
        else:
            if offset < 0:
                c.bad_request = True
    return limit, offset


def check_enum_filter(param, allowed, c):
    v = request.args.get(param)
    if v is not None and v not in allowed:
        c.bad_enum = True
        return None
    return v


def page_slice(records, limit, offset):
    ordered = sorted(records, key=lambda r: (r['created_at'], r['_seq']))
    total = len(ordered)
    return ordered[offset:offset + limit], total


def store_get(collection, raw_id, c, what='resource'):
    """Existence (stage 4). None/mistyped id defers to shape; missing id 404s."""
    if raw_id is None:
        c.bad_request = True
        return None
    if not isinstance(raw_id, str):
        c.bad_request = True
        return None
    rec = collection.get(raw_id)
    if rec is None:
        not_found(what)
    return rec
