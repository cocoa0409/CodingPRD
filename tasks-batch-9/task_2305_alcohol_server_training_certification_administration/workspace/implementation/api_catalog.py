"""Clock, jurisdictions, the course catalogue and state approvals."""

from decimal import Decimal

from flask import Blueprint

import domain
import envelope
import store as st
import validate as v
from auth import authenticate, PROGRAM_ADMIN, STATE_REGULATOR, TRAINER, EMPLOYER_ADMIN
from errors import fail, invalid
from store import apply_changes, create_row, store

bp = Blueprint("catalog", __name__)

READ_CATALOG_ROLES = (PROGRAM_ADMIN, STATE_REGULATOR, TRAINER, EMPLOYER_ADMIN)
READ_APPROVAL_ROLES = (PROGRAM_ADMIN, STATE_REGULATOR, TRAINER)


def paged(items):
    limit, offset = v.pagination()
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


# --- logical clock ---------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    moment = v.req_dt(body, "to_iso8601")
    store.clock = moment
    return envelope.ok({"current_utc": envelope.fmt_dt(moment)})


# --- state jurisdictions ---------------------------------------------------

TRACK_CARDINALITY = {"MANDATORY": 2, "CONDITIONAL": 1, "VOLUNTARY": 0}


@bp.post("/state-jurisdictions")
def create_jurisdiction():
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    state_code = v.req_state_code(body, "state_code")
    mandate_type = v.req_enum(body, "mandate_type", v.MANDATE_TYPES)
    tracks = v.req_enum_array(body, "mandated_tracks", v.TRACKS)
    fields = {
        "state_code": state_code,
        "mandate_type": mandate_type,
        "mandated_tracks": tracks,
        "certificate_validity_months": v.opt_int(
            body, "certificate_validity_months", 1, 120, 36),
        "renewal_grace_days": v.opt_int(body, "renewal_grace_days", 0, 180, 30),
        "new_hire_training_days": v.opt_int(body, "new_hire_training_days", 0, 180, 30),
        "registry_submission_required": v.opt_bool(
            body, "registry_submission_required", True),
        "registry_deadline_days": v.opt_int(body, "registry_deadline_days", 1, 365, 30),
        "registry_late_fee_cents_per_day": v.opt_int(
            body, "registry_late_fee_cents_per_day", 0, None, 250),
        "min_passing_score_pct": v.opt_decimal(
            body, "min_passing_score_pct", Decimal("50"), Decimal("100"), 2,
            Decimal("70.00")),
        "max_retakes_allowed": v.opt_int(body, "max_retakes_allowed", 0, 5, 2),
        "retake_cooling_off_hours": v.opt_int(
            body, "retake_cooling_off_hours", 0, 168, 24),
        "proctor_separation_required": v.opt_bool(
            body, "proctor_separation_required", True),
        "reminder_lead_days": v.opt_int(body, "reminder_lead_days", 0, 365, 60),
        "certificates_issued_count": 0,
    }
    # priority 23
    if len(tracks) != TRACK_CARDINALITY[mandate_type]:
        fail("ERR_MANDATE_TRACK_MISMATCH",
             "mandate_type '%s' does not agree with %d mandated track(s)."
             % (mandate_type, len(tracks)))
    # priority 24
    for row in st.rows("state_jurisdictions"):
        if row["state_code"] == state_code:
            fail("ERR_IDENTITY_ALREADY_REGISTERED",
                 "state_code '%s' is already registered." % state_code)
    return envelope.ok_row(create_row("state_jurisdictions", fields), 201)


# --- courses ---------------------------------------------------------------

@bp.post("/courses")
def create_course():
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    title = v.req_str(body, "title", 1, 160)
    track = v.req_enum(body, "track", v.TRACKS)
    delivery_mode = v.req_enum(body, "delivery_mode", v.DELIVERY_MODES)
    contact_hours = v.req_decimal(body, "contact_hours", None, Decimal("24"), 2)
    if contact_hours <= 0:
        invalid("Field 'contact_hours' must be greater than 0.")
    question_count = v.req_int(body, "question_count", 10, 200)
    version_label = v.req_str(body, "version_label", 1, 32)
    supersedes_course_id = v.opt_str(body, "supersedes_course_id")
    # priority 6
    if supersedes_course_id is not None:
        v.must_exist("courses", supersedes_course_id)
    row = create_row("courses", {
        "title": title,
        "track": track,
        "delivery_mode": delivery_mode,
        "contact_hours": contact_hours,
        "question_count": question_count,
        "version_label": version_label,
        "supersedes_course_id": supersedes_course_id,
        "status": "DRAFT",
        "content_revision_count": 0,
        "retired_at": None,
    })
    return envelope.ok_row(row, 201)


@bp.patch("/courses/<course_id>")
def revise_course(course_id):
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    expected_version = v.req_int(body, "expected_course_version")
    revision_note = v.req_str(body, "revision_note", 1, None)
    title = v.opt_str(body, "title", 1, 160)
    contact_hours = v.opt_decimal(body, "contact_hours", None, Decimal("24"), 2)
    if contact_hours is not None and contact_hours <= 0:
        invalid("Field 'contact_hours' must be greater than 0.")
    question_count = v.opt_int(body, "question_count", 10, 200)
    course = v.must_exist("courses", course_id)                        # priority 4
    if expected_version != course["version"]:                          # priority 8
        fail("ERR_STALE_COURSE_VERSION",
             "expected_course_version %s does not match the course version %s."
             % (expected_version, course["version"]))
    if course["status"] not in ("DRAFT", "PUBLISHED"):                  # priority 10
        fail("ERR_COURSE_INVALID_STATE",
             "A course in status '%s' cannot be revised." % course["status"])
    changes = {"content_revision_count": course["content_revision_count"] + 1}
    if title is not None:
        changes["title"] = title
    if contact_hours is not None:
        changes["contact_hours"] = contact_hours
    if question_count is not None:
        changes["question_count"] = question_count
    apply_changes(course, changes)
    course["_revision_note"] = revision_note
    domain.stale_approvals_of(course)
    return envelope.ok_row(course)


@bp.post("/courses/<course_id>/publish")
def publish_course(course_id):
    authenticate((PROGRAM_ADMIN,))
    v.body()
    course = v.must_exist("courses", course_id)
    if course["status"] != "DRAFT":                                     # priority 10
        fail("ERR_COURSE_INVALID_STATE",
             "Only a DRAFT course may be published; this one is '%s'." % course["status"])
    target_id = course.get("supersedes_course_id")
    if target_id:
        target = st.get("courses", target_id)
        if target is None:
            fail("ERR_CATALOG_NOT_FOUND", "The superseded course does not resolve.")
        if target["status"] != "PUBLISHED":
            fail("ERR_COURSE_INVALID_STATE",
                 "The superseded course must be PUBLISHED; it is '%s'."
                 % target["status"])
    domain.publish_course(course)
    return envelope.ok_row(course)


@bp.get("/courses/<course_id>")
def read_course(course_id):
    authenticate(READ_CATALOG_ROLES)
    return envelope.ok_row(v.must_exist("courses", course_id))


@bp.get("/courses")
def list_courses():
    authenticate(READ_CATALOG_ROLES)
    track = v.q_enum("track", v.TRACKS)
    status = v.q_enum("status", v.COURSE_STATUSES)
    supersedes_course_id = v.q_str("supersedes_course_id")
    approved_state_code = v.q_str("approved_state_code")

    approved_course_ids = None
    if approved_state_code is not None:
        approved_course_ids = set()
        jurisdiction_ids = {
            j["id"] for j in st.rows("state_jurisdictions")
            if j["state_code"] == approved_state_code
        }
        for approval in st.rows("course_approvals"):
            if (approval["approval_status"] == "APPROVED"
                    and approval["state_jurisdiction_id"] in jurisdiction_ids):
                approved_course_ids.add(approval["course_id"])

    def keep(row):
        if track is not None and row["track"] != track:
            return False
        if status is not None and row["status"] != status:
            return False
        if (supersedes_course_id is not None
                and row["supersedes_course_id"] != supersedes_course_id):
            return False
        if approved_course_ids is not None and row["id"] not in approved_course_ids:
            return False
        return True

    return paged([r for r in st.rows("courses") if keep(r)])


# --- course approvals ------------------------------------------------------

@bp.post("/course-approvals")
def create_approval():
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    course_id = v.req_str(body, "course_id", 1, None)
    jurisdiction_id = v.req_str(body, "state_jurisdiction_id", 1, None)
    submission_note = v.opt_str(body, "submission_note", 1, None)
    course = v.must_exist("courses", course_id)                        # priority 6
    jurisdiction = v.must_exist("state_jurisdictions", jurisdiction_id)
    if course["status"] != "PUBLISHED":                                # priority 10
        fail("ERR_COURSE_INVALID_STATE",
             "Only a PUBLISHED course may be submitted for approval.")
    for approval in st.rows("course_approvals"):                       # priority 25
        if (approval["course_id"] == course_id
                and approval["state_jurisdiction_id"] == jurisdiction_id
                and approval["approval_status"] in domain.LIVE_APPROVAL_STATUSES):
            fail("ERR_DUPLICATE_APPROVAL_REQUEST",
                 "A live approval already exists for this course and state.")
    row = create_row("course_approvals", {
        "course_id": course_id,
        "state_jurisdiction_id": jurisdiction["id"],
        "approval_status": "SUBMITTED",
        "approval_number": None,
        "effective_from": None,
        "expires_at": None,
        "review_round": 1,
        "pinned_course_version": None,
        "submission_note": submission_note,
        "changes_requested_note": None,
        "decided_at": None,
    })
    return envelope.ok_row(row, 201)


@bp.post("/course-approvals/<approval_id>/decision")
def decide_approval(approval_id):
    authenticate((STATE_REGULATOR,))
    body = v.body()
    decision = v.req_enum(body, "decision", v.DECISIONS)
    approval_number = None
    effective_from = None
    expires_at = None
    if decision == "APPROVE":
        approval_number = v.req_str(body, "approval_number", 1, None)
        effective_from = v.req_dt(body, "effective_from")
        expires_at = v.req_dt(body, "expires_at")
        if expires_at <= effective_from:
            invalid("Field 'expires_at' must be strictly after 'effective_from'.")
    changes_requested_note = v.opt_str(body, "changes_requested_note", 1, None)

    approval = v.must_exist("course_approvals", approval_id)           # priority 4
    course = st.get("courses", approval["course_id"])
    if decision == "APPROVE" and course["status"] != "PUBLISHED":      # priority 10
        fail("ERR_COURSE_INVALID_STATE",
             "The course must still be PUBLISHED to approve it.")
    if approval["approval_status"] != "SUBMITTED":                     # priority 11
        fail("ERR_APPROVAL_INVALID_STATE",
             "Only a SUBMITTED approval may be decided; this one is '%s'."
             % approval["approval_status"])

    if decision == "APPROVE":
        apply_changes(approval, {
            "approval_status": "APPROVED",
            "approval_number": approval_number,
            "effective_from": effective_from,
            "expires_at": expires_at,
            "pinned_course_version": course["version"],
            "decided_at": store.clock,
        })
    elif decision == "REQUEST_CHANGES":
        apply_changes(approval, {
            "approval_status": "CHANGES_REQUESTED",
            "changes_requested_note": changes_requested_note,
            "decided_at": store.clock,
        })
    else:
        apply_changes(approval, {
            "approval_status": "REJECTED",
            "decided_at": store.clock,
        })
    return envelope.ok_row(approval)


@bp.post("/course-approvals/<approval_id>/resubmit")
def resubmit_approval(approval_id):
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    submission_note = v.opt_str(body, "submission_note", 1, None)
    approval = v.must_exist("course_approvals", approval_id)
    course = st.get("courses", approval["course_id"])
    status = approval["approval_status"]
    if status == "CHANGES_REQUESTED" and course["status"] != "PUBLISHED":  # priority 10
        fail("ERR_COURSE_INVALID_STATE",
             "The course must still be PUBLISHED to resubmit this approval.")
    if status not in ("CHANGES_REQUESTED", "STALE"):                      # priority 11
        fail("ERR_APPROVAL_INVALID_STATE",
             "An approval in '%s' cannot be resubmitted." % status)

    review_round = approval["review_round"] + 1
    changes = {"review_round": review_round}
    if submission_note is not None:
        changes["submission_note"] = submission_note
    if status == "STALE":
        changes["pinned_course_version"] = None
    changes["approval_status"] = (
        "REJECTED" if review_round > domain.MAX_REVIEW_ROUNDS else "SUBMITTED"
    )
    apply_changes(approval, changes)
    return envelope.ok_row(approval)


@bp.get("/course-approvals/<approval_id>")
def read_approval(approval_id):
    authenticate(READ_APPROVAL_ROLES)
    return envelope.ok_row(v.must_exist("course_approvals", approval_id))


@bp.get("/course-approvals")
def list_approvals():
    authenticate(READ_APPROVAL_ROLES)
    course_id = v.q_str("course_id")
    jurisdiction_id = v.q_str("state_jurisdiction_id")
    status = v.q_enum("approval_status", v.APPROVAL_STATUSES)

    def keep(row):
        if course_id is not None and row["course_id"] != course_id:
            return False
        if (jurisdiction_id is not None
                and row["state_jurisdiction_id"] != jurisdiction_id):
            return False
        if status is not None and row["approval_status"] != status:
            return False
        return True

    return paged([r for r in st.rows("course_approvals") if keep(r)])
