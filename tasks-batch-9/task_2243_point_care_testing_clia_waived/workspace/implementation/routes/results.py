"""Patient results and the medical-record posting cycle (PRD 3.6)."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import valid
from middleware import route
from services import derive

bp = Blueprint("results", __name__)

ALL_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor",
             "Operator")
COMPETENT = ("PROVISIONAL", "COMPETENT")


@route(bp, "/test-results", ["POST"], ["Operator"])
def capture_result(user_id, role):
    payload = valid.body()
    # Ranks 11, 12, 13 in precedence order.
    operator = valid.resolve_body("operators", payload, "operator_id")
    device = valid.resolve_body("devices", payload, "device_id")
    lot = valid.resolve_body("lots", payload, "reagent_lot_id")
    # Rank 20.
    patient_mrn = valid.req_str(payload, "patient_mrn")
    analyte = valid.req_str(payload, "analyte")
    measured_value = valid.req_num(payload, "measured_value")
    entry_mode = valid.req_enum(payload, "entry_mode", ("INTERFACED", "MANUAL"))
    manual_reason = valid.opt_str(payload, "manual_entry_reason")
    # Rank 21.
    if entry_mode == "MANUAL" and not (manual_reason or "").strip():
        raise errors.ApiError("ERR_MANUAL_ENTRY_REASON_REQUIRED", 400)
    # Rank 41.
    if device["status"] != "ACTIVE":
        raise errors.ApiError("ERR_DEVICE_QC_LOCKED", 409)
    # Rank 43.
    if lot["verification_status"] in ("QUARANTINED", "DISCARDED", "REJECTED"):
        raise errors.ApiError("ERR_LOT_QUARANTINED", 409)
    # Rank 44.
    if lot["verification_status"] != "VERIFIED":
        raise errors.ApiError("ERR_LOT_NOT_VERIFIED", 409)
    # Rank 50 — the reported analyte must match the instrument's.
    if analyte != device["analyte"]:
        raise errors.invalid_state(
            "The reported analyte does not match the instrument's analyte.")
    # Rank 52.
    if operator["access_status"] != "ACTIVE":
        raise errors.ApiError("ERR_OPERATOR_ACCESS_LOCKED", 422)
    # Rank 53.
    if operator["competency_status"] not in COMPETENT:
        raise errors.ApiError("ERR_OPERATOR_COMPETENCY_LAPSED", 422)
    # Rank 54.
    if clock.today() > clock.parse_date(lot["expiration_date"]):
        raise errors.ApiError("ERR_REAGENT_LOT_EXPIRED", 422)
    # Rank 55.
    derive.recompute_device_schedule(device)
    due = clock.parse_date(device["qc_next_due_at"]) if device["qc_next_due_at"] else None
    if due is None or clock.today() > due:
        raise errors.ApiError("ERR_QC_OVERDUE", 422)
    # Rank 59.
    if lot["device_model"] != device["device_model"]:
        raise errors.ApiError("ERR_LOT_DEVICE_MODEL_MISMATCH", 422)
    # Rank 60.
    if (operator["site_id"] != device["site_id"]
            or lot["site_id"] != device["site_id"]):
        raise errors.ApiError("ERR_CROSS_SITE_REFERENCE", 422)
    # Rank 66.
    site = derive.site_of_device(device)
    if entry_mode == "MANUAL":
        if (site is not None and site["manual_entry_blocked"]) \
                or device["manual_entry_suspended"]:
            raise errors.ApiError("ERR_MANUAL_ENTRY_NOT_PERMITTED", 422)

    row = db.insert("results", {
        "device_id": device["id"],
        "operator_id": operator["id"],
        "reagent_lot_id": lot["id"],
        "patient_mrn": patient_mrn,
        "analyte": analyte,
        "measured_value": measured_value,
        "entry_mode": entry_mode,
        "manual_entry_reason": manual_reason,
        "posted_value": None,
        "posting_status": "PENDING_REVIEW",
        "posted_by_user_id": None,
        "posted_at": None,
        "held_by_device_lock_at": None,
        "correction_count": 0,
        "correction_reason": None,
        "_corrected_value": None,
    })
    derive.recompute_device_rates(device)
    derive.recompute_site(site)
    return response.object_response(serializers.dump("results", row), 201)


@route(bp, "/test-results/<result_id>", ["GET"], ALL_ROLES)
def read_result(user_id, role, result_id):
    row = valid.resolve("results", result_id)
    return response.object_response(serializers.dump("results", row))


@route(bp, "/test-results", ["GET"], ALL_ROLES)
def list_results(user_id, role):
    limit, offset = valid.pagination()
    device_id = valid.arg("device_id")
    operator_id = valid.arg("operator_id")
    lot_id = valid.arg("reagent_lot_id")
    status = valid.arg("posting_status")
    items = [r for r in db.rows("results")
             if (device_id is None or r["device_id"] == device_id)
             and (operator_id is None or r["operator_id"] == operator_id)
             and (lot_id is None or r["reagent_lot_id"] == lot_id)
             and (status is None or r["posting_status"] == status)]
    return response.list_response(
        serializers.dump_many("results", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/test-results/<result_id>/post", ["POST"], ["Operator", "LabDirector"])
def post_result(user_id, role, result_id):
    result = valid.resolve("results", result_id)
    payload = valid.body()
    valid.req_str(payload, "attestation")
    device = db.get("devices", result["device_id"])
    # Rank 41.
    if device is None or device["status"] != "ACTIVE":
        raise errors.ApiError("ERR_DEVICE_QC_LOCKED", 409)
    # Rank 50.
    if result["posting_status"] not in ("PENDING_REVIEW", "CORRECTION_PENDING"):
        raise errors.invalid_state(
            "The result is not PENDING_REVIEW or CORRECTION_PENDING.")
    referenced = db.get("operators", result["operator_id"])
    acting = db.get("operators", user_id)
    # Rank 52 — referenced then acting operator.
    if referenced is not None and referenced["access_status"] != "ACTIVE":
        raise errors.ApiError("ERR_OPERATOR_ACCESS_LOCKED", 422)
    if acting is None or acting["access_status"] != "ACTIVE":
        raise errors.ApiError("ERR_OPERATOR_ACCESS_LOCKED", 422)
    # Rank 53.
    if referenced is not None and referenced["competency_status"] not in COMPETENT:
        raise errors.ApiError("ERR_OPERATOR_COMPETENCY_LAPSED", 422)
    if acting["competency_status"] not in COMPETENT:
        raise errors.ApiError("ERR_OPERATOR_COMPETENCY_LAPSED", 422)
    # Rank 60 — the acting user must belong to the instrument's site.
    if acting["site_id"] != device["site_id"]:
        raise errors.ApiError("ERR_CROSS_SITE_REFERENCE", 422)
    # Rank 65 (d).
    if result["entry_mode"] == "MANUAL" and user_id == result["operator_id"]:
        raise errors.ApiError("ERR_SEGREGATION_OF_DUTIES", 422)

    from_correction = result["posting_status"] == "CORRECTION_PENDING"
    result["posting_status"] = "POSTED"
    if from_correction and result.get("_corrected_value") is not None:
        result["posted_value"] = result["_corrected_value"]
    else:
        result["posted_value"] = result["measured_value"]
    result["posted_by_user_id"] = user_id
    result["posted_at"] = clock.now_iso()
    db.touch(result)

    derive.recompute_site(derive.site_of_device(device))
    return response.object_response(serializers.dump("results", result))


@route(bp, "/test-results/<result_id>/correct", ["POST"],
       ["Operator", "LabDirector"])
def correct_result(user_id, role, result_id):
    result = valid.resolve("results", result_id)
    payload = valid.body()
    corrected_value = valid.req_num(payload, "corrected_value")
    correction_reason = valid.req_str(payload, "correction_reason")
    expected_version = valid.req_int(payload, "expected_test_result_version")
    # Rank 30.
    if expected_version != result["version"]:
        raise errors.ApiError("ERR_STALE_VERSION", 412)
    device = db.get("devices", result["device_id"])
    # Rank 41.
    if device is None or device["status"] != "ACTIVE":
        raise errors.ApiError("ERR_DEVICE_QC_LOCKED", 409)
    # Rank 50.
    if result["posting_status"] != "POSTED":
        raise errors.invalid_state("Only a POSTED result can be corrected.")
    referenced = db.get("operators", result["operator_id"])
    acting = db.get("operators", user_id)
    # Rank 52.
    if referenced is not None and referenced["access_status"] != "ACTIVE":
        raise errors.ApiError("ERR_OPERATOR_ACCESS_LOCKED", 422)
    if acting is None or acting["access_status"] != "ACTIVE":
        raise errors.ApiError("ERR_OPERATOR_ACCESS_LOCKED", 422)
    # Rank 53.
    if referenced is not None and referenced["competency_status"] not in COMPETENT:
        raise errors.ApiError("ERR_OPERATOR_COMPETENCY_LAPSED", 422)

    result["posting_status"] = "CORRECTION_PENDING"
    result["correction_count"] = int(result["correction_count"] or 0) + 1
    result["correction_reason"] = correction_reason
    result["_corrected_value"] = corrected_value
    db.touch(result)

    derive.recompute_site(derive.site_of_device(device))
    return response.object_response(serializers.dump("results", result))
