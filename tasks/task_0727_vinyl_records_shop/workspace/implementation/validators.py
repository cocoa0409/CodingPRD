"""Request parsing / validation helpers."""
from flask import request

from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from calculations import GRADES


def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
        if data is None:
            # allow empty body for action endpoints
            if not request.data:
                return {}
            raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
        if not isinstance(data, dict):
            raise err(ERR_INVALID_REQUEST, "Body must be a JSON object")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def require_grade(body, field):
    return require_enum(body, field, GRADES)


def opt_grade(body, field):
    if body.get(field) is None:
        return None
    return require_grade(body, field)


def get_pagination():
    """Parse limit/offset from query string. Defaults limit=10, offset=0."""
    def parse(name, default, minimum, maximum):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            val = int(raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "Invalid %s" % name)
        if val < minimum:
            raise err(ERR_INVALID_REQUEST, "%s below minimum" % name)
        if maximum is not None and val > maximum:
            raise err(ERR_INVALID_REQUEST, "%s above maximum" % name)
        return val

    limit = parse("limit", 10, 1, 100)
    offset = parse("offset", 0, 0, None)
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted. Returns (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


def sorted_by_created(values):
    return sorted(values, key=lambda x: (x["created_at"], x["id"]))


def lookup(coll, rid):
    ent = coll.get(rid)
    if ent is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return ent
