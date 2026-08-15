"""Cohort capacity, waitlist promotion, window progression, and joinability."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_member,
    create_open_cohort,
    get_cohort,
    get_membership,
    make_coach_headers,
    set_clock,
    setup_active_enrollment,
    setup_multi_client_active_enrollments,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["practice_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / cohort_capacity_exact_boundary
# ---------------------------------------------------------------------------

def test_cohort_joins_below_capacity_land_active(api):
    """PRD §3.7: "Capacity decides the landing state: while the count of
    `ACTIVE` members is below `capacity`, the new membership lands `ACTIVE`,
    stamped with a server-assigned `joined_at`".

    Design: Difficulty/boundary_precision_check/cohort_capacity_exact_boundary
    """
    ctx = setup_multi_client_active_enrollments(2)
    coach_a = ctx["coach_a"]
    e1, e2 = ctx["enrollments"]
    cohort = create_open_cohort(coach_a, capacity=2, title="Pair Cohort")
    m1 = add_member(cohort["id"], e1["id"], coach_a)
    m2 = add_member(cohort["id"], e2["id"], coach_a)
    assert m1["member_status"] == "ACTIVE", "join at count 0 (< capacity 2)"
    assert m2["member_status"] == "ACTIVE", "join at count 1 (< capacity 2)"
    assert m1.get("joined_at") and m2.get("joined_at")


def test_cohort_join_at_exact_capacity_lands_waitlisted(api):
    """PRD §3.7: "at capacity it lands `WAITLISTED` — a full cohort is a
    waitlist outcome, never an error."

    Design: Difficulty/boundary_precision_check/cohort_capacity_exact_boundary
    """
    ctx = setup_multi_client_active_enrollments(3)
    coach_a = ctx["coach_a"]
    e1, e2, e3 = ctx["enrollments"]
    cohort = create_open_cohort(coach_a, capacity=2, title="Pair Cohort")
    add_member(cohort["id"], e1["id"], coach_a)
    add_member(cohort["id"], e2["id"], coach_a)
    resp = api.add_cohort_member(
        cohort["id"], {"enrollment_id": e3["id"]},
        make_coach_headers(coach_a["id"]),
    )
    m3 = validate_success(resp, expected_status=201)
    assert m3["member_status"] == "WAITLISTED", \
        "join at count == capacity is a waitlist outcome, not an error"


def test_waitlist_promotion_order_by_joined_at(api):
    """PRD §3.7: "Whenever a removal leaves an `OPEN` or `IN_PROGRESS` cohort
    below capacity with a non-empty waitlist, exactly one `WAITLISTED` member
    promotes to `ACTIVE`: the earliest `joined_at` wins, with ties broken by
    the earliest `created_at`."

    Design: Corner/endpoints/waitlist_promotion_order_by_joined_at
    """
    # capacity=2 (PRD §3.7: "a `capacity` of at least 2") with four members
    # leaves two members waitlisted, so the promotion ORDER is observable.
    # The clock advances between the two waitlisted joins so their joined_at
    # values differ — "the earliest `joined_at` wins" then decides the order
    # without relying on the created_at tie-break.
    ctx = setup_multi_client_active_enrollments(4)
    coach_a = ctx["coach_a"]
    e1, e2, e3, e4 = ctx["enrollments"]
    cohort = create_open_cohort(coach_a, capacity=2, title="Pair Seat")
    m1 = add_member(cohort["id"], e1["id"], coach_a)
    m2 = add_member(cohort["id"], e2["id"], coach_a)
    set_clock("2026-08-04T00:00:00Z")
    m3 = add_member(cohort["id"], e3["id"], coach_a)
    set_clock("2026-08-05T00:00:00Z")
    m4 = add_member(cohort["id"], e4["id"], coach_a)
    assert m1["member_status"] == "ACTIVE"
    assert m2["member_status"] == "ACTIVE"
    assert m3["member_status"] == "WAITLISTED"
    assert m4["member_status"] == "WAITLISTED"
    validate_success(
        api.remove_cohort_member(
            cohort["id"], m1["id"], make_coach_headers(coach_a["id"])))
    assert get_membership(cohort["id"], m1["id"])["member_status"] == "REMOVED"
    assert get_membership(cohort["id"], m3["id"])["member_status"] == "ACTIVE", \
        "the earliest-joined waitlisted member promotes"
    assert get_membership(cohort["id"], m4["id"])["member_status"] == "WAITLISTED", \
        "exactly one promotion fires; the later-joined member stays waitlisted"


def test_cohort_date_progression_open_to_completed(api):
    """PRD §3.7: "when the current UTC date reaches `window_start`, an `OPEN`
    cohort turns `IN_PROGRESS`, and when the date passes `window_end`, an
    `IN_PROGRESS` cohort becomes `COMPLETED`, at which point its remaining
    `WAITLISTED` memberships move to `REMOVED` because the program is over."
    PRD §2.5: "Setting the clock re-evaluates every date-advance transition
    in the system: coach credential expiry, installment delinquency and
    default, cohort window progression from `OPEN` through `IN_PROGRESS` to
    `COMPLETED`, and the forfeiture of undelivered sessions."

    Design: Corner/consistency_model/cohort_date_progression_open_to_completed
    """
    # capacity=2 (PRD §3.7: "a `capacity` of at least 2") with three members
    # leaves one member waitlisted to exercise the completion cascade.
    ctx = setup_multi_client_active_enrollments(3)
    coach_a = ctx["coach_a"]
    e1, e2, e3 = ctx["enrollments"]
    cohort = create_open_cohort(
        coach_a, capacity=2, title="Short Window",
        window_start="2026-08-10", window_end="2026-08-20")
    m1 = add_member(cohort["id"], e1["id"], coach_a)
    add_member(cohort["id"], e2["id"], coach_a)
    m3 = add_member(cohort["id"], e3["id"], coach_a)
    assert m3["member_status"] == "WAITLISTED"
    set_clock("2026-08-10T00:00:01Z")
    assert get_cohort(cohort["id"])["cohort_status"] == "IN_PROGRESS"
    set_clock("2026-08-21T00:00:01Z")
    assert get_cohort(cohort["id"])["cohort_status"] == "COMPLETED"
    assert get_membership(cohort["id"], m3["id"])["member_status"] == "REMOVED", \
        "WAITLISTED memberships are REMOVED when the program completes"
    assert get_membership(cohort["id"], m1["id"])["member_status"] == "ACTIVE"


def test_join_draft_cohort_rejected(api):
    """PRD §3.7: "The facilitating coach adds an enrollment — named by its
    `enrollment_id` — to a cohort that stands `OPEN` or `IN_PROGRESS`; any
    other cohort status is `ERR_COHORT_NOT_JOINABLE`."

    Design: Corner/validations/join_draft_cohort_rejected
    """
    ctx = setup_active_enrollment()
    coach_a = ctx["coach_a"]
    enrollment = ctx["enrollment"]
    from test_helpers import create_cohort_payload
    resp = api.create_cohort(
        create_cohort_payload(coach_a["id"], title="Draft Cohort", capacity=4),
        make_coach_headers(coach_a["id"]),
    )
    cohort = validate_success(resp, expected_status=201)
    assert cohort["cohort_status"] == "DRAFT"
    resp = api.add_cohort_member(
        cohort["id"], {"enrollment_id": enrollment["id"]},
        make_coach_headers(coach_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COHORT_NOT_JOINABLE)
