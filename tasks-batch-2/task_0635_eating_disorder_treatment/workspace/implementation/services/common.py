"""Shared helpers: request-body validation, FK existence checks, pagination,
common record fields, and serialization.

All field-level validation raises ERR_INVALID_REQUEST (400) per PRD §2.6 unless a
more specific error applies (e.g. ERR_INVALID_WINDOW for review windows).
"""
from flask import request

import errors
from db import store
from errors import ApiError


# ---------------------------------------------------------------------------
# Request body access
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the parsed JSON object body, or raise ERR_INVALID_REQUEST.

    A body is required to be a JSON object for create/transition endpoints that
    read fields; an absent body is treated as an empty object so that
    no-input transitions still work.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body


def get_optional_json_body():
    """For transition endpoints with no input fields: tolerate empty/no body."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# Field validators (ERR_INVALID_REQUEST on failure)
# ---------------------------------------------------------------------------
def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Missing required field: {name}.")
    return body[name]


def validate_non_empty_string(value, name):
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be a non-empty string.")
    return value


def validate_enum(value, name, allowed):
    if value not in allowed:
        raise ApiError(
            errors.ERR_INVALID_REQUEST,
            400,
            f"Field {name} must be one of {sorted(allowed)}.",
        )
    return value


def validate_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer.")
    if minimum is not None and value < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be <= {maximum}.")
    return value


def validate_number(value, name, minimum=None, maximum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be a number.")
    fv = float(value)
    if exclusive_min is not None and fv <= exclusive_min:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be > {exclusive_min}.")
    if minimum is not None and fv < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be >= {minimum}.")
    if maximum is not None and fv > maximum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be <= {maximum}.")
    return value


def validate_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be a boolean.")
    return value


# ---------------------------------------------------------------------------
# Foreign-key existence (priority 4: ERR_*_NOT_FOUND, 404)
# ---------------------------------------------------------------------------
_FK_TABLES = {
    "facility_id": ("facilities", errors.ERR_FACILITY_NOT_FOUND),
    "program_id": ("programs", errors.ERR_PROGRAM_NOT_FOUND),
    "cohort_id": ("cohorts", errors.ERR_COHORT_NOT_FOUND),
    "patient_id": ("patients", errors.ERR_PATIENT_NOT_FOUND),
    "admission_id": ("admissions", errors.ERR_ADMISSION_NOT_FOUND),
    "authorization_id": ("authorizations", errors.ERR_AUTHORIZATION_NOT_FOUND),
    "meal_plan_id": ("meal_plans", errors.ERR_MEAL_PLAN_NOT_FOUND),
}


def check_fk(field_name, value):
    """Verify a foreign key references an existing record; else the resource
    specific not-found error (PRD §2.7)."""
    table_attr, err_id = _FK_TABLES[field_name]
    table = getattr(store, table_attr)
    if value not in table:
        raise ApiError(err_id, 404, f"{field_name} not found.")
    return table[value]


# ---------------------------------------------------------------------------
# Path resource lookup (priority 3)
# ---------------------------------------------------------------------------
def get_or_404(table_attr, resource_id, err_id):
    table = getattr(store, table_attr)
    rec = table.get(resource_id)
    if rec is None:
        raise ApiError(err_id, 404, "Resource not found.")
    return rec


# ---------------------------------------------------------------------------
# Common system fields (PRD §2.4)
# ---------------------------------------------------------------------------
def base_record(with_version=True):
    """Create a record carrying the common system-managed fields.

    Full records carry id, created_at, updated_at, version (version starts at 1).
    Meal events are the exception (with_version is also used to drop updated_at):
    they carry only id and created_at.
    """
    now = store.now_iso()
    rec = {
        "id": store.new_id(),
        "created_at": now,
        "_seq": store.next_seq(),  # internal ordering key, stripped on serialize
    }
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    rec["updated_at"] = store.now_iso()
    rec["version"] = rec.get("version", 1) + 1


def serialize(rec):
    """Strip internal-only keys (those starting with '_') for the response."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination + listing (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    """limit default 10, min 1, max 100; offset default 0. Malformed -> 400."""
    args = request.args

    limit_raw = args.get("limit")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "limit must be an integer.")
        if limit < 1:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "limit must be >= 1.")
        if limit > 100:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "limit must be <= 100.")

    offset_raw = args.get("offset")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "offset must be >= 0.")

    return limit, offset


def list_collection(table_attr, filters=None):
    """Return (page_items, limit, offset, total_count) sorted by created_at ASC.

    filters: dict of {record_field: query_param_name}. Each is read from the
    query string and, if present, used to filter the collection.
    """
    table = getattr(store, table_attr)
    records = list(table.values())

    if filters:
        for field, param in filters.items():
            val = request.args.get(param)
            if val is not None:
                records = [r for r in records if r.get(field) == val]

    # PRD §2.3: sorted by created_at ascending. Use the monotonic seq as the
    # tiebreaker so records sharing a logical-clock instant keep insertion order.
    records.sort(key=lambda r: (r["created_at"], r["_seq"]))

    total_count = len(records)
    limit, offset = parse_pagination()
    page = records[offset:offset + limit]
    return page, limit, offset, total_count
