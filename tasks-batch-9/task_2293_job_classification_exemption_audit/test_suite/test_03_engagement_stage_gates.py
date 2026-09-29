"""Engagement stage transitions and the stage gate that guards interview work."""

from typing import Any, Dict

import pytest

from test_helpers import (
    CLASSIFICATION_REVIEWER_HEADERS,
    COMPENSATION_MANAGER_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    CaseStatus,
    CommunicationStatus,
    ContractorReviewStatus,
    DutiesValidationStatus,
    ErrorId,
    IcTest,
    InterviewStatus,
    PROGRAM_ADMIN_HEADERS,
    PayConversionStatus,
    ProjectStatus,
    RemediationPosture,
    RespondentType,
    assert_family_risk,
    assert_money,
    assert_project_ledgers,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def two_engagements_sharing_an_interviewer(api, pinned_clock) -> Dict[str, Any]:
    """One engagement in FIELDWORK holds the interviewer's window; a second stays in PLANNING."""
    fixtures.register_state_rule(
        api,
        factories.california_rule_payload(
            liquidated_damages_multiplier=1.0, back_wage_lookback_weeks_override=156
        ),
    )
    project_one = fixtures.create_project(api, name="FY26 Wave One")
    family_one = fixtures.create_family(api, project_one["id"])
    fixtures.advance_project(api, project_one["id"], ProjectStatus.FIELDWORK)
    position_one = fixtures.create_position(api, family_one["id"])
    holding = fixtures.book_interview(
        api, position_one["id"], "int-9", ("2026-09-10T14:00:00Z", "2026-09-10T15:00:00Z")
    )

    project_two = fixtures.create_project(api, name="FY26 Wave Two")
    family_two = fixtures.create_family(api, project_two["id"], name="Field Services", code="FLD-SVC")
    position_two = fixtures.create_position(
        api,
        family_two["id"],
        title="Field Lead",
        job_code="FL-200",
        claimed_exemption_test="ADMINISTRATIVE",
        annual_salary_cents=7200000,
        incumbent_count=1,
        avg_weekly_hours=44,
    )
    return {
        "holding_interview": holding,
        "project_two_id": project_two["id"],
        "position_two_id": position_two["id"],
    }


@pytest.fixture
def remediation_engagement_with_a_fresh_interview(api, determined_engagement) -> Dict[str, Any]:
    """After the determination the original interview is voided, rebooked, and the stage advances."""
    position_id = determined_engagement["position_id"]
    original_manager = determined_engagement["interviews"]["manager"]

    get_success_data(
        api.void_interview(
            original_manager["id"],
            {"void_reason": "SUPERSEDED_BY_REBOOKING"},
            CLASSIFICATION_REVIEWER_HEADERS,
        )
    )
    rebooked = fixtures.book_interview(
        api,
        position_id,
        "int-8",
        ("2026-09-25T09:00:00Z", "2026-09-25T10:00:00Z"),
        RespondentType.MANAGER,
        "MGR-2",
    )
    fixtures.advance_project(api, determined_engagement["project_id"], ProjectStatus.REMEDIATION)
    return {
        **determined_engagement,
        "voided_interview": original_manager,
        "rebooked_interview": rebooked,
    }


def test_planning_to_fieldwork_transition_succeeds_and_bumps_the_version(api, pinned_clock):
    """The declared opening edge fires once a family exists and increments the version.

    PRD: "`PLANNING -> FIELDWORK` requires that at least one job family already exist under the
    engagement."

    Design: Corner/state_machines/audit_project_planning_to_fieldwork_transition_succeeds_and_bumps_version
    """
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"])

    updated = validate_success(
        api.set_audit_project_status(
            project["id"],
            factories.project_status_payload(ProjectStatus.FIELDWORK),
            PROGRAM_ADMIN_HEADERS,
        ),
        200,
    )

    assert updated["status"] == ProjectStatus.FIELDWORK, (
        f"the engagement must reach FIELDWORK, got {updated['status']}"
    )
    assert updated["version"] == 2, (
        f"the transition must bump the version to 2, got {updated['version']}"
    )
    assert updated["remediation_posture"] == RemediationPosture.OPEN, (
        f"the posture must stay OPEN, got {updated['remediation_posture']}"
    )
    assert fixtures.read_family(api, family["id"])["remediation_priority_rank"] is None, (
        "the priority rank stays null until remediation begins"
    )


def test_fieldwork_transition_without_a_job_family_is_refused(api, pinned_clock):
    """A precondition failure leaves the engagement's stage and version untouched.

    PRD: "Requesting a `target_status` that is not a declared transition from the current status
    is `ERR_PROJECT_STAGE_INVALID`."

    Design: Corner/state_machines/fieldwork_transition_without_a_job_family_is_refused
    """
    project = fixtures.create_project(api)

    validate_error(
        api.set_audit_project_status(
            project["id"],
            factories.project_status_payload(ProjectStatus.FIELDWORK),
            PROGRAM_ADMIN_HEADERS,
        ),
        ErrorId.PROJECT_STAGE_PRECONDITION_UNMET,
        409,
    )

    unchanged = fixtures.read_project(api, project["id"])
    assert unchanged["status"] == ProjectStatus.PLANNING, (
        f"the engagement must stay in PLANNING, got {unchanged['status']}"
    )
    assert unchanged["version"] == 1, (
        f"a refused transition must not bump the version, got {unchanged['version']}"
    )


def test_newly_created_entities_start_in_their_declared_initial_states(api, ca_engagement):
    """A fresh interview, case and contractor review each land in their declared start state.

    PRD: "A freshly opened engagement sits in `PLANNING` status with `remediation_posture`
    initialized to `OPEN` and every rollup counter initialized to 0"

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    position_id = ca_engagement["position_id"]

    interview = validate_success(
        api.create_interview(
            factories.interview_payload(
                position_id, "int-11", "2026-09-20T09:00:00Z", "2026-09-20T10:00:00Z"
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )
    assert interview["status"] == InterviewStatus.SCHEDULED, (
        f"a new interview starts SCHEDULED, got {interview['status']}"
    )
    assert interview["completed_at"] is None, (
        f"completed_at starts null, got {interview['completed_at']!r}"
    )
    assert interview["attested_at"] is None, (
        f"attested_at starts null, got {interview['attested_at']!r}"
    )

    case = validate_success(
        api.create_reclassification_case(
            factories.reclassification_case_payload(position_id), COMPENSATION_MANAGER_HEADERS
        ),
        201,
    )
    assert case["pay_conversion_status"] == PayConversionStatus.PENDING, (
        f"pay conversion starts PENDING, got {case['pay_conversion_status']}"
    )
    assert case["communication_status"] == CommunicationStatus.NOT_STARTED, (
        f"communication starts NOT_STARTED, got {case['communication_status']}"
    )
    assert case["case_status"] == CaseStatus.OPEN, (
        f"the case starts OPEN, got {case['case_status']}"
    )
    assert_money(case["exposure_cents"], 0, "case exposure_cents")
    assert case["converted_hourly_rate_cents"] is None, (
        f"converted_hourly_rate_cents starts null, got {case['converted_hourly_rate_cents']!r}"
    )

    review = validate_success(
        api.create_contractor_review(
            factories.contractor_review_payload(ca_engagement["project_id"]),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )
    assert review["status"] == ContractorReviewStatus.DRAFT, (
        f"a new contractor review starts DRAFT, got {review['status']}"
    )
    assert review["applied_ic_test"] == IcTest.ABC, (
        "the applied test comes from the registered jurisdiction, got "
        f"{review['applied_ic_test']}"
    )


def test_remediation_entry_ranks_families_by_created_at_when_scores_tie(api, pinned_clock):
    """With every score tied the final tie-break is creation order.

    PRD: "Entering remediation assigns a 1-based `remediation_priority_rank` to every job family
    of the engagement, ordered by `risk_score` descending, then by `family_headcount` descending,
    then by `created_at` ascending as the final tie-break."

    Design: Corner/state_machines/remediation_entry_ranks_families_by_created_at_when_scores_tie
    """
    project = fixtures.create_project(api)
    family_a = fixtures.create_family(api, project["id"], name="Alpha Operations", code="OPS-ALPHA")
    family_b = fixtures.create_family(api, project["id"], name="Beta Operations", code="OPS-BETA")
    fixtures.advance_project(api, project["id"], ProjectStatus.FIELDWORK)

    advanced = validate_success(
        api.set_audit_project_status(
            project["id"],
            factories.project_status_payload(ProjectStatus.REMEDIATION),
            PROGRAM_ADMIN_HEADERS,
        ),
        200,
    )

    assert advanced["status"] == ProjectStatus.REMEDIATION, (
        f"the engagement must reach REMEDIATION, got {advanced['status']}"
    )
    assert_project_ledgers(advanced, posture=RemediationPosture.OPEN)

    first = fixtures.read_family(api, family_a["id"])
    second = fixtures.read_family(api, family_b["id"])
    assert first["remediation_priority_rank"] == 1, (
        f"the earlier family ranks first, got {first['remediation_priority_rank']}"
    )
    assert second["remediation_priority_rank"] == 2, (
        f"the later family ranks second, got {second['remediation_priority_rank']}"
    )
    assert_family_risk(first, 0, "LOW", headcount=0)
    assert_family_risk(second, 0, "LOW", headcount=0)


def test_stage_gate_outranks_interviewer_double_booking(api, two_engagements_sharing_an_interviewer):
    """Both the stage rule and the calendar rule are violated; only the stage error surfaces.

    PRD: "The checks below are evaluated **strictly in this order**; the first rule that is
    violated determines the response, and no later rule runs."

    Design: Difficulty/priority_pair_validation_conflict/project_stage_gate_outranks_interviewer_double_booking_and_returns_stage_error
    """
    scenario = two_engagements_sharing_an_interviewer

    response = api.create_interview(
        factories.interview_payload(
            scenario["position_two_id"],
            "int-9",
            "2026-09-10T14:30:00Z",
            "2026-09-10T15:30:00Z",
            respondent_type=RespondentType.MANAGER,
            respondent_ref="MGR-2",
        ),
        COMPLIANCE_ANALYST_HEADERS,
    )

    error_data = validate_error(response, ErrorId.PROJECT_STAGE_INVALID, 409)
    assert error_data["error_id"] != ErrorId.INTERVIEWER_DOUBLE_BOOKED, (
        "the lower-ranked calendar rule must not surface even though the window intersects"
    )


def test_stage_gated_booking_refusal_leaves_no_interview_and_no_stage_change(
    api, two_engagements_sharing_an_interviewer
):
    """The refused booking writes nothing: no new interview, no touched hold, no stage move.

    PRD: "Fieldwork is the only stage in which interviews may be booked or completed."

    Design: Difficulty/priority_pair_validation_conflict/project_stage_gate_outranks_interviewer_double_booking_and_returns_stage_error
    """
    scenario = two_engagements_sharing_an_interviewer

    validate_error(
        api.create_interview(
            factories.interview_payload(
                scenario["position_two_id"],
                "int-9",
                "2026-09-10T14:30:00Z",
                "2026-09-10T15:30:00Z",
                respondent_type=RespondentType.MANAGER,
                respondent_ref="MGR-2",
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        ErrorId.PROJECT_STAGE_INVALID,
        409,
    )

    listed, listing_meta = validate_paginated(
        api.list_position_interviews(scenario["position_two_id"], COMPLIANCE_ANALYST_HEADERS)
    )
    assert listing_meta["total_count"] == 0, (
        f"no interview may exist for the planning-stage job, got {listing_meta['total_count']}"
    )
    assert listed == [], f"no interview may exist for the planning-stage job, got {listed}"

    holding = fixtures.read_interview(api, scenario["holding_interview"]["id"])
    assert holding["status"] == InterviewStatus.SCHEDULED, (
        f"the existing hold must be untouched, got {holding['status']}"
    )
    stalled = fixtures.read_project(api, scenario["project_two_id"])
    assert stalled["status"] == ProjectStatus.PLANNING, (
        f"the second engagement must stay in PLANNING, got {stalled['status']}"
    )


def test_interview_completion_is_refused_once_remediation_starts(
    api, remediation_engagement_with_a_fresh_interview
):
    """A legally booked interview becomes uncompletable when the engagement leaves fieldwork.

    PRD: "This applies to the stage endpoint, to booking an interview, and to completing an
    interview."

    Design: Difficulty/cross_entity_state_dependency/interview_completion_blocked_by_project_stage_after_remediation_starts
    """
    scenario = remediation_engagement_with_a_fresh_interview

    validate_error(
        api.complete_interview(
            scenario["rebooked_interview"]["id"],
            factories.interview_completion_payload(44.0, 46, 3, True),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        ErrorId.PROJECT_STAGE_INVALID,
        409,
    )

    refused = fixtures.read_interview(api, scenario["rebooked_interview"]["id"])
    assert refused["status"] == InterviewStatus.SCHEDULED, (
        f"the refused interview stays SCHEDULED rather than being voided, got {refused['status']}"
    )
    assert fixtures.read_project(api, scenario["project_id"])["status"] == ProjectStatus.REMEDIATION, (
        "the engagement must remain in REMEDIATION"
    )


def test_remediation_stage_holds_ranks_and_refuses_the_rewind_without_unreviewed_work(
    api, remediation_engagement_with_a_fresh_interview
):
    """Remediation ranked the family, and the cycle edge back needs an unreviewed job.

    PRD: "`REMEDIATION -> FIELDWORK` is the cycle edge back, and it requires the opposite
    condition: at least one position under the engagement must have a `classification_status` of
    `UNREVIEWED`, else `ERR_PROJECT_STAGE_PRECONDITION_UNMET`."

    Design: Difficulty/cross_entity_state_dependency/interview_completion_blocked_by_project_stage_after_remediation_starts
    """
    scenario = remediation_engagement_with_a_fresh_interview

    assert (
        fixtures.read_interview(api, scenario["voided_interview"]["id"])["status"]
        == InterviewStatus.VOIDED
    ), "the superseded manager interview must be VOIDED"
    position = fixtures.read_position(api, scenario["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        "voiding an attested interview drops the duties back to PENDING, got "
        f"{position['duties_validation_status']}"
    )
    family = fixtures.read_family(api, scenario["family_id"])
    assert family["remediation_priority_rank"] == 1, (
        f"the only family must rank first, got {family['remediation_priority_rank']}"
    )

    validate_error(
        api.set_audit_project_status(
            scenario["project_id"],
            factories.project_status_payload(ProjectStatus.FIELDWORK),
            PROGRAM_ADMIN_HEADERS,
        ),
        ErrorId.PROJECT_STAGE_PRECONDITION_UNMET,
        409,
    )

    still_scheduled = fixtures.read_interview(api, scenario["rebooked_interview"]["id"])
    assert still_scheduled["status"] == InterviewStatus.SCHEDULED, (
        f"the refused rewind leaves the interview SCHEDULED, got {still_scheduled['status']}"
    )
