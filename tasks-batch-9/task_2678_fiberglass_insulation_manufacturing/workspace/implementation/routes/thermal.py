"""Thermal tests: lab occupancy, the conformance verdict and the retest cycle."""

from flask import Blueprint

import calc
import ledger
from db import new_row, store, touch
from errors import fail
from middleware import actor, authenticate
from refs import (apply_filters, get_product_line, get_program, get_run, get_thermal_test)
from response import created_response, list_response, object_response
from validate import body, instant_field, list_field, present, to_decimal

bp = Blueprint("thermal", __name__)

READ_ROLES = ("CorporateOps", "QualityEngineer", "CertificationOfficer")
SAMPLED_RUN_STATUSES = ("CURING", "PACKAGED", "CLOSED")


def _closed_windows_intersect(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def _check_lab_capacity(test, program, start_dt, end_dt):
    """Aggregate check: adjacency counts as an intersection."""
    occupied = 0
    for other in store.thermal_tests.values():
        if other["id"] == test["id"]:
            continue
        if other["status"] != "IN_LAB":
            continue
        if other["certification_program_id"] != test["certification_program_id"]:
            continue
        if _closed_windows_intersect(start_dt, end_dt,
                                     other["_window_start_dt"], other["_window_end_dt"]):
            occupied += 1
    if occupied >= program["max_concurrent_lab_tests"]:
        fail("ERR_LAB_CAPACITY_EXCEEDED",
             "the program's concurrent lab-window cap is already taken")


@bp.post("/thermal-tests")
def request_test():
    authenticate(("QualityEngineer",))
    payload = body()
    start_raw, start_dt = instant_field(payload, "window_start")
    end_raw, end_dt = instant_field(payload, "window_end")
    if not end_dt > start_dt:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly later than window_start")

    if not present(payload, "production_run_id"):
        fail("ERR_INVALID_REQUEST", "production_run_id is required")
    run = get_run(payload["production_run_id"])
    if not present(payload, "product_line_id"):
        fail("ERR_INVALID_REQUEST", "product_line_id is required")
    product_line = get_product_line(payload["product_line_id"])
    if not present(payload, "certification_program_id"):
        fail("ERR_INVALID_REQUEST", "certification_program_id is required")
    program = get_program(payload["certification_program_id"])

    if product_line["id"] != run["product_line_id"]:
        fail("ERR_INVALID_STATE", "the SKU under test is not the run's own SKU")
    if run["run_status"] not in SAMPLED_RUN_STATUSES:
        fail("ERR_INVALID_STATE", "there is no product to sample before the oven")

    row = new_row()
    row.update({
        "production_run_id": run["id"],
        "product_line_id": product_line["id"],
        "certification_program_id": program["id"],
        "window_start": start_raw,
        "window_end": end_raw,
        "_window_start_dt": start_dt,
        "_window_end_dt": end_dt,
        "specimen_r_values": [],
        "conformance_basis": program["conformance_basis"],
        "declared_r_value_at_test": product_line["declared_r_value"],
        "specimen_count": 0,
        "mean_r_value": None,
        "min_r_value": None,
        "conformance_verdict": None,
        "attempt_number": 1,
        "recorded_by_user_id": None,
        "status": "REQUESTED",
    })
    store.thermal_tests[row["id"]] = row

    if run["qc_status"] == "UNSAMPLED":
        run["qc_status"] = "SAMPLED"
        touch(run)
    return created_response(row)


@bp.get("/thermal-tests/<test_id>")
def read_test(test_id):
    authenticate(READ_ROLES)
    return object_response(get_thermal_test(test_id))


@bp.get("/thermal-tests")
def list_tests():
    authenticate(READ_ROLES)
    rows = apply_filters(store.thermal_tests.values(), {
        "production_run_id": ("production_run_id", "str"),
        "product_line_id": ("product_line_id", "str"),
        "certification_program_id": ("certification_program_id", "str"),
        "status": ("status", "str"),
        "conformance_verdict": ("conformance_verdict", "str"),
    })
    return list_response(rows)


@bp.post("/thermal-tests/<test_id>/start-lab")
def start_lab(test_id):
    authenticate(("QualityEngineer",))
    test = get_thermal_test(test_id)
    if test["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "only a REQUESTED test may enter the lab")
    program = store.programs[test["certification_program_id"]]
    _check_lab_capacity(test, program, test["_window_start_dt"], test["_window_end_dt"])
    test["status"] = "IN_LAB"
    touch(test)
    return object_response(test)


@bp.post("/thermal-tests/<test_id>/record-result")
def record_result(test_id):
    authenticate(("QualityEngineer",))
    test = get_thermal_test(test_id)
    payload = body()
    raw_values = list_field(payload, "specimen_r_values")
    values = [to_decimal(value, "specimen_r_values") for value in raw_values]

    if test["status"] != "IN_LAB":
        fail("ERR_INVALID_STATE", "only an IN_LAB test may record a result")
    program = store.programs[test["certification_program_id"]]
    if len(values) < program["min_specimen_count"] or any(v <= 0 for v in values):
        fail("ERR_SPECIMEN_COUNT_INSUFFICIENT",
             "at least %d positive specimen values are required" % program["min_specimen_count"])

    floor_r = calc.conformance_floor(test["declared_r_value_at_test"],
                                     program["r_value_tolerance"])
    count, mean_r, min_r = calc.specimen_stats(values)
    if test["conformance_basis"] == "PER_SPECIMEN":
        verdict = "CONFORMING" if min_r >= floor_r else "NONCONFORMING"
    else:
        verdict = "CONFORMING" if mean_r >= floor_r else "NONCONFORMING"

    exhausted = (verdict == "NONCONFORMING"
                 and test["attempt_number"] >= program["retest_limit"])
    test["specimen_r_values"] = values
    test["specimen_count"] = count
    test["mean_r_value"] = mean_r
    test["min_r_value"] = min_r
    test["conformance_verdict"] = verdict
    test["recorded_by_user_id"] = actor()
    test["status"] = "EXHAUSTED" if exhausted else "COMPLETED"
    touch(test)

    run = store.runs[test["production_run_id"]]
    run["qc_status"] = verdict
    touch(run)
    if verdict == "NONCONFORMING":
        ledger.nonconforming_run_cascade(run)

    if exhausted:
        product_line = store.product_lines[test["product_line_id"]]
        product_line["nonconformance_count"] = product_line["nonconformance_count"] + 1
        suspendable = product_line["certification_status"] in (
            "CERTIFIED", "DERATED", "PENDING_CERTIFICATION")
        if product_line["nonconformance_count"] >= calc.NONCONFORMANCE_SUSPEND_THRESHOLD \
                and suspendable:
            ledger.suspend_product_line(product_line, cancel_cycles=True)
        else:
            touch(product_line)
    return object_response(test)


@bp.post("/thermal-tests/<test_id>/request-retest")
def request_retest(test_id):
    authenticate(("QualityEngineer",))
    test = get_thermal_test(test_id)
    payload = body()
    start_raw, start_dt = instant_field(payload, "window_start")
    end_raw, end_dt = instant_field(payload, "window_end")
    if not end_dt > start_dt:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly later than window_start")

    if test["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "only a COMPLETED test may be retested")
    program = store.programs[test["certification_program_id"]]
    if test["conformance_verdict"] != "NONCONFORMING" \
            or test["attempt_number"] >= program["retest_limit"]:
        fail("ERR_RETEST_LIMIT_REACHED", "no retest is due on this test")
    _check_lab_capacity(test, program, start_dt, end_dt)

    test["attempt_number"] = test["attempt_number"] + 1
    test["status"] = "IN_LAB"
    test["window_start"] = start_raw
    test["window_end"] = end_raw
    test["_window_start_dt"] = start_dt
    test["_window_end_dt"] = end_dt
    test["specimen_r_values"] = []
    test["specimen_count"] = 0
    test["mean_r_value"] = None
    test["min_r_value"] = None
    test["conformance_verdict"] = None
    test["recorded_by_user_id"] = None
    touch(test)

    run = store.runs[test["production_run_id"]]
    if run["qc_status"] == "NONCONFORMING":
        run["qc_status"] = "RETEST_PENDING"
        touch(run)
    return object_response(test)
