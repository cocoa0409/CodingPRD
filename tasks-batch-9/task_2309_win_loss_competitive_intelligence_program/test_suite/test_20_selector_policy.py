"""
The selector's ordering policy: each declared tie-break in turn, and the order in which
a multi-deal draw hands its selections back.
"""

from typing import Dict, List

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_field,
    assert_fields,
    assert_frame_slots,
    assert_null,
    assert_ratio,
)
from test_helpers.fixtures import WinLossWorld

CLOCK = "2026-08-01T00:00:00.000Z"


def _program_with_competitor(world: WinLossWorld) -> Dict:
    """An ACTIVE program, one PRIMARY competitor and the analyst who draws."""
    world.set_clock(CLOCK)
    world.active_program()
    competitor = world.create_competitor()
    world.create_analyst()
    return competitor


def _consented_loss(
    world: WinLossWorld, competitor: Dict, crm_deal_ref: str, **overrides
) -> Dict:
    """One LOST deal closing 2026-06-15 with its own consented buyer."""
    deal = world.create_deal(
        crm_deal_ref=crm_deal_ref,
        primary_competitor_id=competitor["id"],
        **overrides,
    )
    world.consented_contact(
        deal_id=deal["id"], email=f"{crm_deal_ref.lower()}@acme.test"
    )
    return deal


def _sealed_frame(world: WinLossWorld, selection_basis: str) -> Dict:
    frame = world.create_frame(
        quota_won=0,
        quota_lost=2,
        quota_no_decision=0,
        selection_basis=selection_basis,
    )
    world.seal_frame(frame["id"])
    return frame


def _draw(world: WinLossWorld, frame: Dict, requested_count: int = 1) -> List[Dict]:
    return validate_success(
        world.api.draw_frame(
            frame["id"],
            f.draw_payload("LOST", requested_count=requested_count),
            world.analyst_headers,
        ),
        201,
    )


def test_a_stratified_tie_is_broken_by_segment_rank_ascending(world):
    """Segment steers the ordering, not the score, and the ranks decide the winner.

    "Under `STRATIFIED_BY_SEGMENT` the candidates are ordered by score descending, then by
    segment rank ascending where `ENTERPRISE` ranks 1, `MIDMARKET` ranks 2 and `SMB` ranks
    3, then by `close_date` descending, then by `created_at` ascending."

    "the deal's `segment` does not multiply anything here, because stratification is
    expressed through the ordering rule instead"

    Design: Corner/selector_policy/stratified_score_tie_is_broken_by_segment_rank_ascending
    """
    competitor = _program_with_competitor(world)
    enterprise = _consented_loss(world, competitor, "CRM-2001", segment="ENTERPRISE")
    midmarket = _consented_loss(world, competitor, "CRM-2002", segment="MIDMARKET")
    frame = _sealed_frame(world, "STRATIFIED_BY_SEGMENT")

    drawn = _draw(world, frame)

    assert len(drawn) == 1, f"expected one drawn deal, got {drawn}"
    assert_fields(drawn[0], {"id": enterprise["id"], "stratum": "LOST"})
    assert_ratio(drawn[0]["selection_rank_score"], 0.9956, "selection_rank_score")
    assert_field(world.get_deal(midmarket["id"]), "research_status", "NOT_SELECTED")
    assert_frame_slots(
        world.get_frame(frame["id"]), selected_lost=1, open_lost=1, coverage=0.5000
    )


def test_a_value_weighted_tie_at_the_ceiling_is_broken_by_acr_descending(world):
    """The value clamp erases the score gap, so the money ordering must still hold.

    "Under `VALUE_WEIGHTED` they are ordered by score descending, then by `acr_usd`
    descending, then by `close_date` descending, then by `created_at` ascending."

    "The **value term** is the deal's `acr_usd` divided by a normalizer of 250,000 US
    dollars, capped at 1.0000, rounded to four decimal places."

    Design: Corner/selector_policy/value_weighted_tie_at_the_value_ceiling_is_broken_by_acr_descending
    """
    competitor = _program_with_competitor(world)
    smaller = _consented_loss(
        world, competitor, "CRM-2001", segment="ENTERPRISE", acr_usd=300000.00
    )
    larger = _consented_loss(
        world, competitor, "CRM-2002", segment="ENTERPRISE", acr_usd=450000.00
    )
    frame = _sealed_frame(world, "VALUE_WEIGHTED")

    drawn = _draw(world, frame)

    assert len(drawn) == 1, f"expected one drawn deal, got {drawn}"
    assert_field(drawn[0], "id", larger["id"])
    assert_ratio(drawn[0]["selection_rank_score"], 1.3260, "selection_rank_score")
    passed_over = world.get_deal(smaller["id"])
    assert_field(passed_over, "research_status", "NOT_SELECTED")
    assert_null(passed_over["selection_rank_score"], "selection_rank_score")

    runner_up = _draw(world, frame)
    assert_field(runner_up[0], "id", smaller["id"])
    assert_ratio(
        runner_up[0]["selection_rank_score"], 1.3260, "selection_rank_score"
    )


def test_the_final_tie_break_is_created_at_ascending(world):
    """Identical in every declared input, so the earlier import must be drawn.

    "A deal's `id` is never a tie-break input under either basis."

    "Under `STRATIFIED_BY_SEGMENT` the candidates are ordered by score descending, then by
    segment rank ascending where `ENTERPRISE` ranks 1, `MIDMARKET` ranks 2 and `SMB` ranks
    3, then by `close_date` descending, then by `created_at` ascending."

    Design: Corner/selector_policy/the_last_tie_break_is_created_at_ascending_and_never_the_id
    """
    competitor = _program_with_competitor(world)
    first_imported = _consented_loss(
        world, competitor, "CRM-2001", segment="ENTERPRISE"
    )
    second_imported = _consented_loss(
        world, competitor, "CRM-2002", segment="ENTERPRISE"
    )
    frame = _sealed_frame(world, "STRATIFIED_BY_SEGMENT")

    drawn = _draw(world, frame)

    assert len(drawn) == 1, f"expected one drawn deal, got {drawn}"
    assert_fields(drawn[0], {"id": first_imported["id"], "crm_deal_ref": "CRM-2001"})
    assert_ratio(drawn[0]["selection_rank_score"], 0.9956, "selection_rank_score")
    assert_field(
        world.get_deal(second_imported["id"]), "research_status", "NOT_SELECTED"
    )
    assert_frame_slots(world.get_frame(frame["id"]), selected_lost=1, open_lost=1)


def test_a_multi_deal_draw_answers_in_selector_order(world):
    """The batch is handed back highest score first, not oldest import first.

    "the response lists the drawn deals in selector order rather than identifier order and
    is returned with a creation status code because it materialises new selections"

    Design: Corner/selector_policy/draw_response_order_is_selector_order_not_insertion_order
    """
    competitor = _program_with_competitor(world)
    low_value = _consented_loss(
        world, competitor, "CRM-2001", segment="MIDMARKET", acr_usd=60000.00
    )
    high_value = _consented_loss(
        world, competitor, "CRM-2002", segment="ENTERPRISE", acr_usd=450000.00
    )
    frame = _sealed_frame(world, "VALUE_WEIGHTED")

    drawn = _draw(world, frame, requested_count=2)

    assert len(drawn) == 2, f"expected two drawn deals, got {drawn}"
    assert_field(drawn[0], "id", high_value["id"])
    assert_ratio(drawn[0]["selection_rank_score"], 1.3260, "selection_rank_score")
    assert_field(drawn[1], "id", low_value["id"])
    assert_ratio(drawn[1]["selection_rank_score"], 0.5668, "selection_rank_score")
    for deal_id in (high_value["id"], low_value["id"]):
        assert_fields(
            world.get_deal(deal_id), {"research_status": "SELECTED", "stratum": "LOST"}
        )
    assert_frame_slots(
        world.get_frame(frame["id"]), selected_lost=2, open_lost=0, coverage=1.0000
    )
