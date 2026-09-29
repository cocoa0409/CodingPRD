"""Laboratory panels and measurements (PRD 3.5)."""

from flask import Blueprint, request

import calc
import cascades
from db import db, new_row, ordered, serialize as _ser, touch
from errors import ApiError
from middleware import authorize, find, user_id
from response import enum_filter, list_response, object_response, string_filter
from support import STATUS_CREATED, body, unique
from validate import field as F
from validate import validate

bp = Blueprint("lab", __name__)

PANEL_STATUS = ("SCHEDULED", "IN_TEST", "PASSED", "FAILED", "RETEST_REQUIRED", "VOIDED")
TEST_TYPES = tuple(calc.CANONICAL_TEST_ORDER)
PANEL_READERS = ("PlantAdmin", "QaTechnician", "TechnicalDirector", "Formulator")

MANDATORY_FOR_PROVISIONAL = ("RESIDUAL_INDENTATION", "DIMENSIONAL_STABILITY_HEAT")


def _results_of(panel, attempt_no=None):
    rows = [r for r in db.test_results.values() if r["test_panel_id"] == panel["id"]]
    if attempt_no is not None:
        rows = [r for r in rows if r["attempt_no"] == attempt_no]
    return ordered(rows)


def _sku_testable(sku):
    """Band 10 (V-XSTATE-1)."""
    if sku["certification_status"] not in ("TESTING", "PROVISIONAL"):
        raise ApiError("ERR_INVALID_SKU_CERTIFICATION_STATE")


@bp.post("/test-panels")
def create_panel():
    authorize("QaTechnician")
    data = validate([
        F("panel_code", "string", required=True),
        F("sku_id", "string", required=True),
    ], body())
    sku = find("product_skus", data["sku_id"])
    _sku_testable(sku)
    unique("test_panels", "panel_code", data["panel_code"])

    row = new_row()
    row.update({
        "panel_code": data["panel_code"],
        "sku_id": sku["id"],
        "status": "SCHEDULED",
        "attempt_no": 1,
        "retest_count": 0,
        "required_test_types": calc.sku_required_test_types(sku),
        "started_by_user_id": None,
        "void_reason": None,
    })
    db.test_panels[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/test-panels")
def list_panels():
    authorize(*PANEL_READERS)
    status = enum_filter(request.args, "status", PANEL_STATUS)
    sku_id = string_filter(request.args, "sku_id")
    rows = [r for r in db.test_panels.values()
            if (status is None or r["status"] == status)
            and (sku_id is None or r["sku_id"] == sku_id)]
    return list_response(rows, request.args, _ser)


@bp.get("/test-panels/<row_id>")
def read_panel(row_id):
    authorize(*PANEL_READERS)
    return object_response(_ser(find("test_panels", row_id)))


@bp.get("/test-panels/<row_id>/results")
def list_results(row_id):
    authorize(*PANEL_READERS)
    panel = find("test_panels", row_id)
    test_type = enum_filter(request.args, "test_type", TEST_TYPES)
    rows = [r for r in db.test_results.values()
            if r["test_panel_id"] == panel["id"]
            and (test_type is None or r["test_type"] == test_type)]
    return list_response(rows, request.args, _ser)


@bp.post("/test-panels/<row_id>/start")
def start_panel(row_id):
    authorize("QaTechnician")
    panel = find("test_panels", row_id)
    if panel["status"] not in ("SCHEDULED", "RETEST_REQUIRED"):
        raise ApiError("ERR_INVALID_PANEL_STATE")
    sku = db.product_skus.get(panel["sku_id"])
    _sku_testable(sku)
    if panel["status"] == "RETEST_REQUIRED" and panel["retest_count"] > 2:
        raise ApiError("ERR_RETEST_LIMIT_EXCEEDED")

    if panel["status"] == "RETEST_REQUIRED":
        panel["attempt_no"] = panel["attempt_no"] + 1
    panel["status"] = "IN_TEST"
    panel["started_by_user_id"] = user_id()
    panel["required_test_types"] = calc.sku_required_test_types(sku)
    touch(panel)
    return object_response(_ser(panel))


@bp.post("/test-panels/<row_id>/results")
def record_result(row_id):
    authorize("QaTechnician")
    data = validate([
        F("test_type", "string", required=True, enum=TEST_TYPES),
        F("measured_value", "number", required=True, min=0, decimals=4),
    ], body())
    panel = find("test_panels", row_id)
    if panel["status"] != "IN_TEST":
        raise ApiError("ERR_INVALID_PANEL_STATE")
    if data["test_type"] not in panel["required_test_types"]:
        raise ApiError("ERR_INVALID_REQUEST")
    attempt = panel["attempt_no"]
    existing = _results_of(panel, attempt)
    if any(r["test_type"] == data["test_type"] for r in existing):
        raise ApiError("ERR_INVALID_REQUEST")

    sku = db.product_skus.get(panel["sku_id"])
    formulation = db.formulations.get(sku["formulation_id"]) if sku else None
    unit, spec, outcome = calc.test_spec_limit_and_outcome(
        sku, formulation, data["test_type"], data["measured_value"])

    result = new_row(versioned=False)
    result.update({
        "test_panel_id": panel["id"],
        "attempt_no": attempt,
        "test_type": data["test_type"],
        "measured_value": data["measured_value"],
        "unit": unit,
        "spec_limit": spec,
        "outcome": outcome,
        "recorded_by_user_id": user_id(),
    })
    db.test_results[result["id"]] = result

    if outcome == "FAIL":
        panel["status"] = "FAILED"
        touch(panel)
        if sku is not None:
            cascades.collapse_certification(sku)
    else:
        current = _results_of(panel, attempt)
        covered = {r["test_type"]: r for r in current}
        if all(t in covered for t in panel["required_test_types"]):
            outcomes = [covered[t]["outcome"] for t in panel["required_test_types"]]
            if all(o == "PASS" for o in outcomes):
                panel["status"] = "PASSED"
                touch(panel)
                if (sku is not None and sku["certification_status"] == "TESTING"
                        and all(t in covered for t in MANDATORY_FOR_PROVISIONAL)):
                    sku["certification_status"] = "PROVISIONAL"
                    touch(sku)
            else:
                panel["status"] = "RETEST_REQUIRED"
                panel["retest_count"] = panel["retest_count"] + 1
                touch(panel)
        else:
            touch(panel)
    return object_response(_ser(result), STATUS_CREATED)


@bp.post("/test-panels/<row_id>/void")
def void_panel(row_id):
    authorize("QaTechnician")
    data = validate([F("void_reason", "string", required=True)], body())
    panel = find("test_panels", row_id)
    if panel["status"] not in ("SCHEDULED", "IN_TEST", "RETEST_REQUIRED"):
        raise ApiError("ERR_INVALID_PANEL_STATE")
    panel["status"] = "VOIDED"
    panel["void_reason"] = data["void_reason"]
    touch(panel)
    return object_response(_ser(panel))


__all__ = ["bp"]
