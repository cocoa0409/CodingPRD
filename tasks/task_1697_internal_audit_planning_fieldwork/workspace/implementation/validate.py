"""Request-body shape validation (pipeline stage 5, PRD 2.7) and reference
existence helpers (stage 4)."""
from datetime import datetime

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SCORE_OUT_OF_RANGE,
    ERR_AUDITABLE_ENTITY_NOT_FOUND,
    ERR_RISK_ASSESSMENT_NOT_FOUND,
    ERR_RATING_CONFIG_NOT_FOUND,
    ERR_AUDIT_PLAN_NOT_FOUND,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_AUDITOR_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_WORKPAPER_NOT_FOUND,
    ERR_FINDING_NOT_FOUND,
    ERR_MANAGEMENT_RESPONSE_NOT_FOUND,
    ERR_ACTION_PLAN_NOT_FOUND,
    ERR_EXTENSION_REQUEST_NOT_FOUND,
    ERR_AUDIT_REPORT_NOT_FOUND,
    ERR_QA_REVIEW_NOT_FOUND,
    ERR_COMMITTEE_PACK_NOT_FOUND,
)

NOT_FOUND_FOR_COLLECTION = {
    "auditable_entities": ERR_AUDITABLE_ENTITY_NOT_FOUND,
    "risk_assessments": ERR_RISK_ASSESSMENT_NOT_FOUND,
    "rating_criteria_configs": ERR_RATING_CONFIG_NOT_FOUND,
    "audit_plans": ERR_AUDIT_PLAN_NOT_FOUND,
    "engagements": ERR_ENGAGEMENT_NOT_FOUND,
    "auditors": ERR_AUDITOR_NOT_FOUND,
    "engagement_assignments": ERR_ASSIGNMENT_NOT_FOUND,
    "workpapers": ERR_WORKPAPER_NOT_FOUND,
    "findings": ERR_FINDING_NOT_FOUND,
    "management_responses": ERR_MANAGEMENT_RESPONSE_NOT_FOUND,
    "action_plans": ERR_ACTION_PLAN_NOT_FOUND,
    "extension_requests": ERR_EXTENSION_REQUEST_NOT_FOUND,
    "audit_reports": ERR_AUDIT_REPORT_NOT_FOUND,
    "qa_reviews": ERR_QA_REVIEW_NOT_FOUND,
    "committee_packs": ERR_COMMITTEE_PACK_NOT_FOUND,
}


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Stage 4: existence (path ids left-to-right, then body FKs in declared order)
# ---------------------------------------------------------------------------

def require_path(collection, rid):
    """Path-parameter existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(NOT_FOUND_FOR_COLLECTION[collection], f"{collection} id not found: {rid}")
    return obj


def body_ref(body, field, collection):
    """Body foreign-key existence. Only fires when the field is present and a
    string (a missing/ill-typed field is a stage-5 shape concern). Returns the
    referenced record or None."""
    v = body.get(field)
    if v is None or not isinstance(v, str):
        return None
    obj = db[collection].get(v)
    if obj is None:
        raise_error(NOT_FOUND_FOR_COLLECTION[collection],
                    f"{field} does not resolve to an existing {collection} record: {v}")
    return obj


# ---------------------------------------------------------------------------
# Stage 5: request shape
# ---------------------------------------------------------------------------

def check_unknown_fields(body, allowed):
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        raise_error(ERR_INVALID_REQUEST,
                    f"unknown or read-only field supplied: {sorted(extra)[0]}")


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    return v


def opt_int(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field)


def req_number(body, field, positive=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    if positive and not v > 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def _validate_datetime_value(v, field):
    if not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid datetime field: {field}")
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 datetime: {field}")
    return v


def req_datetime(body, field):
    return _validate_datetime_value(body.get(field), field)


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return _validate_datetime_value(body.get(field), field)


def opt_nullable_datetime(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    return _validate_datetime_value(v, field)


def req_str_list(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid array field: {field}")
    for item in v:
        if not isinstance(item, str):
            raise_error(ERR_INVALID_REQUEST, f"field {field} must contain only strings")
    return list(v)


def opt_str_list(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_str_list(body, field)


def check_score_range(value, field):
    """Stage 5b: a well-typed 1..5 score outside range -> 422 ERR_SCORE_OUT_OF_RANGE."""
    if value < 1 or value > 5:
        raise_error(ERR_SCORE_OUT_OF_RANGE, f"{field} must be within 1..5 inclusive")
    return value
