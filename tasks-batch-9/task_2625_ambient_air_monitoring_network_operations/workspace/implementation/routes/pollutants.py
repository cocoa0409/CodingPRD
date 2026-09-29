"""The pollutant catalogue and the federal method designations under it."""
from flask import Blueprint

import clock
import constants as C
import response
import validate as V
from auth import ALL_ROLES, require
from db import new_record, sorted_by_created, store, touch
from routes.common import get_method, get_pollutant
from services import serialize as S

bp = Blueprint("pollutants", __name__)


@bp.post("/pollutants")
@require("NetworkAdmin")
def create_pollutant():
    data = V.body()
    code = V.req_enum(data, "code", C.POLLUTANT_CODES)
    averaging_period_hours = V.req_int(data, "averaging_period_hours", lo=1, hi=8760)
    standard_form = V.req_enum(data, "standard_form", C.STANDARD_FORMS)
    primary_standard_value = V.req_number(data, "primary_standard_value", exclusive_lo=0)
    design_value_years = V.opt_int(data, "design_value_years", default=3, lo=1)
    completeness_threshold_pct = V.opt_number(
        data, "completeness_threshold_pct", default=75.0, exclusive_lo=0, hi=100)
    rounding_decimals = V.opt_int(data, "rounding_decimals", default=1, lo=0, hi=3)
    for existing in store.pollutants.values():
        if existing["code"] == code:
            V.bad("A pollutant with code '%s' is already registered." % code)
    rec = new_record(common_fields=False)
    rec.update({
        "code": code,
        "averaging_period_hours": averaging_period_hours,
        "standard_form": standard_form,
        "primary_standard_value": primary_standard_value,
        "design_value_years": design_value_years,
        "completeness_threshold_pct": completeness_threshold_pct,
        "rounding_decimals": rounding_decimals,
    })
    store.pollutants[rec["id"]] = rec
    return response.object_response(S.pollutant(rec), 201)


@bp.get("/pollutants/<pollutant_id>")
@require(*ALL_ROLES)
def read_pollutant(pollutant_id):
    rec = get_pollutant(pollutant_id)
    return response.object_response(S.pollutant(rec))


@bp.get("/pollutants/<pollutant_id>/reference-methods")
@require(*ALL_ROLES)
def list_pollutant_methods(pollutant_id):
    limit, offset = V.pagination()
    designation_status = V.q_enum("designation_status", C.DESIGNATION_STATUSES)
    get_pollutant(pollutant_id)
    rows = [m for m in store.reference_methods.values() if m["pollutant_id"] == pollutant_id]
    if designation_status is not None:
        rows = [m for m in rows if m["designation_status"] == designation_status]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.reference_method(m) for m in page], pagination=meta)


@bp.post("/reference-methods")
@require("NetworkAdmin")
def create_reference_method():
    data = V.body()
    pollutant_id = V.req_id(data, "pollutant_id")
    method_code = V.req_string(data, "method_code", min_len=1, max_len=40)
    designation_type = V.req_enum(data, "designation_type", C.DESIGNATION_TYPES)
    effective_from = V.req_datetime(data, "effective_from")
    max_span_drift_pct = V.req_number(data, "max_span_drift_pct", exclusive_lo=0)
    zero_drift_limit = V.req_number(data, "zero_drift_limit", exclusive_lo=0)
    span_interval = V.req_int(data, "required_span_check_interval_days", lo=1)
    calibration_interval = V.req_int(data, "required_calibration_interval_days", lo=1)
    for existing in store.reference_methods.values():
        if existing["method_code"] == method_code:
            V.bad("A reference method with method_code '%s' is already registered." % method_code)
    get_pollutant(pollutant_id)
    rec = new_record()
    rec.update({
        "pollutant_id": pollutant_id,
        "method_code": method_code,
        "designation_type": designation_type,
        "designation_status": "DESIGNATED",
        "effective_from": effective_from,
        "withdrawn_on": None,
        "max_span_drift_pct": max_span_drift_pct,
        "zero_drift_limit": zero_drift_limit,
        "required_span_check_interval_days": span_interval,
        "required_calibration_interval_days": calibration_interval,
        "designation_change_count": 0,
    })
    store.reference_methods[rec["id"]] = rec
    return response.object_response(S.reference_method(rec), 201)


# DESIGNATED <-> CONDITIONAL is a cycle a method may traverse repeatedly; either
# state may move to the terminal WITHDRAWN (PRD 3.1).
_DESIGNATION_SOURCES = {
    "CONDITIONAL": ("DESIGNATED",),
    "DESIGNATED": ("CONDITIONAL",),
    "WITHDRAWN": ("DESIGNATED", "CONDITIONAL"),
}


@bp.post("/reference-methods/<method_id>/designation")
@require("EpaRegionalReviewer")
def change_designation(method_id):
    data = V.body()
    new_status = V.req_enum(data, "new_designation_status", C.DESIGNATION_STATUSES)
    V.opt_string(data, "determination_note")
    method = get_method(method_id)
    if method["designation_status"] == "WITHDRAWN":
        from errors import ApiError
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "The reference method has already been withdrawn.")
    if method["designation_status"] not in _DESIGNATION_SOURCES[new_status]:
        from errors import ApiError
        raise ApiError(
            "ERR_INVALID_STATE",
            "A method in %s cannot move to %s." % (method["designation_status"], new_status))
    method["designation_status"] = new_status
    method["designation_change_count"] += 1
    method["withdrawn_on"] = clock.now() if new_status == "WITHDRAWN" else None
    touch(method)
    return response.object_response(S.reference_method(method))


@bp.get("/reference-methods/<method_id>")
@require(*ALL_ROLES)
def read_reference_method(method_id):
    return response.object_response(S.reference_method(get_method(method_id)))
