"""
Values placed exactly on a boundary and one step to either side of it.

The substantiation ladder's lower band edge is inclusive, and the sampling frame's
close-date window is inclusive at its start and exclusive at its end.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CLAIM_UNSUBSTANTIATED,
    ERR_NO_ELIGIBLE_DEALS,
    ERR_STRATUM_QUOTA_EXHAUSTED,
)
from test_helpers.assertions import (
    assert_field,
    assert_frame_slots,
    assert_null,
    assert_ratio,
    assert_risk_indices,
    assert_substantiation,
)
from test_helpers.fixtures import WinLossWorld


def _two_cards_astride_the_anecdotal_edge(world: WinLossWorld) -> WinLossWorld:
    """Card A's only claim scores exactly 0.90; card B's scores 0.89.

    Both cards cite fresh answers from the same completed interview, so only the
    source weights and rating factors separate the two totals.
    """
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
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Only one criterion really mattered.",
        recorded_at="2026-08-10T14:05:00.000Z",
        rating=1,
    )
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind bundled the suite.",
        recorded_at="2026-08-10T14:10:00.000Z",
        rating=3,
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="Pricing was never quantified for us.",
        recorded_at="2026-08-10T14:15:00.000Z",
    )
    world.record_response(
        question_key="PRODUCT_GAP",
        verbatim_text="Bulk export was missing.",
        recorded_at="2026-08-10T14:20:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    world.card_at_edge = world.create_battlecard(
        title="Northwind pricing", version_label="v1"
    )
    world.claim_at_edge = world.add_claim(
        [world.response_of("PRICING_PERCEPTION")["id"]],
        battlecard_id=world.card_at_edge["id"],
        claim_text="Northwind never quantifies its pricing advantage.",
        claim_type="FEATURE",
    )
    world.card_below_edge = world.create_battlecard(
        title="Northwind gaps", version_label="v2"
    )
    world.claim_below_edge = world.add_claim(
        [
            world.response_of("PRODUCT_GAP")["id"],
            world.response_of("EVALUATION_CRITERIA")["id"],
        ],
        battlecard_id=world.card_below_edge["id"],
        claim_text="Northwind lacks bulk export.",
        claim_type="FEATURE",
    )
    return world


def _sealed_frame_with_a_deal_on_the_exclusive_bound(world: WinLossWorld) -> WinLossWorld:
    """One WON deal closing at exactly the frame's `window_end`, and open won slots."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.edge_deal = world.create_deal(
        crm_deal_ref="CRM-2001",
        outcome="WON",
        acr_usd=400000.00,
        close_date="2026-07-01T00:00:00.000Z",
        sales_rep_user_ref="rep-80",
        primary_competitor_id=world.competitor["id"],
    )
    edge_contact = world.create_contact(
        deal_id=world.edge_deal["id"],
        email="buyer3@ceres.test",
        full_name="Dee Tres",
        title_band="CHAMPION",
        incentive_eligibility="ELIGIBLE",
    )
    world.record_consent(
        "REQUESTED", deal_id=world.edge_deal["id"], contact_id=edge_contact["id"]
    )
    world.create_frame()
    world.seal_frame()
    return world


def _add_deal_on_the_inclusive_bound(world: WinLossWorld) -> dict:
    """Import a WON deal closing at exactly the frame's `window_start`."""
    deal = world.create_deal(
        crm_deal_ref="CRM-2002",
        outcome="WON",
        acr_usd=200000.00,
        close_date="2026-04-01T00:00:00.000Z",
        sales_rep_user_ref="rep-81",
        primary_competitor_id=world.competitor["id"],
    )
    contact = world.create_contact(
        deal_id=deal["id"],
        email="buyer4@doric.test",
        full_name="Eve Cuatro",
        title_band="CHAMPION",
        incentive_eligibility="ELIGIBLE",
    )
    world.record_consent("REQUESTED", deal_id=deal["id"], contact_id=contact["id"])
    return deal


# ---------------------------------------------------------------------------
# The inclusive lower edge of ANECDOTAL
# ---------------------------------------------------------------------------


def test_a_score_of_exactly_nine_tenths_is_anecdotal_and_passes_submission(world):
    """One unrated pricing answer scores 0.90 and clears the gate.

    "must have no claim whose `substantiation_level` is `UNSUBSTANTIATED` —
    otherwise `ERR_CLAIM_UNSUBSTANTIATED`, whose boundary sits at a
    `substantiation_score` of exactly 0.90, which passes"

    Design: Difficulty/boundary_precision_check/substantiation_exactly_at_anecdotal_min_passes_while_one_cent_below_fails
    """
    _two_cards_astride_the_anecdotal_edge(world)
    assert_substantiation(
        world.get_claim(world.claim_at_edge["id"]), 0.90, "ANECDOTAL", "MEDIUM"
    )

    body = validate_success(
        world.api.submit_legal(world.card_at_edge["id"], world.analyst_headers), 200
    )
    card = body

    assert_field(card, "status", "LEGAL_REVIEW")
    assert_risk_indices(card, 2.00, 2.00)


def test_a_score_one_cent_below_the_edge_is_unsubstantiated(world):
    """0.40 plus 0.49 lands at 0.89 and falls out of the middle band.

    "`substantiation_level` bands that score on a ladder evaluated from the top with
    inclusive boundaries: at least 2.00 is `CORROBORATED`, otherwise at least 0.90
    is `ANECDOTAL`, and anything lower is `UNSUBSTANTIATED`."

    Design: Difficulty/boundary_precision_check/substantiation_exactly_at_anecdotal_min_passes_while_one_cent_below_fails
    """
    _two_cards_astride_the_anecdotal_edge(world)

    claim = world.get_claim(world.claim_below_edge["id"])

    assert_substantiation(claim, 0.89, "UNSUBSTANTIATED", "HIGH")
    assert float(claim["substantiation_score"]) != 0.90, (
        "a rounding slip of one cent would have carried this claim over the edge"
    )


def test_the_claim_below_the_edge_blocks_its_card_from_legal_review(world):
    """The card one cent short cannot leave DRAFT.

    "It is multiplied by a rating factor, which is 1.00 when the response's `rating`
    is null and otherwise sixty hundredths plus ten hundredths per rating point — so
    a rating of 1 gives 0.70 and a rating of 5 gives 1.10."

    Design: Difficulty/boundary_precision_check/substantiation_exactly_at_anecdotal_min_passes_while_one_cent_below_fails
    """
    _two_cards_astride_the_anecdotal_edge(world)

    validate_error(
        world.api.submit_legal(world.card_below_edge["id"], world.analyst_headers),
        ERR_CLAIM_UNSUBSTANTIATED,
        422,
    )

    assert_field(world.get_battlecard(world.card_below_edge["id"]), "status", "DRAFT")


# ---------------------------------------------------------------------------
# The half-open close-date window
# ---------------------------------------------------------------------------


def test_a_deal_closing_on_the_window_end_leaves_the_pool_empty(world):
    """Room remains in the quota, but nothing qualifies, so the pool refusal wins.

    "If the requested stratum's open slots are fewer than `requested_count`, the
    draw fails with `ERR_STRATUM_QUOTA_EXHAUSTED`; if slots remain but the
    eligibility filter leaves the pool empty, it fails with
    `ERR_NO_ELIGIBLE_DEALS`."

    Design: Difficulty/boundary_precision_check/draw_treats_window_end_as_exclusive_and_window_start_as_inclusive
    """
    _sealed_frame_with_a_deal_on_the_exclusive_bound(world)

    body = validate_error(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("WON", requested_count=1),
            world.analyst_headers,
        ),
        ERR_NO_ELIGIBLE_DEALS,
        422,
    )

    assert body["error_id"] != ERR_STRATUM_QUOTA_EXHAUSTED, (
        "an empty pool must not be reported as an exhausted quota"
    )
    frame = world.get_frame()
    assert_frame_slots(frame, selected_won=0, open_won=2)
    edge = world.get_deal(world.edge_deal["id"])
    assert_field(edge, "research_status", "NOT_SELECTED")
    assert_null(edge["selection_rank_score"], "selection_rank_score")


def test_a_deal_closing_on_the_window_start_is_inside_the_frame(world):
    """The same bound read at the other end admits the deal.

    "a pinned deal whose `close_date` falls outside the half-open window is the way
    `ERR_DEAL_OUTSIDE_FRAME_WINDOW` is reached, with a deal closing exactly on
    `window_end` being out of frame and one closing exactly on `window_start` being
    in"

    Design: Difficulty/boundary_precision_check/draw_treats_window_end_as_exclusive_and_window_start_as_inclusive
    """
    _sealed_frame_with_a_deal_on_the_exclusive_bound(world)
    validate_error(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("WON", requested_count=1),
            world.analyst_headers,
        ),
        ERR_NO_ELIGIBLE_DEALS,
        422,
    )
    inside = _add_deal_on_the_inclusive_bound(world)

    body = validate_success(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("WON", requested_count=1),
            world.analyst_headers,
        ),
        201,
    )
    drawn = body

    assert len(drawn) == 1, f"expected exactly one drawn deal, got {drawn}"
    assert drawn[0]["id"] == inside["id"], (
        "the drawn deal must be the one closing on the inclusive lower bound"
    )
    assert_field(world.get_deal(inside["id"]), "research_status", "SELECTED")


def test_the_drawn_boundary_deal_scores_and_moves_the_frame_counters(world):
    """The admitted deal is scored on the stratified basis and consumes one slot.

    "Under `STRATIFIED_BY_SEGMENT`, the raw score is forty hundredths of the value
    term plus forty hundredths of the recency term plus the competitor term, and the
    final `selection_rank_score` is that raw score rounded to four decimal places"

    Design: Difficulty/boundary_precision_check/draw_treats_window_end_as_exclusive_and_window_start_as_inclusive
    """
    _sealed_frame_with_a_deal_on_the_exclusive_bound(world)
    validate_error(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("WON", requested_count=1),
            world.analyst_headers,
        ),
        ERR_NO_ELIGIBLE_DEALS,
        422,
    )
    inside = _add_deal_on_the_inclusive_bound(world)
    validate_success(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("WON", requested_count=1),
            world.analyst_headers,
        ),
        201,
    )

    stored = world.get_deal(inside["id"])
    assert_ratio(stored["selection_rank_score"], 0.7489, "selection_rank_score")
    assert_field(stored, "sampling_frame_id", world.frame["id"])
    assert_field(stored, "stratum", "WON")
    assert_frame_slots(world.get_frame(), selected_won=1, open_won=1, coverage=0.2000)
    assert_field(
        world.get_deal(world.edge_deal["id"]), "research_status", "NOT_SELECTED"
    )
