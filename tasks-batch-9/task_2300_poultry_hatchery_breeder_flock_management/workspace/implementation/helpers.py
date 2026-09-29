"""Response envelope, header auth, body/query validation primitives."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify, request

from errors import ApiError, fail, invalid_request
from store import store

ROLE_NAMES = (
    "HatcheryManager",
    "FlockManager",
    "IncubationOperator",
    "ChickProcessor",
    "Veterinarian",
    "GrowerFarm",
)

_ALNUM = string.ascii_uppercase + string.digits


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _wall_now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(rows) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def ok_array(rows, status=200):
    """Array payload that is not a paginated list endpoint."""
    body = {"meta": _meta(), "response_type": "array", "data": rows}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    return store.clock


def jval(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_dt(value)
    return value


def serialize(rec, fields):
    return {name: jval(rec.get(name)) for name in fields}


COMMON = ("id", "created_at", "updated_at", "version")


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validation ranks 1-2)
# ---------------------------------------------------------------------------
def authorize(roles):
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    role = request.headers.get("X-User-Role")
    if role is None:
        role = request.headers.get("X-Role")
    if role is None or role not in ROLE_NAMES or role not in roles:
        fail("ERR_FORBIDDEN_ROLE", "Role is not authorized for this operation.")
    return user_id, role


# ---------------------------------------------------------------------------
# Body helpers (validation rank 6 unless stated otherwise)
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        invalid_request("Request body must be a JSON object.")
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def need_str(data, name, min_len=1, max_len=None):
    value = data.get(name)
    if not isinstance(value, str):
        invalid_request("%s must be a string." % name)
    if len(value) < min_len or (max_len is not None and len(value) > max_len):
        invalid_request("%s has an invalid length." % name)
    return value


def need_enum(data, name, allowed):
    value = data.get(name)
    if not isinstance(value, str) or value not in allowed:
        invalid_request("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def need_int(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if not is_int(value):
        invalid_request("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid_request("%s is below its minimum." % name)
    if maximum is not None and value > maximum:
        invalid_request("%s is above its maximum." % name)
    return value


def need_num(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if not is_num(value):
        invalid_request("%s must be a number." % name)
    value = Decimal(str(value))
    if minimum is not None and value < Decimal(str(minimum)):
        invalid_request("%s is below its minimum." % name)
    if maximum is not None and value > Decimal(str(maximum)):
        invalid_request("%s is above its maximum." % name)
    return value


def need_dt(data, name):
    value = data.get(name)
    if not isinstance(value, str):
        invalid_request("%s must be an ISO 8601 timestamp string." % name)
    parsed = parse_dt(value)
    if parsed is None:
        invalid_request("%s must be an ISO 8601 timestamp string." % name)
    return parsed


def need_count(data, name, minimum):
    """Validation rank 8 — semantically impossible counts.

    A wrong *type* is rank 6 (ERR_INVALID_REQUEST); a value below the declared
    minimum is rank 8 (ERR_NON_POSITIVE_COUNT).
    """
    value = data.get(name)
    if not is_int(value):
        invalid_request("%s must be an integer." % name)
    return value


def check_count(value, name, minimum):
    if value < minimum:
        fail("ERR_NON_POSITIVE_COUNT", "%s must be at least %s." % (name, minimum))
    return value


# ---------------------------------------------------------------------------
# Pagination + filters (PRD §2.3, validation rank 7)
# ---------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be at least 0.")
    return limit, offset


def apply_filters(rows, spec):
    """spec: {query_param: record_field}. Equality filters only."""
    for param, field in spec.items():
        wanted = request.args.get(param)
        if wanted is None:
            continue
        rows = [r for r in rows if str(r.get(field)) == wanted]
    return rows


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset: offset + limit]
    return [serializer(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Lookups (validation ranks 4 & 5)
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "flock_programs": "ERR_FLOCK_PROGRAM_NOT_FOUND",
    "incubation_profiles": "ERR_INCUBATION_PROFILE_NOT_FOUND",
    "incubation_units": "ERR_INCUBATION_UNIT_NOT_FOUND",
    "breeder_flocks": "ERR_BREEDER_FLOCK_NOT_FOUND",
    "egg_lots": "ERR_EGG_LOT_NOT_FOUND",
    "setter_loads": "ERR_SETTER_LOAD_NOT_FOUND",
    "hatcher_loads": "ERR_HATCHER_LOAD_NOT_FOUND",
    "chick_batches": "ERR_CHICK_BATCH_NOT_FOUND",
    "grower_farms": "ERR_GROWER_FARM_NOT_FOUND",
    "placement_orders": "ERR_PLACEMENT_ORDER_NOT_FOUND",
    "delivery_assignments": "ERR_DELIVERY_ASSIGNMENT_NOT_FOUND",
    "lab_tests": "ERR_LAB_TEST_NOT_FOUND",
    "corrective_actions": "ERR_CORRECTIVE_ACTION_NOT_FOUND",
}


def must_get(table, row_id):
    rec = getattr(store, table).get(row_id)
    if rec is None:
        fail(NOT_FOUND[table], "%s does not resolve." % row_id)
    return rec


def resolve_fk(table, data, field, required=True):
    """Rank-5 body foreign key resolution.

    A missing/mistyped value is left for the rank-6 shape validation; only a
    well-formed identifier that fails to resolve raises the parent's 404.
    """
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        return None
    rec = getattr(store, table).get(value)
    if rec is None:
        fail(NOT_FOUND[table], "%s does not resolve." % field)
    return rec
