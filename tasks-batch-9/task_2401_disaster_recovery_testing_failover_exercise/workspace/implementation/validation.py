"""Request-shape validation (rank 6), foreign-key existence (rank 5), pagination."""

from flask import request

from db import db, parse_dt, sort_key
from errors import ApiError, bad_request

# --------------------------------------------------------------------------- #
# body access
# --------------------------------------------------------------------------- #

def body():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


# --------------------------------------------------------------------------- #
# rank 5 -- foreign keys supplied in the body must reference existing rows
# --------------------------------------------------------------------------- #

TABLE_ERRORS = {
    "stakeholders": "ERR_STAKEHOLDER_NOT_FOUND",
    "sites": "ERR_SITE_NOT_FOUND",
    "applications": "ERR_APPLICATION_NOT_FOUND",
    "assets": "ERR_ASSET_NOT_FOUND",
    "dependency_edges": "ERR_DEPENDENCY_EDGE_NOT_FOUND",
    "recovery_groups": "ERR_RECOVERY_GROUP_NOT_FOUND",
    "runbooks": "ERR_RUNBOOK_NOT_FOUND",
    "runbook_steps": "ERR_RUNBOOK_STEP_NOT_FOUND",
    "exercises": "ERR_EXERCISE_NOT_FOUND",
    "scope_items": "ERR_SCOPE_ITEM_NOT_FOUND",
    "step_executions": "ERR_STEP_EXECUTION_NOT_FOUND",
    "findings": "ERR_FINDING_NOT_FOUND",
    "evidence_packages": "ERR_EVIDENCE_PACKAGE_NOT_FOUND",
}


def table(name):
    return getattr(db, name)


def check_fk(payload, field, table_name):
    """Validate a body-supplied foreign key when it is supplied at all.

    Absent / null values are left for the rank-6 shape check to report.
    """
    value = payload.get(field)
    if isinstance(value, str) and value:
        if value not in table(table_name):
            raise ApiError(TABLE_ERRORS[table_name], "%s does not exist." % field)


def lookup_path(table_name, row_id):
    """Rank 4 -- path-templated id existence."""
    row = table(table_name).get(row_id)
    if row is None:
        raise ApiError(TABLE_ERRORS[table_name], "Resource %s not found." % row_id)
    return row


# --------------------------------------------------------------------------- #
# rank 6 -- request shape
# --------------------------------------------------------------------------- #

_MISSING = object()


def v_str(payload, field, required=True, default=None, allow_empty=False):
    if field not in payload or payload[field] is None:
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % field)
    if not allow_empty and value.strip() == "":
        raise bad_request("Field '%s' must not be blank." % field)
    return value


def v_int(payload, field, required=True, default=None, minimum=None, maximum=None):
    if field not in payload or payload[field] is None:
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s." % (field, maximum))
    return value


def v_enum(payload, field, allowed, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (field, sorted(allowed)))
    return value


def v_dt(payload, field, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    parsed = parse_dt(payload[field])
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO 8601 UTC datetime." % field)
    return parsed


def v_enum_array(payload, field, allowed, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, list) or not value:
        raise bad_request("Field '%s' must be a non-empty array." % field)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad_request(
                "Field '%s' members must be one of %s." % (field, sorted(allowed))
            )
    return list(value)


def v_id_ref(payload, field, required=True, default=None):
    """A stringly-typed foreign key reference (existence already checked)."""
    return v_str(payload, field, required=required, default=default)


# --------------------------------------------------------------------------- #
# pagination and list filters (PRD 2.3)
# --------------------------------------------------------------------------- #

def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise bad_request("Query parameter '%s' must be an integer." % name)


def pagination_args():
    limit = _query_int("limit", 10)
    offset = _query_int("offset", 0)
    if limit < 1 or limit > 100:
        raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if offset < 0:
        raise bad_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def filter_value(name, allowed=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if allowed is not None and raw not in allowed:
        raise bad_request("Query parameter '%s' is not a declared value." % name)
    return raw


def paginate(rows, key=sort_key, reverse=False):
    """Default sort is created_at ascending (PRD 2.3)."""
    limit, offset = pagination_args()
    ordered = sorted(rows, key=key, reverse=reverse)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
