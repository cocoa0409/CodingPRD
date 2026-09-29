"""Divergent valuation variants and multi-stage combinatorial formulas."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    COACH_B_HEADERS,
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    accept_assignment,
    active_provider,
    claim_line,
    completed_visit,
    contract_version,
    create_claim,
    create_enrollment,
    create_order,
    create_substitute,
    open_review,
    order_line,
    provider_with_contract,
    request_coverage,
    set_clock,
    submit_cap,
    submit_claim,
    withdraw_enrollment,
)

# Local setup builders


def _billing_home_with_two_subsidy_children():
    """An ACTIVE home with a July contract and two subsidy-certified children."""
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-07-01T00:00:00Z",
            "absence_rate_pct": 50,
        },
    )
    first = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
        start_on="2026-07-01T00:00:00Z",
    )
    second = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-2",
        family_name="Brody",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
        start_on="2026-07-01T00:00:00Z",
    )
    ctx["e1"] = first["id"]
    ctx["e2"] = second["id"]
    return ctx


def _july_claim(ctx):
    """Draft the 2026-07 claim carrying 18/4 and 10/2 attendance."""
    return create_claim(
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-07",
        [claim_line(ctx["e1"], 18, 4), claim_line(ctx["e2"], 10, 2)],
        contract_version(ctx["contract_id"]),
    )


def _coached_home():
    """An ACTIVE home with three completed visits scoring 60, 88 and 98."""
    set_clock("2026-04-01T00:00:00Z")
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )
    completed_visit(ctx["provider_id"], "2026-04-10T00:00:00Z", 60, focus_area="ENVIRONMENT")
    completed_visit(ctx["provider_id"], "2026-05-20T00:00:00Z", 88, focus_area="CURRICULUM")
    completed_visit(
        ctx["provider_id"], "2026-06-30T00:00:00Z", 98, focus_area="BUSINESS_PRACTICE"
    )
    return ctx


def _pool_home(**substitute_overrides):
    """An ACTIVE home with substitute-pool access and one pool member."""
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["SUBSTITUTE_POOL"]},
    )
    ctx["substitute"] = create_substitute(**substitute_overrides)
    return ctx


# dual_variant_calc


def test_provisional_advance_variant_pays_absence_days_at_the_full_daily_rate(api):
    """Submission values 2026-07 at 153000 cents and advances exactly four fifths of it.

    Line CH-1 carries 18 attended and 4 absent days, so its payable count is the joint
    cap of 22 and it earns 22 * 4500 == 99000 cents with absences at the full rate; line
    CH-2 carries 10 and 2, so 12 * 4500 == 54000 cents. The provisional total is 153000
    and the advance is 153000 * 80 // 100 == 122400 with the fraction discarded.

    PRD: "The provisional valuation is deliberately generous: absence days earn the
    **full** daily rate, there is no per-line absence allowance, and the enrollment's own
    status is not consulted — only the combined 22-day monthly cap applies."

    Design: Difficulty/dual_variant_calc/subsidy_claim_provisional_advance_vs_final_reconciled_divergence
    """
    ctx = _billing_home_with_two_subsidy_children()
    claim = _july_claim(ctx)
    assert claim["provisional_amount_cents"] == 0
    assert claim["final_amount_cents"] == 0

    submitted = validate_success(api.submit_claim(claim["id"], None, ctx["headers"]))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["provisional_amount_cents"] == 153000

    advanced = validate_success(api.advance_claim(claim["id"], None, FISCAL_OFFICER_HEADERS))
    assert advanced["status"] == "ADVANCE_PAID"
    assert advanced["advance_paid_cents"] == 122400

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["claimed_amount_cents"] == 153000


def test_final_reconciled_variant_drops_absences_for_the_child_who_left(api):
    """Reconciliation values the very same lines at 132750 cents instead of 153000.

    CH-1 stays enrolled: 18 * 4500 == 81000 attended plus min(4, 3) * 4500 * 50 / 100 ==
    6750 absence, so 87750. CH-2 withdrew on 2026-07-31, so its absence component is
    zero and only 10 * 4500 == 45000 remains. The final total is 132750, the settlement
    delta is 132750 - 122400 == 10350, and the contract's claimed amount moves from
    153000 to 132750.

    PRD: "Because the enrollment's status is read at the instant reconciliation runs, a
    child who withdrew between submission and reconciliation changes the final valuation
    while leaving the provisional valuation untouched — which is the whole reason both
    figures are stored."

    Design: Difficulty/dual_variant_calc/subsidy_claim_provisional_advance_vs_final_reconciled_divergence
    """
    ctx = _billing_home_with_two_subsidy_children()
    claim = _july_claim(ctx)
    submit_claim(claim["id"], ctx["provider_id"])
    validate_success(api.advance_claim(claim["id"], None, FISCAL_OFFICER_HEADERS))

    withdrawn = withdraw_enrollment(ctx["e2"], ctx["provider_id"], "2026-07-31T00:00:00Z")
    assert withdrawn["status"] == "WITHDRAWN"

    reconciled = validate_success(api.reconcile_claim(claim["id"], None, FISCAL_OFFICER_HEADERS))
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["provisional_amount_cents"] == 153000
    assert reconciled["final_amount_cents"] == 132750
    assert reconciled["settlement_delta_cents"] == 10350

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["claimed_amount_cents"] == 132750


def test_coaching_weighted_variant_blends_the_three_most_recent_observations(api):
    """Conducting the third visit scores the home at 87.40 under recency weights.

    Ordered by conducted date descending the observations are 98, 88 and 60, so the
    weighted sum is 98 * 0.5 + 88 * 0.3 + 60 * 0.2 == 87.4 over a weight sum of 1.0.
    With no open finding there is no penalty, so the score is 87.40 and the band is
    TIER_1.

    PRD: "Otherwise the recency weights one-half, three-tenths and one-fifth are matched
    to the picked visits in that order, the sum of each visit's `observation_score`
    multiplied by its weight is divided by the sum of only the weights actually used — so
    a provider with a single completed visit scores exactly that visit's observation, and
    a provider with two visits has their scores blended five-eighths to three-eighths —
    and the quotient is rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/provider_quality_score_coaching_weighted_vs_compliance_anchored_divergence
    """
    ctx = _coached_home()

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert float(provider["quality_score"]) == 87.40
    assert provider["quality_tier"] == "TIER_1"
    assert provider["quality_variant_applied"] == "COACHING_WEIGHTED"
    assert provider["open_finding_count"] == 0


def test_compliance_anchored_variant_replaces_the_blend_with_a_flat_mean(api):
    """Closing a review re-scores the same three visits at 82.00 rather than 87.40.

    The clock sits at 2026-08-01, so the inclusive 180-day window opens on 2026-02-02 and
    holds all three visits. Their plain mean is (60 + 88 + 98) / 3 == 82.00, which bands
    as TIER_2, and the closing decrement has already taken `open_finding_count` back to
    zero so no penalty applies.

    PRD: "Here every completed visit whose `visit_conducted_on` falls within the
    inclusive window that begins 180 days before the logical clock date and ends at the
    logical clock date is counted, no matter how many that is, and the score is the plain
    arithmetic mean of their `observation_score` values — their sum divided by their count
    — rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/provider_quality_score_coaching_weighted_vs_compliance_anchored_divergence
    """
    ctx = _coached_home()
    set_clock("2026-08-01T00:00:00Z")

    review = open_review(
        ctx["provider_id"], ["QS-7"], "2026-08-31T00:00:00Z", severity="MAJOR"
    )
    submit_cap(
        review["id"], ctx["provider_id"], "Nap-area layout corrected and staff retrained"
    )
    closed = validate_success(api.close_review(review["id"], None, COACH_B_HEADERS))
    assert closed["status"] == "CLOSED_COMPLIANT"

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert float(provider["quality_score"]) == 82.00
    assert provider["quality_tier"] == "TIER_2"
    assert provider["quality_variant_applied"] == "COMPLIANCE_ANCHORED"
    assert provider["open_finding_count"] == 0


# combinatorial_formula


def test_group_purchase_order_rounds_each_line_before_summing_the_subtotal(api):
    """Two insurance lines total 27306 cents, one cent below the sum-then-round answer.

    Sixteen units select the five percent rung. Line LIAB-BASE grosses 2749 * 8 == 21992
    and discounts to 20892.4, rounding to 20892; line ACCIDENT-RIDER grosses 844 * 8 ==
    6752 and discounts to 6414.4, rounding to 6414. Their sum is 27306, whereas rounding
    the combined 28744 * 0.95 == 27306.8 once would have produced 27307.

    PRD: "**The rounding order is pinned:** walking the lines in the order they were
    supplied in the request body, which is also the order they are persisted in, each
    line's gross amount is its `unit_price_cents` multiplied by its `quantity`, the
    discounted amount is that gross multiplied by one minus the discount fraction and
    **then rounded half up to whole cents for that line alone**, and only those per-line
    rounded amounts are accumulated into `subtotal_cents`."

    Design: Difficulty/combinatorial_formula/group_purchase_order_per_line_rounding_then_sum_mode_b
    """
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["GROUP_PURCHASING"]},
    )
    order = create_order(
        ctx["provider_id"],
        [order_line("LIAB-BASE", 2749, 8), order_line("ACCIDENT-RIDER", 844, 8)],
        category="INSURANCE",
    )
    assert order["status"] == "OPEN"
    assert order["subtotal_cents"] == 0

    committed = validate_success(api.commit_order(order["id"], None, ctx["headers"]))
    assert committed["total_quantity"] == 16
    assert float(committed["discount_pct"]) == 0.05
    assert committed["subtotal_cents"] == 27306
    assert committed["subtotal_cents"] != 27307


def test_insurance_admin_fee_is_three_percent_of_the_per_line_subtotal(api):
    """The insurance surcharge is 819 cents and the committed total is 28125 cents.

    Three percent of the 27306 subtotal is 819.18, which rounds half up to 819, and the
    total is 27306 + 819 == 28125. The order lands in its only terminal state.

    PRD: "`insurance_admin_fee_cents` is three percent of `subtotal_cents`, rounded half
    up, but only when the order's `category` is `INSURANCE`; for `SUPPLIES` and
    `CURRICULUM` it is 0."

    Design: Difficulty/combinatorial_formula/group_purchase_order_per_line_rounding_then_sum_mode_b
    """
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["GROUP_PURCHASING"]},
    )
    order = create_order(
        ctx["provider_id"],
        [order_line("LIAB-BASE", 2749, 8), order_line("ACCIDENT-RIDER", 844, 8)],
        category="INSURANCE",
    )

    committed = validate_success(api.commit_order(order["id"], None, ctx["headers"]))
    assert committed["status"] == "COMMITTED"
    assert committed["insurance_admin_fee_cents"] == 819
    assert committed["total_cents"] == 28125
    assert committed["total_cents"] == (
        committed["subtotal_cents"] + committed["insurance_admin_fee_cents"]
    )


def test_network_admin_fee_tier_is_keyed_on_the_pre_fee_subtotal_not_the_total(api):
    """A 14800-cent subtotal draws the ten percent rung, giving 1480 rather than 1184.

    Four billable hours at 3700 cents with no credential premium make a pre-fee subtotal
    of 14800, which sits below 15000 and therefore takes ten percent: 1480 cents. Keying
    the ladder on the 16280-cent final total would have selected eight percent and
    charged 1184 instead.

    PRD: "Fourth — and this is the step implementations get wrong — the network
    administration fee percentage is selected from a ladder keyed on
    `pre_fee_subtotal_cents` and **not** on the final total: six percent when the pre-fee
    subtotal is at least 30000 cents, eight percent when it is at least 15000 cents, and
    ten percent otherwise."

    Design: Difficulty/combinatorial_formula/substitute_cost_fee_tier_keyed_on_pre_fee_subtotal_mode_c
    """
    ctx = _pool_home(
        full_name="Rosa Nunez",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=3700,
        service_county_tiers=["STANDARD"],
    )
    substitute_id = ctx["substitute"]["id"]
    assignment = request_coverage(
        ctx["provider_id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
        requested_substitute_id=substitute_id,
    )
    accept_assignment(assignment["id"], substitute_id)
    set_clock("2026-08-05T12:00:00Z")

    completed = validate_success(
        api.complete_assignment(assignment["id"], None, ctx["headers"])
    )
    assert completed["billable_hours"] == 4
    assert completed["pre_fee_subtotal_cents"] == 14800
    assert completed["network_admin_fee_cents"] == 1480
    assert completed["network_admin_fee_cents"] != 1184


def test_completion_totals_the_coverage_and_advances_both_status_dimensions(api):
    """The same coverage totals 16280 cents and lands COMPLETED with billing ACCRUED.

    The 14800-cent subtotal plus the 1480-cent fee gives 16280. Completion also raises
    the pool member's completed-assignment counter from 0 to 1.

    PRD: "Completion moves `staffing_status` `CONFIRMED → COMPLETED`, advances
    `billing_status` `UNBILLED → ACCRUED`, increases the member's
    `assignment_count_completed` by one, and recomputes the provider's
    `projected_monthly_revenue_cents`, since accrued coverage is a cost in the revenue
    model."

    Design: Difficulty/combinatorial_formula/substitute_cost_fee_tier_keyed_on_pre_fee_subtotal_mode_c
    """
    ctx = _pool_home(
        full_name="Rosa Nunez",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=3700,
        service_county_tiers=["STANDARD"],
    )
    substitute_id = ctx["substitute"]["id"]
    assignment = request_coverage(
        ctx["provider_id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
        requested_substitute_id=substitute_id,
    )
    accept_assignment(assignment["id"], substitute_id)
    set_clock("2026-08-05T12:00:00Z")

    completed = validate_success(
        api.complete_assignment(assignment["id"], None, ctx["headers"])
    )
    assert completed["total_cost_cents"] == 16280
    assert completed["staffing_status"] == "COMPLETED"
    assert completed["billing_status"] == "ACCRUED"

    member = validate_success(api.get_substitute(substitute_id, NETWORK_ADMIN_HEADERS))
    assert member["assignment_count_completed"] == 1
