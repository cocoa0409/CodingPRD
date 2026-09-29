"""SampleLot, RetentionCabinet and RetentionSample endpoints (PRD §3.6)."""

from flask import Blueprint, request

import constants as K
import serializers as S
from db import base_entity, db, now_logical, touch
from errors import fail
from middleware import ALL_ROLES, auth
from response import created, ok
from routes.common import list_response, need
from services import ledger
from validate import (as_datetime, as_decimal, as_enum, as_int, as_str,
                      body_json, optional, present, require)

bp = Blueprint("lots", __name__)


def _lot(lot_id):
    return need(db.lots, lot_id, "ERR_LOT_NOT_FOUND", "sample lot")


def _cabinet(cabinet_id):
    return need(db.cabinets, cabinet_id, "ERR_CABINET_NOT_FOUND",
                "retention cabinet")


def _retention(retention_id):
    return need(db.retentions, retention_id, "ERR_RETENTION_NOT_FOUND",
                "retention sample")


# --- SampleLot --------------------------------------------------------------

@bp.post("/sample-lots")
def create_lot():
    user_id, _role = auth(["LabTech"])
    body = body_json()
    formula_id = as_str(require(body, "formula_id"), "formula_id")
    batch_size_g = as_int(require(body, "batch_size_g"), "batch_size_g",
                          minimum=1, maximum=5000)
    formula = need(db.formulas, formula_id, "ERR_FORMULA_NOT_FOUND", "formula")
    if formula["status"] != "APPROVED":
        fail("ERR_FORMULA_NOT_APPROVED",
             "cannot compound from a formula in status %s" % formula["status"])
    brief = db.briefs.get(formula["brief_id"])

    lot = base_entity()
    lot.update({
        "formula_id": formula["id"],
        "lot_number": ledger.mint_lot_number(formula, brief),
        "formula_iteration_no": formula["iteration_no"],
        "batch_size_g": batch_size_g,
        "qc_status": "PENDING",
        "disposition_status": "HELD",
        "compounded_by_user_id": user_id,
        "qc_by_user_id": None,
    })
    db.lots[lot["id"]] = lot
    return created(S.lot_out(lot))


@bp.get("/sample-lots")
def list_lots():
    auth(ALL_ROLES)
    formula_id = request.args.get("formula_id")
    qc_status = request.args.get("qc_status")
    disposition_status = request.args.get("disposition_status")
    rows = []
    for lot in db.lots.values():
        if formula_id is not None and lot["formula_id"] != formula_id:
            continue
        if qc_status is not None and lot["qc_status"] != qc_status:
            continue
        if disposition_status is not None and \
                lot["disposition_status"] != disposition_status:
            continue
        rows.append(lot)
    return list_response(rows, S.lot_out)


@bp.get("/sample-lots/<lot_id>")
def get_lot(lot_id):
    auth(ALL_ROLES)
    return ok(S.lot_out(_lot(lot_id)))


@bp.post("/sample-lots/<lot_id>/qc")
def record_qc(lot_id):
    user_id, _role = auth(["LabTech"])
    body = body_json()
    result = as_enum(require(body, "result"), "result", ("PASSED", "FAILED"))
    if present(body, "qc_note"):
        as_str(body["qc_note"], "qc_note")

    lot = _lot(lot_id)
    if lot["qc_status"] != "PENDING":
        fail("ERR_LOT_STATE_INVALID",
             "the QC verdict is already %s" % lot["qc_status"])
    if lot["compounded_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the QC recorder may not be the compounder")

    lot["qc_status"] = result
    lot["qc_by_user_id"] = user_id
    if result == "FAILED" and lot["disposition_status"] == "HELD":
        lot["disposition_status"] = "SCRAPPED"
    touch(lot)
    return ok(S.lot_out(lot))


@bp.post("/sample-lots/<lot_id>/release")
def release_lot(lot_id):
    auth(["LabTech"])
    body_json()
    lot = _lot(lot_id)
    if lot["disposition_status"] != "HELD":
        fail("ERR_LOT_STATE_INVALID",
             "cannot release a lot in disposition %s" % lot["disposition_status"])
    if lot["qc_status"] != "PASSED":
        fail("ERR_LOT_NOT_QC_PASSED",
             "the lot's QC status is %s" % lot["qc_status"])
    formula = db.formulas.get(lot["formula_id"])
    if formula is None or formula["status"] != "APPROVED":
        fail("ERR_FORMULA_NOT_APPROVED",
             "the lot's formula is no longer APPROVED")
    lot["disposition_status"] = "RELEASED"
    touch(lot)
    return ok(S.lot_out(lot))


# --- RetentionCabinet -------------------------------------------------------

@bp.post("/retention-cabinets")
def create_cabinet():
    auth(["LabTech"])
    body = body_json()
    cabinet_code = as_str(require(body, "cabinet_code"), "cabinet_code", 1, 40)
    capacity_slots = as_int(require(body, "capacity_slots"), "capacity_slots",
                            minimum=1, maximum=200)
    # no decimal-place constraint is declared for storage_temp_c
    storage_temp_c = as_decimal(require(body, "storage_temp_c"),
                                "storage_temp_c", 6, ge=-40, le=30)
    for existing in db.cabinets.values():
        if existing["cabinet_code"] == cabinet_code:
            fail("ERR_DUPLICATE_CODE",
                 "cabinet_code %s already exists" % cabinet_code)

    cabinet = base_entity()
    cabinet.update({
        "cabinet_code": cabinet_code,
        "capacity_slots": capacity_slots,
        "storage_temp_c": storage_temp_c,
    })
    db.cabinets[cabinet["id"]] = cabinet
    return created(S.cabinet_out(cabinet))


@bp.get("/retention-cabinets")
def list_cabinets():
    auth(ALL_ROLES)
    return list_response(list(db.cabinets.values()), S.cabinet_out)


@bp.get("/retention-cabinets/<cabinet_id>")
def get_cabinet(cabinet_id):
    auth(ALL_ROLES)
    return ok(S.cabinet_out(_cabinet(cabinet_id)))


# --- RetentionSample --------------------------------------------------------

@bp.post("/retention-samples")
def create_retention():
    auth(["LabTech"])
    body = body_json()
    sample_lot_id = as_str(require(body, "sample_lot_id"), "sample_lot_id")
    cabinet_id = as_str(require(body, "cabinet_id"), "cabinet_id")
    quantity_g = as_int(require(body, "quantity_g"), "quantity_g", minimum=1)
    stored_from = as_datetime(require(body, "stored_from"), "stored_from")
    stored_until = as_datetime(require(body, "stored_until"), "stored_until")

    lot = _lot(sample_lot_id)
    cabinet = _cabinet(cabinet_id)

    if lot["disposition_status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASED",
             "the lot's disposition is %s" % lot["disposition_status"])

    slot_count = ledger.slot_count_for(quantity_g)
    occupied = ledger.occupied_slots(cabinet["id"], stored_from, stored_until)
    if occupied + slot_count > cabinet["capacity_slots"]:
        fail("ERR_CABINET_CAPACITY_EXCEEDED",
             "the cabinet cannot admit %d more slot(s) over that interval"
             % slot_count)

    if not stored_from < stored_until:
        fail("ERR_INVALID_INTERVAL", "stored_from must precede stored_until")
    if not ledger.retention_period_ok(stored_from, stored_until):
        fail("ERR_RETENTION_PERIOD_TOO_SHORT",
             "the retention interval must span at least %d days"
             % K.RETENTION_MIN_PERIOD_DAYS)

    if quantity_g > ledger.available_g(lot):
        fail("ERR_INSUFFICIENT_SAMPLE_MASS",
             "the lot only offers %d unallocated gram(s)"
             % ledger.available_g(lot))

    retention = base_entity()
    retention.update({
        "sample_lot_id": lot["id"],
        "cabinet_id": cabinet["id"],
        "quantity_g": quantity_g,
        "slot_count": slot_count,
        "stored_from": stored_from,
        "stored_until": stored_until,
        "status": "STORED",
        "withdrawal_reason": None,
        "withdrawn_at": None,
    })
    db.retentions[retention["id"]] = retention
    ledger.reconcile_lot(lot)
    return created(S.retention_out(retention))


@bp.get("/retention-samples")
def list_retentions():
    auth(ALL_ROLES)
    sample_lot_id = request.args.get("sample_lot_id")
    cabinet_id = request.args.get("cabinet_id")
    status = request.args.get("status")
    rows = []
    for row in db.retentions.values():
        if sample_lot_id is not None and row["sample_lot_id"] != sample_lot_id:
            continue
        if cabinet_id is not None and row["cabinet_id"] != cabinet_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return list_response(rows, S.retention_out)


@bp.get("/retention-samples/<retention_id>")
def get_retention(retention_id):
    auth(ALL_ROLES)
    return ok(S.retention_out(_retention(retention_id)))


@bp.post("/retention-samples/<retention_id>/withdraw")
def withdraw_retention(retention_id):
    auth(["LabTech"])
    body = body_json()
    reason = as_str(require(body, "withdrawal_reason"), "withdrawal_reason")
    retention = _retention(retention_id)
    if retention["status"] != "STORED":
        fail("ERR_RETENTION_STATE_INVALID",
             "the aliquot is already %s" % retention["status"])
    retention["status"] = "WITHDRAWN"
    retention["withdrawal_reason"] = reason
    retention["withdrawn_at"] = now_logical()
    touch(retention)
    lot = db.lots.get(retention["sample_lot_id"])
    if lot is not None:
        ledger.reconcile_lot(lot)
    return ok(S.retention_out(retention))
