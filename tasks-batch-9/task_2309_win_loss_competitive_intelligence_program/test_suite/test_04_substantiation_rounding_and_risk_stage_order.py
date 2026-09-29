"""
Formulas whose rounding position and stage order are themselves normative.

Evidence items are rounded before they are summed, and the card's legal-review
discount is applied before the conditional surcharge rather than after it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_RISK_CEILING_EXCEEDED
from test_helpers.assertions import (
    assert_field,
    assert_money,
    assert_null,
    assert_risk_indices,
)
from test_helpers.fixtures import WinLossWorld


def _three_stale_criteria_responses(world: WinLossWorld) -> WinLossWorld:
    """A DRAFT card and three identical stale EVALUATION_CRITERIA verbatims.

    The clock is left at 2026-08-10T00:00:00.000Z, four months after the interview, so
    every cited answer is past the evidence recency horizon.
    """
    world.set_clock("2026-04-06T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(
        close_date="2026-04-05T00:00:00.000Z", primary_competitor_id=world.competitor["id"]
    )
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview(
        scheduled_start_at="2026-04-10T14:00:00.000Z",
        scheduled_end_at="2026-04-10T15:00:00.000Z",
    )
    for label, minute in (("one: integration depth", "05"), ("two: reporting depth", "10"), ("three: admin tooling", "15")):
        world.record_response(
            question_key="EVALUATION_CRITERIA",
            verbatim_text=f"Criterion {label}.",
            recorded_at=f"2026-04-10T14:{minute}:00Z",
            rating=3,
        )
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind bundled the suite.",
        recorded_at="2026-04-10T14:20:00.000Z",
        rating=3,
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="We were 20 percent above.",
        recorded_at="2026-04-10T14:25:00.000Z",
        rating=3,
    )
    world.set_clock("2026-04-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-04-10T14:00:00.000Z", actual_end_at="2026-04-10T15:00:00.000Z"
    )
    world.create_battlecard(title="Northwind", version_label="v1")
    world.set_clock("2026-08-10T00:00:00.000Z")
    return world


def _criteria_evidence_ids(world: WinLossWorld):
    return [
        response["id"]
        for response in world.responses
        if response["question_key"] == "EVALUATION_CRITERIA"
    ]


def _card_decided_high_high_low(world: WinLossWorld) -> WinLossWorld:
    """A card carrying PRICING, PERFORMANCE and REFERENCE claims on one verbatim."""
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
        verbatim_text="Integration depth decided it.",
        recorded_at="2026-08-10T14:10:00.000Z",
        rating=4,
    )
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind promised a 30 day rollout and a 20 percent discount.",
        recorded_at="2026-08-10T14:15:00.000Z",
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="We were 20 percent above.",
        recorded_at="2026-08-10T14:20:00.000Z",
        rating=2,
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    world.create_battlecard(title="Northwind", version_label="v1")
    evidence = [world.response_of("COMPETITOR_POSITIONING")["id"]]
    world.pricing_claim = world.add_claim(
        evidence,
        claim_text="Northwind discounts 20 percent to win bake-offs.",
        claim_type="PRICING",
    )
    world.performance_claim = world.add_claim(
        evidence,
        claim_text="Northwind cannot sustain a 30 day rollout at enterprise scale.",
        claim_type="PERFORMANCE",
    )
    world.reference_claim = world.add_claim(
        evidence,
        claim_text="Northwind names the same three references in every bake-off.",
        claim_type="REFERENCE",
    )
    world.submit_legal()
    return world


# ---------------------------------------------------------------------------
# Round-then-sum on the evidence set
# ---------------------------------------------------------------------------


def test_each_evidence_item_is_rounded_before_the_items_are_added(world):
    """Three stale items of 0.4725 each score 1.41, not the summed-then-rounded 1.42.

    "The product is rounded to two decimal places, **per item, before any
    addition**. `substantiation_score` is then the sum of those rounded items,
    itself rounded to two decimal places."

    Design: Difficulty/combinatorial_formula/substantiation_rounds_each_evidence_item_before_summing
    """
    _three_stale_criteria_responses(world)

    body = validate_success(
        world.api.create_claim(
            world.battlecard["id"],
            f.claim_payload(
                _criteria_evidence_ids(world),
                claim_text="Buyers rank integration depth above Northwind's bundle.",
                claim_type="FEATURE",
            ),
            world.analyst_headers,
        ),
        201,
    )
    claim = body

    assert_money(claim["substantiation_score"], 1.41, "substantiation_score")
    assert float(claim["substantiation_score"]) != 1.42, (
        "summing unrounded contributions would have produced 1.42"
    )


def test_the_rounded_sum_bands_the_claim_and_sets_its_risk_class(world):
    """1.41 lands in the middle band and a FEATURE claim there is MEDIUM risk.

    "base points are 3 for `PRICING`, 3 for `PERFORMANCE`, 2 for `FEATURE` and 1
    for `REFERENCE`; the level adjusts them by adding 1 for `UNSUBSTANTIATED`,
    adding nothing for `ANECDOTAL`, and subtracting 1 for `CORROBORATED`"

    Design: Difficulty/combinatorial_formula/substantiation_rounds_each_evidence_item_before_summing
    """
    _three_stale_criteria_responses(world)

    claim = world.add_claim(
        _criteria_evidence_ids(world),
        claim_text="Buyers rank integration depth above Northwind's bundle.",
        claim_type="FEATURE",
    )

    stored = world.get_claim(claim["id"])
    assert_field(stored, "substantiation_level", "ANECDOTAL")
    assert_field(stored, "risk_class", "MEDIUM")
    assert_field(stored, "legal_status", "PENDING")


def test_the_single_medium_claim_gives_the_card_an_average_risk_of_two(world):
    """One MEDIUM claim and nothing cleared yet leaves both indices at 2.00.

    "Stage two computes `risk_index_pre` as the average risk of the input set: 3
    points for each `HIGH` claim, 2 for each `MEDIUM` and 1 for each `LOW`, summed
    and divided by the number of claims in the set, rounded to two decimal places."

    Design: Difficulty/combinatorial_formula/substantiation_rounds_each_evidence_item_before_summing
    """
    _three_stale_criteria_responses(world)
    world.add_claim(
        _criteria_evidence_ids(world),
        claim_text="Buyers rank integration depth above Northwind's bundle.",
        claim_type="FEATURE",
    )

    body = validate_success(
        world.api.submit_legal(world.battlecard["id"], world.analyst_headers), 200
    )
    card = body

    assert_field(card, "status", "LEGAL_REVIEW")
    assert_risk_indices(card, 2.00, 2.00)


# ---------------------------------------------------------------------------
# Discount before surcharge
# ---------------------------------------------------------------------------


def test_before_any_decision_the_discount_scale_is_zero_so_the_indices_agree(world):
    """With nothing cleared, the discount has nothing to apply to.

    "That discount only applies to the portion of the set legal has already
    cleared, so a discount scale is computed as the number of claims in the set
    whose `legal_status` is `APPROVED` or `CONDITIONAL`, divided by the size of the
    set, rounded to four decimal places."

    Design: Difficulty/combinatorial_formula/risk_index_applies_discount_before_conditional_surcharge_and_blocks_publish
    """
    _card_decided_high_high_low(world)

    assert_field(world.get_claim(world.pricing_claim["id"]), "risk_class", "HIGH")
    assert_field(world.get_claim(world.performance_claim["id"]), "risk_class", "HIGH")
    assert_field(world.get_claim(world.reference_claim["id"]), "risk_class", "LOW")
    assert_risk_indices(world.get_battlecard(), 2.33, 2.33)


def test_the_conditional_surcharge_is_added_after_the_discount(world):
    """Discount then surcharge gives 2.25; surcharge then discount would give 2.23.

    "Stage five adds a surcharge of fifteen hundredths for each claim in the set
    whose `legal_status` is `CONDITIONAL` — added **after** the discount, not
    before — caps the result at a ceiling of 3.00, and rounds to two decimal places
    to produce `risk_index_final`."

    Design: Difficulty/combinatorial_formula/risk_index_applies_discount_before_conditional_surcharge_and_blocks_publish
    """
    _card_decided_high_high_low(world)

    world.decide_claim("APPROVE", claim_id=world.pricing_claim["id"])
    world.decide_claim(
        "CONDITIONAL",
        claim_id=world.performance_claim["id"],
        conditions_note="Must be phrased as enterprise-scale only.",
    )
    world.decide_claim("APPROVE", claim_id=world.reference_claim["id"])

    card = world.get_battlecard()
    assert_field(card, "status", "APPROVED")
    assert_risk_indices(card, 2.33, 2.25)
    assert float(card["risk_index_final"]) != 2.23, (
        "applying the surcharge before the discount would have produced 2.23"
    )


def test_a_final_index_above_the_ceiling_blocks_publication(world):
    """2.25 exceeds the publication ceiling, so the approved card cannot publish.

    "A card that was approved before a later conditional decision added a surcharge
    can therefore fail here with `ERR_RISK_CEILING_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/risk_index_applies_discount_before_conditional_surcharge_and_blocks_publish
    """
    _card_decided_high_high_low(world)
    world.decide_claim("APPROVE", claim_id=world.pricing_claim["id"])
    world.decide_claim(
        "CONDITIONAL",
        claim_id=world.performance_claim["id"],
        conditions_note="Must be phrased as enterprise-scale only.",
    )
    world.decide_claim("APPROVE", claim_id=world.reference_claim["id"])

    validate_error(
        world.api.publish_battlecard(world.battlecard["id"], world.enablement),
        ERR_RISK_CEILING_EXCEEDED,
        422,
    )

    card = world.get_battlecard()
    assert_field(card, "status", "APPROVED")
    assert_null(card["published_at"], "published_at")
    assert_field(world.get_competitor(), "published_battlecard_count", 0)
