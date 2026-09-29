"""The ninety-percent asset test: valuation variant, ratio boundary, certification."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_asset_test_measurement,
    assert_common_fields,
    assert_fund_aggregates,
    assert_fund_state,
    assert_money,
    assert_noncompliance_months_conserved,
    assert_percent,
)
from test_helpers.factories import OMIT, create_asset_test_payload
from test_helpers.fixtures import (
    certify_asset_test,
    list_fund_penalty_assessments,
    make_asset_test,
    make_fund_asset,
    make_self_certified_fund,
    measure_asset_test,
    read_asset_test,
    read_fund,
)
from test_helpers.test_users import (
    CERTIFIER_HEADERS,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
    OFFICER_MEASURER_USER_ID,
)


def _fund_with_two_assets(api, qualified_basis, qualified_afs, cash_basis, cash_afs):
    """A self-certified fund holding one qualified and one nonqualified row."""
    fund = make_self_certified_fund(api, asset_test_valuation_method="UNADJUSTED_COST_BASIS")
    qualified = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-15T00:00:00Z",
        unadjusted_cost_basis=qualified_basis,
        afs_fair_value=qualified_afs,
        original_use_in_zone=True,
    )
    cash = make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-15T00:00:00Z",
        unadjusted_cost_basis=cash_basis,
        afs_fair_value=cash_afs,
    )
    return fund, qualified, cash


def test_cost_basis_valuation_variant_fails_the_ninety_percent_test(api):
    """
    "Each included asset contributes a value chosen by the test's
    `valuation_method`: its `unadjusted_cost_basis` under `UNADJUSTED_COST_BASIS`,
    its `afs_fair_value` under `APPLICABLE_FINANCIAL_STATEMENT`." Carried at cost,
    850000.00 qualified against 150000.00 nonqualified, "the ratio is 85.0000 and
    the test **fails** with a `shortfall_amount` of 50000.00."

    Design: Difficulty/dual_variant_calc/asset_test_valuation_variant_divergence
    """
    fund, _qualified, _cash = _fund_with_two_assets(
        api, 850000.00, 950000.00, 150000.00, 50000.00
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
        valuation_method_override="UNADJUSTED_COST_BASIS",
    )
    measured = measure_asset_test(api, test["id"], MEASURER_HEADERS)

    assert_asset_test_measurement(
        measured,
        valuation_method="UNADJUSTED_COST_BASIS",
        included_asset_count=2,
        qualified_numerator=850000.00,
        total_denominator=1000000.00,
        ratio_pct=85.0000,
        result="FAIL",
        shortfall_amount=50000.00,
        failed_month_count=6,
    )
    # Measurement alone certifies nothing.
    assert_fund_state(read_fund(api, fund["id"]), compliance_posture="UNTESTED")


def test_financial_statement_variant_passes_on_the_identical_asset_rows(api):
    """
    "Carried on the applicable financial statement, the same two rows at 950000.00
    and 50000.00 produce 95.0000 and the test **passes** with a `shortfall_amount`
    of 0.00." "The test's own `valuation_method` is resolved once at creation: the
    override when one is supplied, otherwise the fund's
    `asset_test_valuation_method` as of that moment."

    Design: Difficulty/dual_variant_calc/asset_test_valuation_variant_divergence
    """
    fund, _qualified, _cash = _fund_with_two_assets(
        api, 850000.00, 950000.00, 150000.00, 50000.00
    )
    cost_test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
        valuation_method_override="UNADJUSTED_COST_BASIS",
    )
    afs_test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-12-31T00:00:00Z",
        period_start="2026-07-01T00:00:00Z",
        period_end="2027-01-01T00:00:00Z",
        valuation_method_override="APPLICABLE_FINANCIAL_STATEMENT",
    )
    cost_measured = measure_asset_test(api, cost_test["id"], MEASURER_HEADERS)
    afs_measured = measure_asset_test(api, afs_test["id"], MEASURER_HEADERS)

    assert_asset_test_measurement(
        afs_measured,
        valuation_method="APPLICABLE_FINANCIAL_STATEMENT",
        included_asset_count=2,
        qualified_numerator=950000.00,
        total_denominator=1000000.00,
        ratio_pct=95.0000,
        result="PASS",
        shortfall_amount=0.00,
        failed_month_count=0,
    )
    assert cost_measured["result"] != afs_measured["result"], (
        "The valuation variant must flip the verdict over an identical asset set"
    )


def test_ratio_exactly_ninety_percent_passes_the_asset_test(api):
    """
    "`result` is `PASS` when `ratio_pct` is at least 90.0000 and `FAIL` otherwise,
    compared against the rounded four-decimal figure." "On a pass,
    `shortfall_amount` is 0.00; on a fail it is `total_denominator` multiplied by 0.90,
    less `qualified_numerator`, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/asset_test_ratio_exactly_ninety_passes
    """
    fund, _qualified, _cash = _fund_with_two_assets(
        api, 900000.00, 900000.00, 100000.00, 100000.00
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    measured = measure_asset_test(api, test["id"], MEASURER_HEADERS)

    assert_asset_test_measurement(
        measured,
        included_asset_count=2,
        total_denominator=1000000.00,
        ratio_pct=90.0000,
        result="PASS",
        shortfall_amount=0.00,
        failed_month_count=0,
    )


def test_ratio_one_hundredth_of_a_point_below_ninety_fails_with_a_shortfall(api):
    """
    "**Percentages and fractions** are carried to exactly 4 decimal places and
    rounded half up", and "on a fail it is `total_denominator` multiplied by 0.90,
    less `qualified_numerator`, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/asset_test_ratio_exactly_ninety_passes
    """
    fund, _qualified, _cash = _fund_with_two_assets(
        api, 899900.00, 899900.00, 100100.00, 100100.00
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    measured = measure_asset_test(api, test["id"], MEASURER_HEADERS)

    assert_asset_test_measurement(
        measured,
        included_asset_count=2,
        total_denominator=1000000.00,
        ratio_pct=89.9900,
        result="FAIL",
        shortfall_amount=100.00,
        failed_month_count=6,
    )
    assert_percent(measured["ratio_pct"], 89.9900, "AssetTest.ratio_pct")


def test_segregation_of_duties_outranks_the_terminal_state_bar(api):
    """
    "On either certification call — the asset test's or the business test's — the
    caller's `X-User-ID` must differ from the `measured_by_user_id` recorded on the
    target test when it was measured. If they are equal, the request is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), even when the caller holds the
    `ComplianceOfficer` role."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_terminal_check
    """
    fund = make_self_certified_fund(api)
    make_fund_asset(
        api,
        fund["id"],
        acquisition_date="2026-01-10T00:00:00Z",
        unadjusted_cost_basis=1000000.00,
        afs_fair_value=1000000.00,
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    measure_asset_test(api, test["id"], MEASURER_HEADERS)
    certified = certify_asset_test(api, test["id"], CERTIFIER_HEADERS)
    assert certified["status"] == "CERTIFIED_PASS"

    # The measurer re-certifies an already terminal test: both rules are violated.
    response = api.certify_asset_test(test["id"], None, MEASURER_HEADERS)
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)


def test_refused_recertification_leaves_the_certified_test_untouched(api):
    """
    "a request that fails any check in §2.11 mutates nothing." "A `PASS` produces
    `MEASURED → CERTIFIED_PASS`, records `certified_by_user_id`, drives the fund's
    `compliance_posture` to `COMPLIANT` — `UNTESTED → COMPLIANT` on a fund that has
    never been tested — and resets `consecutive_failed_tests` to 0."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_terminal_check
    """
    fund = make_self_certified_fund(api)
    make_fund_asset(
        api,
        fund["id"],
        acquisition_date="2026-01-10T00:00:00Z",
        unadjusted_cost_basis=1000000.00,
        afs_fair_value=1000000.00,
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    measure_asset_test(api, test["id"], MEASURER_HEADERS)
    certified = certify_asset_test(api, test["id"], CERTIFIER_HEADERS)
    certifier = certified["certified_by_user_id"]

    api.certify_asset_test(test["id"], None, MEASURER_HEADERS)

    after = read_asset_test(api, test["id"])
    assert after["status"] == "CERTIFIED_PASS"
    assert after["result"] == "PASS"
    assert after["certified_by_user_id"] == certifier
    fund_after = read_fund(api, fund["id"])
    assert_fund_state(fund_after, compliance_posture="COMPLIANT")
    assert fund_after["consecutive_failed_tests"] == 0


def test_a_freshly_opened_test_sits_in_draft_with_every_figure_unmeasured(api):
    """
    "The test's own `valuation_method` is resolved once at creation: the override when
    one is supplied, otherwise the fund's `asset_test_valuation_method` as of that
    moment. The test is created in `status` `DRAFT` with `result` `PENDING`,
    `qualified_numerator` and `total_denominator` at 0.00, `ratio_pct` at 0.0000,
    `included_asset_count` at 0, `shortfall_amount` at 0.00 and `failed_month_count`
    at 0."

    Design: Corner/state_machines/asset_test_created_in_draft_initial_state
    """
    fund = make_self_certified_fund(api, name="Initial State Fund")
    assert fund["asset_test_valuation_method"] == "UNADJUSTED_COST_BASIS"

    response = api.create_asset_test(
        fund["id"],
        create_asset_test_payload(
            measurement_date="2026-06-30T00:00:00Z",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )

    test = validate_success(response, 201)

    assert test["status"] == "DRAFT"
    assert_common_fields(test, "AssetTest")
    assert test["version"] == 1
    assert_asset_test_measurement(
        test,
        qualified_numerator=0.00,
        total_denominator=0.00,
        ratio_pct=0.0000,
        result="PENDING",
        shortfall_amount=0.00,
        failed_month_count=0,
        included_asset_count=0,
        valuation_method="UNADJUSTED_COST_BASIS",
    )
    assert not test["measured_by_user_id"]
    assert not test["certified_by_user_id"]
    fund_after = read_fund(api, fund["id"])
    assert fund_after["compliance_posture"] == "UNTESTED"
    assert not fund_after["last_test_measurement_date"]


def test_a_second_measurement_of_the_same_test_is_an_undeclared_transition(api):
    """
    "Measuring a test moves it `DRAFT → MEASURED`". "The target is in a non-terminal
    state from which the requested transition is declared —
    `ERR_INVALID_STATE_TRANSITION` (409)." "a request that fails any check in §2.11
    mutates nothing."

    Design: Corner/state_machines/asset_test_measure_twice_rejected
    """
    fund = make_self_certified_fund(api, name="Remeasure Fund")
    make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-10T00:00:00Z",
        unadjusted_cost_basis=1000000.00,
        afs_fair_value=1000000.00,
        original_use_in_zone=True,
    )
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    first = measure_asset_test(api, test["id"], MEASURER_HEADERS)
    assert first["status"] == "MEASURED"
    assert_percent(first["ratio_pct"], 100.0000, "ratio_pct")

    response = api.measure_asset_test(test["id"], None, MEASURER_HEADERS)

    validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)
    after = read_asset_test(api, test["id"])
    assert after["status"] == "MEASURED"
    assert after["result"] == "PASS"
    assert_percent(after["ratio_pct"], 100.0000, "ratio_pct")
    assert after["version"] == 2
    assert after["measured_by_user_id"] == OFFICER_MEASURER_USER_ID
    assert not after["certified_by_user_id"]
    assert read_fund(api, fund["id"])["compliance_posture"] == "UNTESTED"


def _afs_default_fund(api):
    """A fund defaulting to AFS valuation, holding one qualified and one cash row."""
    fund = make_self_certified_fund(
        api,
        name="Selection Fund",
        entity_type="CORPORATION",
        asset_test_valuation_method="APPLICABLE_FINANCIAL_STATEMENT",
    )
    make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-10T00:00:00Z",
        unadjusted_cost_basis=800000.00,
        afs_fair_value=950000.00,
        original_use_in_zone=True,
    )
    make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-10T00:00:00Z",
        unadjusted_cost_basis=200000.00,
        afs_fair_value=50000.00,
    )
    return fund


def test_the_valuation_method_is_frozen_at_creation_not_at_measurement(api):
    """
    "The test's own `valuation_method` is resolved once at creation: the override when
    one is supplied, otherwise the fund's `asset_test_valuation_method` as of that
    moment." "Each included asset contributes a value chosen by the test's
    `valuation_method`: its `unadjusted_cost_basis` under `UNADJUSTED_COST_BASIS`, its
    `afs_fair_value` under `APPLICABLE_FINANCIAL_STATEMENT`." "on a fail it is
    `total_denominator` multiplied by 0.90, less `qualified_numerator`, rounded half up
    to two decimal places."

    Design: Corner/calculations/asset_test_valuation_method_resolved_at_creation_from_fund_default
    """
    fund = _afs_default_fund(api)

    inherited = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    overridden = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-12-31T00:00:00Z",
        period_start="2026-07-01T00:00:00Z",
        period_end="2027-01-01T00:00:00Z",
        valuation_method_override="UNADJUSTED_COST_BASIS",
    )

    assert inherited["valuation_method"] == "APPLICABLE_FINANCIAL_STATEMENT"
    assert overridden["valuation_method"] == "UNADJUSTED_COST_BASIS"

    measured_inherited = measure_asset_test(api, inherited["id"], MANAGER_HEADERS)
    measured_overridden = measure_asset_test(api, overridden["id"], MANAGER_HEADERS)

    assert_asset_test_measurement(
        measured_inherited,
        qualified_numerator=950000.00,
        total_denominator=1000000.00,
        ratio_pct=95.0000,
        result="PASS",
        shortfall_amount=0.00,
        included_asset_count=2,
        valuation_method="APPLICABLE_FINANCIAL_STATEMENT",
    )
    assert_asset_test_measurement(
        measured_overridden,
        qualified_numerator=800000.00,
        total_denominator=1000000.00,
        ratio_pct=80.0000,
        result="FAIL",
        shortfall_amount=100000.00,
        failed_month_count=6,
        included_asset_count=2,
        valuation_method="UNADJUSTED_COST_BASIS",
    )
    assert (
        read_asset_test(api, inherited["id"])["valuation_method"]
        == "APPLICABLE_FINANCIAL_STATEMENT"
    )
    fund_after = read_fund(api, fund["id"])
    assert fund_after["last_test_measurement_date"].startswith("2026-12-31T00:00:00")
    assert_money(
        fund_after["aggregate_qualified_afs_value"], 950000.00, "aggregate_qualified_afs_value"
    )


def test_every_derived_figure_is_readable_in_the_very_next_request(api):
    """
    "Its initial `qualification` is derived, not supplied, and there are four cases:
    `QOZ_BUSINESS_PROPERTY` with `original_use_in_zone` true is `QUALIFIED` immediately"
    "`NONQUALIFIED_FINANCIAL_PROPERTY` and `CASH` are always `NONQUALIFIED`."
    "Registration then recomputes all four fund aggregates."
    "`monthly_penalty_amount` is `shortfall_amount` multiplied by an annual underpayment
    rate of 0.08 and divided by 12, rounded half up to the cent **first**."

    Design: Corner/consistency_model/fund_ledger_and_test_results_are_immediately_readable
    """
    fund = make_self_certified_fund(
        api,
        name="Immediate Ledger QOF",
        entity_type="CORPORATION",
        asset_test_valuation_method="UNADJUSTED_COST_BASIS",
    )
    qualified_asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=800000.00,
        afs_fair_value=800000.00,
        original_use_in_zone=True,
    )
    nonqualified_asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="NONQUALIFIED_FINANCIAL_PROPERTY",
        acquisition_date="2026-01-06T00:00:00Z",
        unadjusted_cost_basis=200000.00,
        afs_fair_value=200000.00,
        original_use_in_zone=OMIT,
    )
    assert qualified_asset["qualification"] == "QUALIFIED"
    assert nonqualified_asset["qualification"] == "NONQUALIFIED"

    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=1000000.00,
        aggregate_qualified_basis=800000.00,
        aggregate_afs_value=1000000.00,
        aggregate_qualified_afs_value=800000.00,
    )

    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    assert test["valuation_method"] == "UNADJUSTED_COST_BASIS"

    measured = measure_asset_test(api, test["id"], MANAGER_HEADERS)
    assert_asset_test_measurement(
        measured,
        qualified_numerator=800000.00,
        total_denominator=1000000.00,
        ratio_pct=80.0000,
        result="FAIL",
        shortfall_amount=100000.00,
        failed_month_count=6,
        included_asset_count=2,
    )

    certified = certify_asset_test(api, test["id"], CERTIFIER_HEADERS)
    assert certified["status"] == "CERTIFIED_FAIL"

    assessments = list_fund_penalty_assessments(api, fund["id"])
    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment["status"] == "ASSESSED"
    assert assessment["asset_test_id"] == test["id"]
    assert assessment["failed_month_count"] == 6
    assert_money(assessment["shortfall_amount"], 100000.00, "shortfall_amount")
    assert_money(assessment["monthly_penalty_amount"], 666.67, "monthly_penalty_amount")
    assert_money(assessment["gross_penalty_amount"], 4000.02, "gross_penalty_amount")
    assert_money(assessment["cure_credit_amount"], 0.00, "cure_credit_amount")
    assert_money(assessment["net_penalty_amount"], 4000.02, "net_penalty_amount")

    fund_after = read_fund(api, fund["id"])
    assert fund_after["cumulative_penalty_months"] == 6
    assert fund_after["consecutive_failed_tests"] == 1
    assert_fund_state(fund_after, compliance_posture="DEFICIENT")
    assert_noncompliance_months_conserved(fund_after, assessments)
