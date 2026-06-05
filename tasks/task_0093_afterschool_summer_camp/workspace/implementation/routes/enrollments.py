"""Enrollment routes (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_SESSION_NOT_OPEN,
    ERR_OFFERING_RAINED_OUT,
    ERR_AUTHORIZATION_INCOMPLETE,
    ERR_NO_EMERGENCY_CONTACT,
    ERR_AGE_OUT_OF_GROUP,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_WEEK_OVERLAP_CHILD,
    ERR_STALE_OFFERING_VERSION,
    ERR_ENROLLMENT_BILLED,
)
from middleware import require_roles, ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import (
    make_record,
    serialize,
    serialize_list,
    sort_by_created,
    touch,
    audit,
    get_body,
    require_str,
    require_int,
)
from services.calculations import (
    age_eligible,
    weeks_overlap,
    reconcile_offering_counts,
    compute_line_tuition,
    compute_invoice_totals,
)
from services.lookups import (
    get_child,
    get_weekly_offering,
    get_enrollment,
    require_child_owner,
)
from services.state_machines import withdraw_enrollment_cascade, _attach_to_draft_invoice

bp = Blueprint("enrollments", __name__)


def _child_has_approved_forms(child_id: str) -> bool:
    has_medical = any(
        f["child_id"] == child_id and f["form_type"] == "MEDICAL" and f["status"] == "APPROVED"
        for f in db.authorization_forms.values()
    )
    has_pickup = any(
        f["child_id"] == child_id and f["form_type"] == "PICKUP" and f["status"] == "APPROVED"
        for f in db.authorization_forms.values()
    )
    return has_medical and has_pickup


@bp.post("/enrollments")
def create_enrollment():
    caller = require_roles(ROLE_GUARDIAN)
    body = get_body()
    child_id = require_str(body, "child_id")
    weekly_offering_id = require_str(body, "weekly_offering_id")
    expected_version = require_int(body, "expected_weekly_offering_version")

    # existence (priority 3): both referenced resources
    child = get_child(child_id)
    offering = get_weekly_offering(weekly_offering_id)
    session = db.sessions[offering["session_id"]]

    # priority 4: ownership
    require_child_owner(child, caller.user_id)

    # priority 6: session OPEN
    if session["status"] != "OPEN":
        raise APIError(ERR_SESSION_NOT_OPEN, 409, "Session is not OPEN")

    # priority 7: weather NORMAL
    if offering["weather_state"] != "NORMAL":
        raise APIError(ERR_OFFERING_RAINED_OUT, 409, "Offering is rained out")

    # priority 8: approved MEDICAL + PICKUP authorization forms
    if not _child_has_approved_forms(child_id):
        raise APIError(ERR_AUTHORIZATION_INCOMPLETE, 422, "Child authorization incomplete")

    # priority 9: at least one emergency contact
    if not any(ec["child_id"] == child_id for ec in db.emergency_contacts.values()):
        raise APIError(ERR_NO_EMERGENCY_CONTACT, 422, "Child has no emergency contact")

    # priority 10: age within session group
    if not age_eligible(child, session):
        raise APIError(ERR_AGE_OUT_OF_GROUP, 422, "Child age outside session age group")

    # priority 11: no existing non-WITHDRAWN enrollment for same (child, offering)
    for e in db.enrollments.values():
        if (
            e["child_id"] == child_id
            and e["weekly_offering_id"] == weekly_offering_id
            and e["status"] != "WITHDRAWN"
        ):
            raise APIError(ERR_DUPLICATE_ENROLLMENT, 409, "Duplicate enrollment")

    # priority 12: week overlap with another CONFIRMED/WAITLISTED enrollment
    for e in db.enrollments.values():
        if e["child_id"] != child_id or e["status"] not in ("CONFIRMED", "WAITLISTED"):
            continue
        other = db.weekly_offerings.get(e["weekly_offering_id"])
        if other is None:
            continue
        if weeks_overlap(offering["week_start"], other["week_start"]):
            raise APIError(ERR_WEEK_OVERLAP_CHILD, 409, "Child already enrolled in an overlapping week")

    # priority 17: OCC on the offering version
    if expected_version != offering["version"]:
        raise APIError(ERR_STALE_OFFERING_VERSION, 412, "Stale offering version")

    # branch decision: seat available?
    seat_available = offering["enrolled_count"] < session["weekly_capacity"]

    rec = make_record(
        {
            "child_id": child_id,
            "weekly_offering_id": weekly_offering_id,
            "invoice_id": None,
            "status": "REQUESTED",
            "waitlist_rank": None,
            "provisional_tuition_cents": 0,
            "final_tuition_cents": 0,
        }
    )
    db.enrollments[rec["id"]] = rec

    if seat_available:
        rec["status"] = "CONFIRMED"
        reconcile_offering_counts(offering)
        rec["provisional_tuition_cents"] = compute_line_tuition(rec)
        invoice = _attach_to_draft_invoice(rec)
        compute_invoice_totals(invoice)
        audit("Enrollment", rec["id"], "ENROLLMENT_CONFIRMED", caller.role)
    else:
        rec["status"] = "WAITLISTED"
        reconcile_offering_counts(offering)
        audit("Enrollment", rec["id"], "ENROLLMENT_WAITLISTED", caller.role)

    return ok_object(serialize(rec), 201)


@bp.get("/enrollments/<eid>")
def fetch_enrollment(eid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING)
    rec = get_enrollment(eid)
    return ok_object(serialize(rec), 200)


@bp.get("/enrollments")
def list_enrollments():
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING)
    limit, offset = paginate_params(request.args)
    child_id = request.args.get("child_id")
    invoice_id = request.args.get("invoice_id")
    status = request.args.get("status")
    items = list(db.enrollments.values())
    if child_id is not None:
        items = [e for e in items if e["child_id"] == child_id]
    if invoice_id is not None:
        items = [e for e in items if e.get("invoice_id") == invoice_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    caller = require_roles(ROLE_GUARDIAN)
    enrollment = get_enrollment(eid)
    child = get_child(enrollment["child_id"])
    require_child_owner(child, caller.user_id)

    if enrollment["status"] not in ("CONFIRMED", "WAITLISTED"):
        raise APIError(ERR_INVALID_STATE, 409, "Enrollment cannot be withdrawn from its current state")

    # CONFIRMED can only be withdrawn while its invoice is still DRAFT
    if enrollment["status"] == "CONFIRMED":
        inv_id = enrollment.get("invoice_id")
        inv = db.invoices.get(inv_id) if inv_id else None
        if inv and inv["status"] != "DRAFT":
            raise APIError(ERR_ENROLLMENT_BILLED, 409, "Cannot withdraw a billed enrollment")

    offering = db.weekly_offerings[enrollment["weekly_offering_id"]]
    withdraw_enrollment_cascade(enrollment, offering, caller.role)
    return ok_object(serialize(enrollment), 200)
