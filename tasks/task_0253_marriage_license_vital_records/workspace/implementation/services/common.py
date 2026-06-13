"""Request parsing, pagination, and existence lookups."""
from flask import request

from db import store
from errors import ApiError


def get_body():
    """Return the JSON body as a dict; tolerate empty bodies for no-input POSTs."""
    if request.content_length in (None, 0):
        body = None
    else:
        body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {n}")


def require_enum(value, allowed, field_name):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"{field_name} must be one of {sorted(allowed)}")


def require_int(value, field_name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", f"{field_name} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"{field_name} must be >= {minimum}")
    return value


def require_str(value, field_name):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", f"{field_name} must be a non-empty string")
    return value


def parse_pagination():
    """limit default 10, min 1, max 100; offset default 0, min 0."""
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def sort_by_created(items):
    """Ascending by creation timestamp (oldest first), stable by insertion seq."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---- existence lookups (ERR_NOT_FOUND, 404) ----

_COLLECTIONS = {
    "applicant": "applicants",
    "officiant": "officiants",
    "application": "applications",
    "license": "licenses",
    "return": "returns",
    "record": "records",
    "certified_copy": "certified_copies",
    "amendment": "amendments",
    "apostille": "apostilles",
    "fee_waiver": "fee_waivers",
}


def lookup(kind, entity_id):
    coll = getattr(store, _COLLECTIONS[kind])
    ent = coll.get(entity_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", f"{kind} not found: {entity_id}")
    return ent
