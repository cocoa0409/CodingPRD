"""The QOZB three-prong test: the composite safe harbour and the certify fork."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_business_test_prongs,
    assert_fund_aggregates,
    assert_fund_state,
    assert_money,
    assert_percent,
)
from test_helpers.factories import (
    measure_business_test_payload,
    reported_figures_payload,
)
from test_helpers.fixtures import (
    certify_business_test,
    make_business_test,
    make_fund_asset,
    make_qoz_business,
    make_self_certified_fund,
    measure_business_test,
    read_business_test,
    read_fund,
    read_fund_asset,
    read_qoz_business,
)
from test_helpers.test_users import (
    CERTIFIER_HEADERS,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
)


def test_the_management_and_tangible_branch_takes_the_smaller_component(api):
    """
    "Under `MANAGEMENT_AND_TANGIBLE` it is a composite of three inputs: a management
    component equal to `intangibles_zone_use_amount` divided by
    `intangibles_total_amount` times 100 rounded half up to four decimal places
    (0.0000 when `intangibles_total_amount` is 0.00); a tangible component equal to
    `total_asset_value_measured` less `nqfp_amount_measured`, divided by
    `total_asset_value_measured`, times 100 and rounded half up to four decimal
    places; and then the **smaller** of those two components multiplied by a
    safe-harbor credit of 1.25, rounded half up to four decimal places, and finally
    capped so the result can never exceed 100.0000."

    Design: Difficulty/combinatorial_formula/qozb_management_and_tangible_nested_min_composite
    """
    fund = make_self_certified_fund(api)
    business = make_qoz_business(
        api,
        fund["id"],
        zone_tract_code="12345678901",
        declared_nqfp_amount=40000.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=900000.00,
    )
    test = make_business_test(api, business["id"], testing_date="2026-06-30T00:00:00Z")

    measured = measure_business_test(
        api,
        test["id"],
        MEASURER_HEADERS,
        safe_harbor_used="MANAGEMENT_AND_TANGIBLE",
        gross_income_zone_amount=800000.00,
        gross_income_total_amount=1000000.00,
        intangibles_zone_use_amount=30000.00,
        intangibles_total_amount=100000.00,
        total_asset_value_measured=1000000.00,
    )

    assert measured["status"] == "MEASURED"
    assert_money(measured["nqfp_amount_measured"], 40000.00, "nqfp_amount_measured")
    assert_business_test_prongs(
        measured,
        gross_income_pct=37.5000,
        intangibles_pct=30.0000,
        nqfp_pct=4.0000,
        gross_income_prong="FAIL",
        intangibles_prong="FAIL",
        nqfp_prong="PASS",
    )
    # Neither the raw gross-income ratio nor the uncredited management component.
    assert float(measured["gross_income_pct"]) != 80.0000
    assert float(measured["gross_income_pct"]) != 100.0000


def test_a_passing_nqfp_ceiling_with_two_failed_prongs_only_warns_the_business(api):
    """
    "If `nqfp_prong` is `PASS` but at least one of `gross_income_prong` and
    `intangibles_prong` is `FAIL`, and the business's
    `consecutive_failed_business_tests` stood at 0 before this certification, the
    business moves `UNTESTED → AT_RISK` (or `AT_RISK → DISQUALIFIED` on a second
    failure, below) with the counter set to 1. `AT_RISK` is a warning posture only:
    **no** asset's `qualification` changes and no fund aggregate moves."

    Design: Difficulty/combinatorial_formula/qozb_management_and_tangible_nested_min_composite
    """
    fund = make_self_certified_fund(api)
    business = make_qoz_business(
        api,
        fund["id"],
        zone_tract_code="12345678901",
        declared_nqfp_amount=40000.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=900000.00,
    )
    test = make_business_test(api, business["id"], testing_date="2026-06-30T00:00:00Z")
    measure_business_test(
        api,
        test["id"],
        MEASURER_HEADERS,
        safe_harbor_used="MANAGEMENT_AND_TANGIBLE",
        gross_income_zone_amount=800000.00,
        gross_income_total_amount=1000000.00,
        intangibles_zone_use_amount=30000.00,
        intangibles_total_amount=100000.00,
        total_asset_value_measured=1000000.00,
    )

    certified = certify_business_test(api, test["id"], CERTIFIER_HEADERS)

    assert certified["status"] == "FAILED"
    assert certified["nqfp_prong"] == "PASS"
    business_after = read_qoz_business(api, business["id"])
    assert business_after["qualification_status"] == "AT_RISK"
    assert business_after["consecutive_failed_business_tests"] == 1


def _two_business_fund(api):
    """One fund, two operating businesses, one QOZB_EQUITY holding pointed at each."""
    fund = make_self_certified_fund(api)
    passing = make_qoz_business(
        api,
        fund["id"],
        legal_name="Northline Fabrication LLC",
        zone_tract_code="12345678901",
        declared_nqfp_amount=10000.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=900000.00,
    )
    failing = make_qoz_business(
        api,
        fund["id"],
        legal_name="Southline Fabrication LLC",
        zone_tract_code="12345678902",
        declared_nqfp_amount=300000.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=900000.00,
    )
    passing_equity = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZB_EQUITY",
        qoz_business_id=passing["id"],
        acquisition_date="2026-02-01T00:00:00Z",
        unadjusted_cost_basis=400000.00,
        afs_fair_value=400000.00,
    )
    failing_equity = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZB_EQUITY",
        qoz_business_id=failing["id"],
        acquisition_date="2026-02-01T00:00:00Z",
        unadjusted_cost_basis=400000.00,
        afs_fair_value=400000.00,
    )
    return {
        "fund": fund,
        "passing": passing,
        "failing": failing,
        "passing_equity": passing_equity,
        "failing_equity": failing_equity,
    }


def _measure_actual(api, business_id):
    """Open and measure a test on the actual-gross-income branch."""
    test = make_business_test(api, business_id, testing_date="2026-06-30T00:00:00Z")
    measure_business_test(
        api,
        test["id"],
        MEASURER_HEADERS,
        safe_harbor_used="GROSS_INCOME_ACTUAL",
        gross_income_zone_amount=600000.00,
        gross_income_total_amount=1000000.00,
        intangibles_zone_use_amount=50000.00,
        intangibles_total_amount=100000.00,
        total_asset_value_measured=1000000.00,
    )
    return test


def test_all_three_prongs_passing_qualifies_the_business_and_its_equity(api):
    """
    "When all three prong verdicts are `PASS`, the test goes `MEASURED → PASSED`,
    records `certified_by_user_id`, drives the business `UNTESTED → QUALIFIED` with
    `consecutive_failed_business_tests` reset to 0, and promotes every `QOZB_EQUITY`
    asset pointing at that business whose `status` is `HELD` to `qualification`
    `QUALIFIED`, after which the fund's `aggregate_qualified_basis` and
    `aggregate_qualified_afs_value` are recomputed."

    Design: Difficulty/non_linear_state_machine/business_test_fork_divergent_side_effects
    """
    context = _two_business_fund(api)
    test = _measure_actual(api, context["passing"]["id"])

    certified = certify_business_test(api, test["id"], CERTIFIER_HEADERS)

    assert certified["status"] == "PASSED"
    assert_business_test_prongs(
        certified,
        gross_income_pct=60.0000,
        intangibles_pct=50.0000,
        nqfp_pct=1.0000,
        gross_income_prong="PASS",
        intangibles_prong="PASS",
        nqfp_prong="PASS",
    )
    business_after = read_qoz_business(api, context["passing"]["id"])
    assert business_after["qualification_status"] == "QUALIFIED"
    assert business_after["consecutive_failed_business_tests"] == 0
    equity_after = read_fund_asset(api, context["passing_equity"]["id"])
    assert equity_after["qualification"] == "QUALIFIED"
    assert equity_after["status"] == "HELD"


def test_a_failed_nqfp_ceiling_disqualifies_the_business_and_its_equity(api):
    """
    "If instead `nqfp_prong` is `FAIL`, the business is disqualified outright —
    `UNTESTED → DISQUALIFIED` from a first test, `AT_RISK → DISQUALIFIED` from a
    warned business — and a four-link cascade runs. First, `qualification_status`
    becomes `DISQUALIFIED` and `consecutive_failed_business_tests` is set — to 1 from
    `UNTESTED`, to 2 from `AT_RISK`. Second, because the business is disqualified,
    every asset pointing at it whose `status` is `HELD` or `IMPROVING` gets
    `qualification` `NONQUALIFIED`, and the fund's `aggregate_qualified_basis` and
    `aggregate_qualified_afs_value` are recomputed."

    Design: Difficulty/non_linear_state_machine/business_test_fork_divergent_side_effects
    """
    context = _two_business_fund(api)
    passing_test = _measure_actual(api, context["passing"]["id"])
    certify_business_test(api, passing_test["id"], CERTIFIER_HEADERS)
    failing_test = _measure_actual(api, context["failing"]["id"])

    certified = certify_business_test(api, failing_test["id"], CERTIFIER_HEADERS)

    assert certified["status"] == "FAILED"
    assert_business_test_prongs(
        certified,
        gross_income_pct=60.0000,
        intangibles_pct=50.0000,
        nqfp_pct=30.0000,
        gross_income_prong="PASS",
        intangibles_prong="PASS",
        nqfp_prong="FAIL",
    )
    failing_business = read_qoz_business(api, context["failing"]["id"])
    assert failing_business["qualification_status"] == "DISQUALIFIED"
    assert failing_business["consecutive_failed_business_tests"] == 1
    assert read_fund_asset(api, context["failing_equity"]["id"])["qualification"] == (
        "NONQUALIFIED"
    )
    # The passing branch fired none of this.
    assert read_fund_asset(api, context["passing_equity"]["id"])["qualification"] == (
        "QUALIFIED"
    )
    fund_after = read_fund(api, context["fund"]["id"])
    assert_fund_aggregates(
        fund_after,
        aggregate_asset_basis=800000.00,
        aggregate_qualified_basis=400000.00,
    )
    # No asset test was ever certified, so the compliance dimension never moved.
    assert_fund_state(fund_after, compliance_posture="UNTESTED")


def _business_with_equity(api, fund_name, legal_name, declared_nqfp_amount):
    """A business plus the QOZB_EQUITY asset that tracks it."""
    fund = make_self_certified_fund(api, name=fund_name, entity_type="CORPORATION")
    business = make_qoz_business(
        api,
        fund["id"],
        legal_name=legal_name,
        zone_tract_code="12345678910",
        declared_nqfp_amount=declared_nqfp_amount,
        total_asset_value=1000000.00,
        total_tangible_property_basis=850000.00,
    )
    asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZB_EQUITY",
        qoz_business_id=business["id"],
        acquisition_date="2026-02-01T00:00:00Z",
        unadjusted_cost_basis=400000.00,
        afs_fair_value=400000.00,
    )
    return fund, business, asset


def test_the_warning_posture_leaves_the_equity_asset_exactly_where_it_was(api):
    """
    "If `nqfp_prong` is `PASS` but at least one of `gross_income_prong` and
    `intangibles_prong` is `FAIL`, and the business's
    `consecutive_failed_business_tests` stood at 0 before this certification, the
    business moves `UNTESTED → AT_RISK` (or `AT_RISK → DISQUALIFIED` on a second
    failure, below) with the counter set to 1. `AT_RISK` is a warning posture only:
    **no** asset's `qualification` changes and no fund aggregate moves."

    Design: Corner/state_machines/business_test_at_risk_branch_does_not_promote_assets
    """
    fund, business, asset = _business_with_equity(
        api, "At Risk Fund", "At Risk Operating LLC", 10000.00
    )
    assert asset["qualification"] == "NONQUALIFIED"
    test = make_business_test(api, business["id"], testing_date="2026-06-30T00:00:00Z")
    measured = measure_business_test(
        api,
        test["id"],
        MEASURER_HEADERS,
        safe_harbor_used="GROSS_INCOME_ACTUAL",
        gross_income_zone_amount=300000.00,
        gross_income_total_amount=1000000.00,
        intangibles_zone_use_amount=500000.00,
        intangibles_total_amount=1000000.00,
        total_asset_value_measured=1000000.00,
    )
    assert_business_test_prongs(
        measured,
        gross_income_pct=30.0000,
        intangibles_pct=50.0000,
        nqfp_pct=1.0000,
        gross_income_prong="FAIL",
        intangibles_prong="PASS",
        nqfp_prong="PASS",
    )

    certified = certify_business_test(api, test["id"], CERTIFIER_HEADERS)

    assert certified["status"] == "FAILED"
    assert certified["certified_by_user_id"] != certified["measured_by_user_id"]
    business_after = read_qoz_business(api, business["id"])
    assert business_after["qualification_status"] == "AT_RISK"
    assert business_after["consecutive_failed_business_tests"] == 1
    assert read_fund_asset(api, asset["id"])["qualification"] == "NONQUALIFIED"
    fund_after = read_fund(api, fund["id"])
    assert_fund_aggregates(
        fund_after,
        aggregate_asset_basis=400000.00,
        aggregate_qualified_basis=0.00,
    )
    assert fund_after["compliance_posture"] == "UNTESTED"


def test_the_hours_branch_takes_its_percentage_verbatim_and_ignores_the_income(api):
    """
    "Under `FIFTY_PCT_HOURS` it is `hours_zone_pct` rounded half up to four decimal
    places." "`gross_income_prong` is `PASS` when `gross_income_pct` is at least
    50.0000 and `FAIL` otherwise." "When all three prong verdicts are `PASS`, the test
    goes `MEASURED → PASSED`, records `certified_by_user_id`, drives the business
    `UNTESTED → QUALIFIED` with `consecutive_failed_business_tests` reset to 0, and
    promotes every `QOZB_EQUITY` asset pointing at that business whose `status` is
    `HELD` to `qualification` `QUALIFIED`, after which the fund's
    `aggregate_qualified_basis` and `aggregate_qualified_afs_value` are recomputed."

    Design: Corner/calculations/business_test_fifty_pct_hours_prong_uses_declared_percentage
    """
    fund, business, asset = _business_with_equity(
        api, "Hours Harbor Fund", "Hours Harbor Operating LLC", 20000.00
    )
    test = make_business_test(api, business["id"], testing_date="2026-06-30T00:00:00Z")

    measured = measure_business_test(
        api,
        test["id"],
        MEASURER_HEADERS,
        safe_harbor_used="FIFTY_PCT_HOURS",
        hours_zone_pct=62.5000,
        gross_income_zone_amount=100000.00,
        gross_income_total_amount=1000000.00,
        intangibles_zone_use_amount=450000.00,
        intangibles_total_amount=1000000.00,
        total_asset_value_measured=1000000.00,
    )

    assert_business_test_prongs(
        measured,
        gross_income_pct=62.5000,
        intangibles_pct=45.0000,
        nqfp_pct=2.0000,
        gross_income_prong="PASS",
        intangibles_prong="PASS",
        nqfp_prong="PASS",
    )
    assert_money(measured["nqfp_amount_measured"], 20000.00, "nqfp_amount_measured")
    assert measured["status"] == "MEASURED"
    assert measured["measured_by_user_id"]

    certified = certify_business_test(api, test["id"], CERTIFIER_HEADERS)

    assert certified["status"] == "PASSED"
    business_after = read_qoz_business(api, business["id"])
    assert business_after["qualification_status"] == "QUALIFIED"
    assert business_after["consecutive_failed_business_tests"] == 0
    assert read_fund_asset(api, asset["id"])["qualification"] == "QUALIFIED"
    assert_fund_aggregates(
        read_fund(api, fund["id"]), aggregate_qualified_basis=400000.00
    )


def test_each_safe_harbor_branch_accepts_only_its_own_conditional_percentage(api):
    """
    "Two further inputs are conditional and are the subject of a dedicated check:
    `FIFTY_PCT_HOURS` requires `hours_zone_pct` and `FIFTY_PCT_AMOUNTS_PAID` requires
    `amounts_paid_zone_pct`, each a percentage from 0.0000 through 100.0000;
    `MANAGEMENT_AND_TANGIBLE` and `GROSS_INCOME_ACTUAL` require neither and **reject
    both**. A missing required percentage, or a percentage supplied for a branch that
    does not consume it, yields `ERR_SAFE_HARBOR_INPUT_MISSING`." "Under
    `FIFTY_PCT_AMOUNTS_PAID` it is `amounts_paid_zone_pct` rounded the same way."

    Design: Corner/validations/safe_harbor_input_required_only_for_its_own_variant
    """
    fund = make_self_certified_fund(
        api, name="Safe Harbor Input Fund", entity_type="CORPORATION"
    )
    business = make_qoz_business(
        api,
        fund["id"],
        legal_name="Safe Harbor Operating LLC",
        zone_tract_code="12345678910",
        declared_nqfp_amount=20000.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=850000.00,
    )
    test = make_business_test(api, business["id"], testing_date="2026-06-30T00:00:00Z")
    amounts = {
        "gross_income_zone_amount": 600000.00,
        "gross_income_total_amount": 1000000.00,
        "intangibles_zone_use_amount": 450000.00,
        "intangibles_total_amount": 1000000.00,
        "total_asset_value_measured": 1000000.00,
    }

    missing = api.measure_business_test(
        test["id"],
        measure_business_test_payload(safe_harbor_used="FIFTY_PCT_HOURS", **amounts),
        MEASURER_HEADERS,
    )
    unconsumed = api.measure_business_test(
        test["id"],
        measure_business_test_payload(
            safe_harbor_used="GROSS_INCOME_ACTUAL", hours_zone_pct=62.5000, **amounts
        ),
        MEASURER_HEADERS,
    )

    validate_error(missing, ApiErrorId.SAFE_HARBOR_INPUT_MISSING.value, 422)
    validate_error(unconsumed, ApiErrorId.SAFE_HARBOR_INPUT_MISSING.value, 422)

    accepted = validate_success(
        api.measure_business_test(
            test["id"],
            measure_business_test_payload(
                safe_harbor_used="FIFTY_PCT_AMOUNTS_PAID",
                amounts_paid_zone_pct=55.0000,
                **amounts,
            ),
            MEASURER_HEADERS,
        )
    )

    assert accepted["status"] == "MEASURED"
    assert_percent(accepted["gross_income_pct"], 55.0000, "gross_income_pct")
    assert_business_test_prongs(
        accepted,
        intangibles_pct=45.0000,
        nqfp_pct=2.0000,
        gross_income_prong="PASS",
        intangibles_prong="PASS",
        nqfp_prong="PASS",
    )
    assert read_business_test(api, test["id"])["version"] == 2
    assert read_qoz_business(api, business["id"])["qualification_status"] == "UNTESTED"


def test_correcting_the_reported_figures_moves_nqfp_but_no_measured_prong(api):
    """
    "A manager or platform administrator may update any of `declared_nqfp_amount`,
    `total_asset_value` and `total_tangible_property_basis`, each independently optional
    in the request; the update recomputes `nqfp_amount` from the live shelter and release
    and increments the business's `version`. It deliberately does **not** re-derive any
    prong of any business test: prongs are only ever re-derived by a fresh measurement or
    by the plan-blowout cascade described in §3.7."

    Design: Corner/endpoints/qoz_business_reported_figures_patch_recomputes_nqfp_only
    """
    fund, business, _asset = _business_with_equity(
        api, "Reported Figures Fund", "Reported Figures Operating LLC", 20000.00
    )
    assert_money(business["nqfp_amount"], 20000.00, "nqfp_amount")
    assert business["version"] == 1
    test = make_business_test(api, business["id"], testing_date="2026-06-30T00:00:00Z")
    measured = measure_business_test(
        api,
        test["id"],
        MEASURER_HEADERS,
        safe_harbor_used="GROSS_INCOME_ACTUAL",
        gross_income_zone_amount=600000.00,
        gross_income_total_amount=1000000.00,
        intangibles_zone_use_amount=450000.00,
        intangibles_total_amount=1000000.00,
        total_asset_value_measured=1000000.00,
    )
    assert_money(measured["nqfp_amount_measured"], 20000.00, "nqfp_amount_measured")
    assert_percent(measured["nqfp_pct"], 2.0000, "nqfp_pct")

    patched = validate_success(
        api.patch_qoz_business_reported_figures(
            business["id"],
            reported_figures_payload(declared_nqfp_amount=200000.00),
            MANAGER_HEADERS,
        )
    )

    assert_money(patched["declared_nqfp_amount"], 200000.00, "declared_nqfp_amount")
    assert_money(patched["nqfp_amount"], 200000.00, "nqfp_amount")
    assert patched["version"] == 2
    # The two omitted figures are untouched by the partial update.
    assert_money(patched["total_asset_value"], 1000000.00, "total_asset_value")
    assert_money(
        patched["total_tangible_property_basis"],
        850000.00,
        "total_tangible_property_basis",
    )
    snapshot = read_business_test(api, test["id"])
    assert_money(snapshot["nqfp_amount_measured"], 20000.00, "nqfp_amount_measured")
    assert_percent(snapshot["nqfp_pct"], 2.0000, "nqfp_pct")
    assert snapshot["nqfp_prong"] == "PASS"
    after = read_qoz_business(api, business["id"])
    assert after["qualification_status"] == "UNTESTED"
    assert_money(after["wcsh_protected_amount"], 0.00, "wcsh_protected_amount")
    assert fund["id"] == after["fund_id"]
