"""Shared validation, parsing, pagination and serialization helpers."""
from flask import request

import errors
from db import parse_dt

SPECIES = {'MARKET_STEER', 'MARKET_SWINE', 'MARKET_LAMB', 'MARKET_GOAT'}
ORGANIZATIONS = {'FFA', 'FOUR_H', 'INDEPENDENT'}
AWARDS = {'NONE', 'GRAND_CHAMPION', 'RESERVE_CHAMPION'}
INSPECTION_RESULTS = {'PASS', 'FAIL', 'QUARANTINE'}
DISPOSITION_TYPES = {'HARVEST', 'RETURN'}
POSTURES = [
    'SETUP', 'ENTRIES_OPEN', 'ENTRIES_LOCKED', 'WEIGH_IN',
    'SHOWING', 'AUCTION', 'SETTLEMENT', 'CLOSED',
]

PLACED_STATUSES = {'CLASSIFIED', 'SHOWN', 'SOLD', 'NOT_SOLD', 'CLEARED'}


def body():
    """Return the JSON request body as a dict; anything else is malformed."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request('Request body must be a JSON object')
    return data


def require(body_dict, field):
    if field not in body_dict or body_dict[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    return body_dict[field]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def require_int(body_dict, field, minimum=None):
    v = require(body_dict, field)
    if not is_int(v):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return v


def require_num(body_dict, field, minimum=None):
    v = require(body_dict, field)
    if not is_num(v):
        raise errors.invalid_request(f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return v


def require_str(body_dict, field):
    v = require(body_dict, field)
    if not isinstance(v, str) or not v:
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return v


def require_enum(body_dict, field, allowed):
    v = require(body_dict, field)
    if v not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def require_dt(body_dict, field):
    v = require(body_dict, field)
    dt = parse_dt(v)
    if dt is None:
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 datetime")
    return dt


def optional_dt(body_dict, field):
    v = body_dict.get(field)
    if v is None:
        return None
    dt = parse_dt(v)
    if dt is None:
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 datetime")
    return dt


def pagination_params():
    """limit/offset per PRD §2.3: limit default 10, valid 1..100; offset default 0."""
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            raise errors.invalid_request('limit must be an integer')
        if limit < 1 or limit > 100:
            raise errors.invalid_request('limit must be between 1 and 100')
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            raise errors.invalid_request('offset must be an integer')
        if offset < 0:
            raise errors.invalid_request('offset must be >= 0')
    return limit, offset


def sorted_created(records):
    """Default list order: created_at ascending; _seq is the stable tie-break."""
    return sorted(records, key=lambda r: (r['created_at'], r['_seq']))


def apply_filters(records, filters):
    """Equality filters over stored fields; None values are skipped."""
    out = []
    for rec in records:
        ok = True
        for field, value in filters.items():
            if value is None:
                continue
            if rec.get(field) != value:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def serialize(rec, dt_fields=()):
    from db import iso
    out = {}
    for k, v in rec.items():
        if k.startswith('_'):
            continue
        if k in dt_fields and v is not None:
            out[k] = iso(v)
        else:
            out[k] = v
    return out
