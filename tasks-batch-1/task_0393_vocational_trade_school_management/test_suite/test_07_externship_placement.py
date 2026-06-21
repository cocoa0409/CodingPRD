"""Externship placement: temporal overlap, site capacity, conservation.

Covers difficulty queue A:
  - resource_temporal_overlap / same_agreement_externship_window_pairwise_overlap
  - resource_temporal_overlap / site_aggregate_capacity_overlap_count
  - compensating_invariant / externship_place_then_terminate_conserves_site_count
And corner queue B:
  - errors / site_suspended_rejects_new_placement
  - errors / externship_begin_before_start_term_rejected
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
ADVISOR = TEST_USERS["academic_advisor_headers"]


# --------------------------------------------------------------------------
# resource_temporal_overlap / same_agreement_externship_window_pairwise_overlap
# --------------------------------------------------------------------------
def test_same_agreement_overlapping_window_rejected(api):
    """PRD §3.8: "The requested window must not overlap any existing non-terminal
    assignment of the same agreement, because a student cannot be at two
    externships at once; an overlap is rejected with
    ERR_EXTERNSHIP_WINDOW_CONFLICT, and because windows are half-open
    [start_term_index, end_term_index), a closed-interval touch where one window's
    end equals the next window's start does not count as overlap."

    Design: Difficulty/resource_temporal_overlap/same_agreement_externship_window_pairwise_overlap
    """
    # Existing [2,5); new [4,7) overlaps (4 < 5).
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 400_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 10},
        agreement_overrides={"contract_tuition_cents": 400_000},
    )
    site = fx.create_active_site(daily_slot_capacity=10)
    fx.place_assignment(agreement["id"], site["id"], start_term_index=2, end_term_index=5, planned_hours=100)
    resp = api.create_assignment(
        {"agreement_id": agreement["id"], "site_id": site["id"],
         "start_term_index": 4, "end_term_index": 7, "planned_hours": 100}, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_EXTERNSHIP_WINDOW_CONFLICT.value)


def test_same_agreement_touching_window_allowed(api):
    """PRD §3.8: "because windows are half-open [start_term_index,
    end_term_index), a closed-interval touch where one window's end equals the
    next window's start does not count as overlap."

    Design: Difficulty/resource_temporal_overlap/same_agreement_externship_window_pairwise_overlap
    """
    # Existing [2,5); new [5,8) touches (end==start) -> allowed.
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 400_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 10},
        agreement_overrides={"contract_tuition_cents": 400_000},
    )
    site = fx.create_active_site(daily_slot_capacity=10)
    fx.place_assignment(agreement["id"], site["id"], start_term_index=2, end_term_index=5, planned_hours=100)
    created = validate_success(
        api.create_assignment(
            {"agreement_id": agreement["id"], "site_id": site["id"],
             "start_term_index": 5, "end_term_index": 8, "planned_hours": 100}, ADVISOR),
        expected_status=201)
    assert created["status"] == "PLACED", created


# --------------------------------------------------------------------------
# resource_temporal_overlap / site_aggregate_capacity_overlap_count
# --------------------------------------------------------------------------
def test_site_capacity_exceeded_by_overlapping_assignment(api):
    """PRD §3.8: "Site capacity is also enforced: the count of the site's PLACED
    and IN_PROGRESS assignments whose windows intersect the requested window must
    be strictly less than the site's daily_slot_capacity (else
    ERR_SITE_CAPACITY_EXCEEDED), and here too a closed-interval touch where end
    equals start is not an intersection."

    Design: Difficulty/resource_temporal_overlap/site_aggregate_capacity_overlap_count
    """
    # Capacity 1; A1 has [0,4); A2's [3,6) overlaps -> count 1 not < 1 -> rejected.
    program, cohort = fx.setup_program_and_cohort(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 400_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 10})
    agr1 = fx.create_enrolled_agreement(cohort["id"], contract_tuition_cents=400_000)
    agr2 = fx.create_enrolled_agreement(cohort["id"], contract_tuition_cents=400_000)
    site = fx.create_active_site(daily_slot_capacity=1)
    fx.place_assignment(agr1["id"], site["id"], start_term_index=0, end_term_index=4, planned_hours=100)
    resp = api.create_assignment(
        {"agreement_id": agr2["id"], "site_id": site["id"],
         "start_term_index": 3, "end_term_index": 6, "planned_hours": 100}, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED.value)


def test_site_capacity_allows_non_overlapping_touch(api):
    """PRD §3.8: "the count of the site's PLACED and IN_PROGRESS assignments whose
    windows intersect the requested window must be strictly less than the site's
    daily_slot_capacity (else ERR_SITE_CAPACITY_EXCEEDED), and here too a
    closed-interval touch where end equals start is not an intersection."

    Design: Difficulty/resource_temporal_overlap/site_aggregate_capacity_overlap_count
    """
    # Capacity 1; A1 [0,4); A2's [4,7) only touches -> no intersection -> allowed.
    program, cohort = fx.setup_program_and_cohort(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 400_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 10})
    agr1 = fx.create_enrolled_agreement(cohort["id"], contract_tuition_cents=400_000)
    agr2 = fx.create_enrolled_agreement(cohort["id"], contract_tuition_cents=400_000)
    site = fx.create_active_site(daily_slot_capacity=1)
    fx.place_assignment(agr1["id"], site["id"], start_term_index=0, end_term_index=4, planned_hours=100)
    created = validate_success(
        api.create_assignment(
            {"agreement_id": agr2["id"], "site_id": site["id"],
             "start_term_index": 4, "end_term_index": 7, "planned_hours": 100}, ADVISOR),
        expected_status=201)
    assert created["status"] == "PLACED", created


# --------------------------------------------------------------------------
# compensating_invariant / externship_place_then_terminate_conserves_site_count
# --------------------------------------------------------------------------
def test_place_then_terminate_conserves_site_count(api):
    """PRD §3.8: "On a successful placement the new assignment is PLACED, the
    site's active_assignment_count increases by 1, and the site's version
    increments."
    PRD §3.8: "Terminating an externship from either PLACED or IN_PROGRESS (else
    ERR_INVALID_STATE) moves it to TERMINATED, decrements the site's
    active_assignment_count by 1, and increments the site's version."

    Design: Difficulty/compensating_invariant/externship_place_then_terminate_conserves_site_count
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 400_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 10},
        agreement_overrides={"contract_tuition_cents": 400_000},
    )
    site = fx.create_active_site(daily_slot_capacity=3)
    count_before = site["active_assignment_count"]
    assignment = fx.place_assignment(agreement["id"], site["id"], start_term_index=1,
                                     end_term_index=4, planned_hours=100)
    site_placed = validate_success(api.get_externship_site(site["id"], ADVISOR))
    assert site_placed["active_assignment_count"] == count_before + 1, site_placed

    validate_success(api.terminate_assignment(assignment["id"], ADVISOR))
    site_after = validate_success(api.get_externship_site(site["id"], ADVISOR))
    assert site_after["active_assignment_count"] == count_before == 0, site_after


def test_terminate_sets_assignment_terminated(api):
    """PRD §3.8: "Terminating an externship from either PLACED or IN_PROGRESS
    (else ERR_INVALID_STATE) moves it to TERMINATED, decrements the site's
    active_assignment_count by 1, and increments the site's version."

    Design: Difficulty/compensating_invariant/externship_place_then_terminate_conserves_site_count
    """
    program, cohort, agreement, site, assignment = fx.setup_enrolled_with_placed_assignment(
        site_capacity=3, start_term_index=1, end_term_index=4, planned_hours=100)
    terminated = validate_success(api.terminate_assignment(assignment["id"], ADVISOR))
    assert terminated["status"] == "TERMINATED", terminated


# --------------------------------------------------------------------------
# corner: site_suspended_rejects_new_placement
# --------------------------------------------------------------------------
def test_placement_at_suspended_site_rejected(api):
    """PRD §3.8: "The target site must be ACTIVE; placing at a suspended site is
    rejected with ERR_SITE_SUSPENDED."

    Design: Corner/errors/site_suspended_rejects_new_placement
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    site = fx.create_active_site(daily_slot_capacity=5)
    validate_success(api.suspend_externship_site(site["id"], ADVISOR))
    resp = api.create_assignment(
        {"agreement_id": agreement["id"], "site_id": site["id"],
         "start_term_index": 1, "end_term_index": 4, "planned_hours": 100}, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_SITE_SUSPENDED.value)


# --------------------------------------------------------------------------
# corner: externship_begin_before_start_term_rejected
# --------------------------------------------------------------------------
def test_externship_begin_before_start_term_rejected(api):
    """PRD §3.8: "Beginning an externship moves it PLACED → IN_PROGRESS: it
    requires the assignment to be PLACED (else ERR_INVALID_STATE), the clock's
    current_term_index to have reached at least the assignment's start_term_index
    (else ERR_EXTERNSHIP_NOT_STARTED) ..."

    Design: Corner/errors/externship_begin_before_start_term_rejected
    """
    # PLACED externship start 5 while clock at 0.
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        cohort_overrides={"start_term_index": 0, "end_term_index": 10},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    site = fx.create_active_site(daily_slot_capacity=5)
    assignment = fx.place_assignment(agreement["id"], site["id"], start_term_index=5,
                                     end_term_index=8, planned_hours=100)
    resp = api.begin_assignment(assignment["id"], ADVISOR)
    validate_error(resp, ApiErrorId.ERR_EXTERNSHIP_NOT_STARTED.value)
