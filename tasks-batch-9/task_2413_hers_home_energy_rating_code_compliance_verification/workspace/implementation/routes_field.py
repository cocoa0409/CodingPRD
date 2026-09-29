"""Rough-in and final checkpoints plus their append-only diagnostic measurements."""

from datetime import timedelta

from flask import Blueprint

import calc
import validation as v
from auth import check_cert_level, check_certification_valid, endpoint, require_owner
from db import clock_now_iso, db, new_row, ordered, touch
from errors import ApiError
from graph import (
    plan_of_rating,
    rating_of_inspection,
    require_inspection,
    require_rater,
    require_rating,
    subdivision_of_rating,
    tests_of_inspection,
)
from ops import check_not_locked, check_not_void, invalid_state
from response import Result
from serializers import diagnostic_test_out, inspection_out

bp = Blueprint("field", __name__)

CHECKPOINTS = ("ROUGH_IN", "FINAL")
TEST_TYPES = ("BLOWER_DOOR", "DUCT_LEAKAGE_TOTAL")
FIELD_LEVELS = ("RATING_FIELD_INSPECTOR", "RATER")
READ_ROLES = (
    "RatingProviderAdmin",
    "CertifiedRater",
    "FieldInspector",
    "QADesignee",
    "BuilderRep",
)

BUFFER = timedelta(minutes=calc.INSPECTOR_TRAVEL_BUFFER_MINUTES)


def _buffered(inspection):
    start = v.parse_datetime(inspection["scheduled_start_utc"], "scheduled_start_utc")
    end = v.parse_datetime(inspection["scheduled_end_utc"], "scheduled_end_utc")
    return start - BUFFER, end + BUFFER


@bp.post("/inspections")
@endpoint(["FieldInspector", "CertifiedRater"])
def create_inspection():
    data = v.body()
    rating_id = v.req_str(data, "rating_id")
    inspector_id = v.req_str(data, "inspector_id")
    checkpoint = v.req_enum(data, "checkpoint", CHECKPOINTS)
    start_raw, start = v.req_datetime(data, "scheduled_start_utc")
    end_raw, end = v.req_datetime(data, "scheduled_end_utc")
    if not end > start:
        v.invalid("Field 'scheduled_end_utc' must be strictly after 'scheduled_start_utc'.")
    air_handler_installed = v.opt_bool(data, "air_handler_installed", False)

    rating = require_rating(rating_id)
    require_rater(inspector_id)

    check_not_void(rating)
    check_not_locked(rating)

    check_certification_valid(inspector_id)
    check_cert_level(inspector_id, FIELD_LEVELS)

    new_start, new_end = start - BUFFER, end + BUFFER
    for other in db.inspections.values():
        if other["inspector_id"] != inspector_id or other["status"] != "SCHEDULED":
            continue
        other_start, other_end = _buffered(other)
        if new_start < other_end and other_start < new_end:
            raise ApiError("ERR_INSPECTOR_WINDOW_CONFLICT")

    row = new_row(
        "Inspection",
        {
            "rating_id": rating_id,
            "inspector_id": inspector_id,
            "checkpoint": checkpoint,
            "scheduled_start_utc": start_raw,
            "scheduled_end_utc": end_raw,
            "air_handler_installed": air_handler_installed,
            "status": "SCHEDULED",
            "failed_test_count": 0,
        },
    )
    db.inspections[row["id"]] = row
    return Result(row, inspection_out, status=201)


@bp.get("/inspections/<inspection_id>")
@endpoint(list(READ_ROLES))
def get_inspection(inspection_id):
    return Result(require_inspection(inspection_id), inspection_out)


@bp.get("/inspections")
@endpoint(list(READ_ROLES))
def list_inspections():
    limit, offset = v.pagination()
    rating_id = v.query_str("rating_id")
    inspector_id = v.query_str("inspector_id")
    checkpoint = v.query_enum("checkpoint", CHECKPOINTS)

    rows = []
    for inspection in db.inspections.values():
        if rating_id is not None and inspection["rating_id"] != rating_id:
            continue
        if inspector_id is not None and inspection["inspector_id"] != inspector_id:
            continue
        if checkpoint is not None and inspection["checkpoint"] != checkpoint:
            continue
        rows.append(inspection)
    rows = ordered(rows)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, inspection_out, page=(limit, offset, total))


@bp.post("/inspections/<inspection_id>/tests")
@endpoint(["FieldInspector"])
def create_test(inspection_id):
    data = v.body()
    test_type = v.req_enum(data, "test_type", TEST_TYPES)
    measured_value = v.req_number(data, "measured_value", 0)

    inspection = require_inspection(inspection_id)
    require_owner(inspection["inspector_id"])

    if inspection["status"] != "SCHEDULED":
        invalid_state("Measurements may only be recorded on a SCHEDULED checkpoint.")

    rating = rating_of_inspection(inspection)
    check_not_void(rating)
    check_not_locked(rating)

    check_certification_valid(inspection["inspector_id"])
    check_cert_level(inspection["inspector_id"], FIELD_LEVELS)

    plan = plan_of_rating(rating)
    subdivision = subdivision_of_rating(rating)
    if test_type == "BLOWER_DOOR":
        normalized, threshold, result = calc.blower_door_normalization(
            measured_value, plan, subdivision
        )
    else:
        normalized, threshold, result = calc.duct_leakage_normalization(
            measured_value, plan, inspection
        )

    row = new_row(
        "DiagnosticTest",
        {
            "inspection_id": inspection_id,
            "test_type": test_type,
            "measured_value": measured_value,
            "normalized_value": calc.to_number(normalized),
            "threshold_value": calc.to_number(threshold),
            "result": result,
            "performed_at_utc": clock_now_iso(),
        },
        versioned=False,
    )
    db.diagnostic_tests[row["id"]] = row
    return Result(row, diagnostic_test_out, status=201)


@bp.get("/inspections/<inspection_id>/tests")
@endpoint(list(READ_ROLES))
def list_tests(inspection_id):
    limit, offset = v.pagination()
    require_inspection(inspection_id)
    rows = tests_of_inspection(inspection_id)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, diagnostic_test_out, page=(limit, offset, total))


@bp.post("/inspections/<inspection_id>/complete")
@endpoint(["FieldInspector"])
def complete_inspection(inspection_id):
    inspection = require_inspection(inspection_id)
    require_owner(inspection["inspector_id"])

    if inspection["status"] != "SCHEDULED":
        invalid_state("Only a SCHEDULED checkpoint can be closed.")

    rating = rating_of_inspection(inspection)
    check_not_void(rating)
    check_not_locked(rating)

    check_certification_valid(inspection["inspector_id"])

    tests = tests_of_inspection(inspection_id)
    types = [t["test_type"] for t in tests]
    if inspection["checkpoint"] == "ROUGH_IN":
        if "DUCT_LEAKAGE_TOTAL" not in types:
            raise ApiError("ERR_MISSING_GOVERNING_TEST")
    else:
        if "BLOWER_DOOR" not in types or "DUCT_LEAKAGE_TOTAL" not in types:
            raise ApiError("ERR_MISSING_GOVERNING_TEST")

    failed = sum(1 for t in tests if t["result"] == "FAIL")
    inspection["failed_test_count"] = failed
    inspection["status"] = "PASSED" if failed == 0 else "FAILED"
    touch(inspection)

    if (
        inspection["checkpoint"] == "ROUGH_IN"
        and inspection["status"] == "PASSED"
        and rating is not None
        and rating["stage"] == "PROJECTED"
    ):
        rating["stage"] = "ROUGH_IN_VERIFIED"
        touch(rating)

    return Result(inspection, inspection_out)
