"""ApplicationRig and ApplicationTest endpoints (PRD §3.7)."""

from flask import Blueprint, request

import constants as K
import serializers as S
from db import base_entity, db, now_logical, touch
from errors import fail
from middleware import ALL_ROLES, auth
from response import created, ok
from routes.common import list_response, need
from services import cascade, graph, ledger
from validate import (as_datetime, as_decimal, as_enum, as_int, as_str,
                      body_json, require)

bp = Blueprint("tests", __name__)


def _rig(rig_id):
    return need(db.rigs, rig_id, "ERR_RIG_NOT_FOUND", "application rig")


def _test(test_id):
    return need(db.tests, test_id, "ERR_TEST_NOT_FOUND", "application test")


# --- ApplicationRig ---------------------------------------------------------

@bp.post("/application-rigs")
def create_rig():
    auth(["LabTech"])
    body = body_json()
    rig_code = as_str(require(body, "rig_code"), "rig_code", 1, 40)
    matrix_type = as_enum(require(body, "matrix_type"), "matrix_type",
                          K.MATRIX_TYPES)
    buffer_minutes = as_int(require(body, "cleanout_buffer_minutes"),
                            "cleanout_buffer_minutes", minimum=0, maximum=480)
    for existing in db.rigs.values():
        if existing["rig_code"] == rig_code:
            fail("ERR_DUPLICATE_CODE", "rig_code %s already exists" % rig_code)

    rig = base_entity()
    rig.update({
        "rig_code": rig_code,
        "matrix_type": matrix_type,
        "cleanout_buffer_minutes": buffer_minutes,
    })
    db.rigs[rig["id"]] = rig
    return created(S.rig_out(rig))


@bp.get("/application-rigs")
def list_rigs():
    auth(ALL_ROLES)
    matrix_type = request.args.get("matrix_type")
    rows = [r for r in db.rigs.values()
            if matrix_type is None or r["matrix_type"] == matrix_type]
    return list_response(rows, S.rig_out)


@bp.get("/application-rigs/<rig_id>")
def get_rig(rig_id):
    auth(ALL_ROLES)
    return ok(S.rig_out(_rig(rig_id)))


# --- ApplicationTest --------------------------------------------------------

@bp.post("/application-tests")
def create_test():
    auth(["LabTech"])
    body = body_json()
    sample_lot_id = as_str(require(body, "sample_lot_id"), "sample_lot_id")
    rig_id = as_str(require(body, "rig_id"), "rig_id")
    window_start = as_datetime(require(body, "window_start"), "window_start")
    window_end = as_datetime(require(body, "window_end"), "window_end")
    dosage_pct = as_decimal(require(body, "dosage_pct"), "dosage_pct", 4,
                            gt=0, le=100)
    consumed_g = as_int(require(body, "consumed_g"), "consumed_g", minimum=1)

    lot = need(db.lots, sample_lot_id, "ERR_LOT_NOT_FOUND", "sample lot")
    rig = _rig(rig_id)

    if lot["disposition_status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASED",
             "the lot's disposition is %s" % lot["disposition_status"])

    if not window_start <= window_end:
        fail("ERR_INVALID_INTERVAL", "window_start must be at or before window_end")
    if ledger.rig_conflict(rig, window_start, window_end):
        fail("ERR_RIG_WINDOW_CONFLICT",
             "the rig is occupied within its cleanout buffer of that window")

    brief = graph.brief_of_lot(lot)
    if brief is None or rig["matrix_type"] != brief["matrix_type"]:
        fail("ERR_RIG_MATRIX_MISMATCH",
             "the rig is not plumbed for the brief's matrix type")
    if dosage_pct != brief["dosage_pct"]:
        fail("ERR_DOSAGE_MISMATCH",
             "the test dosage must equal the brief's dosage_pct")

    if consumed_g > ledger.available_g(lot):
        fail("ERR_INSUFFICIENT_SAMPLE_MASS",
             "the lot only offers %d unallocated gram(s)"
             % ledger.available_g(lot))

    test = base_entity()
    test.update({
        "sample_lot_id": lot["id"],
        "rig_id": rig["id"],
        "window_start": window_start,
        "window_end": window_end,
        "dosage_pct": dosage_pct,
        "consumed_g": consumed_g,
        "status": "SCHEDULED",
        "aroma_score": None,
        "taste_score": None,
        "stability_score": None,
        "panel_score": None,
        "verdict_recorded_at": None,
    })
    db.tests[test["id"]] = test
    ledger.reconcile_lot(lot)
    return created(S.test_out(test))


@bp.get("/application-tests")
def list_tests():
    auth(ALL_ROLES)
    sample_lot_id = request.args.get("sample_lot_id")
    rig_id = request.args.get("rig_id")
    status = request.args.get("status")
    rows = []
    for test in db.tests.values():
        if sample_lot_id is not None and test["sample_lot_id"] != sample_lot_id:
            continue
        if rig_id is not None and test["rig_id"] != rig_id:
            continue
        if status is not None and test["status"] != status:
            continue
        rows.append(test)
    return list_response(rows, S.test_out)


@bp.get("/application-tests/<test_id>")
def get_test(test_id):
    auth(ALL_ROLES)
    return ok(S.test_out(_test(test_id)))


@bp.post("/application-tests/<test_id>/start")
def start_test(test_id):
    auth(["LabTech"])
    body_json()
    test = _test(test_id)
    if test["status"] != "SCHEDULED":
        fail("ERR_TEST_STATE_INVALID",
             "cannot start a test in status %s" % test["status"])
    lot = db.lots.get(test["sample_lot_id"])
    if lot is None or lot["qc_status"] != "PASSED":
        fail("ERR_LOT_NOT_QC_PASSED", "the lot is no longer QC-passed")
    if lot["disposition_status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASED",
             "the lot's disposition is %s" % lot["disposition_status"])
    test["status"] = "IN_PROGRESS"
    touch(test)
    return ok(S.test_out(test))


@bp.post("/application-tests/<test_id>/result")
def record_result(test_id):
    auth(["LabTech"])
    body = body_json()
    aroma = as_decimal(require(body, "aroma_score"), "aroma_score", 2,
                       ge=0, le=100)
    taste = as_decimal(require(body, "taste_score"), "taste_score", 2,
                       ge=0, le=100)
    stability = as_decimal(require(body, "stability_score"), "stability_score",
                           2, ge=0, le=100)
    test = _test(test_id)
    if test["status"] != "IN_PROGRESS":
        fail("ERR_TEST_STATE_INVALID",
             "cannot record a result on a test in status %s" % test["status"])

    score = ledger.panel_score(aroma, taste, stability)
    test["aroma_score"] = aroma
    test["taste_score"] = taste
    test["stability_score"] = stability
    test["panel_score"] = score
    test["verdict_recorded_at"] = now_logical()
    test["status"] = ledger.panel_verdict(score)
    touch(test)

    lot = db.lots.get(test["sample_lot_id"])
    formula = db.formulas.get(lot["formula_id"]) if lot is not None else None
    brief = db.briefs.get(formula["brief_id"]) if formula is not None else None

    if test["status"] == "PASSED":
        if brief is not None:
            cascade.recompute_live_forecasts(brief)
    else:
        if formula is not None and formula["status"] == "APPROVED":
            cascade.formula_left_approved(formula, "APPLICATION_TEST_FAILURE")
    return ok(S.test_out(test))
