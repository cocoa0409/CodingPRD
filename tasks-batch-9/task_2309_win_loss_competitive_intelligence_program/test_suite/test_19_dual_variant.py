"""
Two variants of one formula: the two selection bases split an identical pool, and the
provisional incentive is re-measured on a rebooked interval rather than carried over.
"""

from typing import Tuple

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_deal_dimensions,
    assert_field,
    assert_fields,
    assert_frame_slots,
    assert_ledger,
    assert_money,
    assert_null,
    assert_ratio,
)
from test_helpers.fixtures import WinLossWorld

CLOCK = "2026-08-01T00:00:00.000Z"


def _identical_pool(
    world: WinLossWorld, selection_basis: str, tag: str
) -> Tuple[dict, dict, dict]:
    """One program, one PRIMARY competitor and the same two consented losses."""
    world.set_clock(CLOCK)
    world.active_program(name=f"WL {tag}", fiscal_quarter="FY27Q1")
    competitor = world.create_competitor()
    world.create_analyst(linked_user_ref=f"u-ana-{tag}")
    enterprise = world.create_deal(
        crm_deal_ref="CRM-ENT",
        acr_usd=500000.00,
        close_date="2026-04-05T00:00:00.000Z",
        segment="ENTERPRISE",
        primary_competitor_id=competitor["id"],
    )
    midmarket = world.create_deal(
        crm_deal_ref="CRM-MID",
        acr_usd=150000.00,
        close_date="2026-06-30T00:00:00.000Z",
        segment="MIDMARKET",
        primary_competitor_id=competitor["id"],
    )
    world.consented_contact(deal_id=enterprise["id"], email="ent@acme.test")
    world.consented_contact(deal_id=midmarket["id"], email="mid@acme.test")
    frame = world.create_frame(
        quota_won=0,
        quota_lost=1,
        quota_no_decision=0,
        selection_basis=selection_basis,
    )
    world.seal_frame(frame["id"])
    return enterprise, midmarket, frame


def _draw_one(world: WinLossWorld, frame: dict) -> list:
    return validate_success(
        world.api.draw_frame(
            frame["id"],
            f.draw_payload("LOST", requested_count=1),
            world.analyst_headers,
        ),
        201,
    )


def test_the_two_bases_draw_different_deals_from_identical_pools(world, api):
    """Only the basis differs, and the basis alone decides which loss is researched.

    "Under `STRATIFIED_BY_SEGMENT`, the raw score is forty hundredths of the value term
    plus forty hundredths of the recency term plus the competitor term, and the final
    `selection_rank_score` is that raw score rounded to four decimal places; the deal's
    `segment` does not multiply anything here, because stratification is expressed through
    the ordering rule instead. Under `VALUE_WEIGHTED`, the raw score is sixty-five
    hundredths of the value term plus fifteen hundredths of the recency term plus the
    competitor term; that raw score is then multiplied by 1.25 when the deal's `segment` is
    `ENTERPRISE` and by 1.00 otherwise, and the product is rounded to four decimal places."

    Design: Corner/dual_variant_calculation/the_two_selection_bases_draw_different_deals_from_an_identical_pool
    """
    stratified_enterprise, stratified_midmarket, stratified_frame = _identical_pool(
        world, "STRATIFIED_BY_SEGMENT", "A"
    )
    other = WinLossWorld(api)
    value_enterprise, value_midmarket, value_frame = _identical_pool(
        other, "VALUE_WEIGHTED", "B"
    )

    stratified_draw = _draw_one(world, stratified_frame)
    value_draw = _draw_one(other, value_frame)

    assert len(stratified_draw) == 1, f"expected one drawn deal, got {stratified_draw}"
    assert_field(stratified_draw[0], "id", stratified_midmarket["id"])
    assert_ratio(
        stratified_draw[0]["selection_rank_score"], 0.8689, "selection_rank_score"
    )

    assert len(value_draw) == 1, f"expected one drawn deal, got {value_draw}"
    assert_field(value_draw[0], "id", value_enterprise["id"])
    assert_ratio(value_draw[0]["selection_rank_score"], 1.2521, "selection_rank_score")

    passed_over = world.get_deal(stratified_enterprise["id"])
    assert_field(passed_over, "research_status", "NOT_SELECTED")
    assert_null(passed_over["selection_rank_score"], "selection_rank_score")
    passed_over_other = other.get_deal(value_midmarket["id"])
    assert_field(passed_over_other, "research_status", "NOT_SELECTED")
    assert_null(passed_over_other["selection_rank_score"], "selection_rank_score")

    assert_frame_slots(
        world.get_frame(stratified_frame["id"]), selected_lost=1, open_lost=0
    )
    assert_frame_slots(other.get_frame(value_frame["id"]), selected_lost=1, open_lost=0)


def test_a_rebooking_recomputes_the_provisional_on_the_new_interval(world):
    """The provisional variant re-measures the fresh slot; nothing is carried over.

    "On success the interval is replaced, `reschedule_count` increases by one,
    `incentive_provisional_usd` is recomputed by the provisional variant against the new
    interval, `incentive_status` moves `FORFEITED → COMMITTED`, the program's
    `incentive_committed_usd` increases by the new provisional amount with `posture`
    recomputed and `version` incremented, and the analyst's `open_interview_count`
    increases by one while `committed_minutes` is re-reserved for the new duration plus
    fifteen."

    "The **provisional** variant measures `scheduled_end_at` minus `scheduled_start_at`,
    stores its output in `incentive_provisional_usd`, and adds that amount to the program's
    `incentive_committed_usd`."

    Design: Corner/dual_variant_calculation/reschedule_recomputes_the_provisional_on_the_new_interval_not_the_old_one
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    interview = world.schedule_interview()
    world.set_clock("2026-08-10T14:20:00.000Z")
    world.no_show(interview["id"])

    rebooked = validate_success(
        world.api.reschedule_interview(
            interview["id"],
            f.reschedule_payload(
                "2026-08-12T09:00:00.000Z", "2026-08-12T09:30:00.000Z"
            ),
            world.analyst_headers,
        ),
        200,
    )

    assert_fields(
        rebooked,
        {
            "status": "SCHEDULED",
            "reschedule_count": 1,
            "incentive_status": "COMMITTED",
            "scheduled_start_at": "2026-08-12T09:00:00.000Z",
        },
    )
    assert_money(
        rebooked["incentive_provisional_usd"], 150.00, "incentive_provisional_usd"
    )
    assert_ledger(world.refresh_program(), committed_usd=150.00, paid_usd=0.00, posture="OPEN")
    assert_analyst_workload(world.get_analyst(), open_interview_count=1, committed_minutes=45)
    assert_deal_dimensions(
        world.get_deal(), research_status="SELECTED", interview_coverage_count=0
    )
