"""Request-side helpers: auth, ownership, body parsing, validation, pagination."""
from flask import request

from envelope import ApiError
from util import parse_iso

KNOWN_ROLES = {"Anonymous", "Registrant", "CodeOfficer", "ProgramAdmin"}
READ_ROLES = {"Registrant", "CodeOfficer", "ProgramAdmin"}


def authenticate(allowed_roles):
    """Enforce auth (401) then authorization (403). Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or unknown credentials")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this operation")
    return uid, role


def check_property_owner(prop, uid, role):
    """A Registrant may only act on properties it owns."""
    if role == "Registrant" and prop["registrant_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "not the owner of this resource")


# --- body parsing / validation -------------------------------------------
def get_body():
    body = request.get_json(silent=True, force=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return body


def need(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", "missing required field: %s" % f)


def need_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise ApiError("ERR_VALIDATION", "invalid value for %s" % field)
    return val


def need_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_VALIDATION", "%s below minimum" % field)
    if maximum is not None and val > maximum:
        raise ApiError("ERR_VALIDATION", "%s above maximum" % field)
    return val


def need_datetime(body, field):
    val = body.get(field)
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", "%s must be an ISO-8601 string" % field)
    try:
        return parse_iso(val)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "%s is not a valid timestamp" % field)


# --- pagination / listing -------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def ordered(values):
    return sorted(values, key=lambda e: e["_seq"])


def page(items, limit, offset):
    return items[offset:offset + limit]
