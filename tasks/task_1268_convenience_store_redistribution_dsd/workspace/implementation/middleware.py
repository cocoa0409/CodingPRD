"""Auth header extraction, role checks, body parsing, and field validators."""
import json
from datetime import datetime, timezone

from flask import request

from errors import (
    ApiError, unauthenticated, forbidden, validation,
)

ROLES = ('WholesaleAdmin', 'SalesRep', 'StoreManager', 'RouteDriver', 'CreditManager')


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present, role recognized."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    return uid, role


def require_role(role, allowed):
    """Priority 2: role admitted for this endpoint."""
    if role not in allowed:
        raise forbidden('role %s is not permitted for this endpoint' % role)


def check_store_ownership(uid, role, retailer_id):
    """StoreManager is entity-backed: X-User-ID must equal the retailer FK."""
    if role == 'StoreManager' and uid != retailer_id:
        raise forbidden('store manager may only access their own store resources')


def parse_body():
    """Priority 1: body must be well-formed JSON object (empty body == {})."""
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise validation('request body is not well-formed JSON')
    if not isinstance(data, dict):
        raise validation('request body must be a JSON object')
    return data


def _bad(name):
    raise validation("field '%s' is missing or has an invalid type" % name)


def req_raw(body, name):
    if name not in body or body[name] is None:
        _bad(name)
    return body[name]


def req_str(body, name):
    v = req_raw(body, name)
    if not isinstance(v, str):
        _bad(name)
    return v


def opt_str(body, name, nullable=True):
    if name not in body or body[name] is None:
        if name in body and body[name] is None and not nullable:
            _bad(name)
        return None
    v = body[name]
    if not isinstance(v, str):
        _bad(name)
    return v


def req_int(body, name, minimum=None, maximum=None):
    v = req_raw(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name)
    if minimum is not None and v < minimum:
        _bad(name)
    if maximum is not None and v > maximum:
        _bad(name)
    return v


def opt_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name)
    if minimum is not None and v < minimum:
        _bad(name)
    if maximum is not None and v > maximum:
        _bad(name)
    return v


def req_bool(body, name):
    v = req_raw(body, name)
    if not isinstance(v, bool):
        _bad(name)
    return v


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        _bad(name)
    return v


def req_num(body, name, minimum=None, exclusive_minimum=False):
    v = req_raw(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name)
    if minimum is not None:
        if exclusive_minimum and not v > minimum:
            _bad(name)
        if not exclusive_minimum and v < minimum:
            _bad(name)
    return v


def req_enum(body, name, allowed):
    v = req_raw(body, name)
    if not isinstance(v, str) or v not in allowed:
        _bad(name)
    return v


def opt_enum(body, name, allowed):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        _bad(name)
    return v


def parse_date_str(v, name):
    if not isinstance(v, str):
        _bad(name)
    try:
        return datetime.strptime(v, '%Y-%m-%d').date()
    except ValueError:
        _bad(name)


def req_date(body, name):
    v = req_raw(body, name)
    parse_date_str(v, name)
    return v


def opt_date(body, name):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    parse_date_str(v, name)
    return v


def parse_datetime_str(v, name):
    if not isinstance(v, str):
        _bad(name)
    t = v.strip()
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _bad(name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, name):
    v = req_raw(body, name)
    parse_datetime_str(v, name)
    return v


def parse_query_bool(raw, name):
    low = raw.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    raise validation("query parameter '%s' must be true or false" % name)


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    args = request.args
    limit = 10
    offset = 0
    if 'limit' in args:
        raw = args.get('limit')
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise validation("query parameter 'limit' must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise validation("query parameter 'limit' must be between 1 and 100")
    if 'offset' in args:
        raw = args.get('offset')
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise validation("query parameter 'offset' must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise validation("query parameter 'offset' must be >= 0")
    return limit, offset


def list_page(records, serializer, limit, offset):
    """Sort by created_at ascending (insertion sequence is equivalent and
    strictly monotonic), then apply limit/offset windowing."""
    items = sorted(records, key=lambda r: r['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return [serializer(r) for r in page], total
