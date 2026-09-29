"""Claim reimbursement arithmetic: the preliminary and final variants, the per-line-item
rounding granularity, and the administrative cap keyed to the operating reimbursement.

Every scenario is built from scratch against an empty database through PRD endpoints only.
"""

from test_helpers import (
    assert_claim_line_item,
    assert_meal_claim,
    assert_status,
    make_sponsor_admin_headers,
    pay_claim,
    run_edit_check,
    setup_june_claim_scenario,
    submit_claim,
    validate_success,
)

# One rural SELF_PREP site serving 47 LUNCH first meals out of 150 produced, at the
# RURAL_OR_SELF_PREP lunch rate of 470.50 fractional cents: 47 * 470.50 = 22113.50, which rounds
# half-up to a single per-line-item, per-meal-type value of 22114 cents.
LUNCH_LINE_VALUE_CENTS = 22_114
THREE_SITE_CLAIM_VALUE_CENTS = 66_342
SUM_THEN_ROUND_WRONG_TOTAL_CENTS = 66_341


# --- Difficulty/dual_variant_calc -------------------------------------------------------------


def test_preliminary_reimbursement_applies_no_caps_on_submitted_claim(api):
    """PRD §3.8: "The claim's `preliminary_reimbursement_cents` is then written from the
    **preliminary** reimbursement variant, which is deliberately simple: it is the claim's
    `meals_rate_value_cents` plus its `claimed_admin_cost_cents`, with no disallowances subtracted
    and **no caps of any kind applied**."

    Design: Difficulty/dual_variant_calc/claim_reimbursement_preliminary_versus_final_variants
    """
    scenario = setup_june_claim_scenario()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    claim = submit_claim(
        scenario["claim"],
        claimed_operating_cost_cents=30_000,
        claimed_admin_cost_cents=20_000,
    )

    line_item = validate_success(
        api.get_claim_line_item(scenario["line_item"]["id"], sponsor_headers)
    )
    assert_claim_line_item(line_item)
    assert line_item["meals_rate_value_cents"] == LUNCH_LINE_VALUE_CENTS, (
        "the single LUNCH line item must be worth 22114 cents, got "
        f"{line_item['meals_rate_value_cents']}"
    )

    assert_meal_claim(claim)
    assert claim["meals_rate_value_cents"] == LUNCH_LINE_VALUE_CENTS, (
        "the claim's meals_rate_value_cents must be the sum of its rounded line values, 22114, "
        f"got {claim['meals_rate_value_cents']}"
    )
    assert claim["preliminary_reimbursement_cents"] == 42_114, (
        "the preliminary variant must add the asserted admin cost of 20000 to the meals value of "
        f"22114 with no cap applied, expected 42114, got "
        f"{claim['preliminary_reimbursement_cents']}"
    )


def test_final_reimbursement_caps_admin_and_diverges_from_preliminary(api):
    """PRD §3.8: "Step three produces `admin_cap_cents` as 20 percent of **step two's output**,
    floored to whole cents. Step four produces the administrative reimbursement as the lesser of
    `claimed_admin_cost_cents` and that cap. Step five sums steps two and four into the gross
    figure that becomes `final_reimbursement_cents`."

    Design: Difficulty/dual_variant_calc/claim_reimbursement_preliminary_versus_final_variants
    """
    scenario = setup_june_claim_scenario()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    claim = submit_claim(
        scenario["claim"],
        claimed_operating_cost_cents=30_000,
        claimed_admin_cost_cents=20_000,
    )
    validated = run_edit_check(claim)

    assert_meal_claim(validated)
    assert_status(validated, "VALIDATED")
    assert validated["final_reimbursement_cents"] == 26_536, (
        "the final variant must be 22114 operating plus a floored admin cap of 4422, expected "
        f"26536, got {validated['final_reimbursement_cents']}"
    )
    assert validated["final_reimbursement_cents"] != validated["preliminary_reimbursement_cents"], (
        "the capped final figure must diverge from the uncapped preliminary figure, both read "
        f"{validated['final_reimbursement_cents']}"
    )
    assert validated["preliminary_reimbursement_cents"] == 42_114, (
        "the preliminary figure recorded at submission must survive the edit check unchanged, got "
        f"{validated['preliminary_reimbursement_cents']}"
    )

    summary = validate_success(
        api.get_reimbursement_summary(validated["id"], sponsor_headers)
    )
    assert summary["meals_rate_value_cents"] == LUNCH_LINE_VALUE_CENTS, (
        f"summary meals_rate_value_cents must be 22114, got {summary['meals_rate_value_cents']}"
    )
    assert summary["operating_reimbursement_cents"] == LUNCH_LINE_VALUE_CENTS, (
        "step two must take the lesser of the 22114 meals value and the 30000 claimed operating "
        f"cost, expected 22114, got {summary['operating_reimbursement_cents']}"
    )
    assert summary["admin_cap_cents"] == 4_422, (
        "step three must floor 20 percent of 22114 to 4422 cents, got "
        f"{summary['admin_cap_cents']}"
    )
    assert summary["admin_reimbursement_cents"] == 4_422, (
        "step four must take the lesser of the 20000 claimed admin cost and the 4422 cap, got "
        f"{summary['admin_reimbursement_cents']}"
    )
    assert summary["disallowed_meal_count"] == 0, (
        "no meal was disallowed on this clean claim, so the summary must report 0 disallowed "
        f"meals, got {summary['disallowed_meal_count']}"
    )


def test_paid_claim_nets_final_reimbursement_when_no_advances_exist(api):
    """PRD §3.8: "The claim's `net_payable_cents` is its `final_reimbursement_cents` less
    `advance_offset_cents`. When there are no candidates at all, the offset is 0 and the net
    payable equals the final reimbursement exactly."

    Design: Difficulty/dual_variant_calc/claim_reimbursement_preliminary_versus_final_variants
    """
    scenario = setup_june_claim_scenario()

    claim = submit_claim(
        scenario["claim"],
        claimed_operating_cost_cents=30_000,
        claimed_admin_cost_cents=20_000,
    )
    validated = run_edit_check(claim)
    paid = pay_claim(validated)

    assert_meal_claim(paid)
    assert_status(paid, "PAID")
    assert paid["advance_offset_cents"] == 0, (
        "the sponsor holds no disbursed advance, so the recovery waterfall must offset nothing, "
        f"got {paid['advance_offset_cents']}"
    )
    assert paid["net_payable_cents"] == 26_536, (
        "with a zero offset the net payable must equal the 26536-cent final reimbursement, got "
        f"{paid['net_payable_cents']}"
    )


# --- Difficulty/combinatorial_formula: per-line-item rounding then summation -------------------


def test_line_item_rate_class_and_finalized_day_count_for_rural_self_prep_sites(api):
    """PRD §3.8: "The line's `rate_class` is `RURAL_OR_SELF_PREP` when the site's `is_rural` is
    true **or** its `production_mode` is `SELF_PREP`, and `OTHER` otherwise — either condition
    alone is enough to earn the higher rate. Its `finalized_day_count` counts the site's finalized
    days inside `claim_month`."

    Design: Difficulty/combinatorial_formula/meals_rate_value_rounds_per_line_item_then_sums
    """
    scenario = setup_june_claim_scenario(site_count=3)
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    for index, created_line in enumerate(scenario["line_items"]):
        line_item = validate_success(
            api.get_claim_line_item(created_line["id"], sponsor_headers)
        )
        assert_claim_line_item(line_item)
        assert line_item["rate_class"] == "RURAL_OR_SELF_PREP", (
            f"line item {index} references a rural SELF_PREP site and must earn the higher rate "
            f"class, got {line_item['rate_class']}"
        )
        assert line_item["finalized_day_count"] == 1, (
            f"line item {index} covers exactly one finalized June day, got "
            f"{line_item['finalized_day_count']}"
        )


def test_line_item_meals_rate_value_rounds_each_lunch_line_half_up(api):
    """PRD §3.8: "For each type, the net claimable meals are that type's claimed first meals plus
    its claimed second meals, less the disallowed count recorded for that type — which is zero
    before any edit check has run — and the per-type value in cents is that net multiplied by the
    applicable rate and rounded to a whole number of cents with half-up rounding."

    Design: Difficulty/combinatorial_formula/meals_rate_value_rounds_per_line_item_then_sums
    """
    scenario = setup_june_claim_scenario(site_count=3)
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    assert len(scenario["line_items"]) == 3, (
        f"the claim must carry one line item per site, got {len(scenario['line_items'])}"
    )
    for index, created_line in enumerate(scenario["line_items"]):
        line_item = validate_success(
            api.get_claim_line_item(created_line["id"], sponsor_headers)
        )
        assert_claim_line_item(line_item)
        assert line_item["meals_rate_value_cents"] == LUNCH_LINE_VALUE_CENTS, (
            f"line item {index} carries 47 LUNCH first meals at 470.50 cents, so 22113.50 must "
            f"round half-up to 22114 on this line, got {line_item['meals_rate_value_cents']}"
        )


def test_claim_meals_rate_value_sums_rounded_line_values_across_three_sites(api):
    """PRD §3.8: "The rounding order is pinned: each pair of line item and meal type is rounded to
    whole cents **first**, and only the rounded per-type values are summed into the line's
    `meals_rate_value_cents`, which are themselves summed across the claim's lines into the claim's
    `meals_rate_value_cents`. Summing meal counts across line items or across meal types before
    rounding is incorrect and produces a different total."

    Design: Difficulty/combinatorial_formula/meals_rate_value_rounds_per_line_item_then_sums
    """
    scenario = setup_june_claim_scenario(site_count=3)
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    claim = validate_success(
        api.get_meal_claim(scenario["claim"]["id"], sponsor_headers)
    )
    assert_meal_claim(claim)
    assert claim["meals_rate_value_cents"] == THREE_SITE_CLAIM_VALUE_CENTS, (
        "three lines rounded to 22114 each must sum to 66342 on the claim, got "
        f"{claim['meals_rate_value_cents']}"
    )
    assert claim["meals_rate_value_cents"] != SUM_THEN_ROUND_WRONG_TOTAL_CENTS, (
        "summing 141 meals before rounding would yield 66341, which the pinned rounding order "
        "forbids"
    )


# --- Difficulty/combinatorial_formula: the admin cap keyed to the operating reimbursement ------


def test_admin_cap_keyed_to_operating_reimbursement_not_combined_total(api):
    """PRD §3.8: "The cap is keyed to the operating reimbursement, not to the total reimbursement;
    the reading in which the cap is 20 percent of the combined total — which would require solving
    for the administrative amount that satisfies its own ceiling — is explicitly **not** the rule,
    and no fixed-point iteration is ever needed."

    Design: Difficulty/combinatorial_formula/admin_cap_evaluation_order_keyed_to_operating_reimbursement
    """
    scenario = setup_june_claim_scenario()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    claim = submit_claim(
        scenario["claim"],
        claimed_operating_cost_cents=20_000,
        claimed_admin_cost_cents=20_000,
    )
    validated = run_edit_check(claim)

    assert_meal_claim(validated)
    assert_status(validated, "VALIDATED")

    summary = validate_success(
        api.get_reimbursement_summary(validated["id"], sponsor_headers)
    )
    assert summary["operating_reimbursement_cents"] == 20_000, (
        "the operating reimbursement must clamp the 22114 meals value down to the 20000 claimed "
        f"operating cost, got {summary['operating_reimbursement_cents']}"
    )
    assert summary["admin_cap_cents"] == 4_000, (
        "the cap must be 20 percent of the 20000 operating reimbursement, not of the combined "
        f"total, expected 4000, got {summary['admin_cap_cents']}"
    )
    assert summary["admin_reimbursement_cents"] == 4_000, (
        "the administrative reimbursement must be the 4000 cap rather than the 5000 a "
        f"self-referential cap on the combined total would allow, got "
        f"{summary['admin_reimbursement_cents']}"
    )


def test_final_reimbursement_sums_clamped_operating_and_capped_admin(api):
    """PRD §3.8: "Step one takes the claim's `meals_rate_value_cents`, recomputed with the
    disallowed counts subtracted. Step two produces the operating reimbursement as the lesser of
    that meals value and the claim's `claimed_operating_cost_cents`. Step three produces
    `admin_cap_cents` as 20 percent of **step two's output**, floored to whole cents. Step four
    produces the administrative reimbursement as the lesser of `claimed_admin_cost_cents` and that
    cap. Step five sums steps two and four into the gross figure that becomes
    `final_reimbursement_cents`."

    Design: Difficulty/combinatorial_formula/admin_cap_evaluation_order_keyed_to_operating_reimbursement
    """
    scenario = setup_june_claim_scenario()

    claim = submit_claim(
        scenario["claim"],
        claimed_operating_cost_cents=20_000,
        claimed_admin_cost_cents=20_000,
    )
    validated = run_edit_check(claim)

    assert_meal_claim(validated)
    assert validated["final_reimbursement_cents"] == 24_000, (
        "step five must sum the 20000 operating reimbursement and the 4000 capped administrative "
        f"reimbursement, expected 24000, got {validated['final_reimbursement_cents']}"
    )
    assert validated["final_reimbursement_cents"] != 25_000, (
        "25000 is the figure a cap keyed to the combined total would produce, which the pinned "
        "step order forbids"
    )


def test_net_payable_equals_final_reimbursement_with_no_advance_candidates(api):
    """PRD §3.8: "When there are no candidates at all, the offset is 0 and the net payable equals
    the final reimbursement exactly."

    Design: Difficulty/combinatorial_formula/admin_cap_evaluation_order_keyed_to_operating_reimbursement
    """
    scenario = setup_june_claim_scenario()

    claim = submit_claim(
        scenario["claim"],
        claimed_operating_cost_cents=20_000,
        claimed_admin_cost_cents=20_000,
    )
    validated = run_edit_check(claim)
    paid = pay_claim(validated)

    assert_meal_claim(paid)
    assert_status(paid, "PAID")
    assert paid["advance_offset_cents"] == 0, (
        "the sponsor holds no candidate advance, so the offset must be 0, got "
        f"{paid['advance_offset_cents']}"
    )
    assert paid["net_payable_cents"] == 24_000, (
        "the net payable must equal the 24000-cent final reimbursement when nothing is recovered, "
        f"got {paid['net_payable_cents']}"
    )
