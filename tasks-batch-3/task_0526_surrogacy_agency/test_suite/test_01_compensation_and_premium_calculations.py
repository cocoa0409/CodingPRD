"""Calculation claims: carrier total compensation (tiered + conditional add-on),
insurance gap premium (nested rounding), and the two escrow projections
(disbursable-now vs projected-liability).

Covers difficulty queue rules dual_variant_calc, combinatorial_formula and the
corner calculations section.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_intended_parent_actor_headers,
    create_funded_journey,
    add_comp_schedule_line,
    add_and_achieve_milestone,
)
from test_helpers import factories as f

CM = TEST_USERS["case_manager_headers"]
FO = TEST_USERS["finance_officer_headers"]
SCREENER = TEST_USERS["screener_headers"]


# ==========================================================================
# carrier_total_compensation — tiered experience bonus + conditional add-on
# ==========================================================================
def _propose_match_for_comp(proposed_cents, prior_deliveries):
    ip = get_success_data(api_client.create_intended_parent(
        f.create_intended_parent_payload(), CM))
    car = get_success_data(api_client.create_carrier(
        f.create_carrier_payload(prior_deliveries=prior_deliveries), CM))
    match = get_success_data(api_client.create_match(
        f.create_match_payload(ip["id"], car["id"],
                               proposed_carrier_comp_cents=proposed_cents), CM))
    return match


def test_comp_breakdown_tier1_bonus_no_addon(api):
    """PRD §3.3: "when `prior_deliveries` is 2 or 3 the bonus is the base
    multiplied by 0.05, rounded half up to whole cents". PRD §3.3: "A multiples
    add-on of 500,000 cents applies when any milestone of type `HEARTBEAT` on the
    journey is `ACHIEVED` and the journey's `current_phase` is `HEARTBEAT_CONFIRMED`
    or later ...; otherwise the add-on is 0." PRD §3.3: "only then are the base,
    the experience bonus, and the multiples add-on summed to give the total."

    Design: Difficulty/combinatorial_formula/carrier_total_compensation_tiered_conditional_mode_a
    """
    match = _propose_match_for_comp(4_000_000, prior_deliveries=3)
    data = validate_success(api.get_match_comp_breakdown(match["id"], CM))
    assert data["base_cents"] == 4_000_000
    assert data["experience_bonus_cents"] == 200_000
    assert data["multiples_addon_cents"] == 0
    assert data["total_cents"] == 4_200_000


def test_comp_breakdown_tier2_bonus_no_addon(api):
    """PRD §3.3: "when `prior_deliveries` is 4 or more the bonus is the base
    multiplied by 0.10, rounded half up to whole cents". PRD §3.3: "otherwise
    the add-on is 0."

    Design: Corner/calculations/comp_breakdown_tier2_and_multiples_addon
    """
    match = _propose_match_for_comp(4_000_000, prior_deliveries=5)
    data = validate_success(api.get_match_comp_breakdown(match["id"], FO))
    assert data["experience_bonus_cents"] == 400_000
    assert data["multiples_addon_cents"] == 0
    assert data["total_cents"] == 4_400_000


def test_comp_breakdown_tier0_prior_one(api):
    """PRD §3.3: "when `prior_deliveries` is exactly 1 the bonus is 0".

    Design: Corner/calculations/comp_breakdown_tier0_prior_one
    """
    match = _propose_match_for_comp(4_000_000, prior_deliveries=1)
    data = validate_success(api.get_match_comp_breakdown(match["id"], CM))
    assert data["experience_bonus_cents"] == 0
    assert data["total_cents"] == 4_000_000


# ==========================================================================
# insurance_gap_premium — nested rounding, round-per-month-then-multiply
# ==========================================================================
def _carrier_with_pending_exclusion_review(base_comp_cents, prior_deliveries=3):
    car = get_success_data(api_client.create_carrier(
        f.create_carrier_payload(prior_deliveries=prior_deliveries,
                                 base_compensation_cents=base_comp_cents), CM))
    get_success_data(api_client.submit_carrier(car["id"], CM))
    get_success_data(api_client.start_screening_carrier(car["id"], SCREENER))
    ins = get_success_data(api_client.create_insurance_review(
        f.create_insurance_review_payload(car["id"], policy_kind="EXCLUSION"), SCREENER))
    return car, ins


def test_insurance_gap_premium_nested_rounding(api):
    """PRD §3.2: "a monthly figure is computed as `base_compensation_cents`
    multiplied by a monthly gap rate of 0.015, and that monthly figure is
    rounded half up to a whole number of cents. Then `gap_premium_cents` is
    that rounded monthly figure multiplied by 9 months." PRD §3.2: "The
    rounding is applied to the monthly figure before the multiplication by 9,
    not after".

    Design: Difficulty/combinatorial_formula/insurance_gap_premium_nested_rounding_mode_b
    """
    _, ins = _carrier_with_pending_exclusion_review(4_000_033, prior_deliveries=2)
    data = validate_success(api.identify_gap_insurance_review(ins["id"], SCREENER))
    assert data["status"] == "GAP_IDENTIFIED"
    # round_half_up(4000033 * 0.015) = round(60000.495) = 60000; 60000 * 9 = 540000.
    assert data["gap_premium_cents"] == 540_000
    assert data["gap_premium_cents"] != 540_004


def test_insurance_gap_premium_distinct_from_comp_domain(api):
    """PRD §3.2: "that monthly figure is rounded half up to a whole number of
    cents. Then `gap_premium_cents` is that rounded monthly figure multiplied by
    9 months."

    Design: Difficulty/dual_variant_calc/carrier_total_comp_vs_insurance_gap_premium_distinct_domains
    """
    _, ins = _carrier_with_pending_exclusion_review(4_000_033, prior_deliveries=3)
    data = validate_success(api.identify_gap_insurance_review(ins["id"], SCREENER))
    assert data["status"] == "GAP_IDENTIFIED"
    assert data["gap_premium_cents"] == 540_000


# ==========================================================================
# Two escrow projections computed from the same schedule data
# ==========================================================================
def test_escrow_summary_disbursable_now_vs_projected_liability_diverge(api):
    """PRD §3.7: "It considers only those schedule lines whose
    `trigger_milestone_type` corresponds to a milestone already `ACHIEVED` on
    the journey. ... for each candidate line it adds that line's `amount_cents`
    to the running total only if doing so would keep the running total at or
    below `available_cents`". PRD §3.7: "It sums the `amount_cents` of every
    schedule line on the journey whose trigger milestone is not `FAILED` — that
    is, whose corresponding milestone is either scheduled or already achieved —
    including milestones not yet reached."

    Design: Difficulty/dual_variant_calc/escrow_disbursable_now_vs_projected_liability_diverge
    """
    ctx = create_funded_journey(deposit_cents=6_000_000)
    jr_id = ctx["journey"]["id"]
    add_comp_schedule_line(jr_id, "EMBRYO_TRANSFER", 1_000_000)
    add_comp_schedule_line(jr_id, "HEARTBEAT", 2_000_000)
    add_comp_schedule_line(jr_id, "BIRTH", 3_000_000)
    add_and_achieve_milestone(jr_id, "EMBRYO_TRANSFER")

    data = validate_success(api.get_escrow_summary(ctx["escrow"]["id"], FO))
    assert data["available_cents"] == 6_000_000
    assert data["disbursable_now_cents"] == 1_000_000
    assert data["projected_liability_cents"] == 6_000_000
    assert data["disbursable_now_cents"] != data["projected_liability_cents"]


def test_escrow_summary_funding_shortfall_positive(api):
    """PRD §3.7: "a funding shortfall is derived as the projected liability minus
    `available_cents`, floored at 0 so it is never negative, and reported as
    `funding_shortfall_cents`."

    Design: Corner/calculations/escrow_summary_funding_shortfall_positive
    """
    ctx = create_funded_journey(deposit_cents=4_000_000)
    jr_id = ctx["journey"]["id"]
    add_comp_schedule_line(jr_id, "EMBRYO_TRANSFER", 1_000_000)
    add_comp_schedule_line(jr_id, "HEARTBEAT", 2_000_000)
    add_comp_schedule_line(jr_id, "BIRTH", 3_000_000)
    add_and_achieve_milestone(jr_id, "EMBRYO_TRANSFER")

    data = validate_success(api.get_escrow_summary(ctx["escrow"]["id"], FO))
    assert data["available_cents"] == 4_000_000
    assert data["disbursable_now_cents"] == 1_000_000
    assert data["projected_liability_cents"] == 6_000_000
    assert data["funding_shortfall_cents"] == 2_000_000
