"""
Compensating transitions that must restore a quantity to its exact prior value.

Cancelling a booking returns the monetary ledger to zero; handing a selection back
returns the frame's integer slot identity to its pre-draw state.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_analyst_workload,
    assert_deal_dimensions,
    assert_field,
    assert_frame_slots,
    assert_ledger,
    assert_money,
    assert_not_null,
    assert_null,
    decimal_of,
)
from test_helpers.fixtures import WinLossWorld


def _booking_against_a_three_hundred_dollar_budget(world: WinLossWorld) -> WinLossWorld:
    """One 60-minute booking that consumes most of a 300.00 budget."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program(incentive_budget_usd=300.00)
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    return world


def _drawn_deal_with_no_interview(world: WinLossWorld) -> WinLossWorld:
    """A LOST deal drawn into a sealed frame, with consent only requested."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    contact = world.create_contact(incentive_eligibility="ELIGIBLE")
    world.record_consent("REQUESTED", contact_id=contact["id"])
    world.create_frame()
    world.seal_frame()
    world.after_seal = world.get_frame()
    world.draw("LOST", requested_count=1)
    return world


def _ledger_total(program: dict):
    return decimal_of(program["incentive_committed_usd"]) + decimal_of(
        program["incentive_paid_usd"]
    )


# ---------------------------------------------------------------------------
# The monetary ledger
# ---------------------------------------------------------------------------


def test_cancelling_a_scheduled_interview_releases_its_commitment(world):
    """The interview ends up cancelled and released, never paid.

    "From `SCHEDULED`, cancellation is a compensating transition: `incentive_status`
    moves `COMMITTED → RELEASED`, the program's `incentive_committed_usd` decreases
    by the provisional amount so the ledger returns to exactly its pre-scheduling
    value, `posture` is recomputed, and the analyst's still-held counters are
    released."

    Design: Difficulty/compensating_invariant/interview_cancellation_restores_incentive_ledger_conservation
    """
    _booking_against_a_three_hundred_dollar_budget(world)
    assert_money(world.interview["incentive_provisional_usd"], 250.00, "provisional")

    body = validate_success(
        world.api.cancel_interview(
            world.interview["id"],
            world.analyst_headers,
            {"cancel_reason": "Buyer withdrew consent by phone."},
        ),
        200,
    )
    interview = body

    assert_field(interview, "status", "CANCELLED")
    assert_field(interview, "incentive_status", "RELEASED")
    assert_null(interview["incentive_final_usd"], "incentive_final_usd")


def test_the_ledger_returns_to_exactly_its_pre_scheduling_total(world):
    """250.00 committed before, 0.00 across both totals after; nothing became paid.

    "An interview whose `incentive_status` is `RELEASED` or `FORFEITED` contributes
    to neither total."

    Design: Difficulty/compensating_invariant/interview_cancellation_restores_incentive_ledger_conservation
    """
    _booking_against_a_three_hundred_dollar_budget(world)
    before = world.refresh_program()
    assert_ledger(before, 250.00, 0.00)
    assert _ledger_total(before) == decimal_of(250.00), "ledger total before the cancel"

    validate_success(
        world.api.cancel_interview(
            world.interview["id"],
            world.analyst_headers,
            {"cancel_reason": "Buyer withdrew consent by phone."},
        ),
        200,
    )

    after = world.refresh_program()
    assert_ledger(after, 0.00, 0.00, "OPEN")
    assert _ledger_total(after) == decimal_of(0.00), (
        f"ledger not restored: {after['incentive_committed_usd']} committed, "
        f"{after['incentive_paid_usd']} paid"
    )


def test_the_cancellation_releases_the_analyst_but_not_the_sampling_slot(world):
    """The calendar is freed while the frame's selection is deliberately left alone.

    "cancelling a scheduled interview likewise removes it, returning the ledger to
    exactly its pre-scheduling value"

    Design: Difficulty/compensating_invariant/interview_cancellation_restores_incentive_ledger_conservation
    """
    _booking_against_a_three_hundred_dollar_budget(world)
    assert_analyst_workload(world.get_analyst(), 1, 75)

    validate_success(
        world.api.cancel_interview(
            world.interview["id"],
            world.analyst_headers,
            {"cancel_reason": "Buyer withdrew consent by phone."},
        ),
        200,
    )

    assert_analyst_workload(world.get_analyst(), 0, 0)
    assert_deal_dimensions(
        world.get_deal(), research_status="SELECTED", interview_coverage_count=0
    )
    assert_frame_slots(world.get_frame(), selected_lost=1, open_lost=1)


# ---------------------------------------------------------------------------
# The integer slot identity
# ---------------------------------------------------------------------------


def test_sealing_and_drawing_move_the_slot_identity_by_exactly_one(world):
    """The lost stratum reads 0 plus 2 after sealing and 1 plus 1 after the draw.

    "the frame's selected count for that stratum increases by one per drawn deal and
    its open slots decrease by the same amount, `coverage_ratio` is recomputed, and
    both the frame's `version` and each drawn deal's `version` increment"

    Design: Difficulty/compensating_invariant/decline_selection_restores_sampling_slot_conservation
    """
    _drawn_deal_with_no_interview(world)

    assert_frame_slots(world.after_seal, selected_lost=0, open_lost=2, coverage=0.0000)
    assert_frame_slots(world.get_frame(), selected_lost=1, open_lost=1, coverage=0.2000)


def test_declining_the_selection_restores_the_pre_draw_slot_counts(world):
    """Both sides of the identity move back together, and coverage falls to zero.

    "The decline is a compensating transition: the frame's selected count for the
    deal's stratum decreases by one and its open slots increase by one, restoring the
    conservation invariant to exactly its pre-draw value, `coverage_ratio` is
    recomputed, and `selection_rank_score` is set back to null while `stratum` and
    `sampling_frame_id` are retained for audit."

    Design: Difficulty/compensating_invariant/decline_selection_restores_sampling_slot_conservation
    """
    _drawn_deal_with_no_interview(world)

    validate_success(
        world.api.decline_selection(
            world.deal["id"],
            world.analyst_headers,
            {"decline_note": "Buyer declined to participate."},
        ),
        200,
    )

    frame = world.get_frame()
    assert_frame_slots(frame, selected_lost=0, open_lost=2, coverage=0.0000)
    assert_field(frame, "quota_lost", 2)
    assert_frame_slots(frame, open_won=2, open_no_decision=1)


def test_the_declined_deal_clears_its_score_but_keeps_its_audit_trail(world):
    """The score goes away; the stratum and the frame reference stay for audit.

    "Declining a selection moves the deal `SELECTED → DECLINED` and is permitted only
    while no interview on that deal is in `SCHEDULED` or `COMPLETED` and while the
    owning frame's `status` is `SEALED` or `SUSPENDED`; an optional `decline_note` may
    accompany it."

    Design: Difficulty/compensating_invariant/decline_selection_restores_sampling_slot_conservation
    """
    _drawn_deal_with_no_interview(world)
    assert_not_null(world.get_deal()["selection_rank_score"], "selection_rank_score")

    validate_success(
        world.api.decline_selection(
            world.deal["id"],
            world.analyst_headers,
            {"decline_note": "Buyer declined to participate."},
        ),
        200,
    )

    deal = world.get_deal()
    assert_field(deal, "research_status", "DECLINED")
    assert_null(deal["selection_rank_score"], "selection_rank_score")
    assert_field(deal, "sampling_frame_id", world.frame["id"])
    assert_field(deal, "stratum", "LOST")
