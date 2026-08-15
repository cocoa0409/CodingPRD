"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use the lenient get_success_data
validator so failures surface as clear "Setup step failed" errors.

Operator ids are pinned literals (ic_1, ta_1, ta_2, tl_1, tl_2, da_1) so that
segregation-of-duties comparisons are deliberate: the creator of an assessment
or re-entry plan is ta_1 unless overridden, and adjudication runs as tl_1/tl_2.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    complete_checkin_payload,
    complete_interview_payload,
    create_assessment_payload,
    create_case_payload,
    create_checkin_payload,
    create_document_payload,
    create_interview_payload,
    create_plan_payload,
    create_reentry_plan_payload,
    create_referral_payload,
    create_school_payload,
    moderate_score_factors,
    screening_payload,
    triage_payload,
)
from .test_users import (
    TEST_USERS,
    make_district_admin_headers,
    make_intake_coordinator_headers,
    make_team_lead_headers,
    make_threat_assessor_headers,
)

DA = TEST_USERS["district_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
TA1 = make_threat_assessor_headers("ta_1")
TA2 = make_threat_assessor_headers("ta_2")
TL1 = TEST_USERS["team_lead_headers"]
TL2 = make_team_lead_headers("tl_2")


# ---------------------------------------------------------------------------
# Tier 1: single resources and one-step state moves
# ---------------------------------------------------------------------------

def create_school(name="Test School", school_code=None, enrollment_count=500,
                  retention_days=None):
    """Create a school. Returns the school."""
    overrides = {}
    if school_code is not None:
        overrides["school_code"] = school_code
    if retention_days is not None:
        overrides["retention_days"] = retention_days
    payload = create_school_payload(name=name, enrollment_count=enrollment_count,
                                    **overrides)
    return get_success_data(api_client.create_school(payload, DA))


def set_clock(to_iso8601: str):
    """Advance the logical clock (DistrictAdministrator)."""
    return get_success_data(api_client.set_clock(to_iso8601, DA))


def purge_records():
    """Run the district-wide retention purge. Returns {purged_count, purged_case_ids}."""
    return get_success_data(api_client.purge_records(DA))


def get_case(case_id, headers=None):
    return get_success_data(api_client.get_case(case_id, headers or TL1))


def create_case(school_id, **overrides):
    """Intake a threat case (IntakeCoordinator). Returns the INTAKE case."""
    return get_success_data(api_client.create_case(
        create_case_payload(school_id, **overrides), IC))


def triage_case(case_id, priority="ROUTINE", notes="triage notes"):
    """Triage an INTAKE case (IntakeCoordinator). Returns the TRIAGED case."""
    return get_success_data(api_client.triage_case(
        case_id, triage_payload(triage_priority=priority, triage_notes=notes), IC))


def screen_case(case_id, true_count=3, assessor=None, **factor_overrides):
    """Record the initial screening (ThreatAssessor). Returns the updated case."""
    return get_success_data(api_client.record_screening(
        case_id, screening_payload(true_count, **factor_overrides),
        assessor or TA1))


def remove_case(case_id, removal_type="EMERGENCY_REMOVAL",
                reason="interim safety hold", lead=None):
    """Remove the subject from campus (TeamLead). Returns the REMOVED case."""
    return get_success_data(api_client.remove_case(
        case_id, {"removal_type": removal_type, "removal_reason": reason},
        lead or TL1))


def close_case(case_id, lead=None):
    return get_success_data(api_client.close_case(case_id, lead or TL1))


def reopen_case(case_id, coordinator=None):
    return get_success_data(api_client.reopen_case(
        case_id, coordinator or IC))


# ---------------------------------------------------------------------------
# Tier 2: case progression composites
# ---------------------------------------------------------------------------

def setup_case_under_assessment(school_id=None, screening_true_count=3,
                                school_overrides=None, case_overrides=None):
    """School + case + triage + SUBSTANTIVE screening. Returns the
    UNDER_ASSESSMENT case (freshly read)."""
    if school_id is None:
        school_id = create_school(**(school_overrides or {}))["id"]
    case = create_case(school_id, **(case_overrides or {}))
    triage_case(case["id"])
    screen_case(case["id"], true_count=screening_true_count)
    return get_case(case["id"])


def create_draft_assessment(case_id, factors=None, variant="STANDARD",
                            creator=None):
    """Draft an assessment; scores are computed immediately. Returns the DRAFT."""
    return get_success_data(api_client.create_assessment(
        create_assessment_payload(case_id, variant=variant, factors=factors),
        creator or TA1))


def create_and_finalize_assessment(case_id, factors=None, variant="STANDARD",
                                   creator=None, finalizer=None):
    """Draft -> submit -> finalize. Returns the FINALIZED assessment.

    Default creator ta_1 and finalizer tl_1 keep the segregation-of-duties
    comparison satisfied.
    """
    assessment = create_draft_assessment(case_id, factors=factors,
                                         variant=variant, creator=creator)
    get_success_data(api_client.submit_assessment(assessment["id"], creator or TA1))
    return get_success_data(api_client.finalize_assessment(
        assessment["id"], finalizer or TL1))


def create_draft_plan(case_id, cadence_mode="FROM_COMPLETION", cadence_days=None,
                      conditions=None, creator=None):
    """Draft a management plan (ThreatAssessor). Returns the DRAFT plan."""
    return get_success_data(api_client.create_plan(
        create_plan_payload(case_id, cadence_mode=cadence_mode,
                            cadence_days=cadence_days, conditions=conditions),
        creator or TA1))


def activate_plan_for_case(plan_id, case_id, lead=None):
    """Activate a DRAFT plan, threading the case's current version into the
    OCC-guarded activation call. Returns the ACTIVE plan."""
    lead = lead or TL1
    current = get_case(case_id, headers=lead)
    return get_success_data(api_client.activate_plan(
        plan_id, current["version"], lead))


def setup_case_with_finalized_assessment(factors=None, variant="STANDARD",
                                         school_overrides=None,
                                         case_overrides=None):
    """UNDER_ASSESSMENT case + FINALIZED assessment. Returns (case, assessment)
    with the case freshly read (risk_level set)."""
    case = setup_case_under_assessment(school_overrides=school_overrides,
                                       case_overrides=case_overrides)
    assessment = create_and_finalize_assessment(case["id"], factors=factors,
                                                variant=variant)
    return get_case(case["id"]), assessment


def setup_case_plan_active(cadence_mode="FROM_COMPLETION", cadence_days=None,
                           factors=None, variant="STANDARD", conditions=None,
                           school_overrides=None, case_overrides=None):
    """Full chain to PLAN_ACTIVE: case -> screening -> FINALIZED assessment ->
    DRAFT plan -> activation. Returns (case, assessment, plan, first_checkin)
    where first_checkin is the auto-created SCHEDULED monitoring check-in."""
    case, assessment = setup_case_with_finalized_assessment(
        factors=factors, variant=variant, school_overrides=school_overrides,
        case_overrides=case_overrides)
    plan = create_draft_plan(case["id"], cadence_mode=cadence_mode,
                             cadence_days=cadence_days, conditions=conditions)
    plan = activate_plan_for_case(plan["id"], case["id"])
    checkins, _ = list_case_checkins(case["id"])
    assert len(checkins) == 1, "activation must auto-create exactly one check-in"
    return get_case(case["id"]), assessment, plan, checkins[0]


def setup_case_removed(with_active_plan=False, **plan_kwargs):
    """Case driven to REMOVED. With with_active_plan=True the case first
    reaches PLAN_ACTIVE (an ACTIVE plan survives removal). Returns
    (case, plan_or_None)."""
    if with_active_plan:
        case, _assessment, plan, _chk = setup_case_plan_active(**plan_kwargs)
    else:
        case = setup_case_under_assessment()
        plan = None
    case = remove_case(case["id"])
    return case, plan


def propose_reentry_plan(case_id, conditions=None, proposer=None):
    """Propose a re-entry plan (ThreatAssessor). Returns the PROPOSED plan."""
    return get_success_data(api_client.create_reentry_plan(
        create_reentry_plan_payload(case_id, conditions=conditions),
        proposer or TA1))


# ---------------------------------------------------------------------------
# Tier 3: list/read helpers (paginated)
# ---------------------------------------------------------------------------

def list_cases(headers=None, **filters):
    return validate_paginated(api_client.list_cases(headers or TL1, params=filters))


def list_case_interviews(case_id, headers=None, **filters):
    return validate_paginated(api_client.list_case_interviews(
        case_id, headers or TA1, params=filters))


def list_case_assessments(case_id, headers=None, **filters):
    return validate_paginated(api_client.list_case_assessments(
        case_id, headers or TL1, params=filters))


def list_case_plans(case_id, headers=None, **filters):
    return validate_paginated(api_client.list_case_plans(
        case_id, headers or TL1, params=filters))


def list_case_referrals(case_id, headers=None, **filters):
    return validate_paginated(api_client.list_case_referrals(
        case_id, headers or TL1, params=filters))


def list_case_checkins(case_id, headers=None, **filters):
    return validate_paginated(api_client.list_case_checkins(
        case_id, headers or TA1, params=filters))


def list_case_reentry_plans(case_id, headers=None, **filters):
    return validate_paginated(api_client.list_case_reentry_plans(
        case_id, headers or TL1, params=filters))


def list_case_documents(case_id, headers, **filters):
    return validate_paginated(api_client.list_case_documents(
        case_id, headers, params=filters))


def list_case_audit_events(case_id, headers=None, **filters):
    return validate_paginated(api_client.list_case_audit_events(
        case_id, headers or TL1, params=filters))


# ---------------------------------------------------------------------------
# Tier 4: misc one-call action helpers
# ---------------------------------------------------------------------------

def schedule_interview(case_id, interviewee_type="WITNESS",
                       starts_at="2026-08-05T10:00:00Z",
                       ends_at="2026-08-05T11:00:00Z", assessor=None):
    return get_success_data(api_client.create_interview(
        create_interview_payload(case_id, interviewee_type=interviewee_type,
                                 starts_at=starts_at, ends_at=ends_at),
        assessor or TA1))


def complete_interview(interview_id, findings_score=5,
                       summary="interview findings", assessor=None):
    return get_success_data(api_client.complete_interview(
        interview_id,
        complete_interview_payload(findings_score=findings_score, summary=summary),
        assessor or TA1))


def send_referral(case_id, referral_type="MENTAL_HEALTH", agency_name="County MH",
                  urgency="ROUTINE", sender=None):
    """Create-and-send a referral (ThreatAssessor by default). Returns SENT referral."""
    return get_success_data(api_client.create_referral(
        create_referral_payload(case_id, referral_type=referral_type,
                                agency_name=agency_name, urgency=urgency),
        sender or TA1))


def schedule_checkin(case_id, due_date, assessor=None):
    return get_success_data(api_client.create_checkin(
        create_checkin_payload(case_id, due_date), assessor or TA1))


def complete_checkin(checkin_id, outcome="ON_TRACK", notes="check-in notes",
                     assessor=None):
    return get_success_data(api_client.complete_checkin(
        checkin_id, complete_checkin_payload(outcome=outcome, notes=notes),
        assessor or TA1))


def reschedule_checkin(checkin_id, new_due_date, assessor=None):
    return get_success_data(api_client.reschedule_checkin(
        checkin_id, {"new_due_date": new_due_date}, assessor or TA1))


def append_document(case_id, doc_type="INTAKE_NOTE", body="case note body",
                    sealed=None, author=None):
    payload = create_document_payload(doc_type=doc_type, body=body)
    if sealed is not None:
        payload["sealed"] = sealed
    return get_success_data(api_client.create_case_document(
        case_id, payload, author or IC))
