"""The analysis review loop: return, resubmit, rescind, and the guards around them."""

from typing import Any, Dict

import pytest

from test_helpers import (
    CLASSIFICATION_REVIEWER_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    DUAL_HAT_ANALYST_HEADERS,
    DUAL_HAT_REVIEWER_HEADERS,
    AnalysisOutcome,
    AnalysisStatus,
    CLASSIFICATION_REVIEWER_ID,
    ClassificationStatus,
    DutiesValidationStatus,
    ErrorId,
    ExemptionTest,
    RemediationPosture,
    RespondentType,
    TriggerReasonCode,
    TriggerType,
    assert_family_risk,
    assert_money,
    assert_one_decimal,
    assert_project_ledgers,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

RETURN_REASON = "Attach the corroborated supervision evidence"
RESCIND_REASON = "Determination rescinded pending counsel review of the supervision evidence"


@pytest.fixture
def resubmitted_analysis(api, submitted_analysis) -> Dict[str, Any]:
    """The reviewer returns the submitted analysis and the analyst sends it back in."""
    get_success_data(
        api.return_exemption_analysis(
            submitted_analysis["analysis_id"],
            {"return_reason": RETURN_REASON},
            CLASSIFICATION_REVIEWER_HEADERS,
        )
    )
    resubmitted = fixtures.submit_analysis(api, submitted_analysis["analysis_id"])
    return {**submitted_analysis, "analysis": resubmitted}


@pytest.fixture
def half_attested_draft(api, ca_engagement) -> Dict[str, Any]:
    """Only the manager account is attested, so the job's duties are still PENDING."""
    position_id = ca_engagement["position_id"]
    manager = fixtures.book_interview(
        api, position_id, "int-5", ("2026-09-16T09:00:00Z", "2026-09-16T10:00:00Z")
    )
    fixtures.complete_interview(api, manager["id"], (46.0, 45, 3, True))
    fixtures.attest_interview(api, manager["id"])
    incumbent = fixtures.book_interview(
        api,
        position_id,
        "int-5",
        ("2026-09-16T10:00:00Z", "2026-09-16T11:00:00Z"),
        RespondentType.INCUMBENT,
        "INC-1",
    )
    fixtures.complete_interview(api, incumbent["id"], (52.0, 49, 2, True))
    analysis = fixtures.author_analysis(api, position_id)
    return {**ca_engagement, "analysis_id": analysis["id"], "incumbent_interview": incumbent}


@pytest.fixture
def dual_hat_draft(api, corroborated_engagement) -> Dict[str, Any]:
    """One person authored the DRAFT analysis and also wears the reviewer hat."""
    analysis = fixtures.author_analysis(
        api, corroborated_engagement["position_id"], headers=DUAL_HAT_ANALYST_HEADERS
    )
    return {**corroborated_engagement, "analysis_id": analysis["id"]}


@pytest.fixture
def rescinded_determination(api, determined_engagement) -> Dict[str, Any]:
    """The reviewer rescinds the nonexemption determination they had just made."""
    rescinded = get_success_data(
        api.return_exemption_analysis(
            determined_engagement["analysis_id"],
            {"return_reason": RESCIND_REASON},
            CLASSIFICATION_REVIEWER_HEADERS,
        )
    )
    return {**determined_engagement, "analysis": rescinded}


def test_resubmission_loops_back_to_submitted_and_counts_the_revision_round(
    api, resubmitted_analysis
):
    """The analysis re-enters a state it already occupied and the loop counter advances.

    PRD: "The analyst then resubmits, advancing `RETURNED -> SUBMITTED`; this is a genuine loop
    with no bound on how many times it may be traversed."

    Design: Difficulty/non_linear_state_machine/analysis_return_then_resubmit_increments_revision_round_and_reevaluates
    """
    analysis = resubmitted_analysis["analysis"]

    assert analysis["status"] == AnalysisStatus.SUBMITTED, (
        f"the resubmission must land back in SUBMITTED, got {analysis['status']}"
    )
    assert analysis["revision_round"] == 1, (
        f"the first resubmission makes this revision round 1, got {analysis['revision_round']}"
    )
    assert analysis["reviewer_user_id"] == CLASSIFICATION_REVIEWER_ID, (
        "the reviewer who returned the analysis stays recorded on it, got "
        f"{analysis['reviewer_user_id']!r}"
    )


def test_resubmission_reevaluates_the_position_from_scratch(api, resubmitted_analysis):
    """The second evaluation re-snapshots live figures rather than replaying the old answer.

    PRD: "Each resubmission increments `revision_round` by one -- that counter is the observable
    measure of how many revision rounds an analysis has been through -- and re-snapshots and
    re-evaluates the position's current figures from scratch, so a resubmission after a salary or
    duty change reaches a different answer than the first submission did."

    Design: Difficulty/non_linear_state_machine/analysis_return_then_resubmit_increments_revision_round_and_reevaluates
    """
    analysis = resubmitted_analysis["analysis"]

    assert_one_decimal(analysis["primary_duty_pct_snapshot"], 49.6, "primary_duty_pct_snapshot")
    assert_money(
        analysis["applicable_salary_floor_cents"], 132000, "applicable_salary_floor_cents"
    )
    assert analysis["outcome"] == AnalysisOutcome.NONEXEMPT, (
        f"the re-evaluated outcome is still NONEXEMPT, got {analysis['outcome']}"
    )
    position = fixtures.read_position(api, resubmitted_analysis["position_id"])
    assert position["classification_status"] == ClassificationStatus.UNREVIEWED, (
        "a submission is not a determination, so the job stays UNREVIEWED, got "
        f"{position['classification_status']}"
    )


def test_submit_is_refused_while_the_position_duties_are_pending(api, half_attested_draft):
    """The analysis transition is legal on its own terms yet blocked by the other entity.

    PRD: "Submission is refused while the position's `duties_validation_status` is `PENDING`, with
    `ERR_DUTIES_NOT_CORROBORATED`; the audit will not stake a determination on an uncorroborated
    duty picture."

    Design: Difficulty/cross_entity_state_dependency/analysis_submit_blocked_by_position_duties_validation_state
    """
    validate_error(
        api.submit_exemption_analysis(
            half_attested_draft["analysis_id"], COMPLIANCE_ANALYST_HEADERS
        ),
        ErrorId.DUTIES_NOT_CORROBORATED,
        409,
    )

    position = fixtures.read_position(api, half_attested_draft["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"a completed but unattested account leaves PENDING, got {position['duties_validation_status']}"
    )
    assert position["corroborated_supervises_headcount"] == 0, (
        "nothing was corroborated, got "
        f"{position['corroborated_supervises_headcount']}"
    )
    assert position["corroborated_hire_fire_influence"] is False, (
        f"nothing was corroborated, got {position['corroborated_hire_fire_influence']}"
    )
    refused = fixtures.read_analysis(api, half_attested_draft["analysis_id"])
    assert refused["status"] == AnalysisStatus.DRAFT, (
        f"the refused analysis stays DRAFT, got {refused['status']}"
    )


def test_the_same_submit_succeeds_once_the_missing_account_is_attested(api, half_attested_draft):
    """The gate reads live position state, so attesting the second account unblocks it.

    PRD: "**Duties corroborated.** The position's `duties_validation_status` is not `PENDING` when
    an analysis is submitted, else `ERR_DUTIES_NOT_CORROBORATED` (409)."

    Design: Difficulty/cross_entity_state_dependency/analysis_submit_blocked_by_position_duties_validation_state
    """
    validate_error(
        api.submit_exemption_analysis(
            half_attested_draft["analysis_id"], COMPLIANCE_ANALYST_HEADERS
        ),
        ErrorId.DUTIES_NOT_CORROBORATED,
        409,
    )

    fixtures.attest_interview(api, half_attested_draft["incumbent_interview"]["id"])

    position = fixtures.read_position(api, half_attested_draft["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.CORROBORATED, (
        f"the attested pair must corroborate, got {position['duties_validation_status']}"
    )

    submitted = validate_success(
        api.submit_exemption_analysis(
            half_attested_draft["analysis_id"], COMPLIANCE_ANALYST_HEADERS
        ),
        200,
    )
    assert submitted["status"] == AnalysisStatus.SUBMITTED, (
        f"the identical request must now succeed, got {submitted['status']}"
    )
    assert_one_decimal(submitted["primary_duty_pct_snapshot"], 49.6, "primary_duty_pct_snapshot")


def test_invalid_state_transition_outranks_self_review_on_determine(api, dual_hat_draft):
    """The author calls determine on a DRAFT analysis; the state error wins over the 403.

    PRD: "Because the declared-transition check sits at rank 8 and segregation of duties at rank
    10, an analyst who tries to return their own analysis while it is still in `DRAFT` receives
    `ERR_INVALID_STATE_TRANSITION`, not `ERR_SEGREGATION_OF_DUTIES` -- the same actor gets the
    segregation error only once the analysis is genuinely in a returnable state."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_transition_outranks_self_review_on_determine
    """
    error_data = validate_error(
        api.determine_exemption_analysis(
            dual_hat_draft["analysis_id"], DUAL_HAT_REVIEWER_HEADERS
        ),
        ErrorId.INVALID_STATE_TRANSITION,
        409,
    )

    assert error_data["error_id"] != ErrorId.SEGREGATION_OF_DUTIES, (
        "the lower-ranked self-review rule must not surface even though the actor is the analyst"
    )


def test_the_refused_determine_leaves_the_analysis_and_the_position_untouched(api, dual_hat_draft):
    """A rejected determination records no reviewer and moves no classification.

    PRD: "A `ClassificationReviewer` whose `X-User-ID` equals that recorded `analyst_user_id` may
    neither return the analysis nor determine it; either attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_transition_outranks_self_review_on_determine
    """
    validate_error(
        api.determine_exemption_analysis(
            dual_hat_draft["analysis_id"], DUAL_HAT_REVIEWER_HEADERS
        ),
        ErrorId.INVALID_STATE_TRANSITION,
        409,
    )

    analysis = fixtures.read_analysis(api, dual_hat_draft["analysis_id"])
    assert analysis["status"] == AnalysisStatus.DRAFT, (
        f"the analysis must stay DRAFT, got {analysis['status']}"
    )
    assert analysis["reviewer_user_id"] is None, (
        f"no reviewer may be recorded, got {analysis['reviewer_user_id']!r}"
    )
    position = fixtures.read_position(api, dual_hat_draft["position_id"])
    assert position["classification_status"] == ClassificationStatus.UNREVIEWED, (
        f"the job must stay UNREVIEWED, got {position['classification_status']}"
    )


def test_rescission_returns_the_determined_analysis_and_reopens_the_position(
    api, rescinded_determination
):
    """Returning an already-determined analysis puts it back in the revision loop.

    PRD: "A `ClassificationReviewer` other than the author may return an analysis that has already
    been determined, advancing `EXEMPT_CONFIRMED -> RETURNED` or `NONEXEMPT_DETERMINED ->
    RETURNED`, recording `reviewer_user_id` and `return_reason`."

    Design: Difficulty/compensating_invariant/rescinding_a_determination_restores_the_open_misclassified_headcount_ledger
    """
    analysis = rescinded_determination["analysis"]

    assert analysis["status"] == AnalysisStatus.RETURNED, (
        f"the rescinded analysis must sit in RETURNED, got {analysis['status']}"
    )
    assert analysis["revision_round"] == 0, (
        f"a rescission is not a revision round, got {analysis['revision_round']}"
    )
    assert analysis["reviewer_user_id"] == CLASSIFICATION_REVIEWER_ID, (
        f"the rescinding reviewer is recorded, got {analysis['reviewer_user_id']!r}"
    )

    position = fixtures.read_position(api, rescinded_determination["position_id"])
    assert position["classification_status"] == ClassificationStatus.UNREVIEWED, (
        f"the job returns to UNREVIEWED, got {position['classification_status']}"
    )
    assert position["current_fls_status"] == "EXEMPT", (
        "rescission does not touch the job's live status, got "
        f"{position['current_fls_status']}"
    )
    assert position["overtime_eligible"] is False, (
        f"an EXEMPT job is not overtime eligible, got {position['overtime_eligible']}"
    )


def test_rescission_restores_the_family_and_engagement_ledgers_exactly(
    api, rescinded_determination
):
    """Every counter the determination moved comes back to its pre-determination value.

    PRD: "Rescinding from `NONEXEMPT_DETERMINED` reverts `classification_status` to `UNREVIEWED`,
    decrements the family's `open_misclassified_count`, recomputes the family's `risk_score` and
    `risk_tier`, subtracts the position's `incumbent_count` from the engagement's
    `open_misclassified_headcount`, and recomputes the engagement's `remediation_posture` and
    `total_back_wage_exposure_cents`."

    Design: Difficulty/compensating_invariant/rescinding_a_determination_restores_the_open_misclassified_headcount_ledger
    """
    family = fixtures.read_family(api, rescinded_determination["family_id"])
    assert_family_risk(family, 88, "CRITICAL", variant="EVIDENCE_WEIGHTED", misclassified=0)

    project = fixtures.read_project(api, rescinded_determination["project_id"])
    assert_project_ledgers(
        project,
        headcount=0,
        payroll_delta_cents=0,
        posture=RemediationPosture.OPEN,
    )


def test_stale_position_version_blocks_the_analysis_create_then_the_fresh_one_succeeds(
    api, corroborated_engagement
):
    """The version read before a change trigger is refused; the version read after is accepted.

    PRD: "If the position's `version` has advanced since the client last read it -- because a duty
    statement was added, an interview was attested, or an earlier analysis was opened against the
    same position -- the create is rejected with `ERR_STALE_POSITION_VERSION` and HTTP 412."

    Design: Corner/complexity_layers/stale_position_version_blocks_the_analysis_create_then_the_fresh_one_succeeds
    """
    position_id = corroborated_engagement["position_id"]
    stale_version = fixtures.read_position(api, position_id)["version"]

    trigger = validate_success(
        api.create_job_change_trigger(
            factories.job_change_trigger_payload(
                position_id, TriggerType.DUTIES_CHANGE, new_exempt_duty_pct=62.0
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )
    assert trigger["requires_reanalysis"] is True, (
        f"a 12.4 point duty swing forces re-analysis, got {trigger['requires_reanalysis']}"
    )
    assert trigger["reason_code"] == TriggerReasonCode.DUTY_DELTA_EXCEEDED, (
        f"the reason code names the duty delta, got {trigger['reason_code']}"
    )

    validate_error(
        api.create_exemption_analysis(
            factories.exemption_analysis_payload(
                position_id, stale_version, applied_test=ExemptionTest.EXECUTIVE
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        ErrorId.STALE_POSITION_VERSION,
        412,
    )

    fresh_version = fixtures.read_position(api, position_id)["version"]
    assert fresh_version > stale_version, (
        f"the trigger must advance the version past {stale_version}, got {fresh_version}"
    )

    created = validate_success(
        api.create_exemption_analysis(
            factories.exemption_analysis_payload(
                position_id, fresh_version, applied_test=ExemptionTest.EXECUTIVE
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )
    assert created["status"] == AnalysisStatus.DRAFT, (
        f"the accepted create starts in DRAFT, got {created['status']}"
    )
    assert created["revision_round"] == 0, (
        f"a fresh analysis starts at revision round 0, got {created['revision_round']}"
    )

    rows, meta = validate_paginated(
        api.list_position_exemption_analyses(position_id, COMPLIANCE_ANALYST_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"the refused create must have written nothing, got {meta['total_count']} rows"
    )
    assert len(rows) == 1, f"exactly one analysis may exist, got {len(rows)}"
    assert rows[0]["id"] == created["id"], "the surviving analysis is the one created fresh"
