"""Request-body shape validation (pipeline stage 3) and existence checks (stage 4)."""
from datetime import datetime

from db import db
from errors import raise_error, ERR_INVALID_REQUEST

# Collection -> 404 error spec
NOT_FOUND = {}


def _register_not_found():
    from errors import (
        ERR_CARRIER_NOT_FOUND, ERR_DRIVER_NOT_FOUND, ERR_CATEGORY_NOT_FOUND,
        ERR_INSPECTION_NOT_FOUND, ERR_VIOLATION_NOT_FOUND, ERR_CHALLENGE_NOT_FOUND,
        ERR_COACHING_NOT_FOUND, ERR_TEST_NOT_FOUND, ERR_ACCIDENT_NOT_FOUND,
        ERR_AUDIT_CASE_NOT_FOUND, ERR_UPGRADE_REQUEST_NOT_FOUND,
        ERR_PREMIUM_MODEL_NOT_FOUND, ERR_DOCUMENT_NOT_FOUND,
        ERR_TESTING_PERIOD_NOT_FOUND, ERR_SNAPSHOT_NOT_FOUND,
    )
    NOT_FOUND.update({
        "carriers": ERR_CARRIER_NOT_FOUND,
        "drivers": ERR_DRIVER_NOT_FOUND,
        "violation_categories": ERR_CATEGORY_NOT_FOUND,
        "roadside_inspections": ERR_INSPECTION_NOT_FOUND,
        "inspection_violations": ERR_VIOLATION_NOT_FOUND,
        "dataqs_challenges": ERR_CHALLENGE_NOT_FOUND,
        "coaching_assignments": ERR_COACHING_NOT_FOUND,
        "drug_alcohol_tests": ERR_TEST_NOT_FOUND,
        "accident_records": ERR_ACCIDENT_NOT_FOUND,
        "compliance_audit_cases": ERR_AUDIT_CASE_NOT_FOUND,
        "rating_upgrade_requests": ERR_UPGRADE_REQUEST_NOT_FOUND,
        "insurance_premium_models": ERR_PREMIUM_MODEL_NOT_FOUND,
        "document_records": ERR_DOCUMENT_NOT_FOUND,
        "random_testing_periods": ERR_TESTING_PERIOD_NOT_FOUND,
        "measurement_snapshots": ERR_SNAPSHOT_NOT_FOUND,
    })


_register_not_found()


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"invalid field: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_number(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
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


def opt_str_list(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an array")
    for item in v:
        if not isinstance(item, str):
            raise_error(ERR_INVALID_REQUEST, f"field {field} must contain strings")
    return list(v)


def _validate_datetime_str(v, field):
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")


def req_datetime(body, field):
    v = req_str(body, field)
    _validate_datetime_str(v, field)
    return v


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def require_path_resource(collection, rid):
    """Stage 4: path parameter existence (left-to-right)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(NOT_FOUND[collection], f"{collection} id not found: {rid}")
    return obj


def require_ref(collection, rid, field):
    """Stage 4: body-supplied foreign key existence, in declared input order."""
    if rid is None:
        return None
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(NOT_FOUND[collection], f"{field} does not resolve: {rid}")
    return obj
