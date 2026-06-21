"""Composite setup helpers for the SNF-MDS API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server with an empty DB before each test).
Setup calls use get_success_data() so a broken precondition raises a clear
"Setup step failed" error rather than a confusing downstream assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .constants import (
    STANDARD_RATES,
    RATE_EFFECTIVE_FROM,
    STANDARD_ADMIT_AT,
    QUALIFYING_HOSPITAL_ADMIT,
    QUALIFYING_HOSPITAL_DISCHARGE,
)
from . import factories as f

ADMIN = TEST_USERS["administrator_headers"]
COORD = TEST_USERS["admissions_coordinator_headers"]
MDS = TEST_USERS["mds_coordinator_headers"]
THERAPIST = TEST_USERS["therapist_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


# ─── Tier 0: leaf creators ─────────────────────────────

def create_facility(**overrides) -> dict:
    return get_success_data(api_client.create_facility(f.create_facility_payload(**overrides), ADMIN))


def create_resident(facility_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_resident(f.create_resident_payload(facility_id, **overrides), COORD)
    )


def create_qualifying_stay(resident_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_qualifying_stay(resident_id, f.create_qualifying_stay_payload(**overrides), COORD)
    )


def create_pasrr(resident_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_pasrr_screening(resident_id, f.create_pasrr_screening_payload(**overrides), COORD)
    )


def create_cleared_pasrr(resident_id, **overrides) -> dict:
    """Create a PASRR screening and resolve it to CLEARED.

    PRD §3.2 names only the resolution outcome tokens CLEARED / DENIED / ESCALATED;
    the resolve directive uses that same CLEARED token.
    """
    pasrr = create_pasrr(resident_id, **overrides)
    get_success_data(api_client.resolve_pasrr_screening(pasrr["id"], {"resolution": "CLEARED"}, COORD))
    return pasrr


def seed_standard_rate_book() -> None:
    """Create the five PdpmRate rows (PT/OT/SLP/NTA/NURSING) the pricing recipes use."""
    for rate in STANDARD_RATES:
        get_success_data(
            api_client.create_pdpm_rate(
                f.create_pdpm_rate_payload(
                    component=rate["component"],
                    case_mix_group=rate["case_mix_group"],
                    case_mix_index=rate["case_mix_index"],
                    base_rate_cents=rate["base_rate_cents"],
                    effective_from=RATE_EFFECTIVE_FROM,
                ),
                ADMIN,
            )
        )


# ─── Tier 1: admission state progression ───────────────

def create_pending_admission(payer_source="PRIVATE", with_qualifying=False,
                             qualifying_overrides=None, admit_at=STANDARD_ADMIT_AT,
                             pasrr_cleared=True, pasrr_overrides=None,
                             facility_overrides=None, **admission_overrides):
    """Create facility + resident + (optional qualifying stay) + PASRR + a PENDING admission.

    Returns (facility, resident, pasrr, admission, qualifying_stay_or_None).
    """
    facility = create_facility(**(facility_overrides or {}))
    resident = create_resident(facility["id"])

    qs = None
    if with_qualifying:
        qs = create_qualifying_stay(resident["id"], **(qualifying_overrides or {}))

    if pasrr_cleared:
        pasrr = create_cleared_pasrr(resident["id"], **(pasrr_overrides or {}))
    else:
        pasrr = create_pasrr(resident["id"], **(pasrr_overrides or {}))

    payload = f.create_admission_payload(
        resident["id"], facility["id"], pasrr["id"],
        payer_source=payer_source, admit_at=admit_at, **admission_overrides,
    )
    if with_qualifying and qs is not None:
        payload["qualifying_stay_id"] = qs["id"]
    admission = get_success_data(api_client.create_admission(payload, COORD))
    return facility, resident, pasrr, admission, qs


def create_active_admission(payer_source="PRIVATE", with_qualifying=None,
                            allow_non_covered=None, admit_at=STANDARD_ADMIT_AT,
                            facility_overrides=None, qualifying_overrides=None,
                            **admission_overrides):
    """Create a PENDING admission and activate it.

    For MEDICARE_A the qualifying stay defaults on (so activate goes to ACTIVE);
    pass with_qualifying=False + allow_non_covered=True for the NON_COVERED branch.
    Returns (facility, resident, pasrr, admission_after_activate, qualifying_stay_or_None).
    """
    if with_qualifying is None:
        with_qualifying = (payer_source == "MEDICARE_A")

    facility, resident, pasrr, admission, qs = create_pending_admission(
        payer_source=payer_source, with_qualifying=with_qualifying,
        qualifying_overrides=qualifying_overrides, admit_at=admit_at,
        facility_overrides=facility_overrides, **admission_overrides,
    )
    activate_payload = {}
    if allow_non_covered is not None:
        activate_payload["allow_non_covered"] = allow_non_covered
    activated = get_success_data(
        api_client.activate_admission(admission["id"], activate_payload, COORD)
    )
    return facility, resident, pasrr, activated, qs


# ─── Tier 2: assessment lifecycle shortcuts ────────────

def schedule_assessment(admission_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_assessment(admission_id, f.create_assessment_payload(**overrides), MDS)
    )


def create_submitted_assessment(admission_id, **assessment_overrides) -> dict:
    """Schedule -> start -> complete -> submit an assessment. Returns the SUBMITTED row."""
    assessment = schedule_assessment(admission_id, **assessment_overrides)
    get_success_data(api_client.start_assessment(assessment["id"], {}, MDS))
    get_success_data(api_client.complete_assessment(assessment["id"], {}, MDS))
    submitted = get_success_data(api_client.submit_assessment(assessment["id"], {}, MDS))
    return submitted


# ─── Tier 3: priced Medicare claim lifecycle ───────────

def setup_priced_medicare_admission(facility_overrides=None, admit_at=STANDARD_ADMIT_AT,
                                    assessment_overrides=None):
    """Standard rate book + ACTIVE Medicare admission + SUBMITTED TB/SB/NB assessment.

    Returns (facility, resident, admission, submitted_assessment).
    """
    seed_standard_rate_book()
    facility, resident, pasrr, admission, qs = create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True, admit_at=admit_at,
        facility_overrides=facility_overrides,
    )
    assessment = create_submitted_assessment(admission["id"], **(assessment_overrides or {}))
    return facility, resident, admission, assessment


def create_draft_claim(admission_id, driving_assessment_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_claim(
            admission_id, f.create_claim_payload(driving_assessment_id, **overrides), BILLING
        )
    )


def supersede_assessment(admission_id, target_assessment) -> dict:
    """Open a correction against a SUBMITTED target, then complete + submit the
    correction so the target moves to SUPERSEDED. Returns the correcting assessment.

    Used to drive a claim's driving assessment to a non-SUBMITTED state while the claim
    still references it.
    """
    payload = f.create_assessment_payload(
        assessment_type="INTERIM_IPA", assessment_reference_date="2026-02-12T00:00:00Z",
        pt_function_score=9, slp_components_count=2, nta_comorbidity_points=8,
    )
    payload["expected_assessment_version"] = target_assessment["version"]
    correction = get_success_data(api_client.correct_assessment(target_assessment["id"], payload, MDS))
    get_success_data(api_client.start_assessment(correction["id"], {}, MDS))
    get_success_data(api_client.complete_assessment(correction["id"], {}, MDS))
    get_success_data(api_client.submit_assessment(correction["id"], {}, MDS))
    return correction


def setup_estimated_claim(period_start_at="2026-02-01T00:00:00Z",
                          period_end_at="2026-02-06T00:00:00Z",
                          facility_overrides=None, admit_at=STANDARD_ADMIT_AT):
    """Priced Medicare admission + a claim moved to ESTIMATED.

    Returns (facility, admission, assessment, claim_after_estimate).
    """
    facility, resident, admission, assessment = setup_priced_medicare_admission(
        facility_overrides=facility_overrides, admit_at=admit_at,
    )
    claim = create_draft_claim(
        admission["id"], assessment["id"],
        period_start_at=period_start_at, period_end_at=period_end_at,
    )
    estimated = get_success_data(api_client.estimate_claim(claim["id"], {}, BILLING))
    return facility, admission, assessment, estimated


def setup_finalized_claim(period_start_at="2026-02-01T00:00:00Z",
                          period_end_at="2026-02-06T00:00:00Z",
                          facility_overrides=None, admit_at=STANDARD_ADMIT_AT):
    """Priced Medicare admission + a claim moved to FINALIZED (no bed-hold).

    Returns (facility, admission, assessment, claim_after_finalize).
    """
    facility, admission, assessment, estimated = setup_estimated_claim(
        period_start_at=period_start_at, period_end_at=period_end_at,
        facility_overrides=facility_overrides, admit_at=admit_at,
    )
    finalized = get_success_data(api_client.finalize_claim(estimated["id"], {}, BILLING))
    return facility, admission, assessment, finalized


def setup_submitted_claim(period_start_at="2026-02-01T00:00:00Z",
                          period_end_at="2026-02-06T00:00:00Z"):
    """Priced Medicare admission + a claim moved to SUBMITTED (OCC version respected).

    Returns (facility, admission, assessment, claim_after_submit).
    """
    facility, admission, assessment, finalized = setup_finalized_claim(
        period_start_at=period_start_at, period_end_at=period_end_at,
    )
    submitted = get_success_data(
        api_client.submit_claim(
            finalized["id"], {"expected_claim_version": finalized["version"]}, BILLING
        )
    )
    return facility, admission, assessment, submitted


# ─── Tier 4: care-plan lifecycle shortcuts ─────────────

def create_care_plan_with_goal(admission_id, review_interval_days=90,
                               goal_overrides=None):
    """Create a DRAFT care plan and add one OPEN goal. Returns (care_plan, goal)."""
    plan = get_success_data(
        api_client.create_care_plan(
            admission_id, f.create_care_plan_payload(review_interval_days=review_interval_days), PHYSICIAN
        )
    )
    goal = get_success_data(
        api_client.create_goal(plan["id"], f.create_goal_payload(**(goal_overrides or {})), PHYSICIAN)
    )
    return plan, goal


def create_active_care_plan(admission_id, review_interval_days=90, goal_overrides=None):
    """Create a DRAFT care plan with one goal, then activate it. Returns (care_plan, goal)."""
    plan, goal = create_care_plan_with_goal(
        admission_id, review_interval_days=review_interval_days, goal_overrides=goal_overrides
    )
    activated = get_success_data(api_client.activate_care_plan(plan["id"], {}, PHYSICIAN))
    return activated, goal


# ─── Tier 5: discharge-ready / terminal setups ─────────

def setup_discharge_planned_with_active_plan(payer_source="PRIVATE"):
    """ACTIVE admission + ACTIVE care plan + SUBMITTED DISCHARGE assessment, moved to
    DISCHARGE_PLANNED. Mirrors the discharge-cascade and conserved-bed-count recipes.

    Returns (facility, admission, care_plan, goal, discharge_assessment).
    """
    facility, resident, pasrr, admission, qs = create_active_admission(payer_source=payer_source)
    plan, goal = create_active_care_plan(admission["id"])

    # Schedule the DISCHARGE assessment while ACTIVE, plan the discharge (which moves
    # any SCHEDULED DISCHARGE assessment to IN_PROGRESS), then complete + submit it.
    assessment = schedule_assessment(
        admission["id"],
        assessment_type="DISCHARGE",
        assessment_reference_date="2026-02-10T00:00:00Z",
        pt_function_score=12, slp_components_count=0, nta_comorbidity_points=4,
    )
    get_success_data(api_client.plan_discharge_admission(admission["id"], {}, COORD))
    get_success_data(api_client.complete_assessment(assessment["id"], {}, MDS))
    submitted = get_success_data(api_client.submit_assessment(assessment["id"], {}, MDS))
    return facility, admission, plan, goal, submitted
