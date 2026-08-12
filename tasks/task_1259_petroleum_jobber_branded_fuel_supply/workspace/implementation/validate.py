"""Pipeline stage 3: request body shape validation + parsing helpers."""
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError, ERR_VALIDATION_FAILED


def _fail(msg):
    raise ApiError(ERR_VALIDATION_FAILED, 400, msg)


def parse_date_str(s):
    """Strict YYYY-MM-DD -> date, else None."""
    if not isinstance(s, str) or len(s) != 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_dt_str(s):
    """ISO 8601 datetime ('Z' or offset allowed) -> aware UTC datetime."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith('Z') or t.endswith('z'):
        t = t[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_body():
    """JSON object body or None; malformed JSON is a shape failure."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        _fail('Request body must be a JSON object')
    return body


def validate_body(body, spec):
    """Validate body against spec: required fields, no unknown fields,
    type checks, enum membership, numeric bounds. Returns cleaned dict."""
    unknown = set(body) - set(spec)
    if unknown:
        _fail('Unknown field(s): {}'.format(', '.join(sorted(unknown))))
    out = {}
    for name, rules in spec.items():
        if name not in body:
            if rules.get('required'):
                _fail('Missing required field: {}'.format(name))
            continue
        val = body[name]
        if val is None:
            if rules.get('nullable'):
                out[name] = None
                continue
            _fail('Field may not be null: {}'.format(name))
        _check(name, val, rules)
        out[name] = val
    return out


def _check(name, val, rules):
    t = rules['type']
    if t == 'int':
        if isinstance(val, bool) or not isinstance(val, int):
            _fail('Field must be an integer: {}'.format(name))
    elif t == 'number':
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            _fail('Field must be a number: {}'.format(name))
    elif t == 'str':
        if not isinstance(val, str):
            _fail('Field must be a string: {}'.format(name))
    elif t == 'date':
        if parse_date_str(val) is None:
            _fail('Field must be an ISO date (YYYY-MM-DD): {}'.format(name))
    elif t == 'datetime':
        if parse_dt_str(val) is None:
            _fail('Field must be an ISO 8601 datetime: {}'.format(name))
    elif t == 'enum':
        if not isinstance(val, str) or val not in rules['enum']:
            _fail('Field must be one of {}: {}'.format(rules['enum'], name))
    elif t == 'array':
        if not isinstance(val, list):
            _fail('Field must be an array: {}'.format(name))
    elif t == 'bool':
        if not isinstance(val, bool):
            _fail('Field must be a boolean: {}'.format(name))
    if 'gt' in rules and not (val > rules['gt']):
        _fail('Field out of range: {}'.format(name))
    if 'ge' in rules and not (val >= rules['ge']):
        _fail('Field out of range: {}'.format(name))
    if 'le' in rules and not (val <= rules['le']):
        _fail('Field out of range: {}'.format(name))


def parse_pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0)."""
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _fail('limit must be an integer')
        if limit < 1 or limit > 100:
            _fail('limit must be between 1 and 100')
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _fail('offset must be an integer')
        if offset < 0:
            _fail('offset must be >= 0')
    return limit, offset


def apply_filters(items, filters):
    """Exact-match equality filters; None values filter on JSON-null fields."""
    for key, want in filters.items():
        if want is None:
            continue
        items = [r for r in items if r.get(key) == want]
    return items


def sorted_default(items):
    """Default list order: created_at ascending (insertion seq tie-break)."""
    return sorted(items, key=lambda r: (r['created_at'], r['_seq']))


def list_response(items, serialize):
    from response import ok_list
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)
