import re
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, bad_request


def now():
    from db import db
    return db.clock


def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def fmt_date(dt):
    """PRD section 2.5: calendar-date fields use day precision at midnight UTC,
    rendered as 00:00:00Z (no fractional digits — that form is reserved by
    sections 2.2/2.4 for server-stamped instants)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT00:00:00Z')


def midnight(dt):
    """Normalize an instant to midnight UTC (PRD 2.5 day-precision fields)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_dt(value, field):
    if isinstance(value, str):
        v = value.strip()
        try:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
                return datetime.strptime(v, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    bad_request(f'{field} must be an ISO 8601 timestamp')


def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x):
    """round half up to integer cents"""
    return int(D(x).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def to_cwt(lbs):
    return -(-int(lbs) // 100)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return 'req_' + ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(22))


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    data = request.get_data(cache=True)
    if data is None or len(data) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        bad_request('request body must be valid JSON')
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad_request('request body must be a JSON object')
    return body


def _coerce(name, v, kind, extra):
    if kind == 'str':
        if not isinstance(v, str):
            bad_request(f'field {name} must be a string')
        return v
    if kind == 'int':
        if isinstance(v, bool) or not isinstance(v, int):
            bad_request(f'field {name} must be an integer')
        if extra is not None:
            lo, hi = extra
            if lo is not None and v < lo:
                bad_request(f'field {name} must be >= {lo}')
            if hi is not None and v > hi:
                bad_request(f'field {name} must be <= {hi}')
        return v
    if kind == 'num':
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            bad_request(f'field {name} must be a number')
        return v
    if kind == 'bool':
        if not isinstance(v, bool):
            bad_request(f'field {name} must be a boolean')
        return v
    if kind == 'datetime':
        return parse_dt(v, name)
    if kind == 'enum':
        if not isinstance(v, str) or v not in extra:
            bad_request(f'field {name} must be one of {sorted(extra)}')
        return v
    if kind == 'enum_int':
        if isinstance(v, bool) or not isinstance(v, int) or v not in extra:
            bad_request(f'field {name} must be one of {sorted(extra)}')
        return v
    if kind == 'list':
        if not isinstance(v, list):
            bad_request(f'field {name} must be an array')
        return v
    if kind == 'any':
        return v
    bad_request(f'internal: unknown kind {kind}')


def check_body(body, fields):
    """fields: list of (name, kind, required, extra). Rejects unknown fields."""
    if body is None:
        body = {}
    if not isinstance(body, dict):
        bad_request('request body must be a JSON object')
    specs = {f[0]: (f[1], f[2], f[3] if len(f) > 3 else None) for f in fields}
    for k in body:
        if k not in specs:
            bad_request(f'unknown field: {k}')
    vals = {}
    for name, (kind, required, extra) in specs.items():
        if name not in body:
            if required:
                bad_request(f'missing required field: {name}')
            continue
        v = body[name]
        if v is None:
            bad_request(f'field {name} must not be null')
        vals[name] = _coerce(name, v, kind, extra)
    return vals


def check_ref_exists(body, field, collection):
    """Existence of a body-referenced id (pipeline stage 4). Only fires when the
    raw value is present and string-typed; type/presence problems are left to
    check_body (stage 5)."""
    v = body.get(field)
    if isinstance(v, str) and v not in collection:
        raise ApiError('ERR_NOT_FOUND', 404, f'{field} not found')


def get_path(collection, ident):
    obj = collection.get(ident)
    if obj is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'resource not found')
    return obj


def pagination_params():
    from flask import request
    raw_limit = request.args.get('limit', '10')
    raw_offset = request.args.get('offset', '0')
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        bad_request('limit and offset must be integers')
    if limit < 1 or limit > 100:
        bad_request('limit must be between 1 and 100')
    if offset < 0:
        bad_request('offset must be >= 0')
    return limit, offset


def apply_list(collection, filters, view, lim_off=None):
    limit, offset = lim_off if lim_off else pagination_params()
    items = [e for e in collection.values() if all(f(e) for f in filters)]
    items.sort(key=lambda e: e['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    from response import ok_list
    return ok_list([view(e) for e in page], limit, offset, total)
