"""The determination cascade and the change-trigger cascade that unwinds it."""

from typing import Any, Dict

import pytest

from test_helpers import (
    AUDITOR_HEADERS,
    CLASSIFICATION_REVIEWER_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    AnalysisOutcome,
    AnalysisStatus,
    CLASSIFICATION_REVIEWER_ID,
    ClassificationStatus,
    DutiesValidationStatus,
    InterviewStatus,
    RemediationPosture,
    TriggerReasonCode,
    TriggerType,
    assert_family_risk,
    assert_money,
    assert_one_decimal,
    assert_project_ledgers,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)


@pytest.fixture
def duties_change_after_determination(api, determined_engagement) -> Dict[str, Any]:
    """A DUTIES_CHANGE trigger fires on the misclassified job, forcing re-analysis."""
    trigger = validate_success(
        api.create_job_change_trigger(
            factories.job_change_trigger_payload(
                determined_engagement["position_id"],
                TriggerType.DUTIES_CHANGE,
                new_exempt_duty_pct=62.0,
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )
    return {**determined_engagement, "trigger": trigger}


def test_nonexempt_determination_misclassifies_the_position(api, submitted_analysis):
    """The determination lands on the analysis and, through it, on the position.

    PRD: "Determining nonexemption branches on how the position is actually being paid: when the
    position's `current_fls_status` is `EXEMPT` the finding contradicts payroll practice and
    `classification_status` becomes `MISCLASSIFIED`; when `current_fls_status` is already
    `NONEXEMPT` the finding merely confirms practice and `classification_status` becomes
    `CONFIRMED_NONEXEMPT`."

    Design: Difficulty/transitive_cascade/nonexempt_determination_cascades_four_hops_to_frozen_project_posture
    """
    determined = fixtures.determine_analysis(api, submitted_analysis["analysis_id"])

    assert determined["status"] == AnalysisStatus.NONEXEMPT_DETERMINED, (
        f"the analysis must reach NONEXEMPT_DETERMINED, got {determined['status']}"
    )
    position = fixtures.read_position(api, submitted_analysis["position_id"])
    assert position["classification_status"] == ClassificationStatus.MISCLASSIFIED, (
        f"an EXEMPT-paid job with a nonexempt finding is MISCLASSIFIED, got {position['classification_status']}"
    )
    assert position["current_fls_status"] == "EXEMPT", (
        f"the finding alone does not touch payroll, got {position['current_fls_status']}"
    )


def test_nonexempt_determination_freezes_the_engagement_posture(api, submitted_analysis):
    """The fourth hop is reachable only through the family; the endpoint never writes it.

    PRD: "If **any** job family of the engagement has `risk_tier` equal to `CRITICAL` **and** an
    `open_misclassified_count` of at least 1, the posture is `FROZEN`."

    Design: Difficulty/transitive_cascade/nonexempt_determination_cascades_four_hops_to_frozen_project_posture
    """
    fixtures.determine_analysis(api, submitted_analysis["analysis_id"])

    family = fixtures.read_family(api, submitted_analysis["family_id"])
    assert_family_risk(family, 100, "CRITICAL", misclassified=1)

    project = fixtures.read_project(api, submitted_analysis["project_id"])
    assert_project_ledgers(project, headcount=2, posture=RemediationPosture.FROZEN)


def test_duties_change_supersedes_the_determination_and_voids_the_attested_pair(
    api, duties_change_after_determination
):
    """The trigger writes the override, supersedes the analysis and voids both accounts.

    PRD: "Fourth -- and **only** for `DUTIES_CHANGE` -- every `ATTESTED` interview of the position
    transitions to `VOIDED` with a `void_reason` of `CHANGE_TRIGGER_DUTIES`, which necessarily
    forces `duties_validation_status` back to `PENDING`."

    Design: Difficulty/transitive_cascade/duties_change_trigger_cascades_six_hops_back_to_open_posture
    """
    scenario = duties_change_after_determination
    trigger = scenario["trigger"]

    assert trigger["requires_reanalysis"] is True, (
        f"a 12.4 point duty swing forces re-analysis, got {trigger['requires_reanalysis']}"
    )
    assert trigger["reason_code"] == TriggerReasonCode.DUTY_DELTA_EXCEEDED, (
        f"the reason code names the duty delta, got {trigger['reason_code']}"
    )

    position = fixtures.read_position(api, scenario["position_id"])
    assert_one_decimal(
        position["self_reported_exempt_pct_override"], 62.0, "self_reported_exempt_pct_override"
    )
    assert position["classification_status"] == ClassificationStatus.UNREVIEWED, (
        f"the job returns to UNREVIEWED, got {position['classification_status']}"
    )

    analysis = fixtures.read_analysis(api, scenario["analysis_id"])
    assert analysis["status"] == AnalysisStatus.SUPERSEDED, (
        f"the determined analysis must be SUPERSEDED, got {analysis['status']}"
    )

    for label, interview in scenario["interviews"].items():
        voided = fixtures.read_interview(api, interview["id"])
        assert voided["status"] == InterviewStatus.VOIDED, (
            f"the {label} interview must be VOIDED, got {voided['status']}"
        )
        assert voided["void_reason"] == "CHANGE_TRIGGER_DUTIES", (
            f"the {label} void reason must name the duties change, got {voided['void_reason']!r}"
        )


def test_duties_change_rescores_the_family_and_reopens_the_posture(
    api, duties_change_after_determination
):
    """With the evidence voided the family re-scores under the screening variant.

    PRD: "If at least one position in the population still has `duties_validation_status` equal to
    `PENDING`, the family's `risk_variant` is `SCREENING`; if every position in the population has
    a `duties_validation_status` of `CORROBORATED` or `CONFLICTED`, the variant is
    `EVIDENCE_WEIGHTED`."

    Design: Difficulty/transitive_cascade/duties_change_trigger_cascades_six_hops_back_to_open_posture
    """
    scenario = duties_change_after_determination

    position = fixtures.read_position(api, scenario["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"the voided accounts drop the duties to PENDING, got {position['duties_validation_status']}"
    )
    assert_one_decimal(position["primary_duty_pct"], 62.0, "primary_duty_pct")
    assert position["validated_weekly_hours"] == 47, (
        "the employer-reported average is the fallback again, got "
        f"{position['validated_weekly_hours']}"
    )

    family = fixtures.read_family(api, scenario["family_id"])
    assert_family_risk(family, 72, "HIGH", variant="SCREENING", misclassified=0)

    project = fixtures.read_project(api, scenario["project_id"])
    assert_project_ledgers(project, headcount=0, posture=RemediationPosture.OPEN)


def test_determination_side_effects_are_visible_in_the_same_request_cycle(
    api, submitted_analysis
):
    """The determine response and the reads straight after it already show the settled cascade.

    PRD: "None of these values is client-writable, and none of them is computed lazily at read time
    -- every write that can move a derived value recomputes it immediately, in the same request,
    before the response is produced."

    Design: Corner/consistency_model/determination_side_effects_are_visible_in_the_same_request_cycle
    """
    determined = validate_success(
        api.determine_exemption_analysis(
            submitted_analysis["analysis_id"], CLASSIFICATION_REVIEWER_HEADERS
        ),
        200,
    )

    assert determined["status"] == AnalysisStatus.NONEXEMPT_DETERMINED, (
        f"the response itself must carry the new status, got {determined['status']}"
    )
    assert determined["outcome"] == AnalysisOutcome.NONEXEMPT, (
        f"the response itself must carry the outcome, got {determined['outcome']}"
    )
    assert determined["reviewer_user_id"] == CLASSIFICATION_REVIEWER_ID, (
        f"the deciding reviewer is recorded, got {determined['reviewer_user_id']!r}"
    )

    project = get_success_data(
        api.get_audit_project(submitted_analysis["project_id"], AUDITOR_HEADERS)
    )
    assert_project_ledgers(project, headcount=2, posture=RemediationPosture.FROZEN)

    family = get_success_data(
        api.get_job_family(submitted_analysis["family_id"], AUDITOR_HEADERS)
    )
    assert_family_risk(family, 100, "CRITICAL", misclassified=1)

    position = fixtures.read_position(api, submitted_analysis["position_id"])
    assert position["classification_status"] == ClassificationStatus.MISCLASSIFIED, (
        f"the job is already MISCLASSIFIED on the next read, got {position['classification_status']}"
    )


def test_salary_change_that_does_not_cross_the_floor_triggers_no_cascade(api, submitted_analysis):
    """A raise entirely on one side of the floor records a trigger row and nothing else.

    PRD: "**The trigger row is still created and recorded, but no attribute is written onto the
    position and no cascade runs at all.**"

    Design: Corner/state_machines/salary_change_that_does_not_cross_the_floor_triggers_no_cascade
    """
    trigger = validate_success(
        api.create_job_change_trigger(
            factories.job_change_trigger_payload(
                submitted_analysis["position_id"],
                TriggerType.SALARY_CHANGE,
                new_annual_salary_cents=6000000,
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )

    assert trigger["requires_reanalysis"] is False, (
        "both the old and the new weekly figure sit below the state floor, got "
        f"{trigger['requires_reanalysis']}"
    )
    assert trigger["reason_code"] == TriggerReasonCode.NO_REANALYSIS_REQUIRED, (
        f"the reason code must say no re-analysis is needed, got {trigger['reason_code']}"
    )

    position = fixtures.read_position(api, submitted_analysis["position_id"])
    assert_money(position["annual_salary_cents"], 5500000, "annual_salary_cents")
    assert_money(position["weekly_salary_cents"], 105769, "weekly_salary_cents")
    assert position["duties_validation_status"] == DutiesValidationStatus.CORROBORATED, (
        f"the validated duty picture must survive, got {position['duties_validation_status']}"
    )
    assert_one_decimal(position["primary_duty_pct"], 49.6, "primary_duty_pct")
    assert position["classification_status"] == ClassificationStatus.UNREVIEWED, (
        f"the job stays UNREVIEWED, got {position['classification_status']}"
    )

    analysis = fixtures.read_analysis(api, submitted_analysis["analysis_id"])
    assert analysis["status"] == AnalysisStatus.SUBMITTED, (
        f"the submitted analysis must not be superseded, got {analysis['status']}"
    )

    for label, interview in submitted_analysis["interviews"].items():
        still_attested = fixtures.read_interview(api, interview["id"])
        assert still_attested["status"] == InterviewStatus.ATTESTED, (
            f"the {label} interview must stay ATTESTED, got {still_attested['status']}"
        )

    family = fixtures.read_family(api, submitted_analysis["family_id"])
    assert_family_risk(family, 88, "CRITICAL", variant="EVIDENCE_WEIGHTED")

    project = fixtures.read_project(api, submitted_analysis["project_id"])
    assert_project_ledgers(project, posture=RemediationPosture.OPEN)
