"""Priority-0 request-shape validation: unknown fields, missing required
fields, wrong types, non-positive quantities, invalid enum members."""
from flask import request

from errors import bad_request
from util import parse_date, parse_dt


def get_body():
    """Return the JSON object body; {} when absent. 400 on malformed JSON."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b'':
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None or not isinstance(data, dict):
        raise bad_request('Request body must be a JSON object')
    return data


def validate(body, spec):
    """spec: list of (name, kind, required, opts). Returns dict of values.

    Optional fields explicitly passed as null fall back to their default.
    """
    names = {s[0] for s in spec}
    for k in body:
        if k not in names:
            raise bad_request(f'Unknown field: {k}')
    out = {}
    for name, kind, required, opts in spec:
        if name not in body or body[name] is None:
            if required:
                raise bad_request(f'Missing required field: {name}')
            out[name] = opts.get('default')
            continue
        v = body[name]
        if kind == 'str':
            if not isinstance(v, str):
                raise bad_request(f'Field {name} must be a string')
            out[name] = v
        elif kind == 'int':
            if isinstance(v, bool) or not isinstance(v, int):
                raise bad_request(f'Field {name} must be an integer')
            if opts.get('positive') and v <= 0:
                raise bad_request(f'Field {name} must be greater than zero')
            if opts.get('nonnegative') and v < 0:
                raise bad_request(f'Field {name} must be zero or greater')
            out[name] = v
        elif kind == 'num':
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise bad_request(f'Field {name} must be a number')
            if opts.get('positive') and not v > 0:
                raise bad_request(f'Field {name} must be greater than zero')
            if opts.get('nonnegative') and v < 0:
                raise bad_request(f'Field {name} must be zero or greater')
            out[name] = v
        elif kind == 'bool':
            if not isinstance(v, bool):
                raise bad_request(f'Field {name} must be a boolean')
            out[name] = v
        elif kind == 'enum':
            if not isinstance(v, str) or v not in opts['values']:
                raise bad_request(f'Field {name} must be one of {opts["values"]}')
            out[name] = v
        elif kind == 'date':
            d = parse_date(v)
            if d is None:
                raise bad_request(f'Field {name} must be an ISO date (YYYY-MM-DD)')
            out[name] = d
        elif kind == 'datetime':
            dt = parse_dt(v)
            if dt is None:
                raise bad_request(f'Field {name} must be an ISO 8601 datetime')
            out[name] = dt
        elif kind == 'str_list':
            if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
                raise bad_request(f'Field {name} must be a list of strings')
            out[name] = v
        else:  # pragma: no cover
            raise AssertionError(f'unknown kind {kind}')
    return out


def parse_pagination(args):
    """limit/offset query params per PRD §2.3. Returns (limit, offset)."""
    raw_limit = args.get('limit')
    raw_offset = args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request('limit must be an integer')
        if str(raw_limit).strip() != str(limit):
            raise bad_request('limit must be an integer')
        if limit < 1 or limit > 100:
            raise bad_request('limit must be between 1 and 100')
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request('offset must be an integer')
        if str(raw_offset).strip() != str(offset):
            raise bad_request('offset must be an integer')
        if offset < 0:
            raise bad_request('offset must be zero or greater')
    return limit, offset
