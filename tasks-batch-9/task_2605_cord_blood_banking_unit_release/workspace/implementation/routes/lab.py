"""Kit dispatch, collection at delivery, laboratory receipt and rejection."""
from datetime import timedelta

from flask import Blueprint

import calc
import services as svc
from errors import fail
from middleware import endpoint, get_body, v_enum, v_num, v_str, v_ts
from response import object_response
from store import base_row, db, iso, now, pdt, public, touch

bp = Blueprint("lab", __name__)

REJECTION_STATE = {
    "LATE": "REJECTED_LATE",
    "TEMP": "REJECTED_TEMP",
    "VOLUME": "REJECTED_VOLUME",
    "CONTAMINATION": "DISCARDED",
}


def _require_consent_current(enrollment):
    """Ladder rung 11 (PRD 2.11)."""
    if enrollment is None or enrollment["consent_status"] != "CONSENTED" \
            or enrollment["consent_version"] < 1:
        fail("ERR_CONSENT_NOT_CURRENT")


@bp.route("/cbb/collection-kits", methods=["POST"])
@endpoint("IntakeCoordinator", "PlatformAdmin")
def dispatch_kit(user_id, role):
    body = get_body()
    enrollment_id = v_str(body, "enrollment_id", min_len=1)
    lot = v_str(body, "kit_lot_code", min_len=1, max_len=30)
    tracking = v_str(body, "courier_tracking_code", min_len=1, max_len=40)
    enrollment = svc.get_enrollment(enrollment_id)

    if enrollment["lifecycle_status"] != "ACTIVE":
        fail("ERR_INVALID_ENROLLMENT_STATE")
    for kit in svc.enrollment_kits(enrollment_id):
        if kit["status"] in ("DISPATCHED", "HELD"):
            fail("ERR_INVALID_KIT_STATE")
    _require_consent_current(enrollment)

    dispatched = now()
    row = base_row()
    row.update({
        "enrollment_id": enrollment_id,
        "kit_lot_code": lot,
        "courier_tracking_code": tracking,
        "dispatched_at": iso(dispatched),
        "expires_at": iso(dispatched + timedelta(days=calc.KIT_SHELF_LIFE_DAYS)),
        "status": "DISPATCHED",
        "hold_reason_code": None,
    })
    db.kits[row["id"]] = row
    enrollment["lifecycle_status"] = "KIT_DISPATCHED"
    touch(enrollment)
    return object_response(public(row), 201)


@bp.route("/cbb/collections", methods=["POST"])
@endpoint("CollectionSite", "PlatformAdmin")
def record_collection(user_id, role):
    body = get_body()
    kit_id = v_str(body, "kit_id", min_len=1)
    collected_at = v_ts(body, "collected_at")
    gross = v_num(body, "collection_volume_ml", gt=0)
    anticoagulant = v_num(body, "anticoagulant_volume_ml", ge=0)
    mode = v_enum(body, "delivery_mode", ("VAGINAL", "CESAREAN"))
    if anticoagulant >= gross:
        fail("ERR_VALIDATION_FAILED",
             "anticoagulant_volume_ml must be below collection_volume_ml.")
    kit = svc.get_kit(kit_id)
    enrollment = db.enrollments.get(kit["enrollment_id"])

    if kit["status"] != "DISPATCHED":
        fail("ERR_INVALID_KIT_STATE")
    if enrollment is None or enrollment["lifecycle_status"] != "KIT_DISPATCHED":
        fail("ERR_INVALID_ENROLLMENT_STATE")
    _require_consent_current(enrollment)
    expires = pdt(kit["expires_at"])
    if expires is not None and expires < now():
        fail("ERR_KIT_EXPIRED")

    row = base_row()
    row.update({
        "kit_id": kit_id,
        "collected_at": iso(collected_at),
        "collection_volume_ml": calc.num(gross),
        "anticoagulant_volume_ml": calc.num(anticoagulant),
        "delivery_mode": mode,
        "transport_temp_c": None,
        "net_volume_ml": calc.num(calc.net_volume_ml(gross, anticoagulant)),
        "received_at": None,
        "hours_to_receipt": None,
        "status": "COLLECTED",
        "rejection_reason_code": None,
    })
    db.collections[row["id"]] = row
    kit["status"] = "USED"
    touch(kit)
    enrollment["lifecycle_status"] = "COLLECTED"
    touch(enrollment)
    return object_response(public(row), 201)


@bp.route("/cbb/collections/<cid>/receive", methods=["POST"])
@endpoint("ProcessingTechnologist", "PlatformAdmin")
def receive_collection(user_id, role, cid):
    body = get_body()
    temp = v_num(body, "transport_temp_c")
    collection = svc.get_collection(cid)
    kit = db.kits.get(collection["kit_id"])

    if collection["status"] != "COLLECTED":
        fail("ERR_INVALID_COLLECTION_STATE")
    if kit is None or kit["status"] != "USED":
        fail("ERR_INVALID_KIT_STATE")
    expires = pdt(kit["expires_at"])
    if expires is not None and expires < now():
        fail("ERR_KIT_EXPIRED")
    elapsed = calc.elapsed_hours_exact(pdt(collection["collected_at"]), now())
    if elapsed > calc.MAX_HOURS_COLLECTION_TO_RECEIPT:
        fail("ERR_PROCESSING_WINDOW_EXCEEDED")
    if temp < calc.MIN_TRANSPORT_TEMP_C or temp > calc.MAX_TRANSPORT_TEMP_C:
        fail("ERR_TRANSPORT_TEMP_OUT_OF_RANGE")

    collection["transport_temp_c"] = calc.num(temp)
    collection["received_at"] = iso(now())
    collection["hours_to_receipt"] = calc.num(calc.rhu(elapsed, 2))
    collection["status"] = "RECEIVED"
    touch(collection)
    mint_unit(collection, kit)
    return object_response(public(collection), 201)


def mint_unit(collection, kit):
    """PRD 3.2 -- the one and only way a CordBloodUnit comes into existence."""
    enrollment = db.enrollments.get(kit["enrollment_id"]) if kit else None
    account = None
    if enrollment is not None and enrollment["program_type"] == "PRIVATE_FAMILY":
        # Resolved once, at creation: collection -> kit -> enrollment -> account.
        account = svc.enrollment_account(enrollment["id"])
    db.unit_sequence += 1
    row = base_row()
    row.update({
        "collection_id": collection["id"],
        "tank_id": None,
        "storage_account_id": account["id"] if account is not None else None,
        "unit_registry_code": "CBU-%06d" % db.unit_sequence,
        "program_type": enrollment["program_type"] if enrollment else None,
        "processing_status": "RECEIVED",
        "availability_status": "UNAVAILABLE",
        "eligibility_status": "PENDING",
        "eligibility_reason_code": None,
        "eligibility_determined_by_user_id": None,
        "post_processing_volume_ml": None,
        "post_processing_tnc_millions": None,
        "post_processing_cd34_thousands": None,
        "post_processing_viability_pct": None,
        "quality_acceptance_score": None,
        "slot_code": None,
        "cryopreserved_at": None,
        "quarantine_reason_code": None,
        "disposition_reason": None,
        "disposed_at": None,
        "_enrollment_id": enrollment["id"] if enrollment else None,
    })
    db.units[row["id"]] = row
    return row


@bp.route("/cbb/collections/<cid>/reject", methods=["POST"])
@endpoint("ProcessingTechnologist", "MedicalDirector", "PlatformAdmin")
def reject_collection(user_id, role, cid):
    body = get_body()
    reason = v_enum(body, "reason_code", tuple(REJECTION_STATE))
    v_str(body, "note", required=False, min_len=0)
    collection = svc.get_collection(cid)

    if collection["status"] != "COLLECTED":
        fail("ERR_INVALID_COLLECTION_STATE")

    collection["status"] = REJECTION_STATE[reason]
    collection["rejection_reason_code"] = reason
    touch(collection)
    return object_response(public(collection))
