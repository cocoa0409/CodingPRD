"""Affinity groups and chapter programs: group-status gating, venue overlap
with the 60-minute buffer, and the budget compensating invariant
(PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_affinity_group,
    assert_group_budget_invariant,
    assert_program,
    setup_group_with_leader,
    setup_proposed_program,
    setup_approved_program,
    create_program_as_leader,
    propose_program_as_leader,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
DIRECTOR = TEST_USERS["director_headers"]


# ---------------------------------------------------------------------------
# Cross-entity gate: program approval requires an ACTIVE group
# ---------------------------------------------------------------------------

def test_program_approve_rejected_while_group_suspended(api):
    """PRD §3.5: "moving `PROPOSED → APPROVED` requires the group to be
    `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`)" and "programs of the group sitting in
    `DRAFT` or `PROPOSED` survive the suspension but cannot be proposed or
    approved while it lasts."

    Design: Difficulty/cross_entity_state_dependency/program_approve_gated_by_group_status
    """
    ctx = setup_proposed_program(
        group_overrides={"name": "NYC Chapter", "annual_budget_cents": 100000},
        program_overrides={"title": "Spring Mixer", "budget_allocated_cents": 10000},
    )
    group_id = ctx["group"]["id"]
    program_id = ctx["program"]["id"]
    validate_success(api.suspend_group(group_id, DIRECTOR))

    resp = api.approve_program(program_id, STAFF)
    validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE)

    program = validate_success(api.get_program(program_id, STAFF))
    assert program["status"] == "PROPOSED"
    group = validate_success(api.get_group(group_id, STAFF))
    assert group["budget_committed_cents"] == 0


def test_program_approve_succeeds_after_group_reactivated(api):
    """PRD §3.5: "Reactivation returns `SUSPENDED → ACTIVE`" and "Approval
    commits the budget: the group's `budget_committed_cents` increases by
    `budget_allocated_cents` and `budget_remaining_cents` is re-derived."

    Design: Difficulty/cross_entity_state_dependency/program_approve_gated_by_group_status
    """
    ctx = setup_proposed_program(
        group_overrides={"name": "NYC Chapter", "annual_budget_cents": 100000},
        program_overrides={"title": "Spring Mixer", "budget_allocated_cents": 10000},
    )
    group_id = ctx["group"]["id"]
    program_id = ctx["program"]["id"]
    validate_success(api.suspend_group(group_id, DIRECTOR))
    validate_success(api.reactivate_group(group_id, DIRECTOR))

    approved = validate_success(api.approve_program(program_id, STAFF))
    assert approved["status"] == "APPROVED"
    group = validate_success(api.get_group(group_id, STAFF))
    assert group["budget_committed_cents"] == 10000
    assert group["budget_remaining_cents"] == 90000
    assert_group_budget_invariant(group)


# ---------------------------------------------------------------------------
# Venue overlap: closed interval plus 60-minute buffer
# ---------------------------------------------------------------------------

_P1 = {"title": "P1", "venue_slot_start": "2026-06-15T18:00:00Z",
       "venue_slot_end": "2026-06-15T20:00:00Z", "budget_allocated_cents": 10000}


def _group_with_approved_p1(api):
    """Group (budget 500000) with program P1 APPROVED at 18:00-20:00, so its
    occupied interval runs to 21:00 with the post-event buffer."""
    return setup_approved_program(
        group_overrides={"name": "Boston Chapter", "annual_budget_cents": 500000},
        program_overrides=dict(_P1),
    )


def test_venue_conflict_when_starting_inside_buffer(api):
    """PRD §3.5: "no other program of the same group in `APPROVED`,
    `PUBLISHED`, or `COMPLETED` may occupy an overlapping venue interval,
    where each program occupies the closed interval from its
    `venue_slot_start` to sixty minutes after its `venue_slot_end`; a
    conflict fails with `ERR_VENUE_CONFLICT`." P1 occupies
    [18:00, 21:00]; P2 starting at 20:00 overlaps it.

    Design: Difficulty/resource_temporal_overlap/program_venue_closed_interval_with_buffer
    """
    ctx = _group_with_approved_p1(api)
    p2 = create_program_as_leader(
        ctx["group"]["id"], ctx["leader"]["id"],
        title="P2 touching", venue_slot_start="2026-06-15T20:00:00Z",
        venue_slot_end="2026-06-15T22:00:00Z", budget_allocated_cents=10000,
    )
    propose_program_as_leader(p2["id"], ctx["leader"]["id"])

    resp = api.approve_program(p2["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_VENUE_CONFLICT)

    program = validate_success(api.get_program(p2["id"], STAFF))
    assert program["status"] == "PROPOSED"
    group = validate_success(api.get_group(ctx["group"]["id"], STAFF))
    assert group["budget_committed_cents"] == 10000, (
        "A rejected approval must not commit additional budget"
    )


def test_venue_conflict_when_strictly_inside_prior_interval(api):
    """PRD §3.5: "each program occupies the closed interval from its
    `venue_slot_start` to sixty minutes after its `venue_slot_end`; a
    conflict fails with `ERR_VENUE_CONFLICT`." A program at 18:30-19:30 sits
    strictly inside P1's occupied [18:00, 21:00].

    Design: Difficulty/resource_temporal_overlap/program_venue_closed_interval_with_buffer
    """
    ctx = _group_with_approved_p1(api)
    p_mid = create_program_as_leader(
        ctx["group"]["id"], ctx["leader"]["id"],
        title="P mid", venue_slot_start="2026-06-15T18:30:00Z",
        venue_slot_end="2026-06-15T19:30:00Z", budget_allocated_cents=10000,
    )
    propose_program_as_leader(p_mid["id"], ctx["leader"]["id"])

    resp = api.approve_program(p_mid["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_VENUE_CONFLICT)


# ---------------------------------------------------------------------------
# Budget compensating invariant: approve then cancel
# ---------------------------------------------------------------------------

def test_approve_commits_budget_and_rederives_remaining(api):
    """PRD §3.5: "Approval commits the budget: the group's
    `budget_committed_cents` increases by `budget_allocated_cents` and
    `budget_remaining_cents` is re-derived" and "The remaining budget is
    always derived — the annual budget minus committed minus spent — and must
    never go negative."

    Design: Difficulty/compensating_invariant/group_budget_invariant_under_approve_and_cancel
    """
    ctx = setup_proposed_program(
        group_overrides={"name": "DC Chapter", "annual_budget_cents": 200000},
        program_overrides={"title": "Gala", "budget_allocated_cents": 50000,
                           "venue_slot_start": "2026-07-10T18:00:00Z",
                           "venue_slot_end": "2026-07-10T21:00:00Z"},
    )
    approved = validate_success(api.approve_program(ctx["program"]["id"], STAFF))
    assert approved["status"] == "APPROVED"

    group = validate_success(api.get_group(ctx["group"]["id"], STAFF))
    assert_affinity_group(group)
    assert group["budget_committed_cents"] == 50000
    assert group["budget_spent_cents"] == 0
    assert group["budget_remaining_cents"] == 150000
    assert_group_budget_invariant(group)


def test_cancel_after_approve_restores_budget_exactly(api):
    """PRD §3.5: "Staff may instead cancel a program from `APPROVED` or
    `PUBLISHED`, a compensating release that decrements
    `budget_committed_cents` by `budget_allocated_cents` and re-derives the
    remainder."

    Design: Difficulty/compensating_invariant/group_budget_invariant_under_approve_and_cancel
    """
    ctx = setup_approved_program(
        group_overrides={"name": "DC Chapter", "annual_budget_cents": 200000},
        program_overrides={"title": "Gala", "budget_allocated_cents": 50000,
                           "venue_slot_start": "2026-07-10T18:00:00Z",
                           "venue_slot_end": "2026-07-10T21:00:00Z"},
    )
    cancelled = validate_success(api.cancel_program(ctx["program"]["id"], STAFF))
    assert cancelled["status"] == "CANCELLED"

    group = validate_success(api.get_group(ctx["group"]["id"], STAFF))
    assert group["budget_committed_cents"] == 0, "approve +50000 then cancel -50000"
    assert group["budget_spent_cents"] == 0
    assert group["budget_remaining_cents"] == 200000
    assert_group_budget_invariant(group)
