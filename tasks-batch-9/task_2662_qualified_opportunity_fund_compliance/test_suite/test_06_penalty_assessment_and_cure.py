"""Penalty assessment arithmetic, the tiered cure credit and the cure cycle."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fund_state,
    assert_money,
    assert_noncompliance_months_conserved,
)
from test_helpers.factories import cure_decision_payload, cure_request_payload
from test_helpers.fixtures import (
    decide_cure,
    list_fund_penalty_assessments,
    make_certified_asset_test,
    make_fund_asset,
    make_penalty_assessment_context,
    make_self_certified_fund,
    read_asset_test,
    read_fund,
    read_penalty_assessment,
    request_cure,
)
from test_helpers.test_users import (
    CERTIFIER_HEADERS,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
    OFFICER_CERTIFIER_USER_ID,
)


def _assessed_context(api, qualified_basis, nonqualified_basis):
    """Certify a failing asset test so the cascade produces one assessment."""
    return make_penalty_assessment_context(
        api,
        qualified_basis=qualified_basis,
        nonqualified_basis=nonqualified_basis,
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )


def test_penalty_rounds_per_month_before_summing_over_the_months(api):
    """
    "`monthly_penalty_amount` is `shortfall_amount` multiplied by an annual
    underpayment rate of 0.08 and divided by 12, rounded half up to the cent
    **first**." "Worked through: a `shortfall_amount` of 50000.00 over a
    `failed_month_count` of 6 gives a monthly figure of 333.33 and a gross of
    1999.98. Multiplying first and rounding once at the end would give 2000.00;
    that is explicitly not the contract."

    Design: Difficulty/combinatorial_formula/failed_test_penalty_per_month_rounding_order
    """
    context = _assessed_context(api, 850000.00, 150000.00)
    assessment = context["assessment"]
    assert assessment is not None, "A certified failure must create one assessment"

    assert assessment["status"] == "ASSESSED"
    assert assessment["failed_month_count"] == 6
    assert_money(assessment["shortfall_amount"], 50000.00, "shortfall_amount")
    assert_money(assessment["monthly_penalty_amount"], 333.33, "monthly_penalty_amount")
    assert_money(assessment["gross_penalty_amount"], 1999.98, "gross_penalty_amount")
    assert float(assessment["gross_penalty_amount"]) != 2000.00, (
        "Multiplying first and rounding once at the end is not the contract"
    )
    assert_money(assessment["cure_credit_amount"], 0.00, "cure_credit_amount")
    assert_money(assessment["net_penalty_amount"], 1999.98, "net_penalty_amount")


def test_certified_failure_leaves_the_fund_deficient_but_still_certified(api):
    """
    "A `FAIL` produces `MEASURED → CERTIFIED_FAIL` and a three-link cascade: first
    `consecutive_failed_tests` increments by 1; second, because the test is now
    `CERTIFIED_FAIL`, a penalty assessment is created in `ASSESSED` with the fund,
    the test, the `failed_month_count` and the `shortfall_amount` snapshotted onto
    it and the penalty figures computed as in §3.8, and the fund's
    `cumulative_penalty_months` rises by that `failed_month_count`; third, because a
    live assessment now exists, `compliance_posture` becomes `DEFICIENT`, whether by
    `UNTESTED → DEFICIENT` on a first-ever test or by `COMPLIANT → DEFICIENT` on a
    fund that had been passing."

    Design: Difficulty/combinatorial_formula/failed_test_penalty_per_month_rounding_order
    """
    context = _assessed_context(api, 850000.00, 150000.00)
    fund = read_fund(api, context["fund"]["id"])
    assessment = context["assessment"]

    assert context["asset_test"]["status"] == "CERTIFIED_FAIL"
    assert fund["consecutive_failed_tests"] == 1
    assert fund["cumulative_penalty_months"] == 6
    assert_fund_state(
        fund, certification_status="SELF_CERTIFIED", compliance_posture="DEFICIENT"
    )
    assert assessment["fund_id"] == fund["id"]
    assert assessment["asset_test_id"] == context["asset_test"]["id"]
    assert assessment["cure_attempt_count"] == 0
    assert assessment["cure_basis"] == "NONE"
    assert not assessment["requested_by_user_id"]
    assert not assessment["decided_by_user_id"]


def test_cure_credit_tier_is_derived_from_the_gross_penalty(api):
    """
    "The tier basis is the **gross** penalty, never the net figure. The cap
    percentage is 0.60 when the gross is at least 1000.00 and 0.40 otherwise."
    "Worked through on a gross of 1999.98: the gross is at least 1000.00, so the cap
    is 0.60; 0.60 of 1999.98 is 1199.988, which rounds to 1199.99; the floor of
    250.00 does not bind and the cap at gross does not bind, so the credit is 1199.99
    and the net is 799.99."

    Design: Difficulty/combinatorial_formula/penalty_cure_credit_tier_from_gross
    """
    context = _assessed_context(api, 850000.00, 150000.00)
    assessment_id = context["assessment"]["id"]
    request_cure(
        api,
        assessment_id,
        cure_basis="REASONABLE_CAUSE",
        narrative_reference="MEMO-2026-CURE-01",
    )

    decided = decide_cure(api, assessment_id, decision="APPROVE")

    assert decided["status"] == "CURED"
    assert_money(decided["gross_penalty_amount"], 1999.98, "gross_penalty_amount")
    assert_money(decided["cure_credit_amount"], 1199.99, "cure_credit_amount")
    assert_money(decided["net_penalty_amount"], 799.99, "net_penalty_amount")
    assert decided["cure_attempt_count"] == 1
    assert decided["decided_by_user_id"] == OFFICER_CERTIFIER_USER_ID


def test_the_tier_is_never_re_derived_from_the_resulting_net(api):
    """
    "There is no second pass: the cap percentage is never re-derived from the
    resulting net figure even when the net falls below the tier break as a
    consequence of the credit." "Re-deriving the tier from the net, seeing 799.99
    below 1000.00 and applying 0.40 would produce a credit of 800.00 and a net of
    1199.98, which is the wrong answer."

    Design: Difficulty/combinatorial_formula/penalty_cure_credit_tier_from_gross
    """
    context = _assessed_context(api, 850000.00, 150000.00)
    assessment_id = context["assessment"]["id"]
    request_cure(
        api,
        assessment_id,
        cure_basis="REASONABLE_CAUSE",
        narrative_reference="MEMO-2026-CURE-01",
    )
    decide_cure(api, assessment_id, decision="APPROVE")

    assessment = read_penalty_assessment(api, assessment_id)

    assert float(assessment["cure_credit_amount"]) != 800.00, (
        "A credit of 800.00 means the tier was re-derived from the net figure"
    )
    assert float(assessment["net_penalty_amount"]) != 1199.98
    assert_money(assessment["cure_credit_amount"], 1199.99, "cure_credit_amount")
    assert_money(assessment["net_penalty_amount"], 799.99, "net_penalty_amount")
    fund = read_fund(api, context["fund"]["id"])
    assert_fund_state(fund, compliance_posture="COMPLIANT")
    assert fund["cumulative_penalty_months"] == 0


def test_denying_a_reasonable_cause_request_cycles_back_to_assessed(api):
    """
    "Denying a `REASONABLE_CAUSE` request cycles the assessment
    `CURE_REQUESTED → ASSESSED`: `cure_credit_amount` stays 0.00, the fund's
    `cumulative_penalty_months` is unchanged, and `compliance_posture` moves
    `CURE_PENDING → DEFICIENT`."

    Design: Difficulty/non_linear_state_machine/penalty_assessment_cure_cycle_returns_to_assessed
    """
    context = _assessed_context(api, 850000.00, 150000.00)
    assessment_id = context["assessment"]["id"]

    requested = request_cure(
        api,
        assessment_id,
        cure_basis="REASONABLE_CAUSE",
        narrative_reference="MEMO-CYCLE-01",
    )
    assert requested["status"] == "CURE_REQUESTED"
    assert requested["cure_attempt_count"] == 1
    assert_fund_state(
        read_fund(api, context["fund"]["id"]), compliance_posture="CURE_PENDING"
    )

    denied = decide_cure(api, assessment_id, decision="DENY")

    assert denied["status"] == "ASSESSED"
    assert denied["cure_attempt_count"] == 1
    assert_money(denied["cure_credit_amount"], 0.00, "cure_credit_amount")
    fund = read_fund(api, context["fund"]["id"])
    assert_fund_state(fund, compliance_posture="DEFICIENT")
    assert fund["cumulative_penalty_months"] == 6


def test_denying_a_treated_as_failure_request_upholds_the_penalty(api):
    """
    "Denying a `TREATED_AS_FAILURE` request instead moves the assessment
    `CURE_REQUESTED → UPHELD`, which is terminal: `net_penalty_amount` remains equal
    to `gross_penalty_amount`, `compliance_posture` still moves
    `CURE_PENDING → DEFICIENT`, and `cumulative_penalty_months` is unchanged because
    an upheld penalty's months keep counting."

    Design: Difficulty/non_linear_state_machine/penalty_assessment_cure_cycle_returns_to_assessed
    """
    context = _assessed_context(api, 850000.00, 150000.00)
    assessment_id = context["assessment"]["id"]
    request_cure(
        api,
        assessment_id,
        cure_basis="REASONABLE_CAUSE",
        narrative_reference="MEMO-CYCLE-01",
    )
    decide_cure(api, assessment_id, decision="DENY")

    second = request_cure(
        api,
        assessment_id,
        cure_basis="TREATED_AS_FAILURE",
        narrative_reference="MEMO-CYCLE-02",
    )
    assert second["cure_attempt_count"] == 2
    upheld = decide_cure(api, assessment_id, decision="DENY")

    assert upheld["status"] == "UPHELD"
    assert upheld["cure_attempt_count"] == 2
    assert_money(upheld["cure_credit_amount"], 0.00, "cure_credit_amount")
    assert_money(upheld["net_penalty_amount"], 1999.98, "net_penalty_amount")
    assert_money(upheld["gross_penalty_amount"], 1999.98, "gross_penalty_amount")
    fund = read_fund(api, context["fund"]["id"])
    assert_fund_state(fund, compliance_posture="DEFICIENT")
    assert fund["cumulative_penalty_months"] == 6


def test_assessment_months_are_summed_onto_the_fund_while_the_penalty_lives(api):
    """
    "a penalty assessment is created in `ASSESSED` with the fund, the test, the
    `failed_month_count` and the `shortfall_amount` snapshotted onto it and the
    penalty figures computed as in §3.8, and the fund's `cumulative_penalty_months`
    rises by that `failed_month_count`"

    Design: Difficulty/compensating_invariant/noncompliance_months_conserved_across_cure_approval
    """
    context = _assessed_context(api, 800000.00, 200000.00)
    fund = read_fund(api, context["fund"]["id"])
    assessment = context["assessment"]

    assert_money(assessment["shortfall_amount"], 100000.00, "shortfall_amount")
    assert_money(assessment["monthly_penalty_amount"], 666.67, "monthly_penalty_amount")
    assert_money(assessment["gross_penalty_amount"], 4000.02, "gross_penalty_amount")
    assert assessment["failed_month_count"] == 6
    assert fund["cumulative_penalty_months"] == 6
    assert_noncompliance_months_conserved(
        fund, list_fund_penalty_assessments(api, fund["id"])
    )


def test_cure_approval_returns_the_noncompliance_months_it_compensates(api):
    """
    "Approval is also the compensating action for the second conserved quantity. It
    decrements the fund's `cumulative_penalty_months` by exactly this assessment's
    `failed_month_count`, returning that count to its pre-assessment value, moves the
    fund's `compliance_posture` `CURE_PENDING → COMPLIANT` and resets the fund's
    `consecutive_failed_tests` to 0."

    Design: Difficulty/compensating_invariant/noncompliance_months_conserved_across_cure_approval
    """
    context = _assessed_context(api, 800000.00, 200000.00)
    fund_id = context["fund"]["id"]
    assessment_id = context["assessment"]["id"]
    request_cure(
        api,
        assessment_id,
        cure_basis="REASONABLE_CAUSE",
        narrative_reference="MEMO-CURE-APPROVE-01",
    )

    cured = decide_cure(api, assessment_id, decision="APPROVE")

    assert cured["status"] == "CURED"
    assert cured["cure_attempt_count"] == 1
    assert_money(cured["cure_credit_amount"], 2400.01, "cure_credit_amount")
    assert_money(cured["net_penalty_amount"], 1600.01, "net_penalty_amount")
    fund = read_fund(api, fund_id)
    assert fund["cumulative_penalty_months"] == 0
    assert fund["consecutive_failed_tests"] == 0
    assert_fund_state(fund, compliance_posture="COMPLIANT")
    assert_noncompliance_months_conserved(
        fund, list_fund_penalty_assessments(api, fund_id)
    )
    # The cured penalty does not rewrite the test that produced it.
    test_after = read_asset_test(api, context["asset_test"]["id"])
    assert test_after["status"] == "CERTIFIED_FAIL"
    assert test_after["failed_month_count"] == 6


def _cash_only_assessment(api):
    """A cash-only fund fails its test outright, producing a 36000.00 assessment."""
    fund = make_self_certified_fund(api, name="Cure Basis Fund", entity_type="CORPORATION")
    make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=1000000.00,
        afs_fair_value=1000000.00,
    )
    test = make_certified_asset_test(
        api,
        fund["id"],
        measure_headers=MEASURER_HEADERS,
        certify_headers=CERTIFIER_HEADERS,
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    assessments = list_fund_penalty_assessments(api, fund["id"])
    assert len(assessments) == 1
    return fund, test, assessments[0]


def test_a_concession_of_failure_can_be_denied_but_never_approved(api):
    """
    "Approval requires the asserted basis to be approvable: only `REASONABLE_CAUSE` may
    be approved, and approving a `TREATED_AS_FAILURE` basis is rejected with
    `ERR_CURE_BASIS_NOT_APPROVABLE`, because that basis is a concession of the failure
    rather than a defence of it. The decision records `decided_by_user_id`."
    "a request that fails any check in §2.11 mutates nothing."

    Design: Corner/validations/cure_basis_treated_as_failure_cannot_be_approved
    """
    fund, test, assessment = _cash_only_assessment(api)
    assert_money(test["shortfall_amount"], 900000.00, "shortfall_amount")
    assert test["failed_month_count"] == 6
    requested = request_cure(
        api,
        assessment["id"],
        cure_basis="TREATED_AS_FAILURE",
        narrative_reference="NARR-2662-TAF-1",
    )
    assert requested["status"] == "CURE_REQUESTED"

    response = api.create_cure_decision(
        assessment["id"], cure_decision_payload(decision="APPROVE"), CERTIFIER_HEADERS
    )

    validate_error(response, ApiErrorId.CURE_BASIS_NOT_APPROVABLE.value, 422)
    after = read_penalty_assessment(api, assessment["id"])
    assert after["status"] == "CURE_REQUESTED"
    assert_money(after["gross_penalty_amount"], 36000.00, "gross_penalty_amount")
    assert_money(after["cure_credit_amount"], 0.00, "cure_credit_amount")
    assert_money(after["net_penalty_amount"], 36000.00, "net_penalty_amount")
    assert not after["decided_by_user_id"]
    assert after["cure_attempt_count"] == 1
    fund_after = read_fund(api, fund["id"])
    assert fund_after["cumulative_penalty_months"] == 6
    assert fund_after["compliance_posture"] == "CURE_PENDING"


def test_a_third_cure_request_after_two_denials_is_refused(api):
    """
    "The request is permitted only while `cure_attempt_count` is below 2; a third filing
    is rejected with `ERR_CURE_ATTEMPTS_EXHAUSTED` and leaves the assessment
    `ASSESSED`." "Denying a `REASONABLE_CAUSE` request cycles the assessment
    `CURE_REQUESTED → ASSESSED`: `cure_credit_amount` stays 0.00, the fund's
    `cumulative_penalty_months` is unchanged, and `compliance_posture` moves
    `CURE_PENDING → DEFICIENT`. Because the assessment is `ASSESSED` again rather than
    terminal, a second request may be filed — which is what makes the two-attempt cap
    meaningful."

    Design: Corner/errors/third_cure_request_after_two_denials_rejected
    """
    fund, _test, assessment = _cash_only_assessment(api)
    assert_money(assessment["gross_penalty_amount"], 36000.00, "gross_penalty_amount")

    first_request = request_cure(
        api, assessment["id"], narrative_reference="CURE-2662-A"
    )
    assert first_request["status"] == "CURE_REQUESTED"
    assert first_request["cure_attempt_count"] == 1
    assert decide_cure(api, assessment["id"], decision="DENY")["status"] == "ASSESSED"

    second_request = request_cure(
        api, assessment["id"], narrative_reference="CURE-2662-B"
    )
    assert second_request["status"] == "CURE_REQUESTED"
    assert second_request["cure_attempt_count"] == 2
    assert decide_cure(api, assessment["id"], decision="DENY")["status"] == "ASSESSED"

    exhausted = api.create_cure_request(
        assessment["id"],
        cure_request_payload(narrative_reference="CURE-2662-C"),
        MANAGER_HEADERS,
    )

    validate_error(exhausted, ApiErrorId.CURE_ATTEMPTS_EXHAUSTED.value, 409)
    after = read_penalty_assessment(api, assessment["id"])
    assert after["status"] == "ASSESSED"
    assert after["cure_attempt_count"] == 2
    assert after["narrative_reference"] == "CURE-2662-B"
    assert_money(after["cure_credit_amount"], 0.00, "cure_credit_amount")
    assert_money(after["net_penalty_amount"], 36000.00, "net_penalty_amount")
    fund_after = read_fund(api, fund["id"])
    assert_fund_state(fund_after, compliance_posture="DEFICIENT")
    assert fund_after["cumulative_penalty_months"] == 6
