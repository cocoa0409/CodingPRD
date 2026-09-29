"""Third-party certification tests and the warranty startup record.

PRD §3.9.
"""

from flask import Blueprint

import calc
import find
import validate
from db import db, new_row, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    PROGRAM_ADMIN,
    THIRD_PARTY_TESTER,
    acting_user_id,
    authorize,
)
from response import created, listing, ok

bp = Blueprint("certs", __name__)

TEST_STANDARDS = ("NFPA_1901", "NFPA_1911", "NFPA_1917", "AMD_STD_003")
STANDARDS_BY_UNIT_TYPE = {
    "PUMPER": ("NFPA_1901",),
    "AERIAL": ("NFPA_1911",),
    "AMBULANCE": ("NFPA_1917", "AMD_STD_003"),
}
RESULTS = ("PASS", "FAIL")
SUBMITTABLE_CERTIFICATION_STATUSES = ("NOT_SUBMITTED", "REJECTED_TESTING")


@bp.post("/certification-tests")
@authorize(THIRD_PARTY_TESTER)
def submit_certification_test():
    data = validate.body()
    unit_order_id = validate.req_ref(data, "unit_order_id")
    test_standard = validate.req_enum(data, "test_standard", TEST_STANDARDS)
    tested_at = validate.opt_dt(data, "tested_at")

    unit = find.unit_order(unit_order_id)

    if unit["certification_status"] not in SUBMITTABLE_CERTIFICATION_STATUSES:
        raise ApiError("ERR_INVALID_CERTIFICATION_STATE")

    # Rung 23 — the standards house does not test a body the committee has not
    # yet walked through.
    held_mid_con = any(
        t["unit_order_id"] == unit["id"]
        and t["trip_type"] == "MID_CONSTRUCTION"
        and t["status"] == "HELD"
        for t in db.trips.values()
    )
    if not held_mid_con:
        raise ApiError("ERR_MID_CON_INSPECTION_NOT_HELD")

    if test_standard not in STANDARDS_BY_UNIT_TYPE[unit["unit_type"]]:
        raise ApiError("ERR_TEST_STANDARD_MISMATCH")

    row = new_row(
        {
            "unit_order_id": unit["id"],
            "test_standard": test_standard,
            "submitted_by_user_id": acting_user_id(),
            "signed_by_user_id": None,
            "result": None,
            "status": "SUBMITTED",
            "tested_at": tested_at,
            "invalidated_reason": None,
        }
    )
    db.certification_tests[row["id"]] = row

    unit["certification_status"] = "IN_TESTING"
    touch(unit)

    return created(row)


@bp.get("/certification-tests")
@authorize(*ALL_ROLES)
def list_certification_tests():
    limit, offset = validate.pagination()
    unit_order_id = validate.query_filter("unit_order_id")
    status = validate.query_filter("status")
    rows = list(db.certification_tests.values())
    if unit_order_id is not None:
        rows = [r for r in rows if r["unit_order_id"] == unit_order_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, limit, offset)


@bp.get("/certification-tests/<certification_test_id>")
@authorize(*ALL_ROLES)
def read_certification_test(certification_test_id):
    return ok(find.certification_test(certification_test_id))


@bp.post("/certification-tests/<certification_test_id>/record-result")
@authorize(THIRD_PARTY_TESTER)
def record_certification_result(certification_test_id):
    data = validate.body()
    result = validate.req_enum(data, "result", RESULTS)
    signed_by_user_id = validate.req_str(data, "signed_by_user_id", 1, None)

    test = find.certification_test(certification_test_id)
    if test["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_TEST_STATE")

    unit = db.unit_orders.get(test["unit_order_id"])

    # Rung 33 — the engineer who computed the load distribution may not be the
    # signature on the certificate that says the distribution is compliant.
    if unit is not None and signed_by_user_id == unit["weight_calc_engineer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    test["result"] = result
    test["signed_by_user_id"] = signed_by_user_id
    test["status"] = "PASSED" if result == "PASS" else "FAILED"
    touch(test)

    if unit is not None:
        unit["certification_status"] = "CERTIFIED" if result == "PASS" else "REJECTED_TESTING"
        touch(unit)

    return ok(test)


# ==========================================================================
# Warranty startups
# ==========================================================================


@bp.get("/warranty-startups")
@authorize(*ALL_ROLES)
def list_warranty_startups():
    limit, offset = validate.pagination()
    unit_order_id = validate.query_filter("unit_order_id")
    status = validate.query_filter("status")
    rows = list(db.warranty_startups.values())
    if unit_order_id is not None:
        rows = [r for r in rows if r["unit_order_id"] == unit_order_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, limit, offset)


@bp.get("/warranty-startups/<warranty_startup_id>")
@authorize(*ALL_ROLES)
def read_warranty_startup(warranty_startup_id):
    return ok(find.warranty_startup(warranty_startup_id))


@bp.post("/warranty-startups/<warranty_startup_id>/complete-training")
@authorize(PROGRAM_ADMIN)
def complete_warranty_training(warranty_startup_id):
    data = validate.body()
    additional = validate.req_num(data, "additional_training_hours", 0.0)

    record = find.warranty_startup(warranty_startup_id)
    if record["status"] != "PENDING_TRAINING":
        raise ApiError("ERR_INVALID_WARRANTY_STATE")

    # The threshold is evaluated against the accumulated figure, but nothing is
    # written when it falls short: the record keeps its deferred start.
    accumulated = calc.dec(record["training_hours"]) + additional
    if accumulated < calc.REQUIRED_TRAINING_HOURS:
        raise ApiError("ERR_TRAINING_HOURS_NOT_MET")

    start_raw, end_raw = calc.warranty_window(
        record["delivery_date"], int(record["warranty_months"]), deferred=False
    )
    record["training_hours"] = accumulated
    record["status"] = "ACTIVE"
    record["warranty_start_date"] = start_raw
    record["warranty_end_date"] = end_raw
    touch(record)
    return ok(record)
