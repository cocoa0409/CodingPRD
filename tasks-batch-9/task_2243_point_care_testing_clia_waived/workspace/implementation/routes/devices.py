"""Instruments and the quality-control lock lifecycle (PRD 3.4)."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import valid
from middleware import route
from services import derive

bp = Blueprint("devices", __name__)

ALL_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor",
             "Operator")

CONNECTIVITY = ("INTERFACED", "MANUAL_ENTRY", "OFFLINE")


@route(bp, "/devices", ["POST"], ["ProgramAdmin"])
def install_device(user_id, role):
    payload = valid.body()
    site = valid.resolve_body("sites", payload, "site_id")
    device_model = valid.req_str(payload, "device_model")
    serial_number = valid.req_str(payload, "serial_number")
    analyte = valid.req_str(payload, "analyte")
    complexity = valid.req_enum(payload, "complexity_class", ("WAIVED", "MODERATE"))
    connectivity = valid.req_enum(payload, "connectivity_mode", CONNECTIVITY)
    frequency = valid.req_int(payload, "qc_frequency_days", 1)
    if any(d["serial_number"] == serial_number
           for d in db.data["devices"].values()):
        raise errors.invalid_request("serial_number must be unique.")

    # Rank 57 — the site must hold in-force coverage today.
    coverage = derive.in_window_coverage(site["id"])
    if coverage is not None:
        certificate = db.get("certificates", coverage["certificate_id"])
        expiration = clock.parse_date(certificate["expiration_date"])
        if expiration is None or expiration < clock.today():
            coverage = None
    if coverage is None:
        raise errors.ApiError("ERR_CERTIFICATE_EXPIRED", 422)
    # Rank 62.
    if (complexity == "MODERATE"
            and coverage["permitted_complexity_snapshot"] != "MODERATE"):
        raise errors.ApiError("ERR_COMPLEXITY_SCOPE_EXCEEDED", 422)

    row = db.insert("devices", {
        "site_id": site["id"],
        "device_model": device_model,
        "serial_number": serial_number,
        "analyte": analyte,
        "complexity_class": complexity,
        "connectivity_mode": connectivity,
        "qc_frequency_days": frequency,
        "status": "ACTIVE",
        "qc_lock_reason": None,
        "manual_entry_suspended": False,
        "last_two_level_qc_pass_on": None,
        "qc_next_due_at": None,
        "use_day_count": 0,
        "qc_compliance_rate_calendar": 100.00,
        "qc_compliance_rate_day_of_use": 100.00,
        "retirement_reason": None,
    })
    row["qc_next_due_at"] = row["created_at"][:10]
    # Installation recomputes the site aggregates but not this device's rates.
    derive.recompute_site(site)
    return response.object_response(serializers.dump("devices", row), 201)


@route(bp, "/devices/<device_id>", ["GET"], ALL_ROLES)
def read_device(user_id, role, device_id):
    device = valid.resolve("devices", device_id)
    derive.recompute_device_rates(device)
    return response.object_response(serializers.dump("devices", device))


@route(bp, "/devices", ["GET"], ALL_ROLES)
def list_devices(user_id, role):
    limit, offset = valid.pagination()
    for device in db.rows("devices"):
        derive.recompute_device_rates(device)
    site_id = valid.arg("site_id")
    status = valid.arg("status")
    items = [d for d in db.rows("devices")
             if (site_id is None or d["site_id"] == site_id)
             and (status is None or d["status"] == status)]
    return response.list_response(
        serializers.dump_many("devices", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/devices/<device_id>/qc-unlock", ["POST"],
       ["QualityCoordinator", "LabDirector"])
def qc_unlock(user_id, role, device_id):
    device = valid.resolve("devices", device_id)
    payload = valid.body()
    # Rank 14 — the confirming control run.
    run = valid.resolve_body("qc_runs", payload, "confirming_qc_run_id")
    valid.opt_str(payload, "note")
    # Rank 44 — the confirming run's lot must be VERIFIED.
    lot = db.get("lots", run["reagent_lot_id"])
    if lot is None or lot["verification_status"] != "VERIFIED":
        raise errors.ApiError("ERR_LOT_NOT_VERIFIED", 409)
    # Rank 50.
    if device["status"] != "QC_LOCKED":
        raise errors.invalid_state("The instrument is not QC_LOCKED.")
    if device["qc_lock_reason"] == "CERTIFICATE_SCOPE":
        raise errors.invalid_state(
            "A CERTIFICATE_SCOPE lock cannot be cleared by quality control.")
    if run["result"] != "PASS":
        raise errors.invalid_state("The confirming control run did not PASS.")
    # Rank 61.
    if run["device_id"] != device["id"]:
        raise errors.ApiError("ERR_QC_RUN_DEVICE_MISMATCH", 422)

    snap = db.snapshot(device)
    device["status"] = "ACTIVE"
    device["qc_lock_reason"] = None
    db.touch_if_changed(device, snap)
    derive.recompute_device_schedule(device)

    # Compensating action: release only the results this lock held.
    for result in derive.results_of_device(device["id"]):
        if result["posting_status"] != "HELD":
            continue
        if result["held_by_device_lock_at"] is None:
            continue
        rsnap = db.snapshot(result)
        result["posting_status"] = "PENDING_REVIEW"
        result["held_by_device_lock_at"] = None
        db.touch_if_changed(result, rsnap)

    site = derive.site_of_device(device)
    derive.recompute_device_rates(device)
    derive.recompute_site(site)
    return response.object_response(serializers.dump("devices", device))


@route(bp, "/devices/<device_id>/retire", ["POST"], ["ProgramAdmin"])
def retire_device(user_id, role, device_id):
    device = valid.resolve("devices", device_id)
    payload = valid.body()
    reason = valid.req_str(payload, "reason")
    # Rank 50.
    if device["status"] not in ("ACTIVE", "QC_LOCKED"):
        raise errors.invalid_state("The instrument is already RETIRED.")
    blocking = {"PENDING_REVIEW", "HELD", "CORRECTION_PENDING"}
    if any(r["posting_status"] in blocking
           for r in db.data["results"].values()
           if r["device_id"] == device["id"]):
        raise errors.invalid_state(
            "Unfinished patient results block retirement.")

    snap = db.snapshot(device)
    device["status"] = "RETIRED"
    device["retirement_reason"] = reason
    device["qc_lock_reason"] = None
    db.touch_if_changed(device, snap)

    derive.recompute_site(derive.site_of_device(device))
    return response.object_response(serializers.dump("devices", device))
