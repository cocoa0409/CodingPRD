"""Shared helpers: serialization, pagination, body validation."""

from flask import request

from db import store, now_iso, _parse_iso_date, _parse_iso_datetime
from errors import (
    ApiError,
    ERR_VALIDATION,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_DRUG_PROGRAM_NOT_FOUND,
    ERR_FOUNDATION_POOL_NOT_FOUND,
    ERR_PRIOR_AUTHORIZATION_NOT_FOUND,
    ERR_COPAY_ASSISTANCE_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_NURSE_VISIT_NOT_FOUND,
    ERR_ADVERSE_EVENT_NOT_FOUND,
    ERR_OUTCOME_REPORT_NOT_FOUND,
)


# ---------- Body helpers ----------

def body():
    """Return the parsed JSON body, requiring an object.

    Raises ERR_VALIDATION on missing/malformed bodies. Optional-body
    endpoints (those whose inputs are all optional) call body_optional.
    """
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError(ERR_VALIDATION, "Request body must be a JSON object.", 400)
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, "Request body must be a JSON object.", 400)
    return data


def body_optional():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, "Request body must be a JSON object.", 400)
    return data


def req_string(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise ApiError(ERR_VALIDATION, f"Field '{field}' is required and must be a non-empty string.", 400)
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, f"Field '{field}' must be a string.", 400)
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, f"Field '{field}' is required and must be a boolean.", 400)
    return v


def req_int(data, field):
    v = data.get(field)
    # bool is a subclass of int; exclude it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, f"Field '{field}' is required and must be an integer.", 400)
    return v


def opt_int(data, field):
    v = data.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, f"Field '{field}' must be an integer.", 400)
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if v is None or v not in values:
        raise ApiError(ERR_VALIDATION,
                       f"Field '{field}' must be one of {sorted(values)}.", 400)
    return v


def req_date(data, field):
    v = data.get(field)
    d = _parse_iso_date(v)
    if d is None:
        raise ApiError(ERR_VALIDATION,
                       f"Field '{field}' must be a date in YYYY-MM-DD form.", 400)
    return d


def req_datetime(data, field):
    v = data.get(field)
    dt = _parse_iso_datetime(v)
    if dt is None:
        raise ApiError(ERR_VALIDATION,
                       f"Field '{field}' must be an ISO8601 UTC datetime.", 400)
    return dt


# ---------- Existence helpers ----------

def get_enrollment_or_404(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError(ERR_ENROLLMENT_NOT_FOUND, f"Enrollment {eid} not found.", 404)
    return e


def get_program_or_404(pid):
    p = store.drug_programs.get(pid)
    if p is None:
        raise ApiError(ERR_DRUG_PROGRAM_NOT_FOUND, f"Drug program {pid} not found.", 404)
    return p


def get_pool_or_404(pid):
    p = store.foundation_pools.get(pid)
    if p is None:
        raise ApiError(ERR_FOUNDATION_POOL_NOT_FOUND, f"Foundation pool {pid} not found.", 404)
    return p


def get_pa_or_404(pid):
    p = store.prior_authorizations.get(pid)
    if p is None:
        raise ApiError(ERR_PRIOR_AUTHORIZATION_NOT_FOUND, f"Prior authorization {pid} not found.", 404)
    return p


def get_assistance_or_404(aid):
    a = store.copay_assistances.get(aid)
    if a is None:
        raise ApiError(ERR_COPAY_ASSISTANCE_NOT_FOUND, f"Copay assistance {aid} not found.", 404)
    return a


def get_shipment_or_404(sid):
    s = store.shipments.get(sid)
    if s is None:
        raise ApiError(ERR_SHIPMENT_NOT_FOUND, f"Shipment {sid} not found.", 404)
    return s


def get_visit_or_404(vid):
    v = store.nurse_visits.get(vid)
    if v is None:
        raise ApiError(ERR_NURSE_VISIT_NOT_FOUND, f"Nurse visit {vid} not found.", 404)
    return v


def get_ae_or_404(aid):
    a = store.adverse_events.get(aid)
    if a is None:
        raise ApiError(ERR_ADVERSE_EVENT_NOT_FOUND, f"Adverse event {aid} not found.", 404)
    return a


def get_report_or_404(rid):
    r = store.outcome_reports.get(rid)
    if r is None:
        raise ApiError(ERR_OUTCOME_REPORT_NOT_FOUND, f"Outcome report {rid} not found.", 404)
    return r


# ---------- Touch / version ----------

def touch(entity):
    """Refresh updated_at and bump version on a mutated resource."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1


# ---------- Pagination ----------

def pagination_params():
    """Read limit/offset from the query string.

    Defaults: limit=10, offset=0. Min 1, max 100 for limit.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, "Query parameter 'limit' must be an integer.", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, "Query parameter 'limit' must be between 1 and 100.", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, "Query parameter 'offset' must be an integer.", 400)
        if offset < 0:
            raise ApiError(ERR_VALIDATION, "Query parameter 'offset' must be >= 0.", 400)
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (stable chronological) then slice."""
    ordered = sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
