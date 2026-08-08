"""Shared request/response helpers: envelopes, auth, membership, pagination, body validation."""
from flask import jsonify, request

import store
from errors import ApiError
from util import gen_req_id, now_iso

RECOGNIZED_ROLES = {
    "Anonymous",
    "HouseholdOwner",
    "HouseholdMember",
    "ConciergeAgent",
    "ManufacturerAgent",
    "PlatformAdmin",
}


def _meta(pagination=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, code=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), code


def ok_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ------------------------------------------------------------------ auth ----
def new_common():
    """Fresh common-field envelope: id, created_at, updated_at, version, _seq."""
    ts = now_iso()
    return {
        "id": __import__("util").new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def get_headers():
    return request.headers.get("X-User-Role"), request.headers.get("X-User-ID")


def require_auth(allowed_roles):
    """Authenticate (401) then authorize by role membership (403)."""
    role, uid = get_headers()
    if not role or not uid or role not in RECOGNIZED_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return role, uid


def require_household_member(uid, household_id, require_owner=False):
    """For entity-backed household roles: uid must be a Member of household_id."""
    member = store.members.get(uid)
    if member is None or member.get("household_id") != household_id:
        raise ApiError("ERR_NOT_HOUSEHOLD_MEMBER")
    if require_owner and member.get("role") != "OWNER":
        raise ApiError("ERR_UNAUTHORIZED")
    return member


# ------------------------------------------------------------------ body ----
def get_body():
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        return {}
    return body


def bad_request(msg="Malformed request body."):
    return ApiError("ERR_INVALID_REQUEST", msg)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise bad_request("Field '%s' is required and must be a non-empty string." % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (field, sorted(allowed)))
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if v not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (field, sorted(allowed)))
    return v


def require_int(body, field, non_negative=True):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request("Field '%s' must be an integer." % field)
    if non_negative and v < 0:
        raise bad_request("Field '%s' must be non-negative." % field)
    return v


def optional_int(body, field, default, non_negative=True):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field, non_negative=non_negative)


def optional_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise bad_request("Field '%s' must be a boolean." % field)
    return v


# ------------------------------------------------------------ pagination ----
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, serialize):
    """records: list already filtered; sort by _seq asc (== created_at asc)."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serialize(r) for r in page], pagination


def resolve_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec
