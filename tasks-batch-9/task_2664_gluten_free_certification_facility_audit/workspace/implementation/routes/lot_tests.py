"""Lot test recording and reads."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import READ_LOT_TESTS, ROLE_LAB_TECHNICIAN, TEST_TYPES
from errors import ApiError
from services import calc, derive, nc as nc_service

bp = Blueprint("lot_tests", __name__)


@bp.post("/gfco/lot-tests")
def create_lot_test():
    user_id, _ = mw.authenticate([ROLE_LAB_TECHNICIAN])
    data = mw.body()
    product_id = mw.req_str(data, "product_id")
    lot_code = mw.req_str(data, "lot_code")
    test_type = mw.req_enum(data, "test_type", TEST_TYPES)
    sample_collected_on = mw.req_dt(data, "sample_collected_on")
    ppm_result = mw.req_num(data, "ppm_result", minimum=0)
    lab_method = mw.req_str(data, "lab_method")

    product = query.fetch("product", product_id)

    if product["testing_plan_status"] != "ACTIVE":
        raise ApiError("ERR_TESTING_PLAN_NOT_ACTIVE")
    now = clock.now()
    if sample_collected_on > now:
        raise ApiError("ERR_SAMPLE_DATE_IN_FUTURE")
    if test_type == "SCHEDULED":
        _check_exclusion_window(product, sample_collected_on)

    threshold = product["threshold_ppm"]
    verdict = calc.lot_verdict(ppm_result, threshold)

    row = db.insert(
        db.lot_tests,
        {
            "product_id": product_id,
            "lot_code": lot_code,
            "test_type": test_type,
            "sample_collected_on": sample_collected_on,
            "ppm_result": ppm_result,
            "lab_method": lab_method,
            "threshold_applied_ppm": threshold,
            "verdict": verdict,
            "status": "RECORDED",
            "nonconformance_created": False,
            "in_recall_scope": False,
        },
    )

    if test_type == "FOR_CAUSE":
        _supersede_earlier(row)

    before = db.snapshot(product)
    derive.recompute_product_counts(product)
    db.touch_if_changed(product, before)

    if verdict == "FAIL":
        if test_type == "UNANNOUNCED":
            cert = derive.active_certificate_for_product(product_id)
            if cert is not None and cert["status"] == "ISSUED":
                derive.suspend_certificate(cert, "FAILED_UNANNOUNCED_TEST")
        severity = calc.lot_failure_severity(ppm_result, threshold)
        cert = derive.active_certificate_for_product(product_id)
        nc_service.create(
            applicant_id=product["applicant_id"],
            source_type="LOT_TEST",
            category="THRESHOLD_EXCEEDANCE",
            severity=severity,
            description="Lot %s exceeded the certified threshold of %s ppm at %s ppm."
            % (lot_code, threshold, ppm_result),
            raised_by_user_id=user_id,
            certificate_id=cert["id"] if cert is not None else None,
            lot_test_id=row["id"],
        )
        row["nonconformance_created"] = True
        db.touch(row)

    return response.created(response.serialize(row))


def _check_exclusion_window(product, sample_collected_on):
    exclusion_days = product["sampling_exclusion_days"]
    if not exclusion_days:
        return
    for prior in db.ordered(db.lot_tests):
        if prior["product_id"] != product["id"]:
            continue
        if prior["test_type"] != "SCHEDULED" or prior["status"] != "RECORDED":
            continue
        start = prior["sample_collected_on"]
        end = start + timedelta(days=exclusion_days - 1)
        if start <= sample_collected_on <= end:
            raise ApiError("ERR_SAMPLING_EXCLUSION_WINDOW")


def _supersede_earlier(new_row):
    for prior in db.ordered(db.lot_tests):
        if prior["id"] == new_row["id"]:
            continue
        if prior["product_id"] != new_row["product_id"]:
            continue
        if prior["lot_code"] != new_row["lot_code"]:
            continue
        if prior["status"] != "RECORDED":
            continue
        prior["status"] = "SUPERSEDED_BY_RETEST"
        prior["in_recall_scope"] = False
        db.touch(prior)


@bp.get("/gfco/lot-tests/<lot_test_id>")
def get_lot_test(lot_test_id):
    mw.authenticate(READ_LOT_TESTS)
    return response.ok(response.serialize(query.fetch("lot_test", lot_test_id)))


@bp.get("/gfco/lot-tests")
def list_lot_tests():
    mw.authenticate(READ_LOT_TESTS)
    return query.listing(
        db.lot_tests,
        {
            "product_id": query.arg("product_id"),
            "test_type": query.arg("test_type"),
            "verdict": query.arg("verdict"),
        },
    )
