"""Voluntary corrections: who may propose, who may decide, and the two fiscal guards."""

from typing import Any, Dict

import pytest

from test_helpers import (
    COMPENSATION_MANAGER_HEADERS,
    COMPENSATION_MANAGER_ID,
    LEGAL_COUNSEL_HEADERS,
    LEGAL_COUNSEL_ID,
    LEGAL_COUNSEL_SECOND_HEADERS,
    LEGAL_COUNSEL_SECOND_ID,
    ConversionMethod,
    CorrectionDecision,
    CorrectionStatus,
    ErrorId,
    PayConversionStatus,
    assert_money,
    assert_project_ledgers,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

OVER_CAP_CENTS = 30000000
FULL_EXPOSURE_CENTS = 22274928
UNINTERVIEWED_EXPOSURE_CENTS = 17324736
REJECTION_REASON = "PARTIAL_POSTURE_NOT_DEFENSIBLE"


def _misclassify(api, engagement: Dict[str, Any]) -> str:
    """Corroborate the job and determine it nonexempt so it becomes MISCLASSIFIED."""
    position_id = engagement["position_id"]
    fixtures.corroborate_duties(api, position_id, "int-1")
    analysis = fixtures.author_analysis(api, position_id)
    fixtures.submit_analysis(api, analysis["id"])
    fixtures.determine_analysis(api, analysis["id"])
    return analysis["id"]


@pytest.fixture
def over_cap_proposal(api, willful_ca_engagement) -> Dict[str, Any]:
    """Counsel lc-7 proposed a full self-correction above the delegated authority cap."""
    _misclassify(api, willful_ca_engagement)
    case = fixtures.open_case(
        api,
        willful_ca_engagement["position_id"],
        conversion_method=ConversionMethod.COST_NEUTRAL_WITH_OT,
    )
    fixtures.estimate_back_wages(api, case["id"])
    correction = fixtures.propose_correction(
        api, case["id"], OVER_CAP_CENTS, headers=LEGAL_COUNSEL_SECOND_HEADERS
    )
    return {
        **willful_ca_engagement,
        "case_id": case["id"],
        "correction_id": correction["id"],
        "correction": correction,
    }


@pytest.fixture
def underfunded_proposal(api, willful_ca_engagement) -> Dict[str, Any]:
    """No interviews, so the exposure rests on the employer-reported 47 hours."""
    case = fixtures.open_case(api, willful_ca_engagement["position_id"])
    estimate = fixtures.estimate_back_wages(api, case["id"])
    correction = fixtures.propose_correction(api, case["id"], UNINTERVIEWED_EXPOSURE_CENTS)
    return {
        **willful_ca_engagement,
        "case_id": case["id"],
        "estimate": estimate,
        "correction_id": correction["id"],
    }


@pytest.fixture
def partial_proposal(api, ca_engagement) -> Dict[str, Any]:
    """A partial posture proposed by the compensation manager, awaiting counsel."""
    case = fixtures.open_case(api, ca_engagement["position_id"])
    correction = fixtures.propose_correction(
        api, case["id"], 400000, CorrectionDecision.SELF_CORRECT_PARTIAL
    )
    return {**ca_engagement, "case_id": case["id"], "correction_id": correction["id"]}


def test_self_approval_outranks_the_authority_cap_and_returns_the_forbidden_error(
    api, over_cap_proposal
):
    """One request breaks two rules at once; the higher-ranked safety rule decides the answer.

    PRD: "The checks below are evaluated **strictly in this order**; the first rule that is violated
    determines the response, and no later rule runs."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_approval_authority_cap_and_returns_403
    """
    error_data = validate_error(
        api.decide_voluntary_correction(
            over_cap_proposal["correction_id"],
            factories.correction_approval_payload(OVER_CAP_CENTS),
            LEGAL_COUNSEL_SECOND_HEADERS,
        ),
        ErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    assert error_data["error_id"] != ErrorId.APPROVAL_AUTHORITY_EXCEEDED, (
        "the lower-ranked fiscal cap must not surface even though the amount exceeds it"
    )

    rows, _ = validate_paginated(
        api.list_case_voluntary_corrections(
            over_cap_proposal["case_id"], COMPENSATION_MANAGER_HEADERS
        )
    )
    correction = rows[0]
    assert correction["status"] == CorrectionStatus.PROPOSED, (
        f"the refused decision leaves the correction PROPOSED, got {correction['status']}"
    )
    assert correction["approved_amount_cents"] is None, (
        f"no amount may be authorized, got {correction['approved_amount_cents']!r}"
    )
    assert correction["approver_user_id"] is None, (
        f"no approver may be recorded, got {correction['approver_user_id']!r}"
    )
    assert correction["proposed_by_user_id"] == LEGAL_COUNSEL_SECOND_ID, (
        f"the proposer is the counsel who filed it, got {correction['proposed_by_user_id']!r}"
    )

    case = fixtures.read_case(api, over_cap_proposal["case_id"])
    assert case["pay_conversion_status"] == PayConversionStatus.PENDING, (
        f"the pay axis must not move, got {case['pay_conversion_status']}"
    )
    assert_money(case["exposure_cents"], FULL_EXPOSURE_CENTS, "exposure_cents")


def test_a_second_counsel_hits_the_authority_cap_the_self_approval_had_masked(
    api, over_cap_proposal
):
    """With segregation satisfied the fiscal cap becomes visible on the identical amount.

    PRD: "Two fiscal guards apply, in this order: the approved amount may not exceed the delegated
    authority cap of 25,000,000 cents ($250,000), else `ERR_APPROVAL_AUTHORITY_EXCEEDED`; and a
    `SELF_CORRECT_FULL` posture must actually be funded, meaning the approved amount must be at
    least the case's `exposure_cents`, else `ERR_CORRECTION_AMOUNT_BELOW_EXPOSURE`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_approval_authority_cap_and_returns_403
    """
    validate_error(
        api.decide_voluntary_correction(
            over_cap_proposal["correction_id"],
            factories.correction_approval_payload(OVER_CAP_CENTS),
            LEGAL_COUNSEL_HEADERS,
        ),
        ErrorId.APPROVAL_AUTHORITY_EXCEEDED,
        409,
    )

    project = fixtures.read_project(api, over_cap_proposal["project_id"])
    assert_project_ledgers(project, committed_correction_cents=0)


def test_an_underfunded_full_self_correction_is_refused(api, underfunded_proposal):
    """A full posture approved for less than the exposure fails the funding guard, not the cap.

    PRD: "The funding guard applies only to the `SELF_CORRECT_FULL` posture; a partial, deferred or
    agency-supervised correction may be approved for any amount inside the authority cap."

    Design: Corner/errors/underfunded_self_correction_approval_is_rejected
    """
    assert_money(
        underfunded_proposal["estimate"]["total_exposure_cents"],
        UNINTERVIEWED_EXPOSURE_CENTS,
        "total_exposure_cents",
    )

    validate_error(
        api.decide_voluntary_correction(
            underfunded_proposal["correction_id"],
            factories.correction_approval_payload(17000000),
            LEGAL_COUNSEL_HEADERS,
        ),
        ErrorId.CORRECTION_AMOUNT_BELOW_EXPOSURE,
        409,
    )

    case = fixtures.read_case(api, underfunded_proposal["case_id"])
    assert_money(case["exposure_cents"], UNINTERVIEWED_EXPOSURE_CENTS, "exposure_cents")

    rows, _ = validate_paginated(
        api.list_case_voluntary_corrections(
            underfunded_proposal["case_id"], COMPENSATION_MANAGER_HEADERS
        )
    )
    correction = rows[0]
    assert correction["status"] == CorrectionStatus.PROPOSED, (
        f"the refused approval leaves the correction PROPOSED, got {correction['status']}"
    )
    assert correction["approved_amount_cents"] is None, (
        f"no amount may be authorized, got {correction['approved_amount_cents']!r}"
    )
    assert correction["approver_user_id"] is None, (
        f"no approver may be recorded, got {correction['approver_user_id']!r}"
    )

    project = fixtures.read_project(api, underfunded_proposal["project_id"])
    assert_project_ledgers(project, committed_correction_cents=0)


def test_rejecting_a_correction_leaves_the_committed_ledger_untouched(api, partial_proposal):
    """The money side effect belongs to the approval branch alone.

    PRD: "Rejection advances `PROPOSED -> REJECTED`, records the `rejection_reason` and the
    `approver_user_id`, increments only the correction's `version`, and moves no money into the
    engagement rollup."

    Design: Corner/endpoints/rejecting_a_correction_leaves_the_committed_ledger_untouched
    """
    rejected = validate_success(
        api.decide_voluntary_correction(
            partial_proposal["correction_id"],
            factories.correction_rejection_payload(REJECTION_REASON),
            LEGAL_COUNSEL_HEADERS,
        ),
        200,
    )

    assert rejected["status"] == CorrectionStatus.REJECTED, (
        f"the correction must reach REJECTED, got {rejected['status']}"
    )
    assert rejected["rejection_reason"] == REJECTION_REASON, (
        f"the reason must be recorded verbatim, got {rejected['rejection_reason']!r}"
    )
    assert rejected["approver_user_id"] == LEGAL_COUNSEL_ID, (
        f"the deciding counsel is recorded, got {rejected['approver_user_id']!r}"
    )
    assert rejected["approved_amount_cents"] is None, (
        f"the rejection branch authorizes nothing, got {rejected['approved_amount_cents']!r}"
    )

    project = fixtures.read_project(api, partial_proposal["project_id"])
    assert_project_ledgers(project, committed_correction_cents=0)

    case = fixtures.read_case(api, partial_proposal["case_id"])
    assert case["pay_conversion_status"] == PayConversionStatus.PENDING, (
        f"the pay axis is untouched by a rejection, got {case['pay_conversion_status']}"
    )


def test_both_the_compensation_manager_and_counsel_may_propose_a_correction(api, ca_engagement):
    """The proposal endpoint is shared, and each row records whoever actually called it.

    PRD: "Either a `CompensationManager` or a `LegalCounsel` may propose a **voluntary correction**
    against a `reclassification_case_id`, choosing a `decision` posture of `SELF_CORRECT_FULL`,
    `SELF_CORRECT_PARTIAL`, `DEFER` or `AGENCY_SUPERVISED` and a `proposed_amount_cents` of zero or
    more that the proposer recommends paying."

    Design: Corner/rbac/proposing_a_voluntary_correction_is_shared_by_two_roles
    """
    case = fixtures.open_case(api, ca_engagement["position_id"])

    by_manager = validate_success(
        api.create_voluntary_correction(
            factories.voluntary_correction_payload(case["id"], 0, CorrectionDecision.DEFER),
            COMPENSATION_MANAGER_HEADERS,
        ),
        201,
    )
    by_counsel = validate_success(
        api.create_voluntary_correction(
            factories.voluntary_correction_payload(
                case["id"], 250000, CorrectionDecision.AGENCY_SUPERVISED
            ),
            LEGAL_COUNSEL_HEADERS,
        ),
        201,
    )

    assert by_manager["proposed_by_user_id"] == COMPENSATION_MANAGER_ID, (
        f"the manager's row records the manager, got {by_manager['proposed_by_user_id']!r}"
    )
    assert by_manager["status"] == CorrectionStatus.PROPOSED, (
        f"a new proposal starts PROPOSED, got {by_manager['status']}"
    )
    assert by_counsel["proposed_by_user_id"] == LEGAL_COUNSEL_ID, (
        f"counsel's row records counsel, got {by_counsel['proposed_by_user_id']!r}"
    )
    assert by_counsel["status"] == CorrectionStatus.PROPOSED, (
        f"a new proposal starts PROPOSED, got {by_counsel['status']}"
    )

    rows, meta = validate_paginated(
        api.list_case_voluntary_corrections(case["id"], COMPENSATION_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 2, f"both proposals must exist, got {meta['total_count']} rows"
    assert sorted(row["id"] for row in rows) == sorted([by_manager["id"], by_counsel["id"]]), (
        "the listing must return exactly the two proposals"
    )

    project = fixtures.read_project(api, ca_engagement["project_id"])
    assert_project_ledgers(project, committed_correction_cents=0)
