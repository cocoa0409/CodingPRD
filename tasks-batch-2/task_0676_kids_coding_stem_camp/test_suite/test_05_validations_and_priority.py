"""Enrollment / promotion / showcase-accept domain validations, including the two
priority-conflict pairs from the difficulty queue.

Covers difficulty rule priority_pair_validation_conflict and corner validation
instances for duplicate enrollment, sibling index, included-session exhaustion,
promotion requirements (fail + pass), belt-too-low, and age-out-of-range.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    create_enrollment_payload, create_badge, create_accept_payload,
    setup_catalogue, create_guardian, create_member, create_belt_level,
    create_active_membership, create_open_session, enroll_drop_in, enroll_membership,
    current_session_version, award_badge, setup_open_showcase, submit_entry,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


# ─── priority_pair_validation_conflict / program_mismatch_referential_beats_age_constraint ─
def test_program_mismatch_beats_age_check(api):
    """PRD §3.5: "First, the member's `program_id` must equal the session's `program_id`,
    or the request is rejected with `ERR_PROGRAM_MISMATCH` (HTTP 409). Next, the member's
    age in whole completed years at the logical clock must fall within the session
    program's `min_age` and `max_age`, inclusive of both ends, or the request is rejected
    with `ERR_AGE_OUT_OF_RANGE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/program_mismatch_referential_beats_age_constraint
    """
    center, px, _ = setup_catalogue(min_age=4, max_age=18, drop_in_fee_cents=4000)
    py = get_success_data(api.create_program(
        {"name": "PY", "code": "PYX1", "min_age": 4, "max_age": 9, "drop_in_fee_cents": 4000},
        ADMIN))
    get_success_data(api.create_belt_level(
        {"program_id": py["id"], "name": "White", "rank": 1, "required_badge_count": 0}, ADMIN))
    guardian = create_guardian()
    # Member on PX, born 2014-01-01 => age 12 at clock default, out of PY's 4-9 range.
    member = create_member(guardian["id"], px["id"], birth_date="2014-01-01")
    session, _ = create_open_session(center["id"], py["id"], assigned_instructor_count=5)
    v0 = current_session_version(session["id"])
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], member["id"], v0, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_PROGRAM_MISMATCH")


def test_program_mismatch_winner_status_409(api):
    """PRD §2.10: "The relative ordering ensures, for example, that a program mismatch
    surfaces as `ERR_PROGRAM_MISMATCH` before a capacity check could mask it."

    Design: Difficulty/priority_pair_validation_conflict/program_mismatch_referential_beats_age_constraint
    """
    center, px, _ = setup_catalogue(min_age=4, max_age=18, drop_in_fee_cents=4000)
    py = get_success_data(api.create_program(
        {"name": "PY", "code": "PYX2", "min_age": 4, "max_age": 9, "drop_in_fee_cents": 4000},
        ADMIN))
    get_success_data(api.create_belt_level(
        {"program_id": py["id"], "name": "White", "rank": 1, "required_badge_count": 0}, ADMIN))
    guardian = create_guardian()
    member = create_member(guardian["id"], px["id"], birth_date="2014-01-01")
    session, _ = create_open_session(center["id"], py["id"], assigned_instructor_count=5)
    v0 = current_session_version(session["id"])
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], member["id"], v0, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian["id"]),
    )
    assert res.status_code == 409


# ─── priority_pair_validation_conflict / session_capacity_safety_beats_stale_version_constraint ─
def test_capacity_safety_beats_stale_version(api):
    """PRD §3.5: "The enrollment must not push the session's `confirmed_seat_count` above
    the session's effective capacity; a create that would exceed effective capacity is
    rejected with `ERR_SESSION_AT_CAPACITY` (HTTP 409). Finally the optimistic-concurrency
    check on `expected_session_version` is applied (yielding `ERR_STALE_SESSION_VERSION`,
    HTTP 412, on a mismatch)"

    Design: Difficulty/priority_pair_validation_conflict/session_capacity_safety_beats_stale_version_constraint
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 1, "min_student_instructor_ratio": 1}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "CSV1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    get_success_data(api.create_belt_level(
        {"program_id": program["id"], "name": "White", "rank": 1, "required_badge_count": 0},
        ADMIN))
    # Distinct guardians so the second enrollment's sibling_index=1 is correct
    # (the sibling-index check, which precedes capacity, must pass to expose the
    # capacity-vs-stale-version priority under test).
    guardian1 = create_guardian()
    guardian2 = create_guardian()
    m1 = create_member(guardian1["id"], program["id"])
    m2 = create_member(guardian2["id"], program["id"])
    session, v_stale = create_open_session(center["id"], program["id"],
                                           device_seats_requested=1, assigned_instructor_count=1)
    # effective_capacity = min(1//1, 1*1) = 1. Fill the single seat with v_stale.
    enroll_drop_in(guardian1["id"], session["id"], m1["id"], sibling_index=1,
                   expected_session_version=v_stale)
    # Second create: both at capacity AND carries the stale (pre-fill) version.
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], m2["id"], v_stale, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian2["id"]),
    )
    validate_error(res, "ERR_SESSION_AT_CAPACITY")


def test_capacity_safety_winner_status_409(api):
    """PRD §2.10: "those domain rules are themselves ordered, as described in the
    enrollment workflow: program match, then age, then duplicate enrollment, then schedule
    conflict, then sibling-index, then membership coverage, then seat capacity, then the
    optimistic-concurrency version check, and finally field-shape validation."

    Design: Difficulty/priority_pair_validation_conflict/session_capacity_safety_beats_stale_version_constraint
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 1, "min_student_instructor_ratio": 1}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "CSV2", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    get_success_data(api.create_belt_level(
        {"program_id": program["id"], "name": "White", "rank": 1, "required_badge_count": 0},
        ADMIN))
    # Distinct guardians so the second enrollment's sibling_index=1 is correct
    # and the capacity check (not the earlier sibling-index check) is the decider.
    guardian1 = create_guardian()
    guardian2 = create_guardian()
    m1 = create_member(guardian1["id"], program["id"])
    m2 = create_member(guardian2["id"], program["id"])
    session, v_stale = create_open_session(center["id"], program["id"],
                                           device_seats_requested=1, assigned_instructor_count=1)
    enroll_drop_in(guardian1["id"], session["id"], m1["id"], sibling_index=1,
                   expected_session_version=v_stale)
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], m2["id"], v_stale, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian2["id"]),
    )
    assert res.status_code == 409


# ─── Corner / validations / duplicate_enrollment_same_session_rejected ─
def test_duplicate_enrollment_rejected(api):
    """PRD §3.5: "Next, the member must not already hold a non-terminal enrollment in this
    session — that is, no existing enrollment for this member on this session whose
    attendance is `RESERVED` or `CHECKED_IN` — or the request is rejected with
    `ERR_DUPLICATE_ENROLLMENT` (HTTP 409)."

    Design: Corner/validations/duplicate_enrollment_same_session_rejected
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enroll_drop_in(guardian["id"], session["id"], member["id"], sibling_index=1)
    v1 = current_session_version(session["id"])
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], member["id"], v1, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_DUPLICATE_ENROLLMENT")


# ─── Corner / validations / invalid_sibling_index_gap_rejected ─
def test_invalid_sibling_index_gap_rejected(api):
    """PRD §3.5: "The supplied `sibling_index` must equal one plus the count of the same
    guardian's other children who already hold a non-terminal enrollment in this session —
    leaving no gaps and no duplicates — or the request is rejected with
    `ERR_INVALID_SIBLING_INDEX` (HTTP 409)."

    Design: Corner/validations/invalid_sibling_index_gap_rejected
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, v0 = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], member["id"], v0, coverage="DROP_IN",
                                 sibling_index=2),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_INVALID_SIBLING_INDEX")


# ─── Corner / validations / membership_coverage_without_included_seats_rejected ─
def test_membership_no_included_sessions_rejected(api):
    """PRD §3.5: "For `MEMBERSHIP` coverage, the member must have an `ACTIVE` membership
    whose `sessions_used_this_cycle` is strictly less than its `included_sessions_per_cycle`
    (so an included seat remains), or the request is rejected with `ERR_NO_INCLUDED_SESSIONS`
    (HTTP 409)."

    Design: Corner/validations/membership_coverage_without_included_seats_rejected
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    create_active_membership(guardian["id"], member["id"],
                             monthly_fee_cents=5000, included_sessions_per_cycle=1)
    session_a, _ = create_open_session(center["id"], program["id"], format="WEEKLY",
                                       week_count=1, assigned_instructor_count=5)
    enroll_membership(guardian["id"], session_a["id"], member["id"])  # uses the 1 included
    session_b, vb = create_open_session(center["id"], program["id"], format="WEEKLY",
                                        week_count=1, starts_at="2026-05-03T16:00:00Z",
                                        ends_at="2026-05-03T18:00:00Z", assigned_instructor_count=5)
    res = api.create_enrollment(
        create_enrollment_payload(session_b["id"], member["id"], vb, coverage="MEMBERSHIP"),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_NO_INCLUDED_SESSIONS")


# ─── Corner / validations / promotion_requirements_not_met_rejected ─
def test_promotion_requirements_not_met_rejected(api):
    """PRD §3.7: "Promotion is permitted only when the member's `active_badge_count` for
    the current belt is at least the current belt's `required_badge_count`, and the member
    currently holds the prerequisite belt in rank order; if these requirements are not met
    — including the case where no next belt exists — the request is rejected with
    `ERR_PROMOTION_REQUIREMENTS_NOT_MET` (HTTP 409)."

    Design: Corner/validations/promotion_requirements_not_met_rejected
    """
    program = get_success_data(api.create_program(
        {"name": "P", "code": "PMR1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    b1 = create_belt_level(program["id"], rank=1, required_badge_count=2)
    create_belt_level(program["id"], rank=2, prereq_belt_level_id=b1["id"],
                      required_badge_count=2)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    res = api.promote_member(member["id"], INSTRUCTOR)
    validate_error(res, "ERR_PROMOTION_REQUIREMENTS_NOT_MET")
    member_after = get_success_data(api.get_member(member["id"], ADMIN))
    assert member_after["current_belt_level_id"] == b1["id"]


# ─── Corner / validations / promotion_succeeds_when_badges_met ─
def test_promotion_succeeds_resets_badge_count(api):
    """PRD §3.7: "On a successful promotion, the member's `current_belt_level_id` advances
    to the rank-plus-one belt of the program, the member's `active_badge_count` is
    recomputed for the new current belt (effectively resetting relative to the new belt),
    and the member's `version` is incremented by one."

    Design: Corner/validations/promotion_succeeds_when_badges_met
    """
    center, program, b1 = setup_catalogue(drop_in_fee_cents=4000, required_badge_count=2)
    b2 = create_belt_level(program["id"], rank=2, prereq_belt_level_id=b1["id"],
                           required_badge_count=2)
    bd1 = create_badge(b1["id"], name="Loops")
    bd2 = create_badge(b1["id"], name="Variables")
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    award_badge(enrollment["id"], bd1["id"])
    award_badge(enrollment["id"], bd2["id"])
    promoted = get_success_data(api.promote_member(member["id"], INSTRUCTOR))
    assert promoted["current_belt_level_id"] == b2["id"]
    assert promoted["active_badge_count"] == 0


# ─── Corner / validations / belt_too_low_on_accept_rejected ─
def test_belt_too_low_on_accept_rejected(api):
    """PRD §3.8: "An accept whose member's belt rank is below `min_belt_rank` is rejected
    with `ERR_BELT_TOO_LOW` (HTTP 409)"

    Design: Corner/validations/belt_too_low_on_accept_rejected
    """
    center, program, b1 = setup_catalogue(drop_in_fee_cents=4000)
    create_belt_level(program["id"], rank=2, prereq_belt_level_id=b1["id"],
                      required_badge_count=0)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])  # current belt rank 1
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 2,
         "capacity": 5, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    opened = get_success_data(api.open_showcase(created["id"], ADMIN))
    entry = submit_entry(guardian["id"], opened["id"], member["id"])
    res = api.accept_showcase_entry(entry["id"], create_accept_payload(opened["version"]), ADMIN)
    validate_error(res, "ERR_BELT_TOO_LOW")


# ─── Corner / errors / error_age_out_of_range_satisfied_path_note ─
def test_age_out_of_range_rejected(api):
    """PRD §3.5: "Next, the member's age in whole completed years at the logical clock
    must fall within the session program's `min_age` and `max_age`, inclusive of both ends,
    or the request is rejected with `ERR_AGE_OUT_OF_RANGE` (HTTP 409)."

    Design: Corner/errors/error_age_out_of_range_satisfied_path_note
    """
    center, program, _ = setup_catalogue(min_age=4, max_age=9, drop_in_fee_cents=4000)
    guardian = create_guardian()
    # Born 2014-01-01 => age 12 at clock default, above program max_age 9.
    member = create_member(guardian["id"], program["id"], birth_date="2014-01-01")
    session, v0 = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], member["id"], v0, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_AGE_OUT_OF_RANGE")
