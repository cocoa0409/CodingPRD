"""The second consecutive failed asset test and the decertification chain it fires."""

from test_helpers.assertions import (
    assert_asset_test_measurement,
    assert_fund_state,
    assert_money,
    assert_noncompliance_months_conserved,
)
from test_helpers.fixtures import (
    certify_asset_test,
    dispose_asset,
    list_election_inclusion_events,
    list_fund_penalty_assessments,
    make_asset_test,
    make_attested_investor,
    make_deferral_election,
    make_eligible_gain,
    make_fund_asset,
    make_self_certified_fund,
    measure_asset_test,
    read_deferral_election,
    read_fund,
    read_investor_statement,
)
from test_helpers.test_users import CERTIFIER_HEADERS, MANAGER_HEADERS, MEASURER_HEADERS


def _fund_with_one_failing_certification(api):
    """A fund carrying one deferred election and one already-certified failure."""
    investor = make_attested_investor(api)
    fund = make_self_certified_fund(api, asset_test_valuation_method="UNADJUSTED_COST_BASIS")
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=400000.00,
        realization_date="2026-03-15T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    election = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=400000.00
    )
    make_fund_asset(
        api,
        fund["id"],
        acquisition_date="2026-01-15T00:00:00Z",
        unadjusted_cost_basis=800000.00,
        afs_fair_value=800000.00,
    )
    make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-15T00:00:00Z",
        unadjusted_cost_basis=200000.00,
        afs_fair_value=200000.00,
    )
    first = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    measure_asset_test(api, first["id"], MEASURER_HEADERS)
    certify_asset_test(api, first["id"], CERTIFIER_HEADERS)
    second = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-12-31T00:00:00Z",
        period_start="2026-07-01T00:00:00Z",
        period_end="2027-01-01T00:00:00Z",
    )
    measure_asset_test(api, second["id"], MEASURER_HEADERS)
    return {
        "investor": investor,
        "fund": fund,
        "gain": gain,
        "election": election,
        "first_test": first,
        "second_test": second,
    }


def test_the_second_consecutive_failure_decertifies_the_fund(api):
    """
    "When a failing certification lands on a fund whose `compliance_posture` is
    already `DEFICIENT` and whose `consecutive_failed_tests` stands at 1, that count
    becomes 2 and the cascade grows a fourth link: a second penalty assessment is
    still created and `cumulative_penalty_months` still rises by its
    `failed_month_count`, but `compliance_posture` goes `DEFICIENT → FAILED_FINAL` and
    `certification_status` goes `SELF_CERTIFIED → DECERTIFIED`".

    Design: Difficulty/transitive_cascade/second_consecutive_failed_test_decertification_chain
    """
    context = _fund_with_one_failing_certification(api)
    before = read_fund(api, context["fund"]["id"])
    assert before["consecutive_failed_tests"] == 1
    assert_fund_state(
        before, certification_status="SELF_CERTIFIED", compliance_posture="DEFICIENT"
    )

    certified = certify_asset_test(api, context["second_test"]["id"], CERTIFIER_HEADERS)

    assert certified["status"] == "CERTIFIED_FAIL"
    assert certified["failed_month_count"] == 6
    assert_money(certified["shortfall_amount"], 100000.00, "shortfall_amount")
    fund_after = read_fund(api, context["fund"]["id"])
    assert fund_after["consecutive_failed_tests"] == 2
    assert fund_after["cumulative_penalty_months"] == 12
    assert_fund_state(
        fund_after,
        certification_status="DECERTIFIED",
        compliance_posture="FAILED_FINAL",
    )
    assessments = list_fund_penalty_assessments(api, context["fund"]["id"])
    assert len(assessments) == 2
    for assessment in assessments:
        assert assessment["failed_month_count"] == 6
        assert_money(assessment["gross_penalty_amount"], 4000.02, "gross_penalty_amount")
    assert_noncompliance_months_conserved(fund_after, assessments)


def test_decertification_pulls_every_deferred_dollar_into_income(api):
    """
    "because the fund is now decertified, the full fund-decertification inclusion
    cascade of §3.2 fires — a `FUND_DECERTIFICATION` inclusion event on every election
    in `DEFERRED`, `STEPPED_UP` or `INCLUDED_PARTIAL`, those elections moving to
    `INCLUDED_FULL`, and every owning investor's `deferred_gain_outstanding` and
    `included_gain_total` recomputed."

    Design: Difficulty/transitive_cascade/second_consecutive_failed_test_decertification_chain
    """
    context = _fund_with_one_failing_certification(api)
    assert context["election"]["days_from_basis"] == 139
    assert read_deferral_election(api, context["election"]["id"])["status"] == "DEFERRED"

    certify_asset_test(api, context["second_test"]["id"], CERTIFIER_HEADERS)

    events = list_election_inclusion_events(api, context["election"]["id"])
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "FUND_DECERTIFICATION"
    assert float(event["included_fraction"]) == 1.0000
    assert event["holding_days"] == 0
    assert event["holding_tier_applied"] == "UNDER_FIVE"
    assert_money(event["gross_inclusion_amount"], 400000.00, "gross_inclusion_amount")
    assert_money(event["basis_offset_amount"], 0.00, "basis_offset_amount")
    assert_money(event["net_inclusion_amount"], 400000.00, "net_inclusion_amount")
    assert event["is_full"] is True
    election_after = read_deferral_election(api, context["election"]["id"])
    assert election_after["status"] == "INCLUDED_FULL"
    assert_money(election_after["included_amount"], 400000.00, "included_amount")
    assert float(election_after["included_fraction_total"]) == 1.0000
    assert_money(election_after["deferred_remaining"], 0.00, "deferred_remaining")
    statement = read_investor_statement(api, context["investor"]["id"])
    assert_money(
        statement["deferred_gain_outstanding"], 0.00, "deferred_gain_outstanding"
    )
    assert_money(statement["included_gain_total"], 400000.00, "included_gain_total")


def test_a_certified_pass_between_two_failures_resets_the_streak_to_one(api):
    """
    "`consecutive_failed_tests` is defined as the number of that fund's asset tests,
    ordered by `measurement_date` ascending and then by creation timestamp ascending,
    that are `CERTIFIED_FAIL` in an unbroken run ending at the latest one; any
    `CERTIFIED_PASS` resets it to 0." "When a failing certification lands on a fund
    whose `compliance_posture` is already `DEFICIENT` and whose
    `consecutive_failed_tests` stands at 1, that count becomes 2". "an asset disposed
    before `period_end` is excluded from **both** the numerator and the denominator."

    Design: Corner/complexity_layers/consecutive_failed_tests_resets_after_a_certified_pass
    """
    fund = make_self_certified_fund(
        api,
        name="Reset Ladder QOF",
        entity_type="CORPORATION",
        asset_test_valuation_method="UNADJUSTED_COST_BASIS",
    )
    make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=100000.00,
        afs_fair_value=100000.00,
    )

    first = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-03-31T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-04-01T00:00:00Z",
    )
    measured_first = measure_asset_test(api, first["id"], MANAGER_HEADERS)
    assert_asset_test_measurement(
        measured_first,
        included_asset_count=1,
        qualified_numerator=0.00,
        total_denominator=100000.00,
        ratio_pct=0.0000,
        result="FAIL",
        shortfall_amount=90000.00,
        failed_month_count=3,
        valuation_method="UNADJUSTED_COST_BASIS",
    )
    assert certify_asset_test(api, first["id"], CERTIFIER_HEADERS)["status"] == (
        "CERTIFIED_FAIL"
    )
    after_first = read_fund(api, fund["id"])
    assert after_first["consecutive_failed_tests"] == 1
    assert after_first["cumulative_penalty_months"] == 3

    good = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-04-05T00:00:00Z",
        unadjusted_cost_basis=2000000.00,
        afs_fair_value=2000000.00,
        original_use_in_zone=True,
    )
    assert good["qualification"] == "QUALIFIED"
    second = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-04-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    measured_second = measure_asset_test(api, second["id"], MANAGER_HEADERS)
    assert_asset_test_measurement(
        measured_second,
        included_asset_count=2,
        qualified_numerator=2000000.00,
        total_denominator=2100000.00,
        ratio_pct=95.2381,
        result="PASS",
        shortfall_amount=0.00,
        failed_month_count=0,
    )
    assert certify_asset_test(api, second["id"], CERTIFIER_HEADERS)["status"] == (
        "CERTIFIED_PASS"
    )
    after_second = read_fund(api, fund["id"])
    assert after_second["consecutive_failed_tests"] == 0, "the pass wiped the run out"
    assert after_second["cumulative_penalty_months"] == 3
    assert after_second["certification_status"] == "SELF_CERTIFIED"

    disposed = dispose_asset(api, good["id"], proceeds_amount=2100000.00)
    assert disposed["status"] == "DISPOSED"
    assert disposed["disposed_at"].startswith("2026-08-01T00:00:00")
    third = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-09-30T00:00:00Z",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
    )
    measured_third = measure_asset_test(api, third["id"], MANAGER_HEADERS)
    assert_asset_test_measurement(
        measured_third,
        included_asset_count=1,
        qualified_numerator=0.00,
        total_denominator=100000.00,
        ratio_pct=0.0000,
        result="FAIL",
        shortfall_amount=90000.00,
        failed_month_count=3,
    )

    certified_third = certify_asset_test(api, third["id"], CERTIFIER_HEADERS)

    assert certified_third["status"] == "CERTIFIED_FAIL"
    fund_after = read_fund(api, fund["id"])
    assert fund_after["consecutive_failed_tests"] == 1, (
        "the run restarts from the pass, so this failure is the first of a new run"
    )
    assert fund_after["cumulative_penalty_months"] == 6
    assert_fund_state(
        fund_after,
        certification_status="SELF_CERTIFIED",
        compliance_posture="DEFICIENT",
    )
    assessments = list_fund_penalty_assessments(api, fund["id"])
    assert len(assessments) == 2
    assert_noncompliance_months_conserved(fund_after, assessments)
