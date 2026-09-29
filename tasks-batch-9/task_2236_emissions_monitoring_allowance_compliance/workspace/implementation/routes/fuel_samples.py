"""Fuel sampling and laboratory analysis (PRD 3.4)."""

from flask import Blueprint

from constants import (
    ANALYSIS_METHODS,
    API_PREFIX,
    FUEL_ANALYSIS_OUTCOMES,
    FUEL_SAMPLE_STATUSES,
    FUEL_TYPES,
    ROLE_FACILITY_OPERATOR,
    ROLE_QA_ANALYST,
)
from db import base_record, db, public, public_list, sort_rows, touch
from errors import fail
from lookup import facility_of_unit, find, get
from middleware import ANY_ROLE, authenticate, enforce_facility_scope
from response import array_response, object_response
from validation import (
    apply_pagination,
    body_dict,
    check_range,
    dt_field,
    enum_field,
    match_filters,
    num_field,
    pagination,
    present,
    query_filters,
    str_field,
)

bp = Blueprint("fuel_samples", __name__)


@bp.route(API_PREFIX + "/units/<unit_id>/fuel-samples", methods=["POST"])
def draw_sample(unit_id):
    caller = authenticate((ROLE_FACILITY_OPERATOR,))
    body = body_dict()
    enforce_facility_scope(caller, facility_of_unit(find("unit", unit_id)))

    sample_raw, sample_dt = dt_field(body, "sample_utc", required=True)
    fuel_type = enum_field(body, "fuel_type", FUEL_TYPES, required=True)
    lot_identifier = str_field(body, "lot_identifier", required=True, min_len=1)

    unit = get("unit", unit_id)

    for existing in db.fuel_samples.values():
        if existing["unit_id"] == unit["id"] and existing["lot_identifier"] == lot_identifier:
            fail("ERR_INVALID_REQUEST", "lot_identifier is already used by this unit.")

    sample = base_record()
    sample.update(
        {
            "unit_id": unit["id"],
            "sample_utc": sample_raw,
            "fuel_type": fuel_type,
            "lot_identifier": lot_identifier,
            "status": "PENDING",
            "gcv_btu_per_lb": None,
            "sulfur_content_pct": None,
            "analysis_method": None,
            "analyzed_utc": None,
            "invalidation_reason": None,
            "_sample_utc": sample_dt,
        }
    )
    db.fuel_samples[sample["id"]] = sample
    return object_response(public(sample), 201)


@bp.route(API_PREFIX + "/fuel-samples", methods=["GET"])
def list_samples():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "unit_id": "str",
            "status": FUEL_SAMPLE_STATUSES,
            "fuel_type": FUEL_TYPES,
            "lot_identifier": "str",
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.fuel_samples.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/fuel-samples/<sample_id>", methods=["GET"])
def read_sample(sample_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("fuel_sample", sample_id)))


@bp.route(API_PREFIX + "/fuel-samples/<sample_id>/analysis", methods=["POST"])
def record_analysis(sample_id):
    authenticate((ROLE_QA_ANALYST,))
    body = body_dict()

    outcome = enum_field(body, "outcome", FUEL_ANALYSIS_OUTCOMES, required=True)
    gcv = num_field(body, "gcv_btu_per_lb")
    sulfur = num_field(body, "sulfur_content_pct")
    method = enum_field(body, "analysis_method", ANALYSIS_METHODS)
    reason = str_field(body, "invalidation_reason")

    if outcome == "ANALYZED":
        # All three analysis values are mandatory for this outcome (3.4).
        if not present(body, "gcv_btu_per_lb"):
            fail("ERR_INVALID_REQUEST", "gcv_btu_per_lb is required for an ANALYZED outcome.")
        if not present(body, "sulfur_content_pct"):
            fail("ERR_INVALID_REQUEST", "sulfur_content_pct is required for an ANALYZED outcome.")
        if not present(body, "analysis_method"):
            fail("ERR_INVALID_REQUEST", "analysis_method is required for an ANALYZED outcome.")

    sample = get("fuel_sample", sample_id)

    if outcome == "ANALYZED":
        if sample["status"] not in ("PENDING", "INVALIDATED"):
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "An analysis may only be recorded on a PENDING or INVALIDATED sample.",
            )
        check_range("gcv_btu_per_lb", gcv, minimum=1000, maximum=20000)
        check_range("sulfur_content_pct", sulfur, minimum=0, maximum=10)
        sample["gcv_btu_per_lb"] = float(gcv)
        sample["sulfur_content_pct"] = float(sulfur)
        sample["analysis_method"] = method
        sample["analyzed_utc"] = db.now_str()
        sample["invalidation_reason"] = None
        sample["status"] = "ANALYZED"
    else:  # INVALIDATE
        if sample["status"] not in ("PENDING", "ANALYZED"):
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "Only a PENDING or ANALYZED sample may be invalidated.",
            )
        if reason is None or not reason.strip():
            fail("ERR_REASON_REQUIRED", "invalidation_reason is required to invalidate a sample.")
        sample["invalidation_reason"] = reason
        sample["status"] = "INVALIDATED"

    touch(sample)
    return object_response(public(sample))
