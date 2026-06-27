"""Validation-priority conflicts, cross-entity state dependencies, and resource
temporal-overlap conflicts (room buffer vs instructor no-buffer).

Queue A (Difficulty): priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap.
"""
import pytest
from test_helpers import validate_success, validate_error, TEST_USERS, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADMIN_H = TEST_USERS["admin_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# =========================================================================
# Rule 5 — priority_pair_validation_conflict
# =========================================================================
def test_confirm_dropped_enrollment_in_delinquent_family_reports_invalid_state(api):
    """PRD §2.10: "then the legality of the requested state transition (`ERR_INVALID_STATE`)...
    Only after those gates pass does the system evaluate domain-specific business rules —
    eligibility, capacity, scheduling conflicts, fiscal standing, and the like."

    A confirm against an already-DROPPED enrollment in a DELINQUENT family violates both the
    state precondition (state, earlier) and the delinquency gate (fiscal, later). The state
    check wins -> ERR_INVALID_STATE, not ERR_FAMILY_DELINQUENT.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_enrollment_confirm
    """
    # Build a delinquent family whose enrollment in secA is then dropped.
    del_env = fx.setup_delinquent_family(billing_month="2026-02", advance_to="2026-02-20T00:00:00Z")
    assert del_env["family"]["status"] == "DELINQUENT"
    enr = del_env["enrollment_a"]
    validate_success(api.drop_enrollment(enr["id"], ADMIN_H))

    resp = api.confirm_enrollment(enr["id"], ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    fam = validate_success(api.get_family(del_env["family"]["id"], ADMIN_H))
    assert fam["status"] == "DELINQUENT"


def test_add_session_to_nonexistent_section_reports_not_found(api):
    """PRD §2.10: "then existence of every referenced id (`ERR_NOT_FOUND`), then the legality of
    the requested state transition (`ERR_INVALID_STATE`)... Only after those gates pass does the
    system evaluate domain-specific business rules — ... scheduling conflicts."
    PRD §2.7: "the system validates the identifiers left to right and rejects the first one that
    does not resolve to a live resource with `ERR_NOT_FOUND`."

    Adding a session to a bogus section id resolves existence (priority 4) before any room
    conflict (a business check) -> ERR_NOT_FOUND.

    Design: Difficulty/priority_pair_validation_conflict/existence_before_temporal_on_session_create
    """
    # A real section occupies the room at 600-660; trigger targets a bogus section id.
    term = fx.create_term()
    room = fx.create_room(capacity=20)
    instructor = fx.create_instructor()
    sec = fx.create_section(term["id"], room["id"], instructor["id"], discipline="JAZZ")
    fx.add_session(sec["id"], day_of_week=0, start_minute=600, end_minute=660)

    resp = api.create_session(NON_EXISTENT, f.create_session_payload(
        day_of_week=0, start_minute=600, end_minute=660), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# =========================================================================
# Rule 7 — cross_entity_state_dependency
# =========================================================================
def test_enrollment_confirm_blocked_when_family_delinquent(api):
    """PRD §3.3: "A confirmation additionally requires that the family not be `DELINQUENT`; a
    delinquent family's confirmation is refused with `ERR_FAMILY_DELINQUENT`."
    PRD §3.9: "the invoice flips to `PAST_DUE` and its family's `status` flips to `DELINQUENT` —
    which in turn gates that family's new enrollment confirmations and trip signups."

    Entity pair Enrollment->Family: a DELINQUENT family (driven by a PAST_DUE invoice) cannot
    confirm a NEW enrollment in another open section -> ERR_FAMILY_DELINQUENT.

    Design: Difficulty/cross_entity_state_dependency/enrollment_confirm_blocked_by_delinquent_family
    """
    del_env = fx.setup_delinquent_family(billing_month="2026-02", advance_to="2026-02-20T00:00:00Z")
    assert del_env["family"]["status"] == "DELINQUENT"
    # Trigger: enroll the same student into secB (a different open section).
    resp = api.create_enrollment(
        f.create_enrollment_payload(del_env["student"]["id"], del_env["secB"]["id"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_FAMILY_DELINQUENT.value)
    fam = validate_success(api.get_family(del_env["family"]["id"], ADMIN_H))
    assert fam["status"] == "DELINQUENT"


def test_enrollment_into_section_whose_term_still_draft_rejected(api):
    """PRD §3.2: "When its parent term opens, a `SCHEDULED` section transitions to `OPEN` and
    becomes enrollable — this is a system transition guarded on the term: a section opens only
    because its term opened, never independently."
    PRD §3.3: "If the section is `OPEN` with room under effective capacity and the student is
    eligible, the enrollment is confirmed directly; if the section is `FULL`, the enrollment is
    waitlisted."
    PRD §2.10: "then the legality of the requested state transition (`ERR_INVALID_STATE`)."

    Entity pair ClassSection->Term: a section is only enrollable once its term opens. Enrolling
    into a SCHEDULED section whose term is still DRAFT is not a legal placement -> ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/section_open_depends_on_term_open
    """
    term = fx.create_term()
    room = fx.create_room(capacity=20)
    instructor = fx.create_instructor()
    sec = fx.create_section(term["id"], room["id"], instructor["id"], discipline="JAZZ")
    fx.add_session(sec["id"], day_of_week=1, start_minute=600, end_minute=660)
    # NOTE: term is NOT opened, so the section is SCHEDULED, not OPEN.
    family = fx.create_family()
    student = fx.create_student(family["id"], level="ELITE")

    resp = api.create_enrollment(f.create_enrollment_payload(student["id"], sec["id"]), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    sec_after = validate_success(api.get_section(sec["id"], ADMIN_H))
    assert sec_after["status"] == "SCHEDULED"


# =========================================================================
# Rule 8 — resource_temporal_overlap
# =========================================================================
def test_room_conflict_uses_buffered_window(api):
    """PRD §3.2: "a new session **room-conflicts** if, on the same `day_of_week` and in the same
    room, its window from its start up to its end *plus the room's `turnover_buffer_minutes`*
    overlaps the equivalently-buffered window of any other section's session in that room — a
    violation is rejected with `ERR_ROOM_CONFLICT`."

    With a 30-min buffer, sectionA's 600-660 session blocks sectionB's 685-745 in the same room
    (660+30=690 > 685), even though the bare intervals do not touch.

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_turnover_buffer
    """
    term = fx.create_term()
    room = fx.create_room(capacity=20, turnover_buffer_minutes=30)
    inst_a = fx.create_instructor(email="bufA@x.com")
    inst_b = fx.create_instructor(email="bufB@x.com")
    secA = fx.create_section(term["id"], room["id"], inst_a["id"], discipline="JAZZ")
    fx.add_session(secA["id"], day_of_week=0, start_minute=600, end_minute=660)
    secB = fx.create_section(term["id"], room["id"], inst_b["id"], discipline="TAP")

    resp = api.create_session(secB["id"], f.create_session_payload(
        day_of_week=0, start_minute=685, end_minute=745), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_ROOM_CONFLICT.value)


def test_instructor_conflict_uses_unbuffered_window(api):
    """PRD §3.2: "a new session **instructor-conflicts** if, on the same `day_of_week`, its plain
    start-to-end window (no buffer) overlaps another session of the same instructor, rejected
    with `ERR_INSTRUCTOR_CONFLICT`."

    The same instructor across two DIFFERENT rooms: a 650-700 session truly overlaps the existing
    600-660 session -> ERR_INSTRUCTOR_CONFLICT (no buffer applied to instructor checks).

    Design: Difficulty/resource_temporal_overlap/instructor_overlap_no_buffer
    """
    term = fx.create_term()
    room1 = fx.create_room(capacity=20, turnover_buffer_minutes=0)
    room2 = fx.create_room(capacity=20, turnover_buffer_minutes=0)
    instructor = fx.create_instructor(email="solo@x.com")
    secA = fx.create_section(term["id"], room1["id"], instructor["id"], discipline="JAZZ")
    fx.add_session(secA["id"], day_of_week=0, start_minute=600, end_minute=660)
    secB = fx.create_section(term["id"], room2["id"], instructor["id"], discipline="TAP")

    resp = api.create_session(secB["id"], f.create_session_payload(
        day_of_week=0, start_minute=650, end_minute=700), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_CONFLICT.value)
