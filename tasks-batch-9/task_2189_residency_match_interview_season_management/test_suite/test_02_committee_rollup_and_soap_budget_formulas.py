"""Two formulas whose evaluation order is pinned against a plausible alternative.

The committee roll-up rounds per card before averaging, and the SOAP offer budget
selects its reserve credit from the raw vacancy rather than from the budget the
credit feeds.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ScoreCardStatus,
    assert_position_conservation,
    assert_one_decimal,
    assert_score_equals,
    expected_soap_offer_budget,
    get_success_data,
    setup_matched_program,
    setup_program,
    setup_scored_application,
    validate_success,
)

#: (8+9+9+9)/4 = 8.75, which rounds half up to one place.
LEAD_CARD_AVERAGE = 8.8
#: (7+8+8+8)/4 = 7.75, which rounds half up to one place.
MEMBER_CARD_AVERAGE = 7.8
#: Mean of the two already-rounded card figures.
PINNED_COMMITTEE_SCORE = 8.30
#: What summing all eight domains and dividing by eight would have produced.
FORBIDDEN_COMMITTEE_SCORE = 8.25


def test_a_submitted_card_rounds_its_own_domain_mean_and_the_draft_card_is_ignored(api):
    """One submitted card, one draft card: only the submitted one is included.

    The submitted card's four domains average 8.75, which the one-decimal rule
    lifts to 8.8, and that single figure is the whole roll-up.

    PRD 3.6: "Submission writes `ScoreCard.domain_average` as the mean of the four rubric domains rounded half up to **one** decimal place, and then recomputes `Application.committee_score`."
    PRD 3.6: "The included set is every `ScoreCard` for the application whose `status` is `SUBMITTED` or `LOCKED`; cards in `DRAFT` or `AMEND_REQUESTED` are excluded."

    Design: Difficulty/combinatorial_formula/committee_rubric_per_card_rounding_before_averaging
    """
    builder = setup_scored_application(submit_both=False)

    lead_card = get_success_data(
        api.get_score_card(builder.id("sc1"), builder.interviewer("f1"))
    )
    member_card = get_success_data(
        api.get_score_card(builder.id("sc2"), builder.interviewer("f2"))
    )

    assert lead_card["status"] == ScoreCardStatus.SUBMITTED
    assert member_card["status"] == ScoreCardStatus.DRAFT
    assert_one_decimal(
        lead_card["domain_average"], LEAD_CARD_AVERAGE, "ScoreCard.domain_average"
    )
    assert member_card["domain_average"] is None, (
        "a draft card carries no domain average, got "
        f"{member_card['domain_average']}"
    )

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert_score_equals(
        application["committee_score"],
        LEAD_CARD_AVERAGE,
        "Application.committee_score over the one submitted card",
    )


def test_committee_score_averages_the_already_rounded_card_figures(api):
    """Submitting the second card averages 8.8 and 7.8, not the raw domains.

    Each card's mean is lifted to one decimal place first, so the roll-up is
    8.30 — the single-pass alternative would have answered 8.25.

    PRD 2.8: "The committee roll-up rounds **each score card's four-domain mean to one decimal place first**, and only then averages those already-rounded per-card figures and rounds that average to two decimal places."
    PRD 3.6: "**Step two:** add together those **already-rounded** per-card averages, divide by the number of included cards, and round that result half up to **two** decimal places."

    Design: Difficulty/combinatorial_formula/committee_rubric_per_card_rounding_before_averaging
    """
    builder = setup_scored_application(submit_both=False)

    response = api.submit_score_card(builder.id("sc2"), builder.interviewer("f2"))
    member_card = validate_success(response)

    assert_one_decimal(
        member_card["domain_average"], MEMBER_CARD_AVERAGE, "ScoreCard.domain_average"
    )

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert_score_equals(
        application["committee_score"],
        PINNED_COMMITTEE_SCORE,
        "Application.committee_score",
    )
    assert application["committee_score"] != pytest.approx(
        FORBIDDEN_COMMITTEE_SCORE, abs=0.001
    ), (
        "the roll-up must not sum every domain across both cards and divide once, "
        f"which would have produced {FORBIDDEN_COMMITTEE_SCORE}"
    )


def test_a_fresh_two_position_program_reads_a_budget_of_three(api):
    """Base vacancy two earns a credit of one, so the budget is three.

    Re-deriving the tier from the resulting budget of three would earn a credit
    of two and answer four, which the pinned order forbids.

    PRD 3.8: "**Step two:** a reserve credit is selected from that base vacancy in a strict cascade — a base vacancy of at least 6 earns a credit of 3; otherwise a base vacancy of at least 3 earns 2; otherwise a base vacancy of at least 1 earns 1; a base vacancy of 0 earns 0."
    PRD 3.8: "The tier is selected from the base vacancy in step two and is never re-derived from the resulting budget, and implementations must not iterate to a fixed point."

    Design: Difficulty/combinatorial_formula/soap_offer_budget_tier_keyed_on_base_unfilled_not_on_budget
    """
    builder = setup_program(quota_positions=2)

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))

    assert_position_conservation(program, expected_matched=0, expected_unfilled=2)
    assert program["soap_offer_budget"] == 3, (
        "a base vacancy of two earns a credit of one, so the budget is three, got "
        f"{program['soap_offer_budget']}"
    )
    assert program["soap_offer_budget"] != 4, (
        "the reserve credit must not be re-derived from the budget it feeds"
    )


@pytest.mark.parametrize(
    "quota_positions,expected_budget",
    [(1, 2), (3, 5), (6, 9)],
)
def test_the_reserve_cascade_selects_each_tier_from_the_raw_vacancy(
    api, quota_positions, expected_budget
):
    """Each cascade tier is exercised on a program whose vacancy sits in it.

    A freshly registered program has matched nobody, so its base vacancy is its
    whole quota and the tier boundaries at one, three and six are all visible.

    PRD 3.8: "**Step one:** the base vacancy is `quota_positions` minus `matched_count`, computed **before** any reserve is considered, where `matched_count` is the count of `MatchResult` rows for the program whose `outcome` is `MATCHED` at that moment — `VACATED` and `UNMATCHED` rows do not count."
    PRD 3.8: "**Step three:** only now are the two combined, and the budget is the base vacancy plus the reserve credit."

    Design: Difficulty/combinatorial_formula/soap_offer_budget_tier_keyed_on_base_unfilled_not_on_budget
    """
    builder = setup_program(quota_positions=quota_positions)

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))

    assert program["soap_offer_budget"] == expected_budget, (
        f"a base vacancy of {quota_positions} should yield a budget of "
        f"{expected_budget}, got {program['soap_offer_budget']}"
    )
    assert program["soap_offer_budget"] == expected_soap_offer_budget(
        quota_positions, 0
    )


def test_filling_one_of_two_positions_lowers_the_budget_to_the_lower_tier(api):
    """Match day fills a position, so the next read recomputes a base vacancy of one.

    The budget follows the raw vacancy down from three to two, which is only
    observable because the figure is recomputed on every read.

    PRD 3.8: "How many offers a program may hold outstanding is capped by its **SOAP offer budget**, a figure recomputed on every read of the program so that its pinned evaluation order is directly observable."
    PRD 2.10: "For every `Program` at every observable moment, `quota_positions` equals `matched_count` plus `unfilled_positions`."

    Design: Difficulty/combinatorial_formula/soap_offer_budget_tier_keyed_on_base_unfilled_not_on_budget
    """
    builder = setup_matched_program(quota_positions=2)

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))

    assert_position_conservation(program, expected_matched=1, expected_unfilled=1)
    assert program["soap_offer_budget"] == 2, (
        "a base vacancy of one earns a credit of one, so the budget is two, got "
        f"{program['soap_offer_budget']}"
    )
