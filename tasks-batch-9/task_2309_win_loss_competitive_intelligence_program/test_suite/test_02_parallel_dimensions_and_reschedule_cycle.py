"""
State machines that are not a single forward line.

A deal carries two dimensions that move on their own, and an interview leaves
`SCHEDULED` for `NO_SHOW` and comes back again with its money re-committed.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_deal_dimensions,
    assert_field,
    assert_ledger,
    assert_money,
    assert_ratio,
)
from test_helpers.fixtures import WinLossWorld


def _answered_interview(world: WinLossWorld) -> WinLossWorld:
    """A booked, fully answered interview on a drawn ENTERPRISE loss."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_reason("PRICE", "Price")
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.set_clock("2026-08-10T15:30:00.000Z")
    return world


def _booked_interview_past_the_grace_period(world: WinLossWorld) -> WinLossWorld:
    """A booked interview with the clock one minute past start plus the grace."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.set_clock("2026-08-10T14:16:00.000Z")
    return world


# ---------------------------------------------------------------------------
# Two dimensions on one deal row
# ---------------------------------------------------------------------------


def test_completion_advances_only_the_research_dimension(world):
    """The deal reaches (INTERVIEWED, UNATTRIBUTED), a pair only parallelism allows.

    "Deals carry **two independent status dimensions** on the same row."

    Design: Difficulty/non_linear_state_machine/deal_research_and_attribution_dimensions_advance_independently
    """
    _answered_interview(world)

    validate_success(
        world.api.complete_interview(
            world.interview["id"],
            f.complete_interview_payload("2026-08-10T14:00:00.000Z", "2026-08-10T15:00:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )

    assert_deal_dimensions(
        world.get_deal(),
        research_status="INTERVIEWED",
        attribution_status="UNATTRIBUTED",
        interview_coverage_count=1,
    )


def test_authoring_an_attribution_advances_only_the_attribution_dimension(world):
    """Authoring moves the attribution dimension and leaves research where it is.

    "The two dimensions evolve independently: nothing in the research dimension is
    implied by the attribution dimension except where a rule says so explicitly."

    Design: Difficulty/non_linear_state_machine/deal_research_and_attribution_dimensions_advance_independently
    """
    _answered_interview(world)
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    deal = world.get_deal()

    body = validate_success(
        world.api.create_loss_attribution(
            f.loss_attribution_payload(
                deal["id"], world.reasons["PRICE"]["id"], deal["version"]
            ),
            world.analyst_headers,
        ),
        201,
    )
    attribution = body

    assert_field(attribution, "status", "PROVISIONAL")
    assert_deal_dimensions(
        world.get_deal(),
        research_status="INTERVIEWED",
        attribution_status="PROVISIONAL",
    )


def test_the_authored_attribution_carries_its_derived_weight_and_confidence(world):
    """A sole primary reason takes the whole weight and leaves nothing secondary.

    "`weight_secondary` computed as one minus `weight_primary` rounded to two
    decimal places — which is 0.00 when there is no secondary reason"

    Design: Difficulty/non_linear_state_machine/deal_research_and_attribution_dimensions_advance_independently
    """
    _answered_interview(world)
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    attribution = world.create_attribution(world.reasons["PRICE"]["id"])

    stored = world.get_attribution(attribution["id"])
    assert_field(stored, "status", "PROVISIONAL")
    assert_money(stored["weight_primary"], 1.00, "weight_primary")
    assert_money(stored["weight_secondary"], 0.00, "weight_secondary")
    assert_ratio(stored["confidence_score"], 0.60, "confidence_score")


# ---------------------------------------------------------------------------
# The no-show / reschedule cycle
# ---------------------------------------------------------------------------


def test_no_show_forfeits_the_commitment_and_releases_the_calendar(world):
    """The outbound leg of the cycle returns the ledger to zero.

    "The interview moves `SCHEDULED → NO_SHOW`, its `incentive_status` moves
    `COMMITTED → FORFEITED`, the program's `incentive_committed_usd` decreases by
    the provisional amount so the conservation of the ledger is restored, `posture`
    is recomputed and the program's `version` increments, and the analyst's
    `open_interview_count` and `committed_minutes` are released by one interview
    and by the scheduled duration plus fifteen respectively."

    Design: Difficulty/non_linear_state_machine/interview_no_show_then_reschedule_returns_to_scheduled_with_recommitment
    """
    _booked_interview_past_the_grace_period(world)
    assert_ledger(world.refresh_program(), 250.00, 0.00, "OPEN")
    assert_analyst_workload(world.get_analyst(), 1, 75)

    body = validate_success(
        world.api.no_show_interview(world.interview["id"], world.analyst_headers), 200
    )
    interview = body

    assert_field(interview, "status", "NO_SHOW")
    assert_field(interview, "incentive_status", "FORFEITED")
    assert_ledger(world.refresh_program(), 0.00, 0.00, "OPEN")
    assert_analyst_workload(world.get_analyst(), 0, 0)


def test_reschedule_returns_the_interview_to_scheduled_and_re_commits_the_money(world):
    """The return leg is not a no-op: the money is charged again on a new interval.

    "On success the interval is replaced, `reschedule_count` increases by one,
    `incentive_provisional_usd` is recomputed by the provisional variant against
    the new interval, `incentive_status` moves `FORFEITED → COMMITTED`, the
    program's `incentive_committed_usd` increases by the new provisional amount
    with `posture` recomputed and `version` incremented, and the analyst's
    `open_interview_count` increases by one while `committed_minutes` is
    re-reserved for the new duration plus fifteen."

    Design: Difficulty/non_linear_state_machine/interview_no_show_then_reschedule_returns_to_scheduled_with_recommitment
    """
    _booked_interview_past_the_grace_period(world)
    world.no_show()

    body = validate_success(
        world.api.reschedule_interview(
            world.interview["id"],
            f.reschedule_payload("2026-08-20T09:00:00.000Z", "2026-08-20T10:00:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )
    interview = body

    assert_field(interview, "status", "SCHEDULED")
    assert_field(interview, "reschedule_count", 1)
    assert_field(interview, "incentive_status", "COMMITTED")
    assert_money(interview["incentive_provisional_usd"], 250.00, "provisional")
    assert interview["scheduled_start_at"] == "2026-08-20T09:00:00.000Z", (
        f"interval not replaced: {interview['scheduled_start_at']}"
    )
    assert_ledger(world.refresh_program(), 250.00, 0.00, "OPEN")
    assert_analyst_workload(world.get_analyst(), 1, 75)


def test_the_interview_cycle_never_touches_the_deal_research_dimension(world):
    """Looping through NO_SHOW and back leaves the deal at SELECTED.

    "Each drawn deal transitions `NOT_SELECTED → SELECTED`."

    Design: Difficulty/non_linear_state_machine/interview_no_show_then_reschedule_returns_to_scheduled_with_recommitment
    """
    _booked_interview_past_the_grace_period(world)
    assert_deal_dimensions(world.get_deal(), research_status="SELECTED")

    world.no_show()
    assert_deal_dimensions(world.get_deal(), research_status="SELECTED")

    validate_success(
        world.api.reschedule_interview(
            world.interview["id"],
            f.reschedule_payload("2026-08-20T09:00:00.000Z", "2026-08-20T10:00:00.000Z"),
            world.analyst_headers,
        ),
        200,
    )
    assert_deal_dimensions(
        world.get_deal(), research_status="SELECTED", interview_coverage_count=0
    )
