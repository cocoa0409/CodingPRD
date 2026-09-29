"""
Derived numbers: selection scores, incentive tiers, posture ladders and rollups.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_field,
    assert_fields,
    assert_frame_slots,
    assert_ledger,
    assert_money,
    assert_null,
    assert_ratio,
)
from test_helpers.fixtures import WinLossWorld
from test_helpers.test_users import make_sales_rep_headers


def _sealed_frame_with_one_enterprise_loss(
    world: WinLossWorld, **frame_overrides
) -> WinLossWorld:
    """One 300000.00 ENTERPRISE loss closing 47 days before the clock, ready to draw."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame(**frame_overrides)
    world.seal_frame()
    return world


def _published_card(world: WinLossWorld) -> WinLossWorld:
    """A PUBLISHED battlecard resting on one approved positioning claim."""
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
    positioning = world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind demoed deeper analytics",
        recorded_at="2026-08-01T10:05:00.000Z",
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Integration depth ranked first",
        recorded_at="2026-08-01T10:10:00.000Z",
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="List price felt high for the tier",
        recorded_at="2026-08-01T10:15:00.000Z",
    )
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.add_claim(
        [positioning["id"]],
        claim_text="Two enterprise buyers referenced our analytics depth",
        claim_type="FEATURE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE")
    world.publish_battlecard()
    return world


def _product_gap_evidence_on_an_authored_loss(world: WinLossWorld) -> WinLossWorld:
    """A completed interview carrying a PRODUCT_GAP verbatim plus an authored attribution."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor(tier="PRIMARY")
    world.create_two_analysts()
    world.reason = world.create_reason("PRICE", "Price")
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=3)
    world.gap_response = world.record_response(
        question_key="PRODUCT_GAP",
        verbatim_text="We could not export compliance evidence on a schedule.",
        recorded_at="2026-08-10T14:20:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    world.attribution = world.create_attribution(world.reason["id"], weight_primary=1.00)
    return world


# ---------------------------------------------------------------------------
# Selection scoring
# ---------------------------------------------------------------------------


def test_the_value_weighted_basis_multiplies_the_unrounded_raw_sum(world):
    """Enterprise segment lifts the 65/15 blend to 1.3260, not 1.3261.

    "Under `VALUE_WEIGHTED`, the raw score is sixty-five hundredths of the value term
    plus fifteen hundredths of the recency term plus the competitor term; that raw score
    is then multiplied by 1.25 when the deal's `segment` is `ENTERPRISE` and by 1.00
    otherwise, and the product is rounded to four decimal places."

    Design: Corner/calculations/selection_rank_score_value_weighted_variant_applies_enterprise_multiplier
    """
    _sealed_frame_with_one_enterprise_loss(
        world,
        selection_basis="VALUE_WEIGHTED",
        quota_won=0,
        quota_lost=1,
        quota_no_decision=0,
    )

    body = validate_success(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("LOST", requested_count=1),
            world.analyst_headers,
        ),
        201,
    )
    drawn = body

    assert len(drawn) == 1, f"expected exactly one drawn deal, got {drawn}"
    assert drawn[0]["id"] == world.deal["id"], drawn[0]["id"]
    assert_ratio(drawn[0]["selection_rank_score"], 1.3260, "selection_rank_score")
    assert_fields(drawn[0], {"research_status": "SELECTED", "stratum": "LOST"})
    assert_field(drawn[0], "sampling_frame_id", world.frame["id"])
    assert_frame_slots(world.get_frame(), selected_lost=1, open_lost=0, coverage=1.0000)


def test_a_deal_under_the_revenue_floor_is_never_even_scored(world):
    """The small deal drops out of the pool while a quota slot is still open.

    "A deal failing any predicate is excluded from the pool entirely and is never
    scored."

    "Under `STRATIFIED_BY_SEGMENT`, the raw score is forty hundredths of the value term
    plus forty hundredths of the recency term plus the competitor term, and the final
    `selection_rank_score` is that raw score rounded to four decimal places"

    Design: Corner/calculations/draw_eligibility_filter_excludes_deal_below_min_deal_value
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    big = world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(deal_id=big["id"], incentive_eligibility="ELIGIBLE")
    small = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=40000.00,
        close_date="2026-06-16T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    world.consented_contact(
        deal_id=small["id"],
        email="buyer2@brava.test",
        full_name="Cal Dos",
        incentive_eligibility="ELIGIBLE",
    )
    world.create_frame()
    world.seal_frame()

    body = validate_success(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("LOST", requested_count=1),
            world.analyst_headers,
        ),
        201,
    )
    drawn = body

    assert len(drawn) == 1, f"expected exactly one drawn deal, got {drawn}"
    assert drawn[0]["id"] == big["id"], "the drawn deal must be the eligible one"
    assert_ratio(drawn[0]["selection_rank_score"], 0.9956, "selection_rank_score")
    excluded = world.get_deal(small["id"])
    assert_field(excluded, "research_status", "NOT_SELECTED")
    assert_null(excluded["sampling_frame_id"], "sampling_frame_id")
    assert_null(excluded["selection_rank_score"], "selection_rank_score")
    assert_frame_slots(world.get_frame(), selected_lost=1, open_lost=1)


# ---------------------------------------------------------------------------
# Incentive and posture
# ---------------------------------------------------------------------------


def test_the_vendor_uplift_applies_to_the_already_rounded_gross(world):
    """A 30-minute slot at the partial tier commits 150.00, uplifted to 165.00.

    "If the interviewing analyst's `employment_type` is `EXTERNAL_VENDOR`, that
    **already-rounded** gross is then multiplied by an uplift of 1.10 and rounded to two
    decimal places again — the uplift is never folded into the base-times-factor
    product, because the two orders differ at the second decimal place."

    Design: Corner/calculations/incentive_applies_external_vendor_uplift_to_the_rounded_gross
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst(employment_type="EXTERNAL_VENDOR")
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)

    body = validate_success(
        world.api.create_interview(
            f.interview_payload(
                world.deal["id"],
                world.contact["id"],
                world.analyst["id"],
                scheduled_start_at="2026-08-10T14:00:00.000Z",
                scheduled_end_at="2026-08-10T14:30:00.000Z",
            ),
            world.analyst_headers,
        ),
        201,
    )
    interview = body

    assert_money(interview["incentive_provisional_usd"], 165.00, "provisional")
    assert_null(interview["incentive_final_usd"], "incentive_final_usd")
    assert_field(interview, "incentive_status", "COMMITTED")
    assert_ledger(world.refresh_program(), 165.00, 0.00, "OPEN")
    assert_analyst_workload(world.get_analyst(), 1, 45)


def test_utilization_of_exactly_eighty_five_percent_restricts_the_program(world):
    """425.00 against 500.00 sits on the inclusive boundary, and frames stay sealed.

    "The ladder is evaluated from the top and its boundaries are inclusive: utilization
    of at least 1.0000 yields `FROZEN`; otherwise utilization of at least 0.8500 yields
    `RESTRICTED`; otherwise `OPEN`."

    Design: Corner/calculations/posture_turns_restricted_at_exactly_the_utilization_threshold
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program(incentive_budget_usd=500.00)
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    champion = world.create_contact(
        email="buyer2@brava.test",
        full_name="Cal Dos",
        title_band="CHAMPION",
        incentive_eligibility="ELIGIBLE",
    )
    world.record_consent("GRANTED", contact_id=champion["id"])
    world.schedule_interview()

    body = validate_success(
        world.api.create_interview(
            f.interview_payload(
                world.deal["id"],
                champion["id"],
                world.analyst["id"],
                scheduled_start_at="2026-08-10T15:30:00.000Z",
                scheduled_end_at="2026-08-10T16:30:00.000Z",
            ),
            world.analyst_headers,
        ),
        201,
    )

    assert_money(body["incentive_provisional_usd"], 175.00, "provisional")
    assert_ledger(world.refresh_program(), 425.00, 0.00, "RESTRICTED")
    assert_field(world.get_frame(), "status", "SEALED")
    assert_analyst_workload(world.get_analyst(), 2, 150)


# ---------------------------------------------------------------------------
# Enablement adoption
# ---------------------------------------------------------------------------


def test_the_sweep_expires_one_rep_and_keeps_it_in_the_denominator(world):
    """One trained, one expired, one still assigned: adoption is one third.

    "Expired assignments deliberately stay in the denominator, because an expired
    assignment is a missed adoption rather than a void one."

    Design: Corner/calculations/adoption_rate_keeps_expired_assignments_in_the_denominator
    """
    _published_card(world)
    alpha = world.assign(sales_rep_user_ref="rep-alpha", due_at="2026-08-20T00:00:00.000Z")
    beta = world.assign(sales_rep_user_ref="rep-beta", due_at="2026-08-05T00:00:00.000Z")
    gamma = world.assign(sales_rep_user_ref="rep-gamma", due_at="2026-08-20T00:00:00.000Z")
    world.complete_assignment(
        quiz_score=80, assignment_id=alpha["id"], sales_rep_user_ref="rep-alpha"
    )
    world.set_clock("2026-08-06T00:00:00.000Z")

    body = validate_success(
        world.api.run_enablement_sweep(world.program_id, world.enablement), 200
    )

    assert body["expired_count"] == 1, body
    assert_field(world.get_assignment(beta["id"]), "status", "EXPIRED")
    assert_field(world.get_assignment(gamma["id"]), "status", "ASSIGNED")
    card = world.get_battlecard()
    assert_fields(card, {"assigned_count": 3, "trained_count": 1, "status": "PUBLISHED"})
    assert_ratio(card["adoption_rate"], 0.3333, "adoption_rate")


def test_one_point_below_the_pass_mark_fails_the_attempt(world):
    """Seventy-nine records an attempt without a completion instant.

    "A score below 80 moves the assignment to `FAILED`, leaves `completed_at` null and
    leaves `trained_count` unchanged."

    Design: Corner/calculations/quiz_score_one_point_below_pass_marks_assignment_failed
    """
    _published_card(world)
    alpha = world.assign(sales_rep_user_ref="rep-alpha", due_at="2026-08-20T00:00:00.000Z")
    beta = world.assign(sales_rep_user_ref="rep-beta", due_at="2026-08-20T00:00:00.000Z")
    world.complete_assignment(
        quiz_score=80, assignment_id=alpha["id"], sales_rep_user_ref="rep-alpha"
    )

    body = validate_success(
        world.api.complete_assignment(
            beta["id"],
            f.assignment_complete_payload(79),
            make_sales_rep_headers("rep-beta"),
        ),
        200,
    )
    assignment = body

    assert_fields(assignment, {"status": "FAILED", "quiz_score": 79, "attempt_count": 1})
    assert_null(assignment["completed_at"], "completed_at")
    card = world.get_battlecard()
    assert_fields(card, {"assigned_count": 2, "trained_count": 1})
    assert_ratio(card["adoption_rate"], 0.5000, "adoption_rate")
    stored_alpha = world.get_assignment(alpha["id"])
    assert_field(stored_alpha, "status", "TRAINED")
    assert stored_alpha["completed_at"] == "2026-08-01T00:00:00.000Z", (
        stored_alpha["completed_at"]
    )


# ---------------------------------------------------------------------------
# Product-gap scoring and trend aggregation
# ---------------------------------------------------------------------------


def test_a_ratified_enterprise_loss_scores_the_gap_at_thirty_six_forty(world):
    """Revenue and frequency components are scaled by the primary-tier pressure.

    "The revenue component takes `affected_acr_usd` divided by a normalizer of 500,000
    US dollars, caps that ratio at 1.0000 and rounds it to four decimal places,
    multiplies it by a weight of 40, and rounds the product to two decimal places."

    Design: Corner/calculations/product_gap_impact_score_combines_ratified_acr_frequency_and_tier
    """
    _product_gap_evidence_on_an_authored_loss(world)
    world.ratify_attribution(world.attribution["id"])

    body = validate_success(
        world.api.create_product_gap(
            f.product_gap_payload(
                world.program_id,
                world.gap_response["id"],
                gap_summary="Compliance evidence export",
            ),
            world.product,
        ),
        201,
    )
    gap = body

    assert_fields(
        gap,
        {
            "status": "NEW",
            "derived_competitor_id": world.competitor["id"],
            "linked_deal_count": 1,
            "roadmap_priority_band": "P2",
        },
    )
    assert_money(gap["affected_acr_usd"], 300000.00, "affected_acr_usd")
    assert_money(gap["impact_score"], 36.40, "impact_score")
    assert_field(world.get_deal(), "attribution_status", "RATIFIED")


def test_a_merely_provisional_attribution_contributes_no_revenue(world):
    """The same evidence scores 5.20 because no linked deal is ratified yet.

    "`affected_acr_usd` is the sum of `acr_usd` over only those linked deals whose
    `attribution_status` is `RATIFIED`, each counted once, rounded to two decimal
    places; that restriction is what makes the fourth link of the attribution supersede
    cascade observable, since a superseded attribution removes its deal's revenue from
    the gap again."

    Design: Corner/calculations/product_gap_impact_excludes_acr_of_a_deal_whose_attribution_is_only_provisional
    """
    _product_gap_evidence_on_an_authored_loss(world)

    body = validate_success(
        world.api.create_product_gap(
            f.product_gap_payload(
                world.program_id,
                world.gap_response["id"],
                gap_summary="Compliance evidence export",
            ),
            world.product,
        ),
        201,
    )
    gap = body

    assert_field(gap, "linked_deal_count", 1)
    assert_money(gap["affected_acr_usd"], 0.00, "affected_acr_usd")
    assert_money(gap["impact_score"], 5.20, "impact_score")
    assert_field(gap, "roadmap_priority_band", "P3")
    assert_field(world.get_attribution(world.attribution["id"]), "status", "PROVISIONAL")
    assert_field(world.get_deal(), "attribution_status", "PROVISIONAL")


def test_two_sibling_leaves_report_as_one_root_bucket(world):
    """A 0.60/0.40 split across siblings sums to a single share of one.

    "Third, weights are accumulated per pairing of deal segment and root reason: each
    attribution adds its `weight_primary` to the bucket of its primary reason's root,
    and when a secondary reason is present adds its `weight_secondary` to the bucket of
    that reason's root; when primary and secondary collapse to the same root, both
    contributions are kept and sum into the one bucket."

    Design: Corner/calculations/loss_trend_collapses_primary_and_secondary_reasons_into_one_root_bucket
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_two_analysts()
    root = world.create_reason("PRICE", "Price")
    discount = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    terms = world.create_reason(
        "PRICE_TERMS", "Payment terms", parent_reason_id=root["id"]
    )
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=3)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    attribution = world.create_attribution(
        discount["id"], weight_primary=0.60, secondary_reason_id=terms["id"]
    )
    world.ratify_attribution(attribution["id"])

    body = validate_success(
        world.api.get_loss_trends(
            world.program_id, world.product, f.loss_trends_params()
        ),
        200,
    )
    trends = body

    assert_field(trends, "basis", "RATIFIED_ONLY")
    assert_field(trends, "attribution_count", 1)
    assert len(trends["segments"]) == 1, trends["segments"]
    segment = trends["segments"][0]
    assert_field(segment, "segment", "ENTERPRISE")
    assert_money(segment["segment_total"], 1.00, "segment_total")
    assert len(segment["rows"]) == 1, segment["rows"]
    row = segment["rows"][0]
    assert_field(row, "root_reason_code", "PRICE")
    assert_field(row, "root_reason_id", root["id"])
    assert_money(row["weighted_total"], 1.00, "weighted_total")
    assert_ratio(row["share"], 1.0000, "share")
    stored = world.get_attribution(attribution["id"])
    assert_money(stored["weight_secondary"], 0.40, "weight_secondary")
    assert_money(stored["confidence_score"], 0.36, "confidence_score")
    assert_fields(
        world.get_reason(root["id"]),
        {"depth": 1, "is_leaf": False, "ratified_attribution_count": 0},
    )
    assert_fields(
        world.get_reason(discount["id"]),
        {"depth": 2, "is_leaf": True, "ratified_attribution_count": 1},
    )
