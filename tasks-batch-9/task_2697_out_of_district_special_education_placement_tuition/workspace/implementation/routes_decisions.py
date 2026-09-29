"""Placement-team decision records and their revision cycle (PRD 3.2)."""
from flask import Blueprint, g

from common import (
    PLACEMENT_TYPES,
    collection,
    decision_or_404,
    single,
    student_or_404,
)
from calc import MAX_REVISION_ROUNDS, MIN_CONTINUUM_OPTIONS, MIN_LRE_JUSTIFICATION_CHARS
from errors import fail
from middleware import (
    ALL_ROLES,
    PLACEMENT_COORDINATOR,
    TEAM_CHAIR,
    check_scope,
    endpoint,
)
from response import created, ok
from store import db, new_row, now_iso, public, touch
from validation import (
    get_enum,
    get_id,
    get_object_array,
    get_text,
    q_str,
    read_body,
)

bp = Blueprint("decisions", __name__)

AUTHORS = (PLACEMENT_COORDINATOR, TEAM_CHAIR)


def _validate_options(body, name, required=True):
    entries = get_object_array(body, name, required=required, default=None)
    if entries is None:
        return None
    for entry in entries:
        for key, value in entry.items():
            if key not in ("setting", "rejected_reason"):
                fail("ERR_INVALID_REQUEST",
                     "continuum option entries accept only 'setting' and 'rejected_reason'.")
            if value is not None and not isinstance(value, str):
                fail("ERR_INVALID_REQUEST", "continuum option '%s' must be a string." % key)
    return entries


def _lre_complete(decision):
    justification = decision.get("lre_justification") or ""
    if len(justification.strip()) < MIN_LRE_JUSTIFICATION_CHARS:
        return False
    options = decision.get("continuum_options_considered") or []
    if len(options) < MIN_CONTINUUM_OPTIONS:
        return False
    for entry in options:
        setting = entry.get("setting")
        reason = entry.get("rejected_reason")
        if not isinstance(setting, str) or not setting.strip():
            return False
        if not isinstance(reason, str) or not reason.strip():
            return False
    if decision.get("recommended_placement_type") not in PLACEMENT_TYPES:
        return False
    return True


# =========================================================================
# reads
# =========================================================================

@endpoint(bp, "GET", "/placement-decisions", ALL_ROLES)
def list_decisions():
    return collection(db.decisions.values(), [
        ("student_id", q_str("student_id")),
        ("status", q_str("status")),
    ])


@endpoint(bp, "GET", "/placement-decisions/<decision_id>", ALL_ROLES)
def get_decision(decision_id):
    return single(decision_or_404(decision_id))


# =========================================================================
# create and revise
# =========================================================================

@endpoint(bp, "POST", "/placement-decisions", AUTHORS)
def create_decision():
    body = read_body((
        "student_id", "lre_justification", "continuum_options_considered",
        "recommended_placement_type",
    ))
    student_id = get_id(body, "student_id")
    justification = get_text(body, "lre_justification")
    options = _validate_options(body, "continuum_options_considered")
    placement_type = get_enum(body, "recommended_placement_type", PLACEMENT_TYPES)

    student_or_404(student_id)

    row = new_row("decision", {
        "student_id": student_id,
        "authored_by_user_id": g.user_id,
        "reviewed_by_user_id": None,
        "lre_justification": justification,
        "continuum_options_considered": options,
        "recommended_placement_type": placement_type,
        "revision_round": 0,
        "status": "DRAFT",
        "submitted_at": None,
        "decided_at": None,
        "reviewer_notes": None,
    })
    db.decisions[row["id"]] = row
    return created(public(row))


@endpoint(bp, "PATCH", "/placement-decisions/<decision_id>", AUTHORS)
def revise_decision(decision_id):
    decision = decision_or_404(decision_id)
    body = read_body((
        "lre_justification", "continuum_options_considered", "recommended_placement_type",
    ))
    justification = get_text(body, "lre_justification", required=False, default=None)
    options = _validate_options(body, "continuum_options_considered", required=False)
    placement_type = get_enum(body, "recommended_placement_type", PLACEMENT_TYPES,
                              required=False, default=None)

    if decision["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "A decision may only be revised while DRAFT or RETURNED_FOR_REVISION.")

    if "lre_justification" in body:
        decision["lre_justification"] = justification
    if options is not None:
        decision["continuum_options_considered"] = options
    if placement_type is not None:
        decision["recommended_placement_type"] = placement_type
    touch(decision)
    return ok(public(decision))


# =========================================================================
# transitions
# =========================================================================

@endpoint(bp, "POST", "/placement-decisions/<decision_id>/submit", AUTHORS)
def submit_decision(decision_id):
    decision = decision_or_404(decision_id)
    read_body(())

    origin = decision["status"]
    if origin not in ("DRAFT", "RETURNED_FOR_REVISION"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a DRAFT or RETURNED_FOR_REVISION decision may be submitted for review.")

    if not _lre_complete(decision):
        fail("ERR_LRE_DOCUMENTATION_INCOMPLETE",
             "The least-restrictive-environment record is not complete enough to submit.")

    if origin == "DRAFT":
        for other in db.decisions.values():
            if other["id"] == decision["id"]:
                continue
            if (other["student_id"] == decision["student_id"]
                    and other["status"] == "TEAM_REVIEW"):
                fail("ERR_INVALID_STATE_TRANSITION",
                     "Another decision for this student is already in TEAM_REVIEW.")

    decision["status"] = "TEAM_REVIEW"
    decision["submitted_at"] = now_iso()
    touch(decision)
    return ok(public(decision))


@endpoint(bp, "POST", "/placement-decisions/<decision_id>/return-for-revision", (TEAM_CHAIR,))
def return_decision_for_revision(decision_id):
    decision = decision_or_404(decision_id)
    body = read_body(("reviewer_notes",))
    notes = get_text(body, "reviewer_notes")

    if decision["status"] != "TEAM_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a decision in TEAM_REVIEW may be returned for revision.")
    if g.user_id == decision["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The reviewer must differ from the decision's author.")
    if decision["revision_round"] >= MAX_REVISION_ROUNDS:
        fail("ERR_MAX_ROUNDS_EXCEEDED",
             "The review loop is bounded at three revision rounds.")

    decision["status"] = "RETURNED_FOR_REVISION"
    decision["revision_round"] += 1
    decision["reviewed_by_user_id"] = g.user_id
    decision["reviewer_notes"] = notes
    touch(decision)
    return ok(public(decision))


@endpoint(bp, "POST", "/placement-decisions/<decision_id>/approve", (TEAM_CHAIR,))
def approve_decision(decision_id):
    decision = decision_or_404(decision_id)
    body = read_body(("reviewer_notes",))
    notes = get_text(body, "reviewer_notes", required=False, default=None)

    if decision["status"] != "TEAM_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a decision in TEAM_REVIEW may be approved.")
    if g.user_id == decision["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approver must differ from the decision's author.")

    student = db.students.get(decision["student_id"])
    if student is not None and student["placement_status"] == "OOD_ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The student is already in an active out-of-district placement.")

    decision["status"] = "APPROVED"
    decision["decided_at"] = now_iso()
    decision["reviewed_by_user_id"] = g.user_id
    if notes is not None:
        decision["reviewer_notes"] = notes
    touch(decision)

    if student is not None:
        student["placement_status"] = "DECISION_APPROVED"
        touch(student)
    return ok(public(decision))
