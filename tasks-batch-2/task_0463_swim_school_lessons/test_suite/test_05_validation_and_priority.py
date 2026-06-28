"""Validation ordering (deterministic priority) and individual rule violations:
session-open vs full, age vs past-due, certification, lane, reference mismatch,
empty invoice, age boundary, missing auth, and not-found.

Difficulty queue (A): priority_pair_validation_conflict.
Corner queue (B): validations + errors + entities instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_parent_headers,
    set_clock,
    create_location,
    create_level,
    create_instructor,
    create_class_session,
    open_session,
    create_parent,
    create_student,
    setup_parent_with_student,
    setup_open_session,
    create_active_enrollment,
    create_enrollment_payload,
    create_invoice_payload,
    create_invoice,
    issue_invoice,
    get_session_version,
)

ADMIN = TEST_USERS["school_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# ─── priority_pair_validation_conflict ─────────────────────────────────────
def test_session_not_open_takes_priority_over_full(api):
    """PRD §2.10: "cross-entity state preconditions (such as a session being open
    or an enrollment being active); age and certification eligibility;
    temporal-overlap conflicts; makeup-credit validity; capacity and quota"

    Enrolling into a DRAFT (not-open) capacity-1 session returns
    ERR_SESSION_NOT_OPEN — the cross-entity state precondition is checked before
    capacity/quota would ever produce ERR_SESSION_FULL.

    Design: Difficulty/priority_pair_validation_conflict/session_not_open_beats_session_full
    """
    set_clock("2026-01-05T00:00:00Z")
    location = create_location()
    level = create_level(name="Solo", min_age_months=36, max_age_months=200,
                         max_students_per_instructor=1)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(location["id"], level["id"], instructor["id"])
    parent, student = setup_parent_with_student(level["id"])
    headers = make_parent_headers(parent["id"])
    res = api.create_enrollment(
        create_enrollment_payload(student["id"], session["id"], session["version"]),
        headers,
    )
    validate_error(res, "ERR_SESSION_NOT_OPEN")


def test_age_out_of_range_takes_priority_over_past_due(api):
    """PRD §2.10: "age and certification eligibility; temporal-overlap conflicts;
    makeup-credit validity; capacity and quota; advancement gating; account
    standing and invoice-non-empty fiscal checks"

    A PAST_DUE parent enrolling an out-of-age-range student gets
    ERR_AGE_OUT_OF_RANGE — age eligibility is checked before the fiscal
    account-standing check that would produce ERR_ACCOUNT_PAST_DUE.

    Design: Difficulty/priority_pair_validation_conflict/age_out_of_range_beats_account_past_due
    """
    # Build a PAST_DUE parent: an ISSUED invoice past its due_at.
    set_clock("2026-01-05T00:00:00Z")
    env = setup_open_session(
        level_overrides={"min_age_months": 36, "max_age_months": 72,
                         "max_students_per_instructor": 4},
        clock=None,
    )
    level_id = env["level"]["id"]
    parent = create_parent()
    # An eligible student to generate billable tuition. The level window is
    # [36, 72) months; at the clock 2026-01-05 a 2022-01-01 birthdate is 48mo,
    # inside the window so the enrollment activates. (A 2017 birthdate would be
    # ~108mo, above the exclusive 72mo cap, and would itself trip
    # ERR_AGE_OUT_OF_RANGE during setup.)
    big_kid = create_student(parent, level_id, full_name="Big Kid",
                             birthdate="2022-01-01T00:00:00Z")
    create_active_enrollment(parent, big_kid, env["session"])
    inv = create_invoice(parent["id"], "2026-01-01T00:00:00Z",
                         "2026-02-01T00:00:00Z", "2026-02-01T00:00:00Z",
                         variant="FORWARD_LOOKING")
    issue_invoice(inv["id"])
    # Advance past the due_at so the account is PAST_DUE.
    set_clock("2026-02-20T00:00:00Z")
    # A 24-month student (below the 36mo min) at the current clock.
    tiny = create_student(parent, level_id, full_name="Tiny Tot",
                          birthdate="2024-02-20T00:00:00Z")
    headers = make_parent_headers(parent["id"])
    version = get_session_version(env["session"]["id"])
    res = api.create_enrollment(
        create_enrollment_payload(tiny["id"], env["session"]["id"], version),
        headers,
    )
    validate_error(res, "ERR_AGE_OUT_OF_RANGE")


def test_past_due_account_blocks_in_range_enrollment(api):
    """PRD §3.6: "For a client-initiated activation the owning parent must be in
    `CURRENT` standing; a parent in `PAST_DUE` standing is rejected with
    `ERR_ACCOUNT_PAST_DUE`."

    Positive control for the age-vs-fiscal precedence: when the student IS in the
    age window (so the age check passes) but the account is PAST_DUE, the
    enrollment returns ERR_ACCOUNT_PAST_DUE — confirming the fiscal branch is
    real and that ERR_AGE_OUT_OF_RANGE only pre-empts it when age also fails.

    Design: Difficulty/priority_pair_validation_conflict/age_out_of_range_beats_account_past_due
    """
    set_clock("2026-01-05T00:00:00Z")
    env = setup_open_session(
        level_overrides={"min_age_months": 36, "max_age_months": 200,
                         "max_students_per_instructor": 4},
        clock=None,
    )
    level_id = env["level"]["id"]
    parent = create_parent()
    big_kid = create_student(parent, level_id, full_name="Big Kid",
                             birthdate="2017-01-01T00:00:00Z")
    create_active_enrollment(parent, big_kid, env["session"])
    inv = create_invoice(parent["id"], "2026-01-01T00:00:00Z",
                         "2026-02-01T00:00:00Z", "2026-02-01T00:00:00Z",
                         variant="FORWARD_LOOKING")
    issue_invoice(inv["id"])
    set_clock("2026-02-20T00:00:00Z")
    # A second in-range student (born 2020 -> >36mo) for the PAST_DUE parent.
    in_range = create_student(parent, level_id, full_name="In Range",
                              birthdate="2020-01-01T00:00:00Z")
    headers = make_parent_headers(parent["id"])
    version = get_session_version(env["session"]["id"])
    res = api.create_enrollment(
        create_enrollment_payload(in_range["id"], env["session"]["id"], version),
        headers,
    )
    validate_error(res, "ERR_ACCOUNT_PAST_DUE")


# ─── Corner queue (B): individual rule violations ──────────────────────────
def test_open_session_instructor_not_certified_rejected(api):
    """PRD §3.4: "the assigned instructor must be `ACTIVE` and the session's level
    must appear in that instructor's `certified_level_ids`; otherwise the open is
    rejected with `ERR_INSTRUCTOR_NOT_CERTIFIED`."

    Opening a Level-1 session taught by an instructor certified only for Level 2
    is rejected ERR_INSTRUCTOR_NOT_CERTIFIED.

    Design: Corner/validations/instructor_not_certified_blocks_open
    """
    location = create_location()
    lvl2 = create_level(name="Level 2", sequence_order=2, min_age_months=36,
                        max_age_months=200, max_students_per_instructor=6,
                        monthly_tuition_cents=13000)
    lvl1 = create_level(name="Level 1", sequence_order=1, min_age_months=36,
                        max_age_months=200, max_students_per_instructor=4)
    instructor = create_instructor(full_name="Coach Two",
                                   certified_level_ids=[lvl2["id"]])
    session = create_class_session(location["id"], lvl1["id"], instructor["id"])
    res = api.open_class_session(session["id"], ADMIN)
    validate_error(res, "ERR_INSTRUCTOR_NOT_CERTIFIED")


def test_open_session_lane_conflict_rejected(api):
    """PRD §3.4: "The lane check enforces that no other session in `OPEN` or
    `DRAFT` status shares the same combination of `location_id`, `day_of_week`,
    and `lane_number` with an overlapping time window; a clash rejects the open
    with `ERR_LANE_CONFLICT`."

    A second session at the same location/day/lane with an overlapping window
    (10:30-11:15 vs an OPEN 10:00-10:45) is rejected ERR_LANE_CONFLICT.

    Design: Corner/validations/lane_conflict_blocks_create
    """
    location = create_location()
    level = create_level(min_age_months=0, max_age_months=200,
                         max_students_per_instructor=4)
    inst_a = create_instructor(full_name="Coach A", certified_level_ids=[level["id"]])
    inst_b = create_instructor(full_name="Coach B", certified_level_ids=[level["id"]])
    sess_a = create_class_session(location["id"], level["id"], inst_a["id"],
                                  lane_number=1, day_of_week=1,
                                  start_minute=600, end_minute=645)
    open_session(sess_a["id"])
    sess_b = create_class_session(location["id"], level["id"], inst_b["id"],
                                  lane_number=1, day_of_week=1,
                                  start_minute=630, end_minute=675)
    res = api.open_class_session(sess_b["id"], ADMIN)
    validate_error(res, "ERR_LANE_CONFLICT")


def test_enrollment_reference_mismatch_wrong_type_session(api):
    """PRD §3.6: "The body foreign keys are checked for type and ownership
    consistency, rejecting a mismatch with `ERR_REFERENCE_MISMATCH`."

    An enrollment whose class_session_id points at a Location id (wrong entity
    type), carrying a real session's version, is rejected ERR_REFERENCE_MISMATCH.

    Design: Corner/validations/reference_mismatch_enrollment_rejects_wrong_type_session_id
    """
    env = setup_open_session(level_overrides={
        "min_age_months": 0, "max_age_months": 200,
        "max_students_per_instructor": 4,
    })
    parent, student = setup_parent_with_student(env["level"]["id"])
    headers = make_parent_headers(parent["id"])
    version = get_session_version(env["session"]["id"])
    res = api.create_enrollment(
        create_enrollment_payload(student["id"], env["location"]["id"], version),
        headers,
    )
    validate_error(res, "ERR_REFERENCE_MISMATCH")


def test_issue_empty_invoice_rejected(api):
    """PRD §3.10: "Issuing a draft invoice moves it from `DRAFT` to `ISSUED`, but
    only if it has at least one line item; issuing an invoice with empty
    `line_items` is rejected with `ERR_EMPTY_INVOICE`."

    A DRAFT invoice for a parent with no billable enrollments has empty
    line_items and cannot be issued.

    Design: Corner/validations/issue_empty_invoice_returns_empty_invoice
    """
    set_clock("2026-01-05T00:00:00Z")
    parent = create_parent()
    inv = create_invoice(parent["id"], "2026-01-01T00:00:00Z",
                         "2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z",
                         variant="FORWARD_LOOKING")
    res = api.issue_invoice(inv["id"], BILLING)
    validate_error(res, "ERR_EMPTY_INVOICE")


def test_enroll_at_min_age_boundary_succeeds(api):
    """PRD §3.6: "The child's age must fall in the level's window — `age_months`
    at least `min_age_months` and strictly below `max_age_months` — or activation
    is rejected with `ERR_AGE_OUT_OF_RANGE`."

    A student exactly at min_age_months (36mo) is at the inclusive lower bound,
    so enrollment activates ACTIVE and ERR_AGE_OUT_OF_RANGE does not fire.

    Design: Corner/errors/age_out_of_range_eligible_at_min_boundary
    """
    env = setup_open_session(
        level_overrides={"min_age_months": 36, "max_age_months": 72,
                         "max_students_per_instructor": 4},
        clock="2026-01-01T00:00:00Z",
    )
    parent, student = setup_parent_with_student(
        env["level"]["id"],
        student_overrides={"full_name": "Just Three",
                           "birthdate": "2023-01-01T00:00:00Z"},
    )
    enr = create_active_enrollment(parent, student, env["session"])
    assert enr["status"] == "ACTIVE"
    student_read = validate_success(api.get_student(student["id"], ADMIN), 200)
    assert student_read["age_months"] == 36


def test_missing_auth_context_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is
    rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401) before any other
    processing."

    A protected write with no auth headers fails ERR_MISSING_AUTH_CONTEXT.

    Design: Corner/errors/missing_auth_context_returns_401
    """
    res = api.create_location({"name": "Main Pool"}, headers={})
    validate_error(res, "ERR_MISSING_AUTH_CONTEXT")


def test_invoice_parent_not_found(api):
    """PRD §2.6: "existence is checked in path-then-body order and the first
    missing identifier determines which not-found error is returned."
    PRD §2.6: "a missing parent `ERR_PARENT_NOT_FOUND`"

    Generating an invoice for a non-existent parent_id is rejected
    ERR_PARENT_NOT_FOUND.

    Design: Corner/errors/parent_not_found_on_invoice_create
    """
    res = api.create_invoice(
        create_invoice_payload(NON_EXISTENT_UUID, "2026-01-01T00:00:00Z",
                               "2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z"),
        BILLING,
    )
    validate_error(res, "ERR_PARENT_NOT_FOUND")
