"""
Combinatorial formulas: multi-input outcomes, nested rounding and pinned step order.

Three shapes are covered. The escalation requirement is a non-monotonic function of
four inputs, where an adjustment-magnitude clause re-raises a requirement the
risk-tier matrix had already settled at NONE. The reconciled indicated value rounds
every comparable's share before summing, so the answer differs by a cent from the
naive sum-then-divide. And escalation pricing runs five ordered steps in which the
discount tier is keyed on the post-surcharge subtotal.
"""

from test_helpers import assert_instant, fixtures as fx

# One comparable carries a 3000 basis point gross adjustment, above the single
# comparable ceiling, while every other receipt metric stays clean.
OUTSIZED_GROSS_GRID = [
    {
        "street_address": "11 Alder Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 12000000,
        "net_adjustment_cents": 400000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "22 Beech Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": -390000,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "33 Chestnut Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": 0,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _high_tier_review(api, comparables):
    """A high-risk report screened and taken into a DRAFT desk review."""
    env = fx.screened_report(
        api,
        amc={"name": "Meridian Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-2001",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-2A",
            "risk_tier": "HIGH",
            "borrower_display_name": "Dana Borrower",
        },
        appraisal={"effective_date": "2026-07-01T00:00:00Z"},
        comparables=comparables,
    )
    env["desk_review"] = fx.open_desk_review(api, env["appraisal"]["id"])
    return env


def test_adjustment_clause_raises_a_none_matrix_result_to_field_review(api):
    """A high-tier score of 9400 clears the matrix yet still escalates.

    Read through the matrix alone, a final score of 9400 basis points on a HIGH tier
    loan is neither below 7000 nor below 8500, so the matrix answers NONE. The
    adjustment clause then finds a single comparable adjusted by 3000 basis points
    and raises the requirement, which is why the outcome is not monotonic in the
    score.

    PRD: "**Clause three is an adjustment-magnitude upgrade applied after the matrix,
    and it never downgrades**: if the appraisal's `max_gross_adjustment_bps` is
    strictly greater than 2500 basis points and the matrix produced `NONE`, the
    requirement is raised to `FIELD_REVIEW`."

    Design: Difficulty/combinatorial_formula/escalation_matrix_three_input_nonlinear_upgrade
    """
    env = _high_tier_review(api, OUTSIZED_GROSS_GRID)
    review = fx.submit_desk_review(
        api, env["desk_review"]["id"],
        findings_note="One outsized gross adjustment on comparable 1.",
    )

    assert review["final_quality_score_bps"] == 9400
    assert review["risk_tier_at_review"] == "HIGH"
    assert review["required_escalation"] == "FIELD_REVIEW"


def test_a_clean_grid_on_the_same_tier_and_score_band_escalates_to_nothing(api):
    """Without the outsized adjustment the same tier and band answers NONE.

    The matrix row is unchanged and the score stays in the same band above 8500, but
    no comparable breaches the single-adjustment ceiling, so the adjustment clause has
    nothing to upgrade and the requirement remains NONE. The contrast isolates the
    fourth input as the cause of the upgrade.

    PRD: "On a `HIGH` tier loan, a final score below 7000 basis points requires
    `SECOND_APPRAISAL`; otherwise a score below 8500 requires `FIELD_REVIEW`;
    otherwise `NONE`."

    Design: Difficulty/combinatorial_formula/escalation_matrix_three_input_nonlinear_upgrade
    """
    env = _high_tier_review(api, list(fx.CLEAN_COMPARABLES))
    review = fx.submit_desk_review(api, env["desk_review"]["id"])
    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])

    assert appraisal["max_gross_adjustment_bps"] == 100
    assert review["risk_tier_at_review"] == "HIGH"
    assert review["final_quality_score_bps"] == 10000
    assert review["required_escalation"] == "NONE"


def test_all_four_matrix_inputs_are_pinned_on_the_upgraded_review(api):
    """The four inputs the requirement reads are each observable and exact.

    Completeness is a perfect 10000 with exactly one failing row and no warnings, so
    the rule penalty alone takes both score variants to 9400; the bias screen is
    CLEAR so no bias term applies and no override fires; every distance is inside the
    suburban ceiling so no distance term applies; and the gross maximum is 3000.

    PRD: "The appraisal-level maxima are taken across eligible comparables only:
    `max_gross_adjustment_bps` is the greatest `gross_adjustment_bps` among them, and
    `max_net_adjustment_bps` is the greatest `net_adjustment_bps` among them; both are
    0 when the eligible set is empty."

    Design: Difficulty/combinatorial_formula/escalation_matrix_three_input_nonlinear_upgrade
    """
    env = _high_tier_review(api, OUTSIZED_GROSS_GRID)
    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])

    assert appraisal["completeness_score_bps"] == 10000
    assert appraisal["rule_check_fail_count"] == 1
    assert appraisal["rule_check_warn_count"] == 0
    assert appraisal["max_gross_adjustment_bps"] == 3000
    assert appraisal["max_net_adjustment_bps"] == 100
    assert appraisal["indicated_value_cents"] == 40003334
    assert appraisal["variance_vs_reported_bps"] == 1
    assert appraisal["bias_screen_status"] == "CLEAR"

    review = fx.submit_desk_review(
        api, env["desk_review"]["id"],
        findings_note="One outsized gross adjustment on comparable 1.",
    )
    assert review["preliminary_quality_score_bps"] == 9400
    assert review["final_quality_score_bps"] == 9400


# Adjusted prices of 48200000, 49100033 and 47900067: remainders chosen so that the
# per-comparable thirds do not cancel against a single division at the end.
UNEVEN_THIRDS_GRID = [
    {
        "street_address": "77 Quarry Road",
        "sale_price_cents": 47000000,
        "gross_adjustment_cents": 2400000,
        "net_adjustment_cents": 1200000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "88 Ridge Road",
        "sale_price_cents": 50000000,
        "gross_adjustment_cents": 3100033,
        "net_adjustment_cents": -899967,
        "distance_miles": 1.5,
        "sale_date": "2026-05-15T00:00:00Z",
    },
    {
        "street_address": "99 Summit Road",
        "sale_price_cents": 46500000,
        "gross_adjustment_cents": 1900067,
        "net_adjustment_cents": 1400067,
        "distance_miles": 2.0,
        "sale_date": "2026-06-01T00:00:00Z",
    },
]


def _uneven_thirds_report(api):
    """A report whose three comparables divide unevenly by three."""
    return fx.delivered_report(
        api,
        amc={"name": "Quarry Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-2002",
            "license_state": "CA",
        },
        loan={"loan_number": "LN-2747-2B", "borrower_display_name": "Dana Borrower"},
        appraisal={
            "effective_date": "2026-07-01T00:00:00Z",
            "reported_value_cents": 48500000,
        },
        comparables=UNEVEN_THIRDS_GRID,
    )


def test_indicated_value_rounds_each_comparable_before_summing(api):
    """The reconciled value is a cent above the sum-then-divide answer.

    Each comparable's third is rounded half-up to whole cents and the rounded thirds
    are then added, giving 48400034. Summing 145200100 and dividing once would give
    48400033, so the single cent of difference distinguishes the two orders and the
    variance is pinned at 21 basis points against a reported 48500000.

    PRD: "Summing the adjusted prices first and dividing once at the end is forbidden
    and produces a different answer whenever the per-comparable remainders do not
    cancel."

    Design: Difficulty/combinatorial_formula/indicated_value_round_per_comparable_then_sum
    """
    env = _uneven_thirds_report(api)
    appraisal = fx.run_rule_checks(api, env["appraisal"]["id"])

    assert appraisal["indicated_value_cents"] == 48400034
    assert appraisal["indicated_value_cents"] != 48400033
    assert appraisal["variance_vs_reported_bps"] == 21
    assert appraisal["review_status"] == "RULES_CLEARED"
    assert appraisal["rule_check_fail_count"] == 0
    assert appraisal["rule_check_warn_count"] == 0


def test_per_comparable_figures_feeding_the_reconciliation_are_pinned(api):
    """Each row's adjusted price and both ratios are exact before the grid rolls up.

    The three rows are checked one at a time so that the reconciled total is traceable
    to its inputs: the adjusted price is the sale price plus the signed net adjustment,
    the gross ratio is a half-up basis-point share of sale price, and the net ratio is
    taken from the absolute net adjustment, so the downward-adjusted row still carries
    a positive ratio.

    PRD: "Otherwise the reconciled indicated value is built with a **pinned rounding
    order**: take the eligible comparables in ascending `created_at` order, divide each
    one's `adjusted_price_cents` by the number of eligible comparables, round *that
    per-comparable quotient* half-up to whole cents, and then add the rounded quotients
    together."

    Design: Difficulty/combinatorial_formula/indicated_value_round_per_comparable_then_sum
    """
    env = _uneven_thirds_report(api)
    by_address = {row["street_address"]: row for row in env["comparables"]}

    quarry = by_address["77 Quarry Road"]
    assert quarry["adjusted_price_cents"] == 48200000
    assert quarry["gross_adjustment_bps"] == 511
    assert quarry["net_adjustment_bps"] == 255

    ridge = by_address["88 Ridge Road"]
    assert ridge["adjusted_price_cents"] == 49100033
    assert ridge["gross_adjustment_bps"] == 620
    assert ridge["net_adjustment_bps"] == 180

    summit = by_address["99 Summit Road"]
    assert summit["adjusted_price_cents"] == 47900067
    assert summit["gross_adjustment_bps"] == 409
    assert summit["net_adjustment_bps"] == 301

    appraisal = fx.run_rule_checks(api, env["appraisal"]["id"])
    assert appraisal["eligible_comp_count"] == 3
    assert appraisal["closed_comp_count"] == 3
    assert appraisal["completeness_score_bps"] == 10000
    assert appraisal["max_gross_adjustment_bps"] == 620
    assert appraisal["max_net_adjustment_bps"] == 301


# A clean grid; the thin exhibit set alone is what pushes the score under the
# high-tier field-review cut-off.
RIVER_ROAD_GRID = [
    {
        "street_address": "41 River Road",
        "sale_price_cents": 47000000,
        "gross_adjustment_cents": 470000,
        "net_adjustment_cents": 470000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "42 River Road",
        "sale_price_cents": 48000000,
        "gross_adjustment_cents": 480000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "43 River Road",
        "sale_price_cents": 49000000,
        "gross_adjustment_cents": 490000,
        "net_adjustment_cents": -490000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _rush_priced_order(api):
    """A field-review order created at the clock epoch and staffed a day later, so
    only 48 hours of its 72-hour turnaround remain at assignment."""
    env = fx.escalated_report(
        api,
        with_reviewer=True,
        amc={"name": "Harbor Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-2003",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Reviewer",
            "license_number": "CA-BR-2003",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-2C",
            "risk_tier": "HIGH",
            "borrower_display_name": "Dana Borrower",
        },
        appraisal={
            "effective_date": "2026-07-15T00:00:00Z",
            "reported_value_cents": 48000000,
            "exhibit_count": 1,
        },
        comparables=RIVER_ROAD_GRID,
    )
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    env["order"] = fx.assign_order(
        api, env["order"]["id"], env["reviewer"]["id"],
        "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z",
    )
    return env


def test_rush_surcharge_is_added_before_the_discount_tier_is_chosen(api):
    """The 45000 base fee only reaches the discount tier once the surcharge is added.

    Forty-eight hours of turnaround remain, so the order is rush and carries 13500 of
    surcharge. The tier is then read off the 58500 subtotal, which sits inside the
    500 basis point band; the bare 45000 base fee would have earned no discount at
    all. Five hundred basis points of 58500 is 2925, leaving 55575.

    PRD: "Step three picks the volume discount tier from the **post-surcharge
    subtotal**, being base fee plus surcharge: a subtotal below 50000 cents earns
    `discount_pct_bps` of 0; a subtotal from 50000 cents up to and including 80000
    cents earns 500 basis points; a subtotal above 80000 cents earns 1000 basis
    points."

    Design: Difficulty/combinatorial_formula/escalation_cost_rush_before_tier_discount_order
    """
    env = _rush_priced_order(api)
    order = env["order"]

    assert order["escalation_type"] == "FIELD_REVIEW"
    assert_instant(order["due_at"], "2026-08-04T00:00:00Z", "due_at")
    assert order["base_fee_cents"] == 45000
    assert order["rush_surcharge_cents"] == 13500
    assert order["discount_pct_bps"] == 500
    assert order["total_cost_cents"] == 55575


def test_the_priced_total_is_what_reaches_the_ledger_and_the_counters(api):
    """Assignment charges the discounted total, not the subtotal or the base fee.

    The order lands in ASSIGNED with the named appraiser, the company's year-to-date
    spend equals the 55575 the five steps produced, and the assignee carries one open
    assignment. The score that selected the field review is pinned alongside, since a
    different requirement would have priced a different base fee.

    PRD: "A successful assignment writes all four cost fields, adds `total_cost_cents`
    to the management company's `ytd_escalation_spend_cents`, increments the assignee's
    `open_assignment_count`, and reserves the inspection window on that appraiser so it
    participates in future conflict checks."

    Design: Difficulty/combinatorial_formula/escalation_cost_rush_before_tier_discount_order
    """
    env = _rush_priced_order(api)

    assert env["order"]["status"] == "ASSIGNED"
    assert env["order"]["assigned_appraiser_id"] == env["reviewer"]["id"]
    assert env["desk_review"]["final_quality_score_bps"] == 8086
    assert env["desk_review"]["required_escalation"] == "FIELD_REVIEW"

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 55575

    reviewer = fx.read_appraiser(api, env["reviewer"]["id"])
    assert reviewer["open_assignment_count"] == 1
