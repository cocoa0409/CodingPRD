"""DirectoryCorrection endpoints: manual create, list, get, verify."""

from datetime import timedelta

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("corrections", __name__)

CORRECTION_STATUSES = {"SUBMITTED", "VERIFIED", "REJECTED"}
CORRECTION_SLA_HOURS = 72


@bp.route("/network/corrections", methods=["POST"])
@require_roles("NetworkManager")
def create_correction(user_id, role):
    body = helpers.get_body()
    listing_id = helpers.req_str(body, "listing_id")
    changes = body.get("changes")
    if not isinstance(changes, dict) or len(changes) == 0:
        raise errors.err_invalid("changes must be a non-empty object")
    bad_keys = set(changes.keys()) - helpers.CORRECTION_MUTABLE_FIELDS
    if bad_keys:
        raise errors.err_invalid(f"changes contains non-correction-mutable keys: {sorted(bad_keys)}")
    complaint_id = helpers.opt_str(body, "complaint_id")
    listing = db.listings.get(listing_id)
    if listing is None:
        raise errors.err_listing_not_found()
    complaint = None
    if complaint_id is not None:
        complaint = db.complaints.get(complaint_id)
        if complaint is None:
            raise errors.err_complaint_not_found()
    if listing["status"] == "REMOVED":
        raise errors.err_listing_removed()
    if complaint is not None:
        if complaint["listing_id"] != listing_id:
            raise errors.err_correction_listing_mismatch()
        if complaint["status"] != "CONFIRMED_ERROR":
            raise errors.err_correction_listing_mismatch()
    sla = db.clock_now + timedelta(hours=CORRECTION_SLA_HOURS)
    rec = {
        "listing_id": listing_id, "complaint_id": complaint_id,
        "changes": changes, "submitted_by_user_id": user_id,
        "sla_due_at": helpers._dt_to_iso(sla), "is_late": False,
        "status": "SUBMITTED", "verified_at": None, "verified_by_user_id": None,
    }
    helpers.stamp_new(rec)
    db.corrections[rec["id"]] = rec
    return success_object(helpers.ser_correction(rec), 201)


@bp.route("/network/corrections", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_corrections(user_id, role):
    limit, offset = helpers.get_pagination()
    listing_id = helpers.query_str("listing_id")
    complaint_id = helpers.query_str("complaint_id")
    status = helpers.query_enum("status", CORRECTION_STATUSES)
    items = list(db.corrections.values())
    if listing_id is not None:
        items = [c for c in items if c["listing_id"] == listing_id]
    if complaint_id is not None:
        items = [c for c in items if c["complaint_id"] == complaint_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_correction(c) for c in page], limit, offset, total)


@bp.route("/network/corrections/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_correction(user_id, role, cid):
    rec = db.corrections.get(cid)
    if rec is None:
        raise errors.err_correction_not_found()
    return success_object(helpers.ser_correction(rec))


@bp.route("/network/corrections/<cid>/verify", methods=["POST"])
@require_roles("ComplianceOfficer")
def verify_correction(user_id, role, cid):
    rec = db.corrections.get(cid)
    if rec is None:
        raise errors.err_correction_not_found()
    if rec["status"] != "SUBMITTED":
        raise errors.err_correction_not_verifiable()
    # segregation of duties
    if user_id == rec["submitted_by_user_id"]:
        raise errors.err_segregation()
    body = helpers.get_body()
    approve = body.get("approve", True)
    if not isinstance(approve, bool):
        raise errors.err_invalid("approve must be a boolean")
    if not approve:
        rec["status"] = "REJECTED"
        helpers.touch(rec)
        return success_object(helpers.ser_correction(rec))
    # VERIFIED
    now = helpers.now_iso()
    rec["status"] = "VERIFIED"
    rec["verified_at"] = now
    rec["verified_by_user_id"] = user_id
    rec["is_late"] = now > rec["sla_due_at"]
    helpers.touch(rec)
    # apply changes to the listing's correction-mutable fields
    listing = db.listings.get(rec["listing_id"])
    if listing is not None:
        for key, value in rec["changes"].items():
            if key in helpers.CORRECTION_MUTABLE_FIELDS:
                listing[key] = value
        # cascade: linked CONFIRMED_ERROR complaint -> CLOSED; clear data-error flag
        if rec["complaint_id"] is not None:
            complaint = db.complaints.get(rec["complaint_id"])
            if complaint is not None and complaint["status"] == "CONFIRMED_ERROR":
                complaint["status"] = "CLOSED"
                helpers.touch(complaint)
        listing["has_confirmed_data_error"] = False
        helpers.touch(listing)
    return success_object(helpers.ser_correction(rec))
