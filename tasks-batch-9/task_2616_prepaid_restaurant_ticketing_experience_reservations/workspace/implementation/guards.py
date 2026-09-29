"""Auth, ownership, body-shape validation, pagination and list filtering."""
from flask import request

from common import (ApiError, DB, get, must_get, parse_date, parse_iso,
                    public, rows)

ROLES = ("Guest", "RestaurantManager", "KitchenLead", "GuestServices",
         "PlatformAdmin")
ALL_ROLES = ROLES
RESTAURANT_ROLES = ("RestaurantManager", "KitchenLead")


class Ctx(object):
    __slots__ = ("user_id", "role", "body")

    def __init__(self, user_id, role, body):
        self.user_id = user_id
        self.role = role
        self.body = body

    @property
    def is_guest(self):
        return self.role == "Guest"


def _body():
    if request.method in ("GET", "DELETE"):
        return {}
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_VALIDATION", "request body is not valid JSON")
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return body


def auth(*allowed_roles):
    """Priority 1-3: headers present, role recognised, role permitted."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or str(user_id).strip() == "" \
            or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS",
                       "X-User-ID and X-User-Role are both required")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "unrecognised role: %s" % role)
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "role %s may not call this endpoint" % role)
    return Ctx(user_id, role, _body())


# ------------------------------------------------------------------- ownership


def own_guest(ctx, guest_id):
    """Priority 4 for a Guest acting on a guest-scoped resource."""
    if ctx.role == "Guest" and ctx.user_id != guest_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER",
                       "acting guest does not own this resource")


def own_restaurant(ctx, restaurant_id):
    """Priority 4 for RestaurantManager / KitchenLead."""
    if ctx.role in RESTAURANT_ROLES and ctx.user_id != restaurant_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER",
                       "acting restaurant does not own this resource")


def service_of(reservation):
    return DB["services"][reservation["service_id"]]


def own_reservation(ctx, res):
    own_guest(ctx, res["guest_id"])
    own_restaurant(ctx, service_of(res)["restaurant_id"])


# -------------------------------------------------------------- field checking


def _fail(field, why):
    raise ApiError("ERR_VALIDATION", "%s %s" % (field, why))


def present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, max_len=None, allow_empty=False):
    if field not in body or body[field] is None:
        _fail(field, "is required")
    value = body[field]
    if not isinstance(value, str):
        _fail(field, "must be a string")
    if not allow_empty and value.strip() == "":
        _fail(field, "must be a non-empty string")
    if max_len is not None and len(value) > max_len:
        _fail(field, "must be at most %d characters" % max_len)
    return value


def opt_str(body, field, default=None, max_len=None, allow_empty=True):
    if field not in body or body[field] is None:
        return default
    return req_str(body, field, max_len=max_len, allow_empty=allow_empty)


def req_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        _fail(field, "is required")
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an integer")
    if minimum is not None and value < minimum:
        _fail(field, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _fail(field, "must be at most %d" % maximum)
    return value


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_bool(body, field):
    if field not in body or body[field] is None:
        _fail(field, "is required")
    if not isinstance(body[field], bool):
        _fail(field, "must be a boolean")
    return body[field]


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        _fail(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_dt(body, field):
    value = req_str(body, field)
    try:
        return parse_iso(value)
    except Exception:
        _fail(field, "must be an ISO 8601 UTC timestamp")


def opt_dt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_dt(body, field)


def req_date(body, field):
    value = req_str(body, field)
    try:
        return parse_date(value)
    except Exception:
        _fail(field, "must be a YYYY-MM-DD date")


def req_fk(body, field):
    """The declared foreign key, as a raw string, for existence checking."""
    if field not in body or body[field] is None:
        return None
    if not isinstance(body[field], str):
        return None
    return body[field]


def fk_exists(body, field, table):
    """Priority 6: body foreign keys resolved in declaration order."""
    raw = req_fk(body, field)
    if raw is None:
        return None
    rec = get(table, raw)
    if rec is None:
        must_get(table, raw)
    return rec


# ------------------------------------------------------- pagination + filtering


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be at least 0")
    return limit, offset


def _matches(rec, field, raw):
    value = rec.get(field)
    if isinstance(value, bool):
        want = str(raw).strip().lower()
        if want in ("true", "1"):
            return value is True
        if want in ("false", "0"):
            return value is False
        return False
    if value is None:
        return False
    return str(value) == str(raw)


def filtered(table, spec, extra=None):
    """spec maps query-param name -> record field name."""
    out = []
    for rec in rows(table):
        if extra is not None and not extra(rec):
            continue
        keep = True
        for param, field in spec.items():
            raw = request.args.get(param)
            if raw is None or raw == "":
                continue
            if not _matches(rec, field, raw):
                keep = False
                break
        if keep:
            out.append(rec)
    return out


def window(collection):
    limit, offset = pagination()
    total = len(collection)
    page = collection[offset:offset + limit]
    return [public(r) for r in page], limit, offset, total
