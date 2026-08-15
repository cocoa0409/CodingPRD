"""MemberComplaint endpoints: file (Member), list, get, adjudicate (ComplianceOfficer)."""

from datetime import timedelta

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("complaints", __name__)

COMPLAINT_STATUSES = {"OPEN", "CONFIRMED_ERROR", "UNFOUNDED", "CLOSED"}
CORRECTION_SLA_HOURS = 72
FILING_WINDOW_DAYS = 90


@bp.route("/network/complaints", methods=["POST"])
@require_roles("Member")
def file_complaint(user_id, role):
    # entity-backed identity: X-User-ID must be an existing Member id
    member = db.members.get(user_id)
    if member is None:
        raise errors.err_not_owner("Member id unknown")
    body = helpers.get_body()
    listing_id = helpers.req_str(body, "listing_id")
    error_type = helpers.req_enum(body, "error_type", helpers.ERROR_TYPES)
    error_observed_date = helpers.req_str(body, "error_observed_date")
    eod = helpers.parse_date(error_observed_date, "error_observed_date")
    description = helpers.req_str(body, "description")
    listing = db.listings.get(listing_id)
    if listing is None:
        raise errors.err_listing_not_found()
    # state checks
    if member["status"] != "ENROLLED":
        raise errors.err_member_not_enrolled()
    if listing["status"] == "REMOVED":
        raise errors.err_listing_removed()
    # temporal window: observed not in future; filed - observed <= 90 days
    cdate = helpers.clock_date()
    if eod > cdate:
        raise errors.err_complaint_window()
    if (cdate - eod).days > FILING_WINDOW_DAYS:
        raise errors.err_complaint_window()
    # referential: listing's location region must equal member's region
    location = db.locations.get(listing["location_id"])
    if location is None or location["region_id"] != member["region_id"]:
        raise errors.err_listing_not_in_member_region()
    rec = {
        "member_id": member["id"], "listing_id": listing_id,
        "error_type": error_type, "error_observed_date": error_observed_date,
        "description": description, "status": "OPEN",
        "filed_at": helpers.now_iso(), "confirmed_at": None, "notes": None,
    }
    helpers.stamp_new(rec)
    db.complaints[rec["id"]] = rec
    return success_object(helpers.ser_complaint(rec), 201)


@bp.route("/network/complaints", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_complaints(user_id, role):
    limit, offset = helpers.get_pagination()
    member_id = helpers.query_str("member_id")
    listing_id = helpers.query_str("listing_id")
    status = helpers.query_enum("status", COMPLAINT_STATUSES)
    items = list(db.complaints.values())
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if listing_id is not None:
        items = [c for c in items if c["listing_id"] == listing_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_complaint(c) for c in page], limit, offset, total)


@bp.route("/network/complaints/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_complaint(user_id, role, cid):
    rec = db.complaints.get(cid)
    if rec is None:
        raise errors.err_complaint_not_found()
    return success_object(helpers.ser_complaint(rec))


@bp.route("/network/complaints/<cid>/adjudicate", methods=["POST"])
@require_roles("ComplianceOfficer")
def adjudicate_complaint(user_id, role, cid):
    rec = db.complaints.get(cid)
    if rec is None:
        raise errors.err_complaint_not_found()
    if rec["status"] != "OPEN":
        raise errors.err_complaint_not_open()
    body = helpers.get_body()
    outcome = helpers.req_enum(body, "outcome", helpers.COMPLAINT_ADJUDICATE_OUTCOMES)
    notes = helpers.opt_str(body, "notes")
    if outcome == "UNFOUNDED":
        rec["status"] = "UNFOUNDED"
        rec["notes"] = notes
        helpers.touch(rec)
        return success_object(helpers.ser_complaint(rec))
    # CONFIRMED_ERROR
    changes = body.get("correction_changes")
    if not isinstance(changes, dict) or len(changes) == 0:
        raise errors.err_invalid("correction_changes must be present and non-empty")
    rec["status"] = "CONFIRMED_ERROR"
    rec["confirmed_at"] = helpers.now_iso()
    rec["notes"] = notes
    helpers.touch(rec)
    # spawn DirectoryCorrection
    sla = db.clock_now + timedelta(hours=CORRECTION_SLA_HOURS)
    corr = {
        "listing_id": rec["listing_id"], "complaint_id": rec["id"],
        "changes": changes, "submitted_by_user_id": "system:adjudication",
        "sla_due_at": helpers._dt_to_iso(sla), "is_late": False,
        "status": "SUBMITTED", "verified_at": None, "verified_by_user_id": None,
    }
    helpers.stamp_new(corr)
    db.corrections[corr["id"]] = corr
    # flag the listing
    listing = db.listings.get(rec["listing_id"])
    if listing is not None:
        listing["has_confirmed_data_error"] = True
        helpers.touch(listing)
    return success_object(helpers.ser_complaint(rec))
