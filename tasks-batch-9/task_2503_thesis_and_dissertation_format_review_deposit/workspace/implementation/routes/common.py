"""Ladder stages shared by more than one route, plus the two deep cascades."""

import lookup
from db import db, write
from errors import fail
from services import calc, counters
from services.clearance import recompute_for_thesis

PREFIX = "/graduate-school"

ALL_ROLES = [
    "Student",
    "FacultyMember",
    "GradSchoolAnalyst",
    "GraduateDean",
    "IntegrityOfficer",
    "Registrar",
]

TERMINAL_WORKFLOW_STATES = ("CONFERRED", "DEFENSE_FAILED", "TERMINATED")

INTEGRITY_HOLD_STATES = ("SCREEN_FLAGGED", "UNDER_INTEGRITY_REVIEW", "INTEGRITY_UPHELD")


# ------------------------------------------------------------ ladder stage 6


def require_owner(role, user_id, thesis):
    """Stage 6: a Student may only act on their own document."""
    if role == "Student" and thesis["student_id"] != user_id:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "The acting student does not own thesis '%s'" % thesis["id"],
        )


# ------------------------------------------------------------ ladder stage 8


def require_thesis_version(thesis, expected):
    if expected != thesis["version"]:
        fail(
            "ERR_STALE_THESIS_VERSION",
            "expected_thesis_version %s does not match the current thesis version %s"
            % (expected, thesis["version"]),
        )


# ------------------------------------------------------------ ladder stage 9


def require_term_open(thesis):
    term = db.terms.get(thesis["term_id"])
    if term is not None and term["status"] != "OPEN":
        fail(
            "ERR_TERM_DEPOSIT_CLOSED",
            "The deposit window of the governing term is closed",
        )
    return term


def term_of(thesis):
    return db.terms.get(thesis["term_id"])


# ----------------------------------------------------------- ladder stage 12


def require_committee_state(committee, allowed, message):
    if committee is None or committee["status"] not in allowed:
        fail("ERR_COMMITTEE_STATE_INVALID", message)


# ------------------------------------------------------- permission dossier


def permissions_complete(thesis):
    records = lookup.permissions_of_thesis(thesis["id"])
    for record in records:
        if record["status"] not in ("ACCEPTED", "WAIVED"):
            return False
    return thesis["documented_permission_count"] >= thesis["third_party_item_count"]


def embargo_undecided(thesis):
    return any(
        row["status"] in ("REQUESTED", "MORE_INFO_REQUIRED")
        for row in lookup.embargoes_of_thesis(thesis["id"])
    )


def accepted_format_review(thesis):
    for row in lookup.reviews_of_thesis(thesis["id"]):
        if row["status"] == "ACCEPTED":
            return row
    return None


# ------------------------------------------------------------ deep cascades


def revert_approved_committee(committee, thesis):
    """PRD section 3.3: a seat change on an APPROVED committee voids the grant.

    Four linked steps: committee APPROVED -> SUBMITTED with the grant cleared,
    thesis -> COMMITTEE_PENDING, every DRAFT/ANNOUNCED defense -> CANCELLED, and
    the affected rooms' booked_minutes_total recomputed.
    """
    if committee["status"] != "APPROVED":
        return False
    if thesis["workflow_state"] not in (
        "COMMITTEE_APPROVED",
        "DEFENSE_SCHEDULED",
        "DEFENSE_ANNOUNCED",
    ):
        return False

    write(committee, status="SUBMITTED", approved_by_user_id=None, approved_at=None)
    write(thesis, workflow_state="COMMITTEE_PENDING")

    touched_rooms = []
    for event in lookup.events_of_thesis(thesis["id"]):
        if event["status"] in ("DRAFT", "ANNOUNCED"):
            write(
                event,
                status="CANCELLED",
                cancellation_reason=calc.COMMITTEE_CHANGE_REASON,
            )
            touched_rooms.append(event["room_id"])
    counters.recompute_rooms(touched_rooms)
    return True


def integrity_upheld_cascade(screening, thesis, user_id, resolution_note=None):
    """PRD section 3.6: the four-link termination cascade."""
    write(
        screening,
        status="UPHELD",
        resolved_by_user_id=user_id,
        resolution_note=resolution_note,
    )
    write(thesis, integrity_state="INTEGRITY_UPHELD", workflow_state="TERMINATED")

    for review in lookup.reviews_of_thesis(thesis["id"]):
        if review["status"] in ("PENDING_REVIEW", "REVISIONS_REQUIRED"):
            write(review, status="VOID")
    for deposit in lookup.deposits_of_thesis(thesis["id"]):
        if deposit["status"] == "DEPOSITED":
            write(deposit, status="WITHDRAWN")

    counters.sync_thesis_counters(thesis)
    clearance = recompute_for_thesis(thesis)

    if clearance is not None:
        write(
            clearance,
            status="WITHHELD",
            withheld_reason=calc.WITHHOLD_REASON,
            transcript_notation=calc.WITHHOLD_NOTATION,
            cleared_at=None,
        )
        student = db.students.get(thesis["student_id"])
        if student is not None:
            write(
                student,
                graduation_clearance_state="WITHHELD",
                transcript_notation=calc.WITHHOLD_NOTATION,
                degree_conferred=False,
            )
