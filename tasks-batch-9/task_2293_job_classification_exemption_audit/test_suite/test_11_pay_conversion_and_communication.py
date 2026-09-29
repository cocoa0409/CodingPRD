"""Pay-structure conversion, its reversal, and the independent employee-communication axis."""

from typing import Any, Dict

import pytest

from test_helpers import (
    COMPENSATION_MANAGER_HEADERS,
    EMPLOYEE_RELATIONS_LEAD_HEADERS,
    CaseStatus,
    ClassificationStatus,
    CommunicationAction,
    CommunicationStatus,
    ConversionMethod,
    CorrectionStatus,
    ErrorId,
    FlsStatus,
    NoticeChannel,
    PayConversionStatus,
    RemediationPosture,
    assert_family_risk,
    assert_money,
    assert_project_ledgers,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

EXPECTED_WEEKLY_HOURS = {"expected_weekly_hours": 47}
ESCALATION_REASON = "Incumbent disputes the overtime eligibility change"
EXPOSURE_CENTS = 22274928


def _misclassify(api, engagement: Dict[str, Any]) -> str:
    """Corroborate the job and determine it nonexempt so it becomes MISCLASSIFIED."""
    position_id = engagement["position_id"]
    fixtures.corroborate_duties(api, position_id, "int-1")
    analysis = fixtures.author_analysis(api, position_id)
    fixtures.submit_analysis(api, analysis["id"])
    fixtures.determine_analysis(api, analysis["id"])
    return analysis["id"]


@pytest.fixture
def cost_neutral_conversion_ready(api, willful_ca_engagement) -> Dict[str, Any]:
    """A misclassified job with a cost-neutral case carrying no exposure at all."""
    analysis_id = _misclassify(api, willful_ca_engagement)
    case = fixtures.open_case(
        api,
        willful_ca_engagement["position_id"],
        conversion_method=ConversionMethod.COST_NEUTRAL_WITH_OT,
    )
    return {**willful_ca_engagement, "analysis_id": analysis_id, "case_id": case["id"]}


@pytest.fixture
def funded_case(api, willful_ca_engagement) -> Dict[str, Any]:
    """The same case, now carrying a full-rate estimate and a proposed correction for it."""
    analysis_id = _misclassify(api, willful_ca_engagement)
    case = fixtures.open_case(
        api,
        willful_ca_engagement["position_id"],
        conversion_method=ConversionMethod.COST_NEUTRAL_WITH_OT,
    )
    fixtures.estimate_back_wages(api, case["id"])
    correction = fixtures.propose_correction(api, case["id"], EXPOSURE_CENTS)
    return {
        **willful_ca_engagement,
        "analysis_id": analysis_id,
        "case_id": case["id"],
        "correction_id": correction["id"],
    }


@pytest.fixture
def reverted_ready_case(api, funded_case) -> Dict[str, Any]:
    """The correction is approved and the conversion executed, so the ledger reads -1156."""
    fixtures.approve_correction(api, funded_case["correction_id"], EXPOSURE_CENTS)
    converted = validate_success(
        api.convert_pay(
            funded_case["case_id"], dict(EXPECTED_WEEKLY_HOURS), COMPENSATION_MANAGER_HEADERS
        ),
        200,
    )
    return {**funded_case, "converted": converted}


@pytest.fixture
def communicating_case(api, ca_engagement) -> Dict[str, Any]:
    """A case whose notice was sent, escalated and then sent again.

    The job is never determined, so the pay axis has nothing to do throughout.
    """
    case = fixtures.open_case(api, ca_engagement["position_id"])
    fixtures.send_notice(api, case["id"])
    validate_success(
        api.case_communication(
            case["id"],
            factories.communication_payload(
                CommunicationAction.ESCALATE,
                notice_channel=None,
                escalation_reason=ESCALATION_REASON,
            ),
            EMPLOYEE_RELATIONS_LEAD_HEADERS,
        ),
        200,
    )
    resent = fixtures.send_notice(api, case["id"], notice_channel=NoticeChannel.CERTIFIED_MAIL)
    return {**ca_engagement, "case_id": case["id"], "resent": resent}


def test_cost_neutral_conversion_solves_the_rate_from_the_unrounded_salary(
    api, cost_neutral_conversion_ready
):
    """The rate is solved in closed form against the premium-weighted hour denominator.

    PRD: "Under `COST_NEUTRAL_WITH_OT`, first form a denominator of hours as 40 plus one and a half
    times the overtime hours, then divide the annual salary by 52 times that denominator and round
    the quotient half up to a whole cent -- the rate is discounted by the overtime premium so that
    the projected cost lands within one rounding step of the old salary."

    Design: Difficulty/combinatorial_formula/cost_neutral_conversion_solves_closed_form_then_recosts_from_rounded_rate
    """
    converted = validate_success(
        api.convert_pay(
            cost_neutral_conversion_ready["case_id"],
            dict(EXPECTED_WEEKLY_HOURS),
            COMPENSATION_MANAGER_HEADERS,
        ),
        200,
    )

    assert converted["pay_conversion_status"] == PayConversionStatus.CONVERTED, (
        f"the pay axis must advance to CONVERTED, got {converted['pay_conversion_status']}"
    )
    assert_money(converted["converted_hourly_rate_cents"], 2094, "converted_hourly_rate_cents")
    assert_money(converted["projected_annual_cost_cents"], 5498844, "projected_annual_cost_cents")


def test_the_recosted_delta_is_not_zero_and_lands_on_the_engagement_ledger(
    api, cost_neutral_conversion_ready
):
    """Recosting from the rounded rate leaves a small negative residue, not a perfect zero.

    PRD: "Because the projected cost consumes the already-rounded rate, the delta is generally
    non-zero even under `COST_NEUTRAL_WITH_OT`, where it may land slightly negative; under
    `SALARY_DIV_2080` it is positive whenever `expected_weekly_hours` exceeds 40."

    Design: Difficulty/combinatorial_formula/cost_neutral_conversion_solves_closed_form_then_recosts_from_rounded_rate
    """
    converted = validate_success(
        api.convert_pay(
            cost_neutral_conversion_ready["case_id"],
            dict(EXPECTED_WEEKLY_HOURS),
            COMPENSATION_MANAGER_HEADERS,
        ),
        200,
    )

    assert_money(converted["cost_delta_cents"], -1156, "cost_delta_cents")
    assert converted["cost_delta_cents"] != 0, (
        "a rate solved by iteration to a fixed point would report a zero delta"
    )

    project = fixtures.read_project(api, cost_neutral_conversion_ready["project_id"])
    assert_project_ledgers(project, payroll_delta_cents=-1156)

    position = fixtures.read_position(api, cost_neutral_conversion_ready["position_id"])
    assert position["current_fls_status"] == FlsStatus.NONEXEMPT, (
        f"conversion rewrites the live status, got {position['current_fls_status']}"
    )
    assert position["overtime_eligible"] is True, (
        f"a NONEXEMPT job is overtime eligible, got {position['overtime_eligible']}"
    )
    assert position["classification_status"] == ClassificationStatus.RECLASSIFIED, (
        f"the job must move to RECLASSIFIED, got {position['classification_status']}"
    )


def test_pay_conversion_is_blocked_while_the_correction_is_only_proposed(api, funded_case):
    """The exposure crossed the mandatory threshold, so a proposal alone does not clear the gate.

    PRD: "**Cross-entity prerequisites for pay conversion.** The position is `MISCLASSIFIED`, and an
    `APPROVED` voluntary correction exists when the case's exposure reaches the mandatory-correction
    threshold, else `ERR_POSITION_NOT_MISCLASSIFIED` or `ERR_VOLUNTARY_CORRECTION_REQUIRED` (both
    409)."

    Design: Difficulty/cross_entity_state_dependency/pay_conversion_blocked_until_a_voluntary_correction_is_approved
    """
    validate_error(
        api.convert_pay(
            funded_case["case_id"], dict(EXPECTED_WEEKLY_HOURS), COMPENSATION_MANAGER_HEADERS
        ),
        ErrorId.VOLUNTARY_CORRECTION_REQUIRED,
        409,
    )

    case = fixtures.read_case(api, funded_case["case_id"])
    assert_money(case["exposure_cents"], EXPOSURE_CENTS, "exposure_cents")
    assert case["pay_conversion_status"] == PayConversionStatus.PENDING, (
        f"the refused conversion leaves the axis PENDING, got {case['pay_conversion_status']}"
    )
    assert case["converted_hourly_rate_cents"] is None, (
        f"no rate may be written, got {case['converted_hourly_rate_cents']!r}"
    )

    rows, _ = validate_paginated(
        api.list_case_voluntary_corrections(funded_case["case_id"], COMPENSATION_MANAGER_HEADERS)
    )
    assert len(rows) == 1, f"exactly one correction was proposed, got {len(rows)}"
    assert rows[0]["status"] == CorrectionStatus.PROPOSED, (
        f"a merely proposed correction does not clear the gate, got {rows[0]['status']}"
    )

    position = fixtures.read_position(api, funded_case["position_id"])
    assert position["classification_status"] == ClassificationStatus.MISCLASSIFIED, (
        f"the job stays MISCLASSIFIED, got {position['classification_status']}"
    )
    assert position["overtime_eligible"] is False, (
        f"the refused conversion does not touch payroll, got {position['overtime_eligible']}"
    )


def test_the_same_conversion_succeeds_once_the_correction_is_approved(api, funded_case):
    """The gate reads the sibling's live status, so approving it unblocks the identical call.

    PRD: "And when the case's `exposure_cents` has reached the mandatory-correction threshold of
    5,000,000 cents ($50,000), an `APPROVED` voluntary correction must already exist for that case,
    else `ERR_VOLUNTARY_CORRECTION_REQUIRED`; below that threshold no correction is required."

    Design: Difficulty/cross_entity_state_dependency/pay_conversion_blocked_until_a_voluntary_correction_is_approved
    """
    validate_error(
        api.convert_pay(
            funded_case["case_id"], dict(EXPECTED_WEEKLY_HOURS), COMPENSATION_MANAGER_HEADERS
        ),
        ErrorId.VOLUNTARY_CORRECTION_REQUIRED,
        409,
    )

    approved = fixtures.approve_correction(api, funded_case["correction_id"], EXPOSURE_CENTS)
    assert approved["status"] == CorrectionStatus.APPROVED, (
        f"the correction must reach APPROVED, got {approved['status']}"
    )

    converted = validate_success(
        api.convert_pay(
            funded_case["case_id"], dict(EXPECTED_WEEKLY_HOURS), COMPENSATION_MANAGER_HEADERS
        ),
        200,
    )
    assert converted["pay_conversion_status"] == PayConversionStatus.CONVERTED, (
        f"the identical call must now succeed, got {converted['pay_conversion_status']}"
    )
    assert_money(converted["converted_hourly_rate_cents"], 2094, "converted_hourly_rate_cents")


def test_reverting_the_conversion_returns_the_signed_payroll_ledger_to_zero(
    api, reverted_ready_case
):
    """The ledger holds a negative balance, so the compensation must subtract a negative number.

    PRD: "A revert clears `converted_hourly_rate_cents`, `projected_annual_cost_cents` and
    `cost_delta_cents` back to null, subtracts the previous `cost_delta_cents` from the engagement's
    `converted_annual_payroll_delta_cents` -- the same figure that was added, exactly reversed --
    sets the position's `current_fls_status` back to `EXEMPT`, which makes `overtime_eligible`
    false, moves `classification_status` from `RECLASSIFIED` back to `MISCLASSIFIED`, restores the
    family's `open_misclassified_count` and the engagement's misclassified headcount, recomputes the
    family and engagement derived figures, and increments the `version` of the case, the position,
    the family and the engagement."

    Design: Difficulty/compensating_invariant/reverting_a_pay_conversion_restores_the_converted_payroll_delta_ledger
    """
    before = fixtures.read_project(api, reverted_ready_case["project_id"])
    assert_project_ledgers(before, payroll_delta_cents=-1156)

    reverted = validate_success(
        api.revert_pay_conversion(reverted_ready_case["case_id"], COMPENSATION_MANAGER_HEADERS),
        200,
    )

    assert reverted["pay_conversion_status"] == PayConversionStatus.REVERTED, (
        f"the pay axis must land on REVERTED, got {reverted['pay_conversion_status']}"
    )
    assert reverted["converted_hourly_rate_cents"] is None, (
        f"the rate must be cleared, got {reverted['converted_hourly_rate_cents']!r}"
    )
    assert reverted["projected_annual_cost_cents"] is None, (
        f"the projected cost must be cleared, got {reverted['projected_annual_cost_cents']!r}"
    )
    assert reverted["cost_delta_cents"] is None, (
        f"the delta must be cleared, got {reverted['cost_delta_cents']!r}"
    )

    after = fixtures.read_project(api, reverted_ready_case["project_id"])
    assert_project_ledgers(after, payroll_delta_cents=0)
    assert after["converted_annual_payroll_delta_cents"] != -2312, (
        "adding the delta a second time instead of subtracting it would reach -2312"
    )


def test_reverting_the_conversion_releases_no_committed_correction_money(api, reverted_ready_case):
    """The approved correction is a separate commitment that reverting payroll must not touch.

    PRD: "The `committed_correction_cents` sums `approved_amount_cents` over the engagement's
    voluntary corrections whose `status` is `APPROVED`."

    Design: Difficulty/compensating_invariant/reverting_a_pay_conversion_restores_the_converted_payroll_delta_ledger
    """
    validate_success(
        api.revert_pay_conversion(reverted_ready_case["case_id"], COMPENSATION_MANAGER_HEADERS),
        200,
    )

    case = fixtures.read_case(api, reverted_ready_case["case_id"])
    assert_money(case["exposure_cents"], EXPOSURE_CENTS, "exposure_cents after the revert")
    assert case["communication_status"] == CommunicationStatus.NOT_STARTED, (
        f"the communication axis was never driven, got {case['communication_status']}"
    )

    rows, _ = validate_paginated(
        api.list_case_voluntary_corrections(
            reverted_ready_case["case_id"], COMPENSATION_MANAGER_HEADERS
        )
    )
    assert rows[0]["status"] == CorrectionStatus.APPROVED, (
        f"the correction stays APPROVED, got {rows[0]['status']}"
    )

    position = fixtures.read_position(api, reverted_ready_case["position_id"])
    assert position["current_fls_status"] == FlsStatus.EXEMPT, (
        f"the live status must be restored to EXEMPT, got {position['current_fls_status']}"
    )
    assert position["overtime_eligible"] is False, (
        f"an EXEMPT job is not overtime eligible, got {position['overtime_eligible']}"
    )
    assert position["classification_status"] == ClassificationStatus.MISCLASSIFIED, (
        f"the job returns to MISCLASSIFIED, got {position['classification_status']}"
    )

    family = fixtures.read_family(api, reverted_ready_case["family_id"])
    assert_family_risk(family, 100, "CRITICAL", misclassified=1)

    project = fixtures.read_project(api, reverted_ready_case["project_id"])
    assert_project_ledgers(
        project,
        headcount=2,
        committed_correction_cents=EXPOSURE_CENTS,
        posture=RemediationPosture.FROZEN,
    )


def test_the_communication_axis_returns_to_notice_sent_after_an_escalation(api, communicating_case):
    """Three consecutive transitions put the axis back in a state it already held.

    PRD: "A re-send from `ESCALATED` clears `escalation_reason` back to null and refreshes
    `notice_sent_at`."

    Design: Difficulty/non_linear_state_machine/communication_dimension_escalates_and_renotifies_while_pay_dimension_holds
    """
    resent = communicating_case["resent"]

    assert resent["communication_status"] == CommunicationStatus.NOTICE_SENT, (
        f"the axis must re-enter NOTICE_SENT, got {resent['communication_status']}"
    )
    assert resent["escalation_reason"] is None, (
        f"the re-send clears the escalation reason, got {resent['escalation_reason']!r}"
    )

    case = fixtures.read_case(api, communicating_case["case_id"])
    assert case["communication_status"] == CommunicationStatus.NOTICE_SENT, (
        f"the stored row agrees with the response, got {case['communication_status']}"
    )
    assert case["escalation_reason"] is None, (
        f"the stored row carries no escalation reason, got {case['escalation_reason']!r}"
    )


def test_the_pay_axis_holds_while_the_communication_axis_moves_three_times(
    api, communicating_case
):
    """Neither axis drags the other, and their conjunction keeps the case OPEN.

    PRD: "The computed `case_status` is their conjunction: it is `COMPLETED` exactly when
    `pay_conversion_status` is `CONVERTED` **and** `communication_status` is `ACKNOWLEDGED`, and
    `OPEN` in every other combination."

    Design: Difficulty/non_linear_state_machine/communication_dimension_escalates_and_renotifies_while_pay_dimension_holds
    """
    case = fixtures.read_case(api, communicating_case["case_id"])

    assert case["pay_conversion_status"] == PayConversionStatus.PENDING, (
        f"the pay axis must not have moved, got {case['pay_conversion_status']}"
    )
    assert case["converted_hourly_rate_cents"] is None, (
        f"no rate may exist, got {case['converted_hourly_rate_cents']!r}"
    )
    assert case["cost_delta_cents"] is None, (
        f"no delta may exist, got {case['cost_delta_cents']!r}"
    )
    assert case["case_status"] == CaseStatus.OPEN, (
        f"a PENDING pay axis keeps the case OPEN, got {case['case_status']}"
    )

    position = fixtures.read_position(api, communicating_case["position_id"])
    assert position["current_fls_status"] == FlsStatus.EXEMPT, (
        f"communication never touches payroll, got {position['current_fls_status']}"
    )
    assert position["overtime_eligible"] is False, (
        f"an EXEMPT job is not overtime eligible, got {position['overtime_eligible']}"
    )


def test_a_notice_sent_inside_the_state_lead_time_is_rejected(api, ca_engagement):
    """Four days of lead time falls short of California's seven-day minimum.

    PRD: "Both edges are gated on lead time: the number of calendar days from the logical clock's
    date to the case's `effective_date` must be at least the jurisdiction's `reclass_notice_days`
    for the position's `work_state_code`, else `ERR_NOTICE_WINDOW_TOO_SHORT`."

    Design: Corner/errors/notice_sent_inside_the_state_lead_time_is_rejected
    """
    case = fixtures.open_case(
        api,
        ca_engagement["position_id"],
        effective_date="2026-08-05",
        effective_end_date="2026-08-20",
    )

    validate_error(
        api.case_communication(
            case["id"], factories.communication_payload(), EMPLOYEE_RELATIONS_LEAD_HEADERS
        ),
        ErrorId.NOTICE_WINDOW_TOO_SHORT,
        409,
    )

    unchanged = fixtures.read_case(api, case["id"])
    assert unchanged["communication_status"] == CommunicationStatus.NOT_STARTED, (
        f"the refused notice leaves the axis NOT_STARTED, got {unchanged['communication_status']}"
    )
    assert unchanged["notice_sent_at"] is None, (
        f"no send timestamp may be stamped, got {unchanged['notice_sent_at']!r}"
    )
    assert unchanged["notice_channel"] is None, (
        f"no channel may be recorded, got {unchanged['notice_channel']!r}"
    )
