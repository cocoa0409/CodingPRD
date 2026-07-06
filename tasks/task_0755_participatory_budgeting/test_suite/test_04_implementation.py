"""Implementation tracking: milestone state machine, completion bubble-up, report-backs."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    scenario_milestone, scenario_milestone_in_progress, scenario_implementation_proposal,
    TEST_USERS,
)

ADMIN = TEST_USERS["budget_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / milestone_in_progress_blocked_loop
# ---------------------------------------------------------------------------

def test_milestone_returns_to_in_progress_after_blocked_loop(api):
    """PRD §3.8: "moving an `IN_PROGRESS` milestone to `BLOCKED` records the supplied
    `blocked_reason`, and moving it back from `BLOCKED` to `IN_PROGRESS` clears that reason —
    a cyclic loop that may repeat."

    Design: Difficulty/non_linear_state_machine/milestone_in_progress_blocked_loop
    """
    sc = scenario_milestone_in_progress(api)
    validate_success(api.transition_milestone(sc["mid"], {"target_status": "BLOCKED", "blocked_reason": "permits pending"}, REVIEWER))
    back = validate_success(api.transition_milestone(sc["mid"], {"target_status": "IN_PROGRESS"}, REVIEWER))
    assert back["status"] == "IN_PROGRESS"


def test_milestone_blocked_reason_cleared_on_return_to_in_progress(api):
    """PRD §3.8: "moving it back from `BLOCKED` to `IN_PROGRESS` clears that reason"

    Design: Difficulty/non_linear_state_machine/milestone_in_progress_blocked_loop
    """
    sc = scenario_milestone_in_progress(api)
    blocked = validate_success(api.transition_milestone(sc["mid"], {"target_status": "BLOCKED", "blocked_reason": "permits pending"}, REVIEWER))
    assert blocked["blocked_reason"] == "permits pending"
    back = validate_success(api.transition_milestone(sc["mid"], {"target_status": "IN_PROGRESS"}, REVIEWER))
    assert back["blocked_reason"] is None, f"blocked_reason must clear to null, got {back['blocked_reason']}"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / milestone_completion_cascades_to_proposal_and_cycle_count
# ---------------------------------------------------------------------------

def test_completing_last_milestone_completes_the_proposal(api):
    """PRD §3.8: "if so — and provided the proposal has at least one milestone — it
    transitions the proposal from `IN_IMPLEMENTATION` to `COMPLETED` as a bubble-up side
    effect, incrementing the proposal's `version`."

    Design: Difficulty/transitive_cascade/milestone_completion_cascades_to_proposal_and_cycle_count
    """
    sc = scenario_milestone_in_progress(api)
    ms = validate_success(api.transition_milestone(sc["mid"], {"target_status": "COMPLETED"}, REVIEWER))
    assert ms["status"] == "COMPLETED"
    prop = validate_success(api.get_proposal(sc["pid"], ADMIN))
    assert prop["status"] == "COMPLETED"


def test_project_completion_increments_cycle_completed_count(api):
    """PRD §3.8: "That project completion in turn increments the cycle's
    `completed_project_count` by one."

    Design: Difficulty/transitive_cascade/milestone_completion_cascades_to_proposal_and_cycle_count
    """
    sc = scenario_milestone_in_progress(api)
    validate_success(api.transition_milestone(sc["mid"], {"target_status": "COMPLETED"}, REVIEWER))
    cycle = validate_success(api.get_budget_cycle(sc["cyc"], ADMIN))
    assert cycle["completed_project_count"] == 1, cycle


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / milestone_schedules_overlap_rejected_closed_buffer
# ---------------------------------------------------------------------------

def test_second_milestone_overlapping_sibling_rejected(api):
    """PRD §3.8: "A milestone whose schedule overlaps a sibling or violates that one-day
    buffer is rejected with `ERR_MILESTONE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/milestone_schedules_overlap_rejected_closed_buffer
    """
    sc = scenario_milestone(api, start="2026-05-01T00:00:00Z", end="2026-05-10T00:00:00Z")
    resp = api.create_milestone(
        sc["pid"],
        {"title": "M2", "scheduled_start": "2026-05-05T00:00:00Z", "scheduled_end": "2026-05-15T00:00:00Z"},
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_MILESTONE_OVERLAP.value)


def test_second_milestone_contained_within_sibling_rejected(api):
    """PRD §3.8: "a new milestone's window must sit clear of every sibling milestone's window
    with at least a one-day buffer between them, meaning each milestone's start must fall
    strictly after the previous one's end with a gap of at least one day."

    Design: Difficulty/resource_temporal_overlap/milestone_schedules_overlap_rejected_closed_buffer
    """
    sc = scenario_milestone(api, start="2026-05-01T00:00:00Z", end="2026-05-10T00:00:00Z")
    resp = api.create_milestone(
        sc["pid"],
        {"title": "M2", "scheduled_start": "2026-05-03T00:00:00Z", "scheduled_end": "2026-05-07T00:00:00Z"},
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_MILESTONE_OVERLAP.value)


# ---------------------------------------------------------------------------
# Corner: entities / corner_reportback_append_only_no_version
# ---------------------------------------------------------------------------

def test_report_back_is_append_only_without_version(api):
    """PRD §2.5: "The report-back resource is the one exception: it is append-only and
    immutable after creation, so it carries only `id` and `created_at`. It has no `updated_at`
    field and no `version` field."

    Design: Corner/entities/corner_reportback_append_only_no_version
    """
    sc = scenario_implementation_proposal(api)
    rb = validate_success(
        api.create_report_back(sc["pid"], {"period_label": "Q1", "narrative": "progress", "spent_cents": 1000}, REVIEWER),
        expected_status=201,
    )
    assert rb["proposal_id"] == sc["pid"]
    assert rb["spent_cents"] == 1000
    assert "version" not in rb, "append-only report-back must carry no version field"
    assert "updated_at" not in rb, "append-only report-back must carry no updated_at field"
