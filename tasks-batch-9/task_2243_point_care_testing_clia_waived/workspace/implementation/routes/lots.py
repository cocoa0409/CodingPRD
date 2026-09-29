"""Reagent lots and lot verification (PRD 3.5)."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import valid
from middleware import route
from services import calc, derive

bp = Blueprint("lots", __name__)

ALL_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor",
             "Operator")


@route(bp, "/reagent-lots", ["POST"], ["ProgramAdmin", "QualityCoordinator"])
def receive_lot(user_id, role):
    payload = valid.body()
    # Rank 10 then rank 14.
    site = valid.resolve_body("sites", payload, "site_id")
    unit = valid.resolve_body("storage_units", payload, "storage_unit_id")
    # Rank 20.
    device_model = valid.req_str(payload, "device_model")
    lot_number = valid.req_str(payload, "lot_number")
    expiration = valid.req_date(payload, "expiration_date")
    received_at = valid.req_datetime(payload, "received_at")
    min1 = valid.req_num(payload, "control_min_level_1")
    max1 = valid.req_num(payload, "control_max_level_1")
    min2 = valid.req_num(payload, "control_min_level_2")
    max2 = valid.req_num(payload, "control_max_level_2")
    if calc.dec(max1) <= calc.dec(min1):
        raise errors.invalid_request(
            "control_max_level_1 must be strictly greater than "
            "control_min_level_1.")
    if calc.dec(max2) <= calc.dec(min2):
        raise errors.invalid_request(
            "control_max_level_2 must be strictly greater than "
            "control_min_level_2.")
    if any(lot["site_id"] == site["id"]
           and lot["device_model"] == device_model
           and lot["lot_number"] == lot_number
           for lot in db.data["lots"].values()):
        raise errors.invalid_request(
            "lot_number must be unique for this site and device model.")
    # Rank 54.
    if clock.today() > expiration:
        raise errors.ApiError("ERR_REAGENT_LOT_EXPIRED", 422)
    # Rank 56.
    if unit["excursion_state"] != "IN_RANGE":
        raise errors.ApiError("ERR_TEMP_EXCURSION_ACTIVE", 422)
    # Rank 60.
    if unit["site_id"] != site["id"]:
        raise errors.ApiError("ERR_CROSS_SITE_REFERENCE", 422)

    row = db.insert("lots", {
        "site_id": site["id"],
        "storage_unit_id": unit["id"],
        "device_model": device_model,
        "lot_number": lot_number,
        "expiration_date": expiration.isoformat(),
        "received_at": clock.iso(received_at),
        "control_min_level_1": min1,
        "control_max_level_1": max1,
        "control_min_level_2": min2,
        "control_max_level_2": max2,
        "verification_status": "UNVERIFIED",
        "verified_at": None,
        "quarantine_reason": None,
    })
    return response.object_response(serializers.dump("lots", row), 201)


@route(bp, "/reagent-lots/<lot_id>", ["GET"], ALL_ROLES)
def read_lot(user_id, role, lot_id):
    row = valid.resolve("lots", lot_id)
    return response.object_response(serializers.dump("lots", row))


@route(bp, "/reagent-lots", ["GET"], ALL_ROLES)
def list_lots(user_id, role):
    limit, offset = valid.pagination()
    site_id = valid.arg("site_id")
    unit_id = valid.arg("storage_unit_id")
    status = valid.arg("verification_status")
    items = [lot for lot in db.rows("lots")
             if (site_id is None or lot["site_id"] == site_id)
             and (unit_id is None or lot["storage_unit_id"] == unit_id)
             and (status is None or lot["verification_status"] == status)]
    return response.list_response(
        serializers.dump_many("lots", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/reagent-lots/<lot_id>/verify", ["POST"],
       ["QualityCoordinator", "LabDirector"])
def verify_lot(user_id, role, lot_id):
    lot = valid.resolve("lots", lot_id)
    payload = valid.body()
    # Rank 14 — the two referenced control runs.
    run1 = valid.resolve_body("qc_runs", payload, "level_1_qc_run_id")
    run2 = valid.resolve_body("qc_runs", payload, "level_2_qc_run_id")
    site = db.get("sites", lot["site_id"])
    # Rank 42.
    if site is not None and site["oversight_posture"] == "SUSPENDED":
        raise errors.ApiError("ERR_SITE_OVERSIGHT_SUSPENDED", 409)
    # Rank 43.
    if lot["verification_status"] in ("QUARANTINED", "DISCARDED", "REJECTED"):
        raise errors.ApiError("ERR_LOT_QUARANTINED", 409)
    # Rank 50.
    if lot["verification_status"] != "UNVERIFIED":
        raise errors.invalid_state("The reagent lot is not UNVERIFIED.")
    # Rank 54.
    if clock.today() > clock.parse_date(lot["expiration_date"]):
        raise errors.ApiError("ERR_REAGENT_LOT_EXPIRED", 422)
    # Rank 61.
    if (run1["reagent_lot_id"] != lot["id"]
            or run2["reagent_lot_id"] != lot["id"]
            or run1["control_level"] != "LEVEL_1"
            or run2["control_level"] != "LEVEL_2"
            or run1["device_id"] != run2["device_id"]):
        raise errors.ApiError("ERR_QC_RUN_DEVICE_MISMATCH", 422)

    snap = db.snapshot(lot)
    if run1["result"] == "PASS" and run2["result"] == "PASS":
        lot["verification_status"] = "VERIFIED"
        lot["verified_at"] = clock.now_iso()
    else:
        lot["verification_status"] = "REJECTED"
    db.touch_if_changed(lot, snap)
    return response.object_response(serializers.dump("lots", lot))
