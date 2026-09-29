"""Response envelope, authentication, request-body validation and pagination.

Envelope shape, pagination parameter names and defaults are read from
SCAFFOLD response_envelope / PRD 2.2-2.3.
"""

from decimal import Decimal

from flask import jsonify, request

from core import ROLES, db, fmt_ms, new_request_id, parse_date, parse_iso, to_decimal
from errors import ApiError


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ms(db.clock),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def no_content():
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), 204


def listing(items, total, limit, offset):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# authentication + authorization (PRD 2.1, validations priority 1 and 2)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# ---------------------------------------------------------------------------
# request body validation (validations priority 3 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


class Body(object):
    def __init__(self, raw):
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            _bad("The request body must be a JSON object.")
        self.raw = raw

    def present(self, key):
        return key in self.raw and self.raw[key] is not None

    def has_key(self, key):
        return key in self.raw

    def string(self, key, required=True, default=None, min_len=None, max_len=None):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return default
        value = self.raw[key]
        if not isinstance(value, str):
            _bad("Field %r must be a string." % key)
        if min_len is not None and len(value) < min_len:
            _bad("Field %r must be at least %d characters." % (key, min_len))
        if max_len is not None and len(value) > max_len:
            _bad("Field %r must be at most %d characters." % (key, max_len))
        return value

    def integer(self, key, required=True, default=None, minimum=None, maximum=None):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return default
        value = self.raw[key]
        if isinstance(value, bool) or not isinstance(value, int):
            _bad("Field %r must be an integer." % key)
        if minimum is not None and value < minimum:
            _bad("Field %r must be >= %s." % (key, minimum))
        if maximum is not None and value > maximum:
            _bad("Field %r must be <= %s." % (key, maximum))
        return value

    def number(self, key, required=True, default=None, minimum=None, maximum=None,
               exclusive_minimum=None):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return default
        value = self.raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad("Field %r must be a number." % key)
        dec = to_decimal(value)
        if minimum is not None and dec < Decimal(str(minimum)):
            _bad("Field %r must be >= %s." % (key, minimum))
        if maximum is not None and dec > Decimal(str(maximum)):
            _bad("Field %r must be <= %s." % (key, maximum))
        if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
            _bad("Field %r must be > %s." % (key, exclusive_minimum))
        return dec

    def boolean(self, key, required=True, default=None):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return default
        value = self.raw[key]
        if not isinstance(value, bool):
            _bad("Field %r must be a boolean." % key)
        return value

    def enum(self, key, values, required=True, default=None):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return default
        value = self.raw[key]
        if not isinstance(value, str) or value not in values:
            _bad("Field %r must be one of %s." % (key, ", ".join(values)))
        return value

    def enum_array(self, key, values, required=True, default=None, non_empty=True):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return default
        value = self.raw[key]
        if not isinstance(value, list):
            _bad("Field %r must be an array." % key)
        if non_empty and not value:
            _bad("Field %r must be a non-empty array." % key)
        out = []
        for entry in value:
            if not isinstance(entry, str) or entry not in values:
                _bad("Field %r may only contain %s." % (key, ", ".join(values)))
            if entry not in out:
                out.append(entry)
        return out

    def datetime(self, key, required=True, default=None):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return default
        return parse_iso(self.raw[key])

    def date(self, key, required=True, default=None):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return default
        return parse_date(self.raw[key])

    def array(self, key, required=False, default=None):
        if not self.present(key):
            if required:
                _bad("Missing required field %r." % key)
            return [] if default is None else default
        value = self.raw[key]
        if not isinstance(value, list):
            _bad("Field %r must be an array." % key)
        return value


def get_body():
    if request.content_length:
        try:
            raw = request.get_json(force=True, silent=False)
        except Exception:
            _bad("The request body is not valid JSON.")
    else:
        raw = None
    return Body(raw)


# ---------------------------------------------------------------------------
# pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def pagination():
    args = request.args
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'limit' must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            _bad("Query parameter 'limit' must be between %d and %d." % (MIN_LIMIT, MAX_LIMIT))
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            _bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(records, serializer):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return listing([serializer(r) for r in page], total, limit, offset)


def query_flag(name):
    """Parse an optional boolean query filter; returns None when absent."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    low = raw.strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    _bad("Query parameter %r must be a boolean." % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
