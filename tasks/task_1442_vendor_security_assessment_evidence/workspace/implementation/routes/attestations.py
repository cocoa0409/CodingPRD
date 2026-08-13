"""OffboardingAttestation lifecycle (PRD §3.9): REQUESTED -> SUBMITTED ->
VERIFIED (vendor OFFBOARDED) or REJECTED (compensation loop with a fresh
REQUESTED attestation and a 30-day deadline extension).
"""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import helpers
import util
from errors import ApiError
from middleware import body, paginate, require_roles, scope_vendor_or_403
from response import ok, ok_list
from serializers import serialize

bp = Blueprint("attestations", __name__,
               url_prefix="/vsa/vendors/<vid>/offboarding-attestations")


def _resolve(vid, aid):
    vendor = helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    attestation = helpers.get_vendor_child(db.attestations, vendor, aid,
                                           "OffboardingAttestation")
    return vendor, attestation


@bp.get("")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_attestations(vid):
    helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    items = [a for a in db.attestations.values() if a["vendor_id"] == vid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("attestation", a) for a in page],
                   limit, offset, total)


@bp.post("/<aid>/submit")
@require_roles("VendorContact")
def submit_attestation(vid, aid):
    vendor, attestation = _resolve(vid, aid)
    if attestation["status"] != "REQUESTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a REQUESTED attestation can be submitted")
    if vendor["posture"] != "OFFBOARDING":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Vendor is not in OFFBOARDING")
    # Deadline (priority 7): submission by offboarding_deadline.
    if vendor.get("offboarding_deadline") \
            and util.now() > util.parse_dt(vendor["offboarding_deadline"]):
        raise ApiError(errors.ERR_DEADLINE_PASSED, 422,
                       "offboarding_deadline has passed")
    data = body()
    data_returned = data.get("data_returned")
    data_destroyed = data.get("data_destroyed")
    destruction_method = data.get("destruction_method")
    attested_by = data.get("attested_by")
    # Schema + semantic completeness (shared priority 8).
    if not isinstance(data_returned, bool) or not isinstance(data_destroyed, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "data_returned and data_destroyed must be booleans")
    if not isinstance(attested_by, str) or not attested_by:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "attested_by is required")
    if data_destroyed and (not isinstance(destruction_method, str)
                           or not destruction_method):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "destruction_method is required when data_destroyed is true")
    if not data_returned and not data_destroyed:
        raise ApiError(errors.ERR_ATTESTATION_INCOMPLETE, 422,
                       "Attestation must assert data return or destruction")
    attestation["data_returned"] = data_returned
    attestation["data_destroyed"] = data_destroyed
    attestation["destruction_method"] = destruction_method
    attestation["attested_by"] = attested_by
    attestation["submitted_at"] = util.iso(util.now())
    attestation["status"] = "SUBMITTED"
    helpers.touch("attestations", attestation)
    return ok(serialize("attestation", attestation))


@bp.post("/<aid>/verify")
@require_roles("RiskAnalyst")
def verify_attestation(vid, aid):
    vendor, attestation = _resolve(vid, aid)
    if attestation["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED attestation can be verified")
    # Offboarding blockers (priority 22): non-terminal cycle or live alerts.
    if helpers.non_terminal_cycle(vendor) is not None or any(
            a["vendor_id"] == vid and a["status"] in ("OPEN", "ACKNOWLEDGED")
            for a in db.alerts.values()):
        raise ApiError(errors.ERR_OFFBOARDING_BLOCKED, 422,
                       "Vendor has a non-terminal cycle or unresolved alerts")
    attestation["status"] = "VERIFIED"
    vendor["posture"] = "OFFBOARDED"
    vendor["active_cycle_id"] = None
    vendor["next_reassessment_due"] = None
    helpers.touch("attestations", attestation)
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)
    return ok(serialize("attestation", attestation))


@bp.post("/<aid>/reject")
@require_roles("RiskAnalyst")
def reject_attestation(vid, aid):
    vendor, attestation = _resolve(vid, aid)
    if attestation["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED attestation can be rejected")
    attestation["status"] = "REJECTED"
    helpers.touch("attestations", attestation)
    # Compensation loop: fresh REQUESTED attestation + 30-day slip.
    fresh = {
        "vendor_id": vid,
        "data_returned": None,
        "data_destroyed": None,
        "destruction_method": None,
        "attested_by": None,
        "status": "REQUESTED",
        "submitted_at": None,
    }
    helpers.stamp_new("attestations", fresh)
    db.attestations[fresh["id"]] = fresh
    previous_due = (util.parse_dt(vendor["offboarding_deadline"])
                    if vendor.get("offboarding_deadline") else None)
    base = previous_due if previous_due is not None else util.now()
    new_due = base + timedelta(days=30)
    vendor["offboarding_deadline"] = util.iso(new_due)
    helpers.append_schedule(vid, "OFFBOARDING_SLIP", previous_due, new_due,
                            attestation["id"])
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)
    return ok(serialize("attestation", attestation))
