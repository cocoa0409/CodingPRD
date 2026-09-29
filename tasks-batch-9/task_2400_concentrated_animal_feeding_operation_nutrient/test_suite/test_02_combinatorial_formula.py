"""Multi-step formulas whose pinned evaluation order changes the answer: the
allowable-rate chain, the round-then-sum nutrient roll-up and the renewal fee.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_budget_rates,
    assert_quantity,
    assert_state,
)
from test_helpers.fixtures import (
    add_budget,
    create_plan,
    draft_permit,
    file_soil_test,
    open_annual_report,
    record_application,
    register_field,
    register_operation,
    set_clock,
    setup_ready_operation,
    setup_scenario,
)
from test_helpers.test_users import make_operator_headers


def _two_soil_tests_on_one_field():
    """One field carrying a 42 ppm test (MEDIUM index) and a 62 ppm test (HIGH
    index), plus a draft plan ready to take budgets against either."""
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    permit = draft_permit(operation_id, operator_headers)
    field = register_field(operation_id)
    medium_test = file_soil_test(field["id"])
    high_test = file_soil_test(
        field["id"], sampled_on="2026-03-16T00:00:00Z", soil_test_p_ppm=62
    )
    plan = create_plan(operation_id, permit["id"])
    return {
        "operation": operation,
        "operator_headers": operator_headers,
        "field": field,
        "medium_test": medium_test,
        "high_test": high_test,
        "plan": plan,
    }


def _three_small_applications():
    """Three identical 1,503-gallon single-acre injections, spaced a month
    apart so the re-application buffer is clear."""
    ctx = setup_ready_operation()
    ctx["events"] = [
        record_application(
            ctx["operation"]["id"],
            ctx["plan"]["id"],
            ctx["budget"]["id"],
            ctx["storage"]["id"],
            ctx["operator_headers"],
            applied_on=applied_on,
            gallons_applied=1503,
            acres_treated=1.0,
        )
        for applied_on in (
            "2026-04-01T00:00:00Z",
            "2026-05-01T00:00:00Z",
            "2026-06-01T00:00:00Z",
        )
    ]
    return ctx


def test_medium_phosphorus_index_leaves_the_budget_nitrogen_bound():
    """On a MEDIUM index the phosphate allowance is doubled, which puts the
    phosphorus rate above the nitrogen rate, so nitrogen binds.

    PRD: "`p_index` is `soil_test_p_ppm` multiplied by one plus the parent field's `slope_pct` divided by 100, rounded half up to 2 decimal places — so steeper ground converts the same measured concentration into a higher runoff risk index."
    PRD: "`p_allowance_lbs` is `crop_p_removal_lbs` multiplied by a multiplier keyed on the referenced soil test's `p_index_category`, rounded half up to 2 decimal places."
    PRD: "`binding_basis` records which limit bound: it is `NITROGEN` when `allowable_n_rate_gal_per_acre` is less than or equal to `allowable_p_rate_gal_per_acre`, and `PHOSPHORUS` otherwise — so a tie is attributed to nitrogen."

    Design: Difficulty/combinatorial_formula/budget_rate_binding_basis_switches_with_p_index_tier
    """
    ctx = _two_soil_tests_on_one_field()

    assert_quantity(ctx["medium_test"]["p_index"], 43.68, "p_index")
    assert ctx["medium_test"]["p_index_category"] == "MEDIUM", (
        f"p_index_category: expected MEDIUM, got {ctx['medium_test']['p_index_category']}"
    )

    budget = add_budget(
        ctx["plan"]["id"], ctx["field"]["id"], ctx["medium_test"]["id"]
    )

    assert_budget_rates(
        budget,
        crop_n_need=209.00,
        legume_credit=40,
        adjusted_n_need=169.00,
        crop_p_removal=70.30,
        p_allowance=140.60,
        allowable_n_rate=10800,
        allowable_p_rate=14000,
        binding_basis="NITROGEN",
        allowable_rate=10800,
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)
    assert_state(budget, "budget_status", "LOCKED")


def test_high_phosphorus_index_switches_the_binding_basis_to_phosphorus():
    """Raising only the measured phosphorus to 62 ppm moves the index into the
    HIGH band, halves the multiplier and makes the phosphorus rate the smaller
    of the two, so the same field's total allowance collapses.

    PRD: "`p_index_category` follows from inclusive lower bounds: `VERY_HIGH` when `p_index` is at least 100; `HIGH` when it is at least 50 but below 100; `MEDIUM` when it is at least 20 but below 50; and `LOW` otherwise."
    PRD: "`allowable_rate_gal_per_acre` is whichever of the two limits is smaller."
    PRD: "`allowable_total_gallons` is `allowable_rate_gal_per_acre` multiplied by the field's `net_applicable_acres`, floored to a whole gallon."

    Design: Difficulty/combinatorial_formula/budget_rate_binding_basis_switches_with_p_index_tier
    """
    ctx = _two_soil_tests_on_one_field()

    assert_quantity(ctx["high_test"]["p_index"], 64.48, "p_index")
    assert ctx["high_test"]["p_index_category"] == "HIGH", (
        f"p_index_category: expected HIGH, got {ctx['high_test']['p_index_category']}"
    )

    assert_quantity(ctx["field"]["required_setback_ft"], 200, "required_setback_ft")
    assert_quantity(ctx["field"]["excluded_acres"], 4.13, "excluded_acres")
    assert_quantity(ctx["field"]["net_applicable_acres"], 38.37, "net_applicable_acres")

    budget = add_budget(ctx["plan"]["id"], ctx["field"]["id"], ctx["high_test"]["id"])

    assert_budget_rates(
        budget,
        crop_p_removal=70.30,
        p_allowance=70.30,
        allowable_n_rate=10800,
        allowable_p_rate=7000,
        binding_basis="PHOSPHORUS",
        allowable_rate=7000,
    )
    assert_budget_ledger(budget, applied=0.00, remaining=268590, total=268590)
    assert_state(budget, "budget_status", "LOCKED")


def test_each_application_persists_its_own_rounded_nutrient_masses():
    """Every event rounds its nitrogen and phosphate to 2 decimals at the moment
    it is written, which is what makes the annual sum reproducible.

    PRD: "Per-event nutrient masses are rounded to 2 decimal places and persisted at the moment the event is recorded, and every annual nutrient total is the sum of those already-rounded persisted values."
    PRD: "The per-acre rate, `rate_gal_per_acre`, computed as `gallons_applied` divided by `acres_treated` and rounded half up to 2 decimal places, may not exceed the budget's `allowable_rate_gal_per_acre`, or the record is refused with `ERR_RATE_EXCEEDS_LIMIT`."

    Design: Difficulty/combinatorial_formula/application_nutrient_round_per_event_then_sum
    """
    ctx = _three_small_applications()

    for event in ctx["events"]:
        assert_quantity(event["rate_gal_per_acre"], 1503.00, "rate_gal_per_acre")
        assert_quantity(event["n_applied_lbs"], 23.45, "n_applied_lbs")
        assert_quantity(event["p2o5_applied_lbs"], 15.03, "p2o5_applied_lbs")
        assert_state(event, "event_status", "RECORDED")


def test_annual_totals_sum_the_persisted_masses_rather_than_the_raw_ones():
    """Three events of 23.45 pounds sum to 70.35, not to the 70.34 that rounding
    the raw product once at the end would produce.

    PRD: "Summing raw unrounded masses and rounding once at the end is explicitly not the pinned order and will produce different totals."
    PRD: "`total_n_applied_lbs` and `total_p2o5_applied_lbs` are the year's nutrient roll-ups over the same record set as step 1: the sums of the persisted, already-rounded `n_applied_lbs` and `p2o5_applied_lbs` values of those records."
    PRD: "`variance_classification` is `WITHIN_TOLERANCE` when the absolute value of `variance_pct` is at most 15.00, and `EXCEEDS_TOLERANCE` otherwise."

    Design: Difficulty/combinatorial_formula/application_nutrient_round_per_event_then_sum
    """
    ctx = _three_small_applications()
    report = open_annual_report(
        ctx["operation"]["id"], ctx["plan"]["id"], ctx["operator_headers"]
    )

    assert_quantity(report["total_n_applied_lbs"], 70.35, "total_n_applied_lbs")
    assert float(report["total_n_applied_lbs"]) != 70.34, (
        "70.34 is the sum-then-round answer and is not the pinned order"
    )
    assert_quantity(report["total_p2o5_applied_lbs"], 45.09, "total_p2o5_applied_lbs")

    assert_quantity(
        report["recorded_land_applied_gallons"], 4509.00, "recorded_land_applied_gallons"
    )
    assert_quantity(
        report["recorded_transferred_gallons"], 0.00, "recorded_transferred_gallons"
    )
    assert_quantity(
        report["recorded_total_gallons"], 3378807.00, "recorded_total_gallons"
    )
    assert_quantity(
        report["mass_balance_expected_gallons"],
        3374298.00,
        "mass_balance_expected_gallons",
    )
    assert_quantity(report["variance_pct"], 0.13, "variance_pct")
    assert_state(report, "variance_classification", "WITHIN_TOLERANCE")
    assert_state(report, "report_status", "DRAFT")

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], ctx["operator_headers"]), 200
    )
    assert_budget_ledger(budget, applied=4509.00, remaining=409887, total=414396)


def test_renewal_fee_keys_the_discount_on_gross_and_the_surcharge_on_net():
    """The conservation tier is chosen from the pre-discount fee while the late
    surcharge is taken on the post-discount fee, so the total is 699.44.

    PRD: "Initiation is also the moment the **renewal fee** is assessed, in six steps whose order is pinned because the discount tier is keyed on the pre-discount amount while the late surcharge is keyed on the post-discount amount."
    PRD: "`late_surcharge_amount` is `net_fee` multiplied by 0.25, rounded half up to 2 decimal places, when `is_late_renewal` is true; it is exactly 0.00 when `is_late_renewal` is false."
    PRD: "`total_due` is `net_fee` plus `late_surcharge_amount`, rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/permit_renewal_fee_tier_on_gross_surcharge_on_net
    """
    ctx = setup_scenario("COVERED")
    set_clock("2030-10-10T00:00:00Z")

    permit = validate_success(
        api_client.initiate_permit_renewal(
            ctx["permit"]["id"], ctx["operator_headers"]
        ),
        200,
    )

    assert_quantity(permit["gross_fee"], 589.00, "gross_fee")
    assert_quantity(
        permit["conservation_discount_pct"], 0.05, "conservation_discount_pct"
    )
    assert_quantity(
        permit["conservation_discount_amount"], 29.45, "conservation_discount_amount"
    )
    assert_quantity(permit["net_fee"], 559.55, "net_fee")
    assert permit["is_late_renewal"] is True, (
        "a renewal filed on 10 October 2030 is past the 3 October due date"
    )
    assert_quantity(permit["late_surcharge_amount"], 139.89, "late_surcharge_amount")
    assert_quantity(permit["total_due"], 699.44, "total_due")

    # Surcharging the gross fee instead of the net fee would total 706.80.
    assert abs(float(permit["total_due"]) - 706.80) > 0.005, (
        "the late surcharge must be taken on the net fee, not the gross fee"
    )
    assert abs(float(permit["total_due"]) - 559.55) > 0.005, (
        "a late renewal must carry the surcharge"
    )


def test_initiating_a_renewal_moves_only_the_coverage_dimension():
    """Initiation stamps the renewal instant and the five-year term dates while
    the compliance dimension stays in good standing.

    PRD: "Issuance is what stamps the term: `expiration_on` becomes `effective_on` plus a coverage term of 5 years; `renewal_window_opens_on` becomes `expiration_on` minus 180 days; and `renewal_due_on` becomes `expiration_on` minus 90 days."
    PRD: "Initiation stamps `renewal_submitted_at` from the logical clock and sets `is_late_renewal` to true exactly when `renewal_submitted_at` is strictly later than `renewal_due_on`."

    Design: Difficulty/combinatorial_formula/permit_renewal_fee_tier_on_gross_surcharge_on_net
    """
    ctx = setup_scenario("COVERED")
    covered = ctx["permit"]

    assert covered["expiration_on"].startswith("2031-01-01"), (
        f"expiration_on: expected 1 January 2031, got {covered['expiration_on']}"
    )
    assert covered["renewal_window_opens_on"].startswith("2030-07-05"), (
        f"renewal_window_opens_on: expected 5 July 2030, "
        f"got {covered['renewal_window_opens_on']}"
    )
    assert covered["renewal_due_on"].startswith("2030-10-03"), (
        f"renewal_due_on: expected 3 October 2030, got {covered['renewal_due_on']}"
    )

    set_clock("2030-10-10T00:00:00Z")
    permit = validate_success(
        api_client.initiate_permit_renewal(covered["id"], ctx["operator_headers"]),
        200,
    )

    assert_state(permit, "coverage_status", "RENEWAL_PENDING")
    assert_state(permit, "compliance_status", "IN_GOOD_STANDING")
    assert permit["renewal_submitted_at"].startswith("2030-10-10"), (
        f"renewal_submitted_at: expected 10 October 2030, "
        f"got {permit['renewal_submitted_at']}"
    )
