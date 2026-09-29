"""Envelope construction, authentication/authorization, pagination and body checks."""

import functools
import random
import string

from flask import jsonify, request

from errors import ApiError, fail
from store import db, iso, parse_date, parse_datetime, rhu, sorted_records

ROLES = (
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
    "Recruiter",
)

_ALNUM = string.ascii_uppercase + string.digits


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": iso(db.now)}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
class Ctx(object):
    __slots__ = ("user_id", "role", "body")

    def __init__(self, user_id, role, body):
        self.user_id = user_id
        self.role = role
        self.body = body


def _parse_body():
    if request.method in ("GET", "HEAD", "DELETE"):
        return {}
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def endpoint(*roles):
    """Rungs 1 and 2 of the global ladder: authentication then authorization."""

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                fail("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required.")
            if role not in roles:
                fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
            ctx = Ctx(user_id, role, _parse_body())
            return fn(ctx, **kwargs)

        return wrapper

    return decorate


# ---------------------------------------------------------------------------
# pagination and listing
# ---------------------------------------------------------------------------
def _as_int(raw):
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if digits == "" or not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def paging():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit is None or limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset is None or offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
    return limit, offset


def listing(kind, filters, serializer):
    """Generic list endpoint: filter by exact query-parameter match, then page."""
    limit, offset = paging()
    records = db.all(kind)
    for field in filters:
        wanted = request.args.get(field)
        if wanted is None:
            continue
        records = [r for r in records if r.get(field) == wanted]
    records = sorted_records(records)
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# body shape checks (ladder rung 5)
# ---------------------------------------------------------------------------
def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=1, max_len=None):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def opt_str(body, name, default=None, min_len=1, max_len=None):
    if not present(body, name):
        return default
    return req_str(body, name, min_len, max_len)


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_int(body, name, low=None, high=None):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if low is not None and value < low:
        _bad(name, "must be at least %s" % low)
    if high is not None and value > high:
        _bad(name, "must be at most %s" % high)
    return value


def opt_int(body, name, default=None, low=None, high=None):
    if not present(body, name):
        return default
    return req_int(body, name, low, high)


def req_num(body, name, low=None, high=None, places=None):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    number = rhu(value, places) if places is not None else value
    if low is not None and number < low:
        _bad(name, "must be at least %s" % low)
    if high is not None and number > high:
        _bad(name, "must be at most %s" % high)
    return number


def opt_num(body, name, default=None, low=None, high=None, places=None):
    if not present(body, name):
        return default
    return req_num(body, name, low, high, places)


def req_date(body, name):
    text = req_str(body, name)
    value = parse_date(text)
    if value is None:
        _bad(name, "must be a date in YYYY-MM-DD form")
    return value


def opt_date(body, name, default=None):
    if not present(body, name):
        return default
    return req_date(body, name)


def req_dt(body, name):
    text = req_str(body, name)
    value = parse_datetime(text)
    if value is None:
        _bad(name, "must be an ISO 8601 datetime")
    return value


def opt_dt(body, name, default=None):
    if not present(body, name):
        return default
    return req_dt(body, name)


def forbid(body, *names):
    for name in names:
        if present(body, name):
            _bad(name, "must be absent for this action")


def require_fk(body, name):
    """Body foreign keys are validated for shape here; existence is rung 9."""
    return req_str(body, name)


def api_error_response(exc):
    if not isinstance(exc, ApiError):
        raise exc
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status
