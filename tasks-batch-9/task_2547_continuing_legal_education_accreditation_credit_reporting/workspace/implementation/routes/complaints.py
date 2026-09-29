"""Complaints: filing, disposition and the substantiation cascade (PRD 3.9)."""
from flask import Blueprint

import constants as C
import db
import middleware
import response
from errors import fail
from services import cascades

bp = Blueprint("complaints", __name__)

SUBJECT_TYPES = ["PROVIDER", "COURSE"]
ALLEGATION_CATEGORIES = [
    "MISREPRESENTED_CREDIT",
    "NO_SHOW_FACULTY",
    "ATTENDANCE_FRAUD",
    "FEE_DISPUTE",
]
DISPOSITION_ACTIONS = ["OPEN_REVIEW", "SUBSTANTIATE", "DISMISS"]
COMPLAINANT_ROLE = {C.ROLE_ATTORNEY: "ATTORNEY", C.ROLE_BOARD_ADMIN: "BOARD_ADMIN"}
REVOCABLE_COURSE_STATUSES = ("APPROVED", "SUSPENDED_PENDING_REVIEW", "EXPIRED")


def load_complaint(complaint_id):
    complaint = db.get("complaints", complaint_id)
    if complaint is None:
        fail("ERR_COMPLAINT_NOT_FOUND", "No complaint matches that identifier.")
    return complaint


@bp.route("/cle/complaints", methods=["POST"])
def file_complaint():
    user_id, role = middleware.require_roles([C.ROLE_ATTORNEY, C.ROLE_BOARD_ADMIN])
    body = middleware.body_json()

    subject_type = middleware.req_enum(body, "subject_type", SUBJECT_TYPES)
    subject_id = middleware.req_str(body, "subject_id", 1, None)

    # Step 4: the polymorphic reference is resolved in the table subject_type selects.
    collection = "providers" if subject_type == "PROVIDER" else "courses"
    if db.get(collection, subject_id) is None:
        fail("ERR_COMPLAINT_NOT_FOUND", "subject_id resolves to nothing in the selected table.")

    # Step 6: request shape.
    allegation = middleware.req_str(body, "allegation", 1, 2000)
    allegation_category = middleware.req_enum(body, "allegation_category", ALLEGATION_CATEGORIES)

    complaint = db.insert(
        "complaints",
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "complainant_role": COMPLAINANT_ROLE[role],
            "complainant_user_id": user_id,
            "allegation": allegation,
            "allegation_category": allegation_category,
            "status": "RECEIVED",
            "disposition_reason": None,
            "escalated": False,
        },
    )
    return response.success(db.serialize(complaint), 201)


@bp.route("/cle/complaints/<complaint_id>", methods=["GET"])
def read_complaint(complaint_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    return response.success(db.serialize(load_complaint(complaint_id)), 200)


@bp.route("/cle/complaints/<complaint_id>/disposition", methods=["POST"])
def dispose(complaint_id):
    user_id, _role = middleware.require_roles([C.ROLE_BOARD_ADMIN])
    complaint = load_complaint(complaint_id)
    body = middleware.body_json()
    action = middleware.req_enum(body, "action", DISPOSITION_ACTIONS)
    reason = middleware.opt_str(body, "disposition_reason", 1, None, None)
    if action in ("SUBSTANTIATE", "DISMISS") and reason is None:
        fail("ERR_INVALID_REQUEST", "disposition_reason is required with %s." % action)

    status = complaint.get("status")

    # Step 8: state preconditions.
    if action == "OPEN_REVIEW" and status != "RECEIVED":
        fail("ERR_INVALID_STATE_TRANSITION", "OPEN_REVIEW is not declared from %s." % status)
    if action == "DISMISS" and status not in ("RECEIVED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE_TRANSITION", "DISMISS is not declared from %s." % status)
    if action == "SUBSTANTIATE" and status != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION", "SUBSTANTIATE is not declared from %s." % status)

    # Step 12: segregation of duties.
    if complaint.get("complainant_user_id") == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "The complainant may not dispose of its own complaint.")

    if action == "OPEN_REVIEW":
        cascades.set_fields(complaint, {"status": "UNDER_REVIEW"})
    elif action == "DISMISS":
        cascades.set_fields(complaint, {"status": "DISMISSED", "disposition_reason": reason})
    else:
        cascades.set_fields(complaint, {"status": "SUBSTANTIATED", "disposition_reason": reason})
        _substantiate(complaint, reason)
    return response.success(db.serialize(complaint), 200)


def _bump_substantiated(provider):
    cascades.set_fields(
        provider,
        {"substantiated_complaint_count": int(provider.get("substantiated_complaint_count") or 0) + 1},
    )


def _substantiate(complaint, reason):
    """The longest cascade in the specification (PRD 3.9)."""
    if complaint.get("subject_type") == "PROVIDER":
        provider = db.get("providers", complaint.get("subject_id"))
        if provider is None:
            return
        _bump_substantiated(provider)
        if provider.get("accreditation_status") == "ACCREDITED":
            # probation_reason records the complaint that caused the reversion,
            # and the score is recomputed under the post-cascade standing (PRD 3.1).
            cascades.move_provider_status(provider, "PROBATIONARY")
            cascades.set_fields(
                provider,
                {"probation_reason": "Substantiated complaint %s" % complaint["id"]},
            )
        cascades.refresh_risk(provider)
        return

    course = db.get("courses", complaint.get("subject_id"))
    if course is None or course.get("status") not in REVOCABLE_COURSE_STATUSES:
        return
    cascades.set_fields(course, {"status": "REVOKED", "denial_reason": reason})
    for record in db.all_rows("credit_records"):
        if record.get("course_id") != course["id"]:
            continue
        if record.get("status") != "VERIFIED":
            continue
        cascades.mark_voided(record, "COURSE_REVOKED")
    provider = db.get("providers", course.get("provider_id"))
    if provider is not None:
        _bump_substantiated(provider)
        cascades.refresh_risk(provider)
