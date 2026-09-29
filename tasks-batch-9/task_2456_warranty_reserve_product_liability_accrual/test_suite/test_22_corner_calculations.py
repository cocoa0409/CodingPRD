"""Calculation coverage: pinned rounding orders, input-set filters, constants and clamps.

PRD §1: "every derived figure is a full recompute from source rows rather than an
incremental adjustment ... the reserve rollforward disclosed to auditors must reconcile to
the penny against the accruals, campaign accruals, changes in estimate, claims paid and
supplier recoveries that produced it."
"""

from test_helpers import (
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    RESERVE_CONTROLLER_USER_ID,
    apply_true_up,
    assert_rollforward_identity,
    create_accrual,
    create_adequacy_review,
    create_failure_mode,
    create_family,
    create_field_action,
    create_liability_reserve,
    create_observation,
    create_period,
    create_recovery,
    create_remedy_option,
    create_service_contract,
    create_supplier,
    create_vintage,
    decide_field_action,
    generate_rollforward,
    lock_period,
    open_review,
    post_accrual,
    propose_accrual,
    read_family,
    read_field_action,
    read_period,
    read_recovery,
    read_supplier,
    select_remedy,
    submit_field_action,
    success_data,
    validate_paginated,
)


def _analog_basis(api, observation_period_code="2026-Q3"):
    """FAM-A: 300 observed claims on a 10000-unit cohort, the standard analogue basis."""
    analog_family = create_family(
        api,
        family_code="FAM-A",
        name="Legacy Compressor Platform",
        launch_date="2022-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=100000000,
    )
    analog_vintage = create_vintage(
        api,
        analog_family["id"],
        vintage_code="A-MY2022",
        units_shipped=10000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2029-12-31",
    )
    analog_mode = create_failure_mode(
        api,
        analog_family["id"],
        mode_code="FM-A-CORE",
        description="Legacy compressor core wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        analog_vintage["id"],
        analog_mode["id"],
        observation_period_code=observation_period_code,
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )
    return analog_family


def _remedy_options(api, field_action_id):
    """The candidate options of one action, where `per_unit_expected_cents` is stored."""
    return validate_paginated(api.list_remedy_options(ENGINEER_HEADERS, field_action_id))


def test_historical_rate_rounds_each_failure_mode_before_summing(api):
    """Per-mode rounding is visible in both the rate and the ultimate claim count.

    PRD §3.3: "The rounding order here is pinned and observable: the rate and the ultimate
    claim count are each rounded **per failure mode, before any summation**, never summed as
    exact rationals and rounded once at the end ... The accrual's `expected_claim_rate_ppm`
    is the sum of the per-mode rounded rates", and "`cost_per_claim_basis_cents` is 0 when
    the summed ultimate claim count across all modes is 0, and otherwise the gross ultimate
    cost divided by that summed ultimate claim count, rounded to the nearest integer."

    Design: Corner/calculations/corner_historical_rate_rounds_each_failure_mode_before_summing
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-PR",
        name="Precision Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=25000,
        reserve_cap_cents=20000000,
    )
    target = create_vintage(
        api,
        family["id"],
        vintage_code="PR-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_vintage(
        api,
        family["id"],
        vintage_code="PR-MY2025",
        units_shipped=2500,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-12-31",
    )
    bearing = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-PR-01",
        description="Precision bearing wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    board = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-PR-02",
        description="Precision control board fault",
        severity="FUNCTIONAL",
        cost_per_claim_cents=35000,
    )
    create_observation(
        api,
        target["id"],
        bearing["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=7,
        paid_cost_cents=100000,
    )
    create_observation(
        api,
        target["id"],
        board["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=4,
        paid_cost_cents=80000,
    )
    assert read_family(api, family["id"])["history_maturity_status"] == "MATURE"

    accrual = create_accrual(
        api,
        period["id"],
        target["id"],
        method="HISTORICAL_RATE",
        elapsed_exposure_bps=3000,
    )

    assert accrual["expected_claim_rate_ppm"] == 3666
    assert accrual["paid_to_date_cents"] == 180000
    assert accrual["cost_per_claim_basis_cents"] == 25556
    assert accrual["accrued_amount_cents"] == 510000


def test_historical_rate_ignores_other_vintages_of_the_same_family(api):
    """The working set is the accrual's own cohort, not the whole family.

    PRD §3.3: "Assemble the set of failure modes belonging to the cohort's family for which
    at least one claim observation exists naming both this cohort and that mode", and
    "`paid_to_date_cents` is the sum of `paid_cost_cents` over every claim observation of
    this accrual's own cohort". PRD §3.3 closes the point: "`HISTORICAL_RATE` reads only
    observations of this accrual's own cohort".

    Design: Corner/calculations/corner_historical_rate_ignores_other_vintages_of_the_same_family
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-IF",
        name="Filtering Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=20000000,
    )
    target = create_vintage(
        api,
        family["id"],
        vintage_code="IF-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    sibling = create_vintage(
        api,
        family["id"],
        vintage_code="IF-MY2025",
        units_shipped=2500,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-12-31",
    )
    shared_mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-IF-01",
        description="Shared mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    sibling_only_mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-IF-02",
        description="Sibling-only mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=50000,
    )
    create_observation(
        api,
        target["id"],
        shared_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=7,
        paid_cost_cents=100000,
    )
    create_observation(
        api,
        sibling["id"],
        shared_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=500,
        paid_cost_cents=9000000,
    )
    create_observation(
        api,
        sibling["id"],
        sibling_only_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=50,
        paid_cost_cents=500000,
    )

    accrual = create_accrual(
        api,
        period["id"],
        target["id"],
        method="HISTORICAL_RATE",
        elapsed_exposure_bps=2500,
    )

    assert accrual["expected_claim_rate_ppm"] == 2333
    assert accrual["paid_to_date_cents"] == 100000
    assert accrual["cost_per_claim_basis_cents"] == 20000
    assert accrual["accrued_amount_cents"] == 240000


def test_the_field_labour_rate_constant_is_applied_per_centi_hour(api):
    """Labour converts at 9500 cents an hour with the centi-hour scaling undone.

    PRD §3.5: "Convert labour first: multiply `labor_hours_centi` by the standard field
    labour rate of 9500 cents per hour — ninety-five dollars an hour — divide by 100 to undo
    the hundredths-of-an-hour scaling, and round to the nearest integer to obtain per-unit
    labour cost in cents." PRD §3.5 also holds the approval dimension still: "From `DRAFT`
    the action stays in `DRAFT` — a self-loop that lets the engineer re-price freely before
    submitting."

    Design: Corner/calculations/corner_field_action_labor_rate_constant_applied_per_centi_hour
    """
    family = create_family(
        api,
        family_code="FAM-LR",
        name="Labour Rate Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=20000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-LR-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=100,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-LR-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=100,
        labor_hours_centi=250,
        admin_cost_cents=50,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )

    selected = select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )

    assert selected["selected_remedy_option_id"] == option["id"]
    assert selected["specific_accrual_cents"] == 2390000
    assert selected["approval_state"] == "DRAFT"

    options, _ = _remedy_options(api, action["id"])
    assert options[0]["per_unit_expected_cents"] == 23900


def test_the_ibnr_exposure_floor_overrides_the_asserted_reserve_cap(api):
    """The floor is applied outermost, so it can beat the cap by orders of magnitude.

    PRD §3.8: "Apply the cap first, taking the lesser of the raw IBNR figure and the cap;
    then apply the floor to that capped value, taking the greater of it and the floor ...
    Because the floor is applied outermost, the floor **wins** over the cap: for a family
    with large unit exposure relative to its case reserves, `ibnr_reserve_cents` may
    legitimately exceed one and a half times `asserted_case_reserve_cents`." The floor is
    "the covered family's `units_sold_lifetime` multiplied by 25 cents per unit."

    Design: Corner/calculations/corner_ibnr_exposure_floor_overrides_the_asserted_reserve_cap
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-FL",
        name="Floor Platform",
        launch_date="2022-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=9000,
        reserve_cap_cents=900000000,
    )
    create_vintage(
        api,
        family["id"],
        vintage_code="FL-MY2022",
        units_shipped=4000000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2029-12-31",
    )

    reserve = create_liability_reserve(
        api,
        period["id"],
        family["id"],
        reported_claim_count=2,
        asserted_case_reserve_cents=100000,
        reporting_lag_months=1,
        severity_trend_bps=0,
    )

    assert reserve["avg_case_severity_cents"] == 50000
    assert reserve["lag_factor_bps"] == 1200
    assert reserve["ibnr_claim_count"] == 0
    assert reserve["ibnr_reserve_cents"] == 100000000
    assert reserve["total_liability_reserve_cents"] == 100100000
    assert reserve["status"] == "DRAFT"


def test_the_ibnr_lag_factor_saturates_at_its_ceiling_constant(api):
    """Lag beyond five months adds nothing, and a negative trend deflates severity.

    PRD §3.8: "multiply `reporting_lag_months` by 1200 basis points per month — twelve
    percent of reported frequency for each month of lag — and take the lesser of that product
    and a hard ceiling of 6000 basis points, so a lag of five months already saturates the
    factor and a longer lag adds nothing." PRD §3.8 permits the negative input: "a
    `severity_trend_bps` between -5000 and 10000 inclusive ... note that this is the one
    basis-point field permitted to be negative, because severity can trend down."

    Design: Corner/calculations/corner_ibnr_lag_factor_saturates_at_its_cap_constant
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-LC",
        name="Lag Cap Platform",
        launch_date="2022-06-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=30000000,
    )
    create_vintage(
        api,
        family["id"],
        vintage_code="LC-MY2022",
        units_shipped=1000,
        ship_period_code="2022-Q3",
        warranty_expiry_date="2028-12-31",
    )

    reserve = create_liability_reserve(
        api,
        period["id"],
        family["id"],
        reported_claim_count=100,
        asserted_case_reserve_cents=5000000,
        reporting_lag_months=24,
        severity_trend_bps=-2000,
    )

    assert reserve["lag_factor_bps"] == 6000
    assert reserve["avg_case_severity_cents"] == 50000
    assert reserve["ibnr_claim_count"] == 60
    assert reserve["ibnr_reserve_cents"] == 2400000
    assert reserve["total_liability_reserve_cents"] == 7400000


def test_an_adequacy_ratio_of_exactly_eighty_percent_is_redundant(api):
    """The inclusive upper bound puts 8000 bps in the release tier.

    PRD §3.4: "A ratio of 8000 basis points or less means claims are running at eighty
    percent of expectation or better, so `trend_adjustment_bps` becomes -1000 and
    `adequacy_status` becomes `REDUNDANT` ... Every threshold is an inclusive upper bound, so
    a ratio of exactly 8000 is `REDUNDANT`." PRD §3.4 gives step seven:
    "`recommended_true_up_cents` is ... `adjusted_remaining_cents` less
    `remaining_base_cents` ... plus the amount by which actuals have already diverged from
    expectation, that is `actual_paid_cents` less `expected_to_date_cents`."

    Design: Corner/calculations/corner_adequacy_ratio_exactly_eighty_percent_selects_redundant_tier
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = _analog_basis(api)
    family = create_family(
        api,
        family_code="FAM-AD",
        name="Adequacy Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=20000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    accrued_vintage = create_vintage(
        api,
        family["id"],
        vintage_code="AD-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    paid_vintage = create_vintage(
        api,
        family["id"],
        vintage_code="AD-MY2025",
        units_shipped=1200,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-12-31",
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-AD-01",
        description="Adequacy platform pump failure",
        severity="FUNCTIONAL",
        cost_per_claim_cents=30000,
    )
    create_observation(
        api,
        paid_vintage["id"],
        mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=9,
        claim_count=20,
        paid_cost_cents=465600,
    )
    accrual = create_accrual(
        api,
        period["id"],
        accrued_vintage["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
    )
    propose_accrual(api, accrual["id"])
    lock_period(api, period["id"])
    post_accrual(api, accrual["id"])

    review = create_adequacy_review(api, period["id"], family["id"])

    assert review["expected_to_date_cents"] == 582000
    assert review["actual_paid_cents"] == 465600
    assert review["ave_ratio_bps"] == 8000
    assert review["trend_adjustment_bps"] == -1000
    assert review["adequacy_status"] == "REDUNDANT"
    assert review["remaining_base_cents"] == 2328000
    assert review["adjusted_remaining_cents"] == 2095200
    assert review["recommended_true_up_cents"] == -349200

    applied = apply_true_up(api, review["id"])
    assert applied["true_up_applied"] is True
    assert applied["applied_by_user_id"] == RESERVE_CONTROLLER_USER_ID

    family_now = read_family(api, family["id"])
    assert family_now["warranty_reserve_balance_cents"] == 2560800
    assert family_now["reserve_posture"] == "NORMAL"


def test_the_two_recognition_variants_diverge_on_identical_terms(api):
    """Straight-line and the front-loaded curve part company at the 2500 bps boundary.

    PRD §3.6: "Because the curve recognizes a tenth of the contract immediately —
    infant-mortality claims arrive early — the two methods return different
    `recognized_revenue_cents` and different `deferred_revenue_cents` for an identical price,
    term, sold date and clock position", and "Each bucket's upper bound is inclusive, so an
    elapsed fraction of exactly 2500 recognizes 1000 basis points". PRD §3.6 also keeps the
    ledgers apart: "no service contract ever affects the warranty reserve."

    Design: Corner/calculations/corner_service_contract_variants_diverge_on_identical_terms
    """
    family = create_family(
        api,
        family_code="FAM-VD",
        name="Variant Divergence Platform",
        launch_date="2024-01-01",
        base_warranty_months=12,
        standard_cost_per_claim_cents=8000,
        reserve_cap_cents=10000000,
    )

    straight_line = create_service_contract(
        api,
        family["id"],
        contract_number="SC-VD-SL",
        sold_date="2026-02-01",
        term_months=24,
        total_contract_price_cents=480000,
        recognition_method="STRAIGHT_LINE",
    )
    claims_pattern = create_service_contract(
        api,
        family["id"],
        contract_number="SC-VD-CP",
        sold_date="2026-02-01",
        term_months=24,
        total_contract_price_cents=480000,
        recognition_method="CLAIMS_PATTERN",
    )

    assert straight_line["status"] == "ACTIVE"
    assert claims_pattern["status"] == "ACTIVE"
    assert straight_line["months_elapsed"] == 6
    assert claims_pattern["months_elapsed"] == 6

    assert straight_line["recognized_revenue_cents"] == 120000
    assert straight_line["deferred_revenue_cents"] == 360000
    assert claims_pattern["recognized_revenue_cents"] == 48000
    assert claims_pattern["deferred_revenue_cents"] == 432000
    assert (
        straight_line["recognized_revenue_cents"] - claims_pattern["recognized_revenue_cents"]
        == 72000
    )

    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 0


def test_the_contractual_cap_clamps_the_expected_value_recovery(api):
    """A thin purchase volume caps the receivable far below its probability weighting.

    PRD §3.7: "Both variants first compute a contractual ceiling: multiply the supplier's
    `annual_purchase_volume_cents` by its `contractual_recovery_cap_bps`, divide by 10000, and
    round to the nearest integer", and "Multiply `asserted_amount_cents` by that weighting,
    divide by 10000, round to the nearest integer, and then take the lesser of that figure and
    the contractual ceiling ... Rounding happens before the ceiling comparison, not after."
    PRD §3.7 also fixes the birth valuation: "it is valued immediately on creation under the
    `EXPECTED_VALUE` variant".

    Design: Corner/calculations/corner_supplier_recovery_contractual_cap_clamps_expected_value
    """
    supplier = create_supplier(
        api,
        supplier_code="SUP-CP",
        name="Cap Components Ltd",
        credit_rating="AAA",
        annual_purchase_volume_cents=10000000,
        contractual_recovery_cap_bps=500,
    )
    family = create_family(
        api,
        family_code="FAM-CP",
        name="Cap Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=14000,
        reserve_cap_cents=20000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-CP-01",
        description="Capped component fault",
        severity="FUNCTIONAL",
        cost_per_claim_cents=14000,
        supplier_id=supplier["id"],
    )

    recovery = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=2000000
    )

    assert recovery["valuation_variant"] == "EXPECTED_VALUE"
    assert recovery["collectability_rating_at_valuation"] == "HIGH"
    assert recovery["recognized_recovery_cents"] == 500000

    asserted = success_data(api.assert_recovery(ANALYST_HEADERS, recovery["id"]))
    assert asserted["recognized_recovery_cents"] == 500000

    supplier_now = read_supplier(api, supplier["id"])
    assert supplier_now["gross_asserted_recovery_cents"] == 2000000
    assert supplier_now["open_recovery_asset_cents"] == 500000


def test_the_booking_period_selector_skips_a_period_in_actuarial_review(api):
    """The lexically greatest period loses because its status is ineligible.

    PRD §3.1: "Its candidate set is every accrual period whose status is `OPEN` or
    `ANALYSIS_LOCKED`; periods in `ACTUARIAL_REVIEW` and `CLOSED` are excluded outright.
    Candidates are ranked by `period_code` descending, so the chronologically latest
    still-bookable period wins." PRD §3.1 also bounds the disclosure counter: it counts
    field actions "whose `specific_accrual_cents` is at least 50,000,000 cents".

    Design: Corner/calculations/corner_booking_period_selector_skips_periods_in_actuarial_review
    """
    create_period(api, "2026-Q2", "2026-04-01", "2026-06-30")
    winner = create_period(api, "2026-Q4", "2026-10-01", "2026-12-31")
    excluded = create_period(api, "2027-Q1", "2027-01-01", "2027-03-31")
    lock_period(api, excluded["id"])
    open_review(api, excluded["id"])

    family = create_family(
        api,
        family_code="FAM-BP",
        name="Booking Period Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=16000,
        reserve_cap_cents=40000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-BP-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-02-28",
        affected_unit_count=500,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-BP-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, action["id"])

    approved = decide_field_action(api, action["id"], "APPROVED")

    assert approved["approval_state"] == "APPROVED"
    assert approved["approved_period_id"] == winner["id"]
    assert approved["specific_accrual_cents"] == 5350000

    booked_period = read_period(api, winner["id"])
    assert booked_period["significant_exposure_count"] == 0
    assert booked_period["requires_significant_exposure_disclosure"] is False


def test_the_implicit_remedy_selector_ranks_by_cost_then_take_rate(api):
    """Two filters remove candidates and the take-rate tie-break settles the rest.

    PRD §3.5: "The eligibility filter admits remedy options belonging to this action whose
    `is_engineering_approved` is true, whose `expected_take_rate_bps` is at least 1, and —
    when the action's `is_safety_recall` is true — whose `remedy_class` is
    `PERMANENT_REPAIR`; when `is_safety_recall` is false, the remedy class is unrestricted.
    Surviving candidates are ranked by `per_unit_expected_cents` ascending ... Ties are broken
    by `expected_take_rate_bps` ascending, and any remaining tie by `created_at` ascending;
    the row identifier is never a ranking or tie-break input."

    Design: Corner/calculations/corner_remedy_selector_ranks_by_per_unit_cost_then_take_rate
    """
    family = create_family(
        api,
        family_code="FAM-RS",
        name="Remedy Selector Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=40000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-RS-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-03-31",
        affected_unit_count=2000,
    )
    unapproved = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-RS-A",
        remedy_class="PART_REPLACEMENT",
        parts_cost_cents=100,
        labor_hours_centi=0,
        admin_cost_cents=0,
        expected_take_rate_bps=5000,
        is_engineering_approved=False,
    )
    zero_take = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-RS-B",
        remedy_class="INTERIM_REPAIR",
        parts_cost_cents=500,
        labor_hours_centi=0,
        admin_cost_cents=0,
        expected_take_rate_bps=0,
        is_engineering_approved=True,
    )
    tie_winner = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-RS-C",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=6000,
        labor_hours_centi=0,
        admin_cost_cents=0,
        expected_take_rate_bps=5000,
        is_engineering_approved=True,
    )
    tie_loser = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-RS-D",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=3000,
        labor_hours_centi=0,
        admin_cost_cents=0,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )

    selected = select_remedy(api, action["id"], expected_field_action_version=1)

    assert selected["selected_remedy_option_id"] == tie_winner["id"]
    assert selected["selected_remedy_option_id"] != unapproved["id"]
    assert selected["selected_remedy_option_id"] != zero_take["id"]
    assert selected["selected_remedy_option_id"] != tie_loser["id"]
    assert selected["specific_accrual_cents"] == 6000000
    assert selected["version"] == 2

    options, meta = _remedy_options(api, action["id"])
    assert meta["total_count"] == 4
    chosen = [row for row in options if row["id"] == tie_winner["id"]][0]
    assert chosen["per_unit_expected_cents"] == 3000


def test_only_completed_execution_reduces_the_family_balance(api):
    """Incurred cost accumulates on the row long before it enters the ledger.

    PRD §2.10: "field actions in `DRAFT`, `SUBMITTED` or `REJECTED` contribute nothing to the
    approved campaign total". PRD §3.5: "each progress call adds the supplied
    `incurred_cost_cents` to the action's running `executed_cost_cents` ... Reaching
    `COMPLETED` is also a ledger event: because the completed action's `executed_cost_cents`
    now enters the deduction term of the family reserve, the family's
    `warranty_reserve_balance_cents` is recomputed in full and its `reserve_posture` is then
    re-derived."

    Design: Corner/calculations/corner_only_completed_execution_reduces_the_family_balance
    """
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-EX",
        name="Execution Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=30000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-EX-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-03-31",
        affected_unit_count=1000,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-EX-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=2000,
        labor_hours_centi=100,
        admin_cost_cents=500,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, action["id"])
    decide_field_action(api, action["id"], "APPROVED")

    after_approval = read_family(api, family["id"])
    assert after_approval["warranty_reserve_balance_cents"] == 12000000
    assert after_approval["reserve_posture"] == "NORMAL"

    in_progress = success_data(
        api.execution_progress(
            ENGINEER_HEADERS,
            action["id"],
            to_execution_state="IN_PROGRESS",
            incurred_cost_cents=1000000,
        )
    )
    assert in_progress["execution_state"] == "IN_PROGRESS"
    assert in_progress["executed_cost_cents"] == 1000000
    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 12000000

    completed = success_data(
        api.execution_progress(
            ENGINEER_HEADERS,
            action["id"],
            to_execution_state="COMPLETED",
            incurred_cost_cents=500000,
        )
    )
    assert completed["execution_state"] == "COMPLETED"
    assert completed["executed_cost_cents"] == 1500000

    family_now = read_family(api, family["id"])
    assert family_now["warranty_reserve_balance_cents"] == 10500000
    assert family_now["reserve_posture"] == "NORMAL"


def test_realization_of_exactly_seventy_five_hundred_bps_holds_the_base_rating(api):
    """The hold threshold is inclusive, so 7500 does not cost a notch.

    PRD §3.7: "when `realization_bps` is at least 7500 the base rating stands; otherwise, when
    `realization_bps` is at least 4000 the base rating is downgraded by one notch; and in every
    remaining case the base rating is downgraded by two notches." The same subsection defines
    the ratio: "let the denominator be `realized_recovery_cents` plus
    `written_off_recovery_cents` ... `realization_bps` is `realized_recovery_cents` multiplied
    by 10000, divided by that denominator, rounded to the nearest integer."

    Design: Corner/calculations/corner_realization_exactly_seventy_five_hundred_bps_holds_base_rating
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    supplier = create_supplier(
        api,
        supplier_code="SUP-RZ",
        name="Realization Components SA",
        credit_rating="AAA",
        annual_purchase_volume_cents=1000000000,
        contractual_recovery_cap_bps=2000,
    )
    family = create_family(
        api,
        family_code="FAM-RZ",
        name="Realization Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=20000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-RZ-01",
        description="Sourced pump defect",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier["id"],
    )
    settled_claim = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=4000000
    )
    written_off_claim = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=1000000
    )
    success_data(api.assert_recovery(ANALYST_HEADERS, settled_claim["id"]))
    success_data(api.assert_recovery(ANALYST_HEADERS, written_off_claim["id"]))

    settled = success_data(
        api.close_recovery(
            CONTROLLER_HEADERS,
            settled_claim["id"],
            outcome="SETTLED",
            settled_amount_cents=3000000,
        )
    )
    assert settled["status"] == "SETTLED"
    assert settled["valuation_variant"] == "CONTRACTUAL_FLOOR"
    assert settled["recognized_recovery_cents"] == 3000000
    assert settled["settled_period_id"] == period["id"]

    after_first = read_supplier(api, supplier["id"])
    assert after_first["realized_recovery_cents"] == 3000000
    assert after_first["written_off_recovery_cents"] == 0
    assert after_first["closed_recovery_count"] == 1
    assert after_first["realization_bps"] == 10000
    assert after_first["collectability_rating"] == "HIGH"

    success_data(
        api.close_recovery(CONTROLLER_HEADERS, written_off_claim["id"], outcome="WRITTEN_OFF")
    )
    written_off = read_recovery(api, written_off_claim["id"])
    assert written_off["status"] == "WRITTEN_OFF"
    assert written_off["recognized_recovery_cents"] == 0

    supplier_now = read_supplier(api, supplier["id"])
    assert supplier_now["written_off_recovery_cents"] == 1000000
    assert supplier_now["closed_recovery_count"] == 2
    assert supplier_now["realization_bps"] == 7500
    assert supplier_now["collectability_rating"] == "HIGH"
    assert supplier_now["gross_asserted_recovery_cents"] == 5000000
    assert supplier_now["open_recovery_asset_cents"] == 0


def test_the_rollforward_composes_every_disclosure_component(api):
    """Each movement figure carries its own scope key and status filter.

    PRD §3.9: "`accruals_cents` is the sum of `accrued_amount_cents` over warranty accruals
    whose `period_id` is this period and whose status is `POSTED`. `campaign_accruals_cents`
    is the sum of `specific_accrual_cents` over field actions whose `approved_period_id` is
    this period and whose `approval_state` is `APPROVED` ... `claims_paid_cents` is the sum of
    `paid_cost_cents` over claim observations whose `observation_period_code` equals this
    period's `period_code`." PRD §3.9 also fixes the chain: "`beginning_balance_cents` is that
    prior snapshot's `ending_balance_cents`, or 0 when no such prior snapshot exists."

    Design: Corner/calculations/corner_rollforward_composes_all_six_disclosure_components
    """
    create_period(api, "2025-Q4", "2025-10-01", "2025-12-31")
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = _analog_basis(api, observation_period_code="2025-Q4")
    family = create_family(
        api,
        family_code="FAM-RF",
        name="Rollforward Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=40000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    accrued_vintage = create_vintage(
        api,
        family["id"],
        vintage_code="RF-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    paid_vintage = create_vintage(
        api,
        family["id"],
        vintage_code="RF-MY2025",
        units_shipped=1200,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-12-31",
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-RF-01",
        description="Rollforward platform valve leak",
        severity="FUNCTIONAL",
        cost_per_claim_cents=30000,
    )
    create_observation(
        api,
        paid_vintage["id"],
        mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=9,
        claim_count=20,
        paid_cost_cents=465600,
    )
    accrual = create_accrual(
        api,
        period["id"],
        accrued_vintage["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
    )
    propose_accrual(api, accrual["id"])
    lock_period(api, period["id"])
    post_accrual(api, accrual["id"])

    action = create_field_action(
        api,
        family["id"],
        action_code="FA-RF-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-02-28",
        affected_unit_count=500,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-RF-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, action["id"])
    decide_field_action(api, action["id"], "APPROVED")
    assert read_field_action(api, action["id"])["approved_period_id"] == period["id"]

    rollforward = generate_rollforward(api, period["id"])

    assert rollforward["beginning_balance_cents"] == 0
    assert rollforward["accruals_cents"] == 2910000
    assert rollforward["campaign_accruals_cents"] == 5350000
    assert rollforward["claims_paid_cents"] == 465600
    assert rollforward["changes_in_estimate_cents"] == 0
    assert rollforward["supplier_recoveries_cents"] == 0
    assert rollforward["ending_balance_cents"] == 7794400
    assert rollforward["significant_exposure_count"] == 0
    assert rollforward["generated_by_user_id"] == RESERVE_CONTROLLER_USER_ID
    assert_rollforward_identity(rollforward)

    assert read_period(api, period["id"])["rollforward_generated"] is True
