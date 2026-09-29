"""
Queue A — §1.8 rule ``boundary_precision_check``.

Both instances live one unit away from a decision: one ten-thousandth of a
covenant ratio, and one filed giving period against the four-period minimum.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.assertions import assert_fields, assert_nulls, assert_ratio
from test_helpers.factories import (
    REFERENCE_AUDITED_QUARTERS,
    covenant_test_payload,
    submit_underwriting_payload,
)
from test_helpers.fixtures import (
    build_covenant,
    build_authorized_authorization,
    build_draft_application,
    build_giving_period,
    build_giving_periods,
    build_institution,
    chain_through_loan,
)
from test_helpers.test_users import (
    ANALYST_1,
    CREDIT_ANALYST,
    LOAN_SERVICER,
    make_credit_analyst_headers,
)

AS_OF = "2026-08-01T00:00:00Z"


def _boundary_loan(api):
    """
    The reference borrower funded with ``annual_debt_service_cents`` 36000200, so the
    DSCR denominator is 360002 dollars against the 432001-dollar numerator.
    """
    return chain_through_loan(
        api,
        loan_overrides={
            "annual_debt_service_cents": 36000200,
            "interest_reserve_shortfall_cents": 0,
        },
    )


def test_a_ratio_that_rounds_to_exactly_the_threshold_passes(api):
    """
    432001 / 360002 is 1.19999333... raw, but the stored ratio is 1.2000 and 1.2000 passes.

    PRD §3.8: "The ratio is the numerator divided by the denominator, rounded half up
    to four decimal places."

    PRD §3.8: "The test result is `PASS` when the ratio is greater than or equal to the
    covenant's `threshold_ratio` and `FAIL` otherwise — the boundary is inclusive, so a
    ratio landing exactly on the threshold passes."

    PRD §3.8: "The denominator is the loan's current `annual_debt_service_cents` divided
    by 100 and rounded half up to whole dollars; "current" matters, because an approved
    term-extension workout may have lowered it."

    Design: Difficulty/boundary_precision_check/dscr_ratio_exactly_at_threshold_passes
    """
    chain = _boundary_loan(api)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.2000)

    tested = get_success_data(
        api.run_covenant_test(covenant["id"], covenant_test_payload(AS_OF), LOAN_SERVICER)
    )

    assert_fields(
        tested,
        last_test_numerator_dollars=432001,
        last_test_denominator_dollars=360002,
        last_test_result="PASS",
        status="COMPLIANT",
        consecutive_fail_count=0,
        test_count=1,
    )
    assert_ratio(tested["last_test_ratio"], 1.2000, "last_test_ratio")
    assert_fields(chain.read_loan(), risk_posture="OPEN")


def test_one_ten_thousandth_either_side_of_the_ratio_splits_pass_from_fail(api):
    """
    The same numerator and denominator pass a 1.1999 threshold and fail a 1.2001 one.

    PRD §3.8: "The test result is `PASS` when the ratio is greater than or equal to the
    covenant's `threshold_ratio` and `FAIL` otherwise — the boundary is inclusive, so a
    ratio landing exactly on the threshold passes."

    PRD §3.8: "From `COMPLIANT`, a failing test moves the covenant `COMPLIANT →
    BREACH_PENDING_CURE` and sets `consecutive_fail_count` to 1."

    PRD §3.8: "This is the soft-breach window, and it is what drives the loan `OPEN →
    WATCH` on the risk dimension."

    Design: Difficulty/boundary_precision_check/dscr_ratio_exactly_at_threshold_passes
    """
    chain = _boundary_loan(api)
    at = build_covenant(api, chain.loan_id, threshold_ratio=1.2000)
    below = build_covenant(api, chain.loan_id, threshold_ratio=1.1999, test_frequency="ANNUAL")
    above = build_covenant(api, chain.loan_id, threshold_ratio=1.2001, test_frequency="ANNUAL")

    at_tested = get_success_data(
        api.run_covenant_test(at["id"], covenant_test_payload(AS_OF), LOAN_SERVICER)
    )
    below_tested = get_success_data(
        api.run_covenant_test(below["id"], covenant_test_payload(AS_OF), LOAN_SERVICER)
    )
    assert_fields(at_tested, last_test_result="PASS", status="COMPLIANT")
    assert_fields(below_tested, last_test_result="PASS", status="COMPLIANT")
    assert_fields(chain.read_loan(), risk_posture="OPEN")

    above_tested = get_success_data(
        api.run_covenant_test(above["id"], covenant_test_payload(AS_OF), LOAN_SERVICER)
    )

    assert_fields(
        above_tested,
        last_test_result="FAIL",
        status="BREACH_PENDING_CURE",
        consecutive_fail_count=1,
        last_test_numerator_dollars=432001,
        last_test_denominator_dollars=360002,
    )
    assert_ratio(above_tested["last_test_ratio"], 1.2000, "last_test_ratio")
    assert_fields(chain.read_loan(), risk_posture="WATCH")


def _three_period_borrower(api):
    """
    Institution with only 2025Q2, 2025Q3 and 2025Q4 filed, an AUTHORIZED packet and a
    DRAFT application for 225000000 over 240 months.
    """
    institution = build_institution(api)
    build_giving_periods(api, institution["id"], REFERENCE_AUDITED_QUARTERS[1:])
    authorization = build_authorized_authorization(api, institution["id"])
    application = build_draft_application(api, institution["id"], authorization["id"])
    return institution, application


def _read_institution(api, institution_id):
    return get_success_data(api.get_institution(institution_id, CREDIT_ANALYST))


def _submit(api, application_id, note):
    return api.submit_underwriting(
        application_id,
        submit_underwriting_payload(analyst_note=note),
        make_credit_analyst_headers(ANALYST_1),
    )


def test_three_filed_giving_periods_are_refused_and_leave_the_application_untouched(api):
    """
    The minimum is four and the gate is inclusive, so three periods cannot underwrite.

    PRD §2.10: "The institution has at least four recorded giving periods —
    `ERR_INSUFFICIENT_GIVING_HISTORY` (HTTP 422), on submit-underwriting."

    PRD §3.5: "The institution must have at least four giving periods on file, or the
    request is refused with `ERR_INSUFFICIENT_GIVING_HISTORY` — the giving base is
    undefined on a shorter history and would otherwise read as 0."

    PRD §3.5: "A new application opens in `DRAFT` with `revision_count` at 0 and every
    snapshot and audit field null: `giving_basis`, `giving_base_cents`,
    `net_available_dollars`, `collateral_lending_value_cents`,
    `max_supportable_principal_cents`, `prepared_by_user_id`, `decided_by_user_id` and
    `revision_reason`."

    Design: Difficulty/boundary_precision_check/submit_underwriting_with_three_giving_periods_rejected_four_accepted
    """
    institution, application = _three_period_borrower(api)
    assert_fields(
        _read_institution(api, institution["id"]), period_count=3, audited_period_count=3
    )

    validate_error(
        _submit(api, application["id"], "Attempt with three periods"),
        "ERR_INSUFFICIENT_GIVING_HISTORY",
        422,
    )

    after = get_success_data(api.get_loan_application(application["id"], CREDIT_ANALYST))
    assert_fields(after, status="DRAFT", version=application["version"])
    assert_nulls(
        after, "giving_basis", "giving_base_cents", "net_available_dollars", "prepared_by_user_id"
    )


def test_the_fourth_filed_period_flips_the_identical_submission_to_success(api):
    """
    Filing 2025Q1 completes the window and the same request snapshots the giving figures.

    PRD §3.1: "The window is then the first four candidates in that order."

    PRD §3.1: "Filing a period also reconciles its institution. `period_count` rises by
    1, and `audited_period_count` rises by 1 as well when the new period's `source` is
    `AUDITED`."

    PRD §3.5: "The mandated basis is resolved exactly as in §3.1 — `AUDITED_ONLY` when
    the institution's `audited_period_count` is 4 or more, `BLENDED` otherwise — and
    stored as `giving_basis`."

    PRD §3.5: "Only then sum the four rounded per-period dollar figures. That sum is the
    net-available-for-debt-service figure in whole dollars."

    Design: Difficulty/boundary_precision_check/submit_underwriting_with_three_giving_periods_rejected_four_accepted
    """
    institution, application = _three_period_borrower(api)
    validate_error(
        _submit(api, application["id"], "Attempt with three periods"),
        "ERR_INSUFFICIENT_GIVING_HISTORY",
        422,
    )

    build_giving_period(api, institution["id"], REFERENCE_AUDITED_QUARTERS[0])
    assert_fields(
        _read_institution(api, institution["id"]), period_count=4, audited_period_count=4
    )

    submitted = get_success_data(_submit(api, application["id"], "Attempt with four periods"))

    assert_fields(
        submitted,
        status="UNDERWRITING",
        giving_basis="AUDITED_ONLY",
        giving_base_cents=207000000,
        net_available_dollars=432001,
        prepared_by_user_id=ANALYST_1,
    )
