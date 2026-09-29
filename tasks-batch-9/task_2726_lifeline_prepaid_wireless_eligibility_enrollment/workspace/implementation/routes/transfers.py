"""Porting a live benefit between carriers: the two-sided handshake of PRD 3.7."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (PROVIDER_AGENT, REJECTION_REASONS, ROLES_ALL,
                           TRANSFER_STATUSES, authenticate, get_enrollment,
                           get_provider, get_transfer)
from services import calc, derive

bp = Blueprint("transfers", __name__)


@bp.post("/lifeline/service-transfers")
def open_transfer():
    caller = authenticate((PROVIDER_AGENT,))

    body = v.get_body()
    enrollment_id = v.string_field(body, "enrollment_id")
    target_provider_id = v.string_field(body, "target_provider_id")
    consent_ref = v.string_field(body, "subscriber_consent_ref", min_len=1, max_len=64)
    expected_version = v.int_field(body, "expected_enrollment_version")

    enrollment = get_enrollment(enrollment_id)
    target = get_provider(target_provider_id)

    source_provider_id = enrollment["provider_id"]
    if caller.user_id != source_provider_id:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only the source carrier may open a port request")

    if expected_version != enrollment["version"]:
        raise ApiError("ERR_STALE_ENROLLMENT_VERSION",
                       "The enrollment version does not match")

    if enrollment["benefit_status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", "The benefit is not active")

    now = db.now()
    freeze_until = calc.port_freeze_until(enrollment["benefit_start_date"])
    if freeze_until is not None and now < freeze_until:
        raise ApiError("ERR_PORT_FREEZE_ACTIVE", "The porting freeze is active")

    if target_provider_id == source_provider_id:
        raise ApiError("ERR_TRANSFER_SAME_PROVIDER",
                       "The port must name a different carrier")

    for prior in db.by_created(derive.transfers_of_enrollment(enrollment_id)):
        if prior["status"] == "REQUESTED":
            prior["status"] = "SUPERSEDED"
            prior["completed_at"] = now
            db.touch(prior)

    row = db.base_row()
    row.update({
        "enrollment_id": enrollment_id,
        "source_provider_id": source_provider_id,
        "target_provider_id": target_provider_id,
        "subscriber_consent_ref": consent_ref,
        "status": "REQUESTED",
        "rejection_reason": None,
        "rejection_note": None,
        "acceptance_note": None,
        "requested_at": now,
        "completed_at": None,
        "port_freeze_until_snapshot": freeze_until,
    })
    db.db.service_transfers[row["id"]] = row
    db.touch(enrollment)
    return response.ok(derive.service_transfer_json(row), 201)


@bp.get("/lifeline/service-transfers/<transfer_id>")
def read_transfer(transfer_id):
    authenticate(ROLES_ALL)
    return response.ok(derive.service_transfer_json(get_transfer(transfer_id)))


@bp.get("/lifeline/service-transfers")
def list_transfers():
    authenticate(ROLES_ALL)
    enrollment_id = response.filter_str("enrollment_id")
    source_provider_id = response.filter_str("source_provider_id")
    target_provider_id = response.filter_str("target_provider_id")
    status = response.filter_enum("status", TRANSFER_STATUSES)
    rows = list(db.db.service_transfers.values())
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if source_provider_id is not None:
        rows = [r for r in rows if r["source_provider_id"] == source_provider_id]
    if target_provider_id is not None:
        rows = [r for r in rows if r["target_provider_id"] == target_provider_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(db.by_created(rows), derive.service_transfer_json)


def _decidable(transfer, caller):
    if caller.user_id != transfer["target_provider_id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only the gaining carrier may decide a port request")
    if transfer["status"] != "REQUESTED":
        raise ApiError("ERR_TRANSFER_NOT_REQUESTED",
                       "The port request is no longer open")


@bp.post("/lifeline/service-transfers/<transfer_id>/accept")
def accept_transfer(transfer_id):
    caller = authenticate((PROVIDER_AGENT,))
    transfer = get_transfer(transfer_id)

    body = v.get_body()
    note = v.string_field(body, "acceptance_note", required=False, default=None)

    _decidable(transfer, caller)

    enrollment = db.db.enrollments.get(transfer["enrollment_id"])
    if enrollment is None or enrollment["benefit_status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", "The benefit is not active")

    target = db.db.providers.get(transfer["target_provider_id"])
    if target is None or target["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", "The gaining carrier is not active")
    counters = derive.provider_counters(target)
    if counters["active_enrollment_count"] + 1 > target["enrollment_cap"]:
        raise ApiError("ERR_PROVIDER_ENROLLMENT_CAP_EXCEEDED",
                       "The gaining carrier has no room for the ported benefit")

    now = db.now()
    transfer["status"] = "ACCEPTED_COMPLETED"
    transfer["completed_at"] = now
    transfer["acceptance_note"] = note
    db.touch(transfer)

    source = db.db.providers.get(transfer["source_provider_id"])

    # Link one: the benefit changes carrier; every temporal anchor is preserved.
    enrollment["provider_id"] = transfer["target_provider_id"]

    # Link two: hardware never changes owner, so the handset is reclaimed.
    for device in db.by_created(derive.devices_of_enrollment(enrollment["id"])):
        if device["status"] == "ISSUED":
            device["status"] = "RECLAIM_PENDING"
            db.touch(device)
            if source is not None:
                db.touch(source)

            # Link three: the gaining carrier starts a fresh non-usage window.
            enrollment["device_status"] = "RECLAIM_PENDING"
            enrollment["usage_status"] = "PENDING_FIRST_USE"
            enrollment["last_usage_at"] = None
            enrollment["non_usage_flagged_at"] = None
            enrollment["cure_deadline_at"] = None
            break

    derive.recompute_risk(enrollment)
    db.touch(enrollment)

    if source is not None:
        db.touch(source)
    db.touch(target)

    return response.ok(derive.service_transfer_json(transfer))


@bp.post("/lifeline/service-transfers/<transfer_id>/reject")
def reject_transfer(transfer_id):
    caller = authenticate((PROVIDER_AGENT,))
    transfer = get_transfer(transfer_id)

    body = v.get_body()
    reason = v.enum_field(body, "rejection_reason", REJECTION_REASONS)
    note = v.string_field(body, "rejection_note", required=False, default=None)

    _decidable(transfer, caller)

    transfer["status"] = "REJECTED"
    transfer["rejection_reason"] = reason
    transfer["rejection_note"] = note
    transfer["completed_at"] = db.now()
    db.touch(transfer)
    return response.ok(derive.service_transfer_json(transfer))
