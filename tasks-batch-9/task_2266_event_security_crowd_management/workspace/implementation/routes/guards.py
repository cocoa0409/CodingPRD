"""Guard endpoints (PRD 3.5)."""

from flask import Blueprint

import engine
import serial
import valid
from auth import authenticate, check_action_authority, require_action
from db import clock_iso, db, make_record, now, now_iso, parse_iso, touch
from errors import ApiError
from response import object_response
from routes._common import get_guard, match_filters, paginated
from routes.vendors import license_in_use

bp = Blueprint("guards", __name__)

EMPLOYMENT_TYPES = ("EMPLOYEE", "SUBCONTRACTED")
VERIFICATION_STATUSES = (
    "UNVERIFIED",
    "PENDING_REVIEW",
    "VERIFIED",
    "REJECTED",
    "EXPIRED",
    "DISQUALIFIED",
)
SUPERVISOR_MIN_CREDENTIAL_LEVEL = 3


def _refresh_vendor(guard):
    vendor_id = guard.get("subcontractor_id")
    if not vendor_id:
        return
    vendor = db.subcontractors.get(vendor_id)
    if vendor is None:
        return
    if engine.recompute_vendor_guard_count(vendor):
        touch(vendor)


@bp.post("/guards")
def create_guard():
    actor = authenticate({"StaffingCoordinator", "SubcontractorLiaison"})
    payload = valid.body()
    full_name = valid.req_string(payload, "full_name")
    employment_type = valid.req_enum(payload, "employment_type", EMPLOYMENT_TYPES)
    subcontractor_id = valid.opt_string(payload, "subcontractor_id")
    credential_level = valid.req_int(payload, "credential_level", minimum=1, maximum=4)
    license_number = valid.req_string(payload, "license_number")
    credential_expires_on = valid.req_datetime(payload, "credential_expires_on")
    base_hourly_rate_cents = valid.req_int(payload, "base_hourly_rate_cents", minimum=1)

    if employment_type == "SUBCONTRACTED" and subcontractor_id is None:
        valid.bad("Field 'subcontractor_id' is required for a SUBCONTRACTED guard.")
    if employment_type == "EMPLOYEE" and subcontractor_id is not None:
        valid.bad("Field 'subcontractor_id' must be absent for an EMPLOYEE guard.")

    if subcontractor_id is not None and db.subcontractors.get(subcontractor_id) is None:
        raise ApiError("ERR_SUBCONTRACTOR_NOT_FOUND")

    if actor.is_liaison and subcontractor_id != actor.user_id:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "A liaison may only source guards for their own subcontractor.",
        )

    if license_in_use(license_number):
        raise ApiError("ERR_DUPLICATE_LICENSE_NUMBER")

    record = make_record(
        {
            "full_name": full_name,
            "employment_type": employment_type,
            "subcontractor_id": subcontractor_id,
            "credential_level": credential_level,
            "license_number": license_number,
            "credential_expires_on": credential_expires_on[0],
            "base_hourly_rate_cents": base_hourly_rate_cents,
            "verification_status": "UNVERIFIED",
            "verified_at": None,
            "is_supervisor_qualified": credential_level >= SUPERVISOR_MIN_CREDENTIAL_LEVEL,
        }
    )
    db.guards[record["id"]] = record
    return object_response(serial.guard(record), 201)


@bp.get("/guards/<guard_id>")
def read_guard(guard_id):
    authenticate(
        {
            "SecurityDirector",
            "StaffingCoordinator",
            "CredentialAuditor",
            "IncidentCommander",
            "PostSupervisor",
            "SubcontractorLiaison",
        }
    )
    guard = get_guard(guard_id)
    return object_response(serial.guard(guard))


@bp.get("/guards")
def list_guards():
    authenticate(
        {"SecurityDirector", "StaffingCoordinator", "CredentialAuditor", "SubcontractorLiaison"}
    )
    filters = {
        "subcontractor_id": valid.query_string("subcontractor_id"),
        "verification_status": valid.query_enum("verification_status", VERIFICATION_STATUSES),
        "employment_type": valid.query_enum("employment_type", EMPLOYMENT_TYPES),
    }
    records = [g for g in db.guards.values() if match_filters(g, filters)]
    return paginated(records, serial.guard)


@bp.post("/guards/<guard_id>/credential-verification")
def credential_verification(guard_id):
    actor = authenticate({"StaffingCoordinator", "CredentialAuditor", "SubcontractorLiaison"})
    payload = valid.body()
    action = require_action(payload, "cred_verification")
    check_action_authority(actor, "cred_verification", action)
    supplied_expiry = valid.opt_datetime(payload, "credential_expires_on")
    supplied_level = valid.opt_int(payload, "credential_level", minimum=1, maximum=4)

    guard = get_guard(guard_id)
    status = guard.get("verification_status")

    if actor.is_liaison and guard.get("subcontractor_id") != actor.user_id:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "A liaison may only act on their own subcontractor's guards.",
        )

    if action == "SUBMIT_FOR_REVIEW":
        if status not in ("UNVERIFIED", "VERIFIED", "REJECTED", "EXPIRED"):
            raise ApiError("ERR_INVALID_STATE", "This guard may not be submitted for review.")
        if status == "EXPIRED":
            if supplied_expiry is None:
                valid.bad("Field 'credential_expires_on' is required from EXPIRED.")
            if supplied_expiry[1] <= now():
                raise ApiError("ERR_GUARD_CREDENTIAL_INVALID")
            guard["credential_expires_on"] = supplied_expiry[0]
        elif status == "REJECTED":
            if supplied_expiry is not None:
                guard["credential_expires_on"] = supplied_expiry[0]
            if supplied_level is not None:
                guard["credential_level"] = supplied_level
                guard["is_supervisor_qualified"] = (
                    supplied_level >= SUPERVISOR_MIN_CREDENTIAL_LEVEL
                )
        guard["verification_status"] = "PENDING_REVIEW"
        touch(guard)
        _refresh_vendor(guard)

    elif action == "VERIFY":
        if status not in ("UNVERIFIED", "PENDING_REVIEW"):
            raise ApiError("ERR_INVALID_STATE", "This guard may not be verified from here.")
        expires = parse_iso(guard.get("credential_expires_on"))
        if expires is None or expires <= now():
            raise ApiError("ERR_GUARD_CREDENTIAL_INVALID")
        if guard.get("employment_type") == "SUBCONTRACTED":
            vendor = db.subcontractors.get(guard.get("subcontractor_id"))
            vendor_expiry = parse_iso(vendor.get("insurance_expires_on")) if vendor else None
            if (
                vendor is None
                or vendor.get("status") != "APPROVED"
                or vendor_expiry is None
                or vendor_expiry <= now()
            ):
                raise ApiError("ERR_SUBCONTRACTOR_NOT_ELIGIBLE")
        guard["verification_status"] = "VERIFIED"
        guard["verified_at"] = clock_iso()
        touch(guard)
        _refresh_vendor(guard)

    elif action == "REJECT":
        if status != "PENDING_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Only a guard under review may be rejected.")
        guard["verification_status"] = "REJECTED"
        guard["verified_at"] = None
        touch(guard)
        engine.void_assignments_for_guard(guard)
        _refresh_vendor(guard)

    else:  # DISQUALIFY
        if status != "REJECTED":
            raise ApiError("ERR_INVALID_STATE", "Only a REJECTED guard may be disqualified.")
        guard["verification_status"] = "DISQUALIFIED"
        touch(guard)
        _refresh_vendor(guard)

    return object_response(serial.guard(guard))
