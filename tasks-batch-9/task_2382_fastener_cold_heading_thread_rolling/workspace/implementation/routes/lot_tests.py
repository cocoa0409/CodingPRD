"""Destructive lot testing (PRD 3.7)."""

from flask import Blueprint, g

import enums
from db import db, new_record, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok, ok_list
from services import calc
from services.lookup import (
    compute_pre_test_risk,
    guard_disposition,
    lot_test_or_404,
    lot_tests,
    production_lot_or_404,
    required_ops_satisfied,
    spec_for_lot,
)
from util import dec
from validate import (
    field_int,
    field_num,
    field_str,
    paginate,
    pagination,
    query_enum,
)

bp = Blueprint("lot_tests", __name__)


def _may_open_test(lot, spec):
    state = lot["process_state"]
    if state == "BAKED":
        return True
    if spec.get("plating_spec") == "NONE" and state in ("HEAT_TREATED", "SECONDARY_DONE"):
        return True
    if state == "TESTING":
        existing = lot_tests(lot["id"])
        if existing and all(t["result"] == "REJECT" for t in existing):
            return True
    return False


def _severity_for(lot):
    pre_test = lot.get("risk_score_pre_test")
    if pre_test is not None and dec(pre_test) >= calc.TIGHTENED_RISK_THRESHOLD:
        return "TIGHTENED"
    key = (lot["part_spec_id"], lot.get("traceability_heat_id"))
    sibling_ids = {
        other["id"]
        for other in db.production_lots.values()
        if (other["part_spec_id"], other.get("traceability_heat_id")) == key
    }
    for test in db.lot_tests.values():
        if test["result"] == "REJECT" and test["production_lot_id"] in sibling_ids:
            return "TIGHTENED"
    return "NORMAL"


@bp.post("/lot-tests")
@endpoint("QualityInspector")
def create_lot_test():
    production_lot_id = field_str(g.body, "production_lot_id")

    lot = production_lot_or_404(production_lot_id)
    guard_disposition(lot)

    spec = spec_for_lot(lot)
    if not _may_open_test(lot, spec):
        raise ApiError("ERR_INVALID_LOT_STATE")

    if not required_ops_satisfied(lot, spec):
        raise ApiError("ERR_SECONDARY_OPS_INCOMPLETE")

    # An unplated part reaches its first test without ever passing through the
    # bake, so pass one of the risk score is computed here instead.
    if lot.get("risk_score_pre_test") is None:
        lot["risk_score_pre_test"] = compute_pre_test_risk(lot)

    severity = _severity_for(lot)
    sample_size, acceptance_number = calc.sampling_plan(severity, lot["available_count"])
    if int(lot["available_count"]) < sample_size:
        raise ApiError("ERR_INSUFFICIENT_SAMPLE_PIECES")

    test = new_record(
        {
            "production_lot_id": production_lot_id,
            "severity": severity,
            "sample_size": sample_size,
            "acceptance_number": acceptance_number,
            "destructive": True,
            "proof_load_failures": None,
            "tensile_failures": None,
            "min_measured_core_hardness_hv": None,
            "total_failures": None,
            "result": "PENDING",
            "performed_by_user_id": g.user_id,
            "completed_at": None,
        }
    )
    db.lot_tests[test["id"]] = test

    lot["inspection_severity"] = severity
    lot["destructive_test_count"] = int(lot["destructive_test_count"]) + sample_size
    lot["available_count"] = int(lot["available_count"]) - sample_size
    lot["process_state"] = "TESTING"
    touch(lot)
    return created(test)


@bp.get("/production-lots/<lot_id>/lot-tests")
@endpoint(ANY_ROLE)
def list_lot_tests(lot_id):
    limit, offset = pagination()
    result = query_enum("result", enums.LOT_TEST_RESULTS)
    production_lot_or_404(lot_id)

    records = lot_tests(lot_id)
    if result is not None:
        records = [r for r in records if r["result"] == result]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/lot-tests/<test_id>/results")
@endpoint("QualityInspector")
def record_lot_test_results(test_id):
    body = g.body
    proof_load_failures = field_int(body, "proof_load_failures")
    tensile_failures = field_int(body, "tensile_failures")
    min_measured_core_hardness_hv = field_num(body, "min_measured_core_hardness_hv")

    test = lot_test_or_404(test_id)
    lot = db.production_lots.get(test["production_lot_id"])
    if lot is None:
        raise ApiError("ERR_PRODUCTION_LOT_NOT_FOUND")

    guard_disposition(lot)

    if test["result"] != "PENDING" or lot["process_state"] != "TESTING":
        raise ApiError("ERR_INVALID_LOT_STATE")

    sample_size = int(test["sample_size"])
    total_failures = proof_load_failures + tensile_failures
    if (
        proof_load_failures < 0
        or tensile_failures < 0
        or proof_load_failures > sample_size
        or tensile_failures > sample_size
        or total_failures > sample_size
    ):
        raise ApiError("ERR_PIECE_COUNT_INVALID")

    result = "ACCEPT" if total_failures <= int(test["acceptance_number"]) else "REJECT"

    test["proof_load_failures"] = proof_load_failures
    test["tensile_failures"] = tensile_failures
    test["min_measured_core_hardness_hv"] = min_measured_core_hardness_hv
    test["total_failures"] = total_failures
    test["result"] = result
    test["completed_at"] = db.now_iso()
    touch(test)

    lot["risk_score_final"] = calc.risk_score_final(
        lot.get("risk_score_pre_test"), total_failures
    )
    if result == "ACCEPT":
        spec = spec_for_lot(lot)
        lot["achieved_strength_class"] = calc.certified_strength_class(
            spec["strength_class"], min_measured_core_hardness_hv
        )
        lot["process_state"] = "TESTED"
    else:
        lot["disposition"] = "HOLD"
        lot["hold_source"] = "TEST_REJECT"
    touch(lot)
    return ok(test)
