"""Composite setup helpers for the physical-therapy rehab benchmark.

Each fixture builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.x). The runner restarts the API server before every individual pytest
test, so each fixture starts from an empty database — no entities, no clock state.

Fixtures use `get_success_data()` (lenient validator) so setup failures surface
as clear "Setup failed" traces rather than cryptic assertion failures.

Identity threading: the Therapist role is entity-backed (PRD §2.1). Any
ownership-gated call must use `make_therapist_headers(therapist["id"])`, never
the shared `TEST_USERS["therapist_headers"]` fallback (which carries a fake
X-User-ID that never matches a real Therapist row).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_patient_payload,
    create_therapist_payload,
    create_veteran_referral_payload,
    create_plan_of_care_payload,
    create_evaluation_payload,
    create_authorization_grant_payload,
    create_visit_payload,
    complete_visit_payload,
    finalize_visit_payload,
    create_home_exercise_program_payload,
    create_mips_measure_payload,
    create_discharge_assessment_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_therapist_headers,
)


_ADMIN = TEST_USERS["platform_admin_headers"]
_CASE_MANAGER = TEST_USERS["case_manager_headers"]
_BILLING_CLERK = TEST_USERS["billing_clerk_headers"]
_VA_COORDINATOR = TEST_USERS["va_coordinator_headers"]


# ─── Tier 0: clock ──────────────────────────────────────────────


def set_clock(iso8601: str) -> dict:
    """Advance the server's logical UTC clock (PRD §2.10)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), _ADMIN))


# ─── Tier 1: leaf creators ──────────────────────────────────────


def create_therapist(
    license_state: str = "CA",
    medicare_provider_enrolled: bool = False,
    full_name: str = "Test Therapist",
    **overrides,
) -> dict:
    res = api_client.create_therapist(
        create_therapist_payload(
            full_name=full_name,
            license_state=license_state,
            medicare_provider_enrolled=medicare_provider_enrolled,
            **overrides,
        ),
        _ADMIN,
    )
    return get_success_data(res)


def create_patient(
    insurance_type: str = "COMMERCIAL",
    is_veteran: bool = False,
    full_name: str = "Test Patient",
    date_of_birth: str = "1970-01-01",
    **overrides,
) -> dict:
    res = api_client.create_patient(
        create_patient_payload(
            full_name=full_name,
            date_of_birth=date_of_birth,
            insurance_type=insurance_type,
            is_veteran=is_veteran,
            **overrides,
        ),
        _ADMIN,
    )
    return get_success_data(res)


def create_veteran_referral(
    patient_id: str,
    max_authorized_visits: int = 20,
    expires_on: str = "2026-12-31",
    **overrides,
) -> dict:
    res = api_client.create_veteran_referral(
        create_veteran_referral_payload(
            patient_id=patient_id,
            max_authorized_visits=max_authorized_visits,
            expires_on=expires_on,
            **overrides,
        ),
        _VA_COORDINATOR,
    )
    return get_success_data(res)


# ─── Tier 2: plan-of-care creation in DRAFT ─────────────────────


def create_draft_poc(
    patient_id: str,
    therapist_id: str,
    certified_start_date: str = "2026-06-01",
    certified_end_date: str = "2026-07-31",
    veteran_referral_id: str = None,
    **overrides,
) -> dict:
    """Create a PlanOfCare in DRAFT (PRD §3.2). Therapist-as-creator."""
    res = api_client.create_plan_of_care(
        create_plan_of_care_payload(
            patient_id=patient_id,
            primary_therapist_id=therapist_id,
            certified_start_date=certified_start_date,
            certified_end_date=certified_end_date,
            veteran_referral_id=veteran_referral_id,
            **overrides,
        ),
        make_therapist_headers(therapist_id),
    )
    return get_success_data(res)


def record_initial_evaluation(
    poc_id: str,
    therapist_id: str,
    performed_on: str = "2026-06-01",
    functional_score: int = 40,
    minutes_spent: int = 30,
) -> dict:
    """Record an INITIAL Evaluation under the POC (PRD §3.3)."""
    res = api_client.create_evaluation(
        create_evaluation_payload(
            plan_of_care_id=poc_id,
            therapist_id=therapist_id,
            evaluation_kind="INITIAL",
            performed_on=performed_on,
            functional_score=functional_score,
            minutes_spent=minutes_spent,
        ),
        make_therapist_headers(therapist_id),
    )
    return get_success_data(res)


def record_re_evaluation(
    poc_id: str,
    therapist_id: str,
    performed_on: str,
    functional_score: int = 55,
    minutes_spent: int = 25,
) -> dict:
    """Record a RE_EVALUATION (PRD §3.3, §3.6)."""
    res = api_client.create_evaluation(
        create_evaluation_payload(
            plan_of_care_id=poc_id,
            therapist_id=therapist_id,
            evaluation_kind="RE_EVALUATION",
            performed_on=performed_on,
            functional_score=functional_score,
            minutes_spent=minutes_spent,
        ),
        make_therapist_headers(therapist_id),
    )
    return get_success_data(res)


def activate_poc(poc_id: str, therapist_id: str) -> dict:
    """Activate the POC (PRD §3.2). Pins capped_dollar_limit_cents."""
    res = api_client.activate_plan_of_care(poc_id, make_therapist_headers(therapist_id))
    return get_success_data(res)


# ─── Tier 3: composite "active POC" setups ──────────────────────


def setup_active_poc(
    insurance_type: str = "COMMERCIAL",
    is_veteran: bool = False,
    medicare_enrolled: bool = False,
    license_state: str = "CA",
    certified_start_date: str = "2026-06-01",
    certified_end_date: str = "2026-07-31",
    initial_clock: str = "2026-06-01T00:00:00Z",
    functional_score: int = 40,
    **patient_overrides,
) -> dict:
    """Create therapist + patient + DRAFT POC + INITIAL Eval + activate (PRD §3.1–§3.3).

    Returns {"therapist", "patient", "poc"} where poc is the post-activate row.
    """
    set_clock(initial_clock)
    th = create_therapist(
        license_state=license_state,
        medicare_provider_enrolled=medicare_enrolled,
        full_name="Setup Therapist",
    )
    pt = create_patient(
        insurance_type=insurance_type,
        is_veteran=is_veteran,
        full_name="Setup Patient",
        **patient_overrides,
    )
    poc = create_draft_poc(
        pt["id"], th["id"],
        certified_start_date=certified_start_date,
        certified_end_date=certified_end_date,
    )
    record_initial_evaluation(
        poc["id"], th["id"],
        performed_on=certified_start_date,
        functional_score=functional_score,
    )
    poc_active = activate_poc(poc["id"], th["id"])
    return {"therapist": th, "patient": pt, "poc": poc_active}


def setup_active_va_poc(
    is_veteran: bool = True,
    max_authorized_visits: int = 20,
    referral_expires_on: str = "2026-12-31",
    certified_start_date: str = "2026-06-01",
    certified_end_date: str = "2026-07-31",
    initial_clock: str = "2026-06-01T00:00:00Z",
) -> dict:
    """VA_TRICARE patient + veteran referral + DRAFT POC linked + INITIAL Eval + activate (PRD §3.2)."""
    set_clock(initial_clock)
    th = create_therapist(license_state="CA", medicare_provider_enrolled=False,
                          full_name="VA Setup Therapist")
    pt = create_patient(insurance_type="VA_TRICARE", is_veteran=is_veteran,
                        full_name="VA Setup Patient", date_of_birth="1965-01-01")
    referral = create_veteran_referral(
        pt["id"], max_authorized_visits=max_authorized_visits,
        expires_on=referral_expires_on,
    )
    poc = create_draft_poc(
        pt["id"], th["id"],
        certified_start_date=certified_start_date,
        certified_end_date=certified_end_date,
        veteran_referral_id=referral["id"],
    )
    record_initial_evaluation(poc["id"], th["id"], performed_on=certified_start_date)
    poc_active = activate_poc(poc["id"], th["id"])
    return {
        "therapist": th, "patient": pt, "referral": referral, "poc": poc_active,
    }


# ─── Tier 4: grant / visit composites ───────────────────────────


def create_grant(
    poc_id: str,
    total_units_granted: int = 20,
    effective_from: str = "2026-06-01",
    effective_to: str = "2026-07-31",
    veteran_referral_id: str = None,
) -> dict:
    """Create an AuthorizationGrant under the POC (PRD §3.4)."""
    res = api_client.create_authorization_grant(
        create_authorization_grant_payload(
            plan_of_care_id=poc_id,
            total_units_granted=total_units_granted,
            effective_from=effective_from,
            effective_to=effective_to,
            veteran_referral_id=veteran_referral_id,
        ),
        _CASE_MANAGER,
    )
    return get_success_data(res)


def schedule_visit(
    grant_id: str,
    therapist_id: str,
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    planned_minutes: int,
    cpt_code: str = "CPT_97110_THER_EX",
) -> dict:
    """Schedule a SCHEDULED Visit (PRD §3.5)."""
    res = api_client.create_visit(
        create_visit_payload(
            authorization_grant_id=grant_id,
            therapist_id=therapist_id,
            scheduled_start_utc=scheduled_start_utc,
            scheduled_end_utc=scheduled_end_utc,
            planned_minutes=planned_minutes,
            cpt_code=cpt_code,
        ),
        make_therapist_headers(therapist_id),
    )
    return get_success_data(res)


def complete_visit(visit_id: str, therapist_id: str, actual_minutes: int) -> dict:
    """Transition SCHEDULED → COMPLETED with actual_minutes (PRD §3.5).

    PRD §3.5: completion requires "today (UTC) is on or after the date portion
    of `scheduled_start_utc`". The runner restarts the clock to its default each
    test, so this fixture reads the visit's scheduled_start_utc and advances the
    clock to that exact instant before issuing the complete call. Tests retain
    full control over later clock movement.
    """
    v = get_success_data(
        api_client.get_visit(visit_id, make_therapist_headers(therapist_id))
    )
    set_clock(v["scheduled_start_utc"])
    res = api_client.complete_visit(
        visit_id, complete_visit_payload(actual_minutes=actual_minutes),
        make_therapist_headers(therapist_id),
    )
    return get_success_data(res)


def get_poc_version(poc_id: str) -> int:
    """Read the current PlanOfCare.version (PRD §2.4, §2.6)."""
    res = api_client.get_plan_of_care(poc_id, _BILLING_CLERK)
    return get_success_data(res)["version"]


def finalize_visit(visit_id: str, poc_id: str) -> dict:
    """Transition COMPLETED → FINALIZED, pinning the POC's current version (PRD §3.5, §2.6)."""
    poc_v = get_poc_version(poc_id)
    res = api_client.finalize_visit(
        visit_id, finalize_visit_payload(expected_plan_of_care_version=poc_v),
        _BILLING_CLERK,
    )
    return get_success_data(res)


def complete_and_finalize_visit(
    visit_id: str, therapist_id: str, actual_minutes: int, poc_id: str
) -> dict:
    """Walk SCHEDULED → COMPLETED → FINALIZED (PRD §3.5)."""
    complete_visit(visit_id, therapist_id, actual_minutes)
    return finalize_visit(visit_id, poc_id)


# ─── Tier 5: scenario shortcuts driven by §1.8 difficulty design ─


def setup_poc_with_grant(
    insurance_type: str = "COMMERCIAL",
    is_veteran: bool = False,
    medicare_enrolled: bool = False,
    total_units_granted: int = 20,
    certified_start_date: str = "2026-06-01",
    certified_end_date: str = "2026-07-31",
    grant_effective_from: str = "2026-06-01",
    grant_effective_to: str = "2026-07-31",
    initial_clock: str = "2026-06-01T00:00:00Z",
) -> dict:
    """ACTIVE POC + 1 ACTIVE Grant (PRD §3.2, §3.4)."""
    ctx = setup_active_poc(
        insurance_type=insurance_type,
        is_veteran=is_veteran,
        medicare_enrolled=medicare_enrolled,
        certified_start_date=certified_start_date,
        certified_end_date=certified_end_date,
        initial_clock=initial_clock,
    )
    grant = create_grant(
        ctx["poc"]["id"],
        total_units_granted=total_units_granted,
        effective_from=grant_effective_from,
        effective_to=grant_effective_to,
    )
    ctx["grant"] = grant
    return ctx


def setup_completed_visit(
    insurance_type: str = "MEDICARE",
    medicare_enrolled: bool = True,
    planned_minutes: int = 30,
    actual_minutes: int = 30,
    cpt_code: str = "CPT_97110_THER_EX",
    scheduled_start_utc: str = "2026-06-02T09:00:00Z",
    scheduled_end_utc: str = "2026-06-02T09:30:00Z",
    initial_clock: str = "2026-06-01T00:00:00Z",
    total_units_granted: int = 20,
) -> dict:
    """ACTIVE POC + Grant + Visit scheduled and completed (PRD §3.5)."""
    ctx = setup_poc_with_grant(
        insurance_type=insurance_type,
        medicare_enrolled=medicare_enrolled,
        total_units_granted=total_units_granted,
        initial_clock=initial_clock,
    )
    v = schedule_visit(
        ctx["grant"]["id"], ctx["therapist"]["id"],
        scheduled_start_utc=scheduled_start_utc,
        scheduled_end_utc=scheduled_end_utc,
        planned_minutes=planned_minutes,
        cpt_code=cpt_code,
    )
    v_completed = complete_visit(v["id"], ctx["therapist"]["id"], actual_minutes)
    ctx["visit"] = v_completed
    return ctx


def setup_recert_due_poc(
    certified_start_date: str = "2026-06-01",
    certified_end_date: str = "2026-06-08",
    initial_clock: str = "2026-06-01T00:00:00Z",
    advance_clock_to: str = "2026-06-04T12:00:00Z",
    re_eval_performed_on: str = "2026-06-04",
) -> dict:
    """ACTIVE COMMERCIAL POC short-window + clock advanced inside the 7-day
    window so the POC auto-transitions to RECERT_DUE (PRD §3.6); RE_EVAL recorded.
    Returns ctx with the RECERT_DUE POC.
    """
    ctx = setup_active_poc(
        insurance_type="COMMERCIAL",
        certified_start_date=certified_start_date,
        certified_end_date=certified_end_date,
        initial_clock=initial_clock,
    )
    set_clock(advance_clock_to)
    record_re_evaluation(ctx["poc"]["id"], ctx["therapist"]["id"], re_eval_performed_on)
    # Re-read POC so callers see the RECERT_DUE status and latest version.
    poc_after = get_success_data(
        api_client.get_plan_of_care(ctx["poc"]["id"], make_therapist_headers(ctx["therapist"]["id"]))
    )
    ctx["poc"] = poc_after
    return ctx


def record_discharge_assessment(
    poc_id: str,
    therapist_id: str,
    goals_met_count: int = 8,
    total_goals_count: int = 10,
    final_functional_score: int = 70,
    assessed_on: str = "2026-06-10",
) -> dict:
    res = api_client.create_discharge_assessment(
        create_discharge_assessment_payload(
            plan_of_care_id=poc_id,
            assessing_therapist_id=therapist_id,
            final_functional_score=final_functional_score,
            goals_met_count=goals_met_count,
            total_goals_count=total_goals_count,
            assessed_on=assessed_on,
        ),
        make_therapist_headers(therapist_id),
    )
    return get_success_data(res)


def discharge_poc(poc_id: str, therapist_id: str) -> dict:
    res = api_client.discharge_plan_of_care(poc_id, make_therapist_headers(therapist_id))
    return get_success_data(res)


# ─── Tier 6: MIPS / HEP composites ──────────────────────────────


def create_hep(
    poc_id: str,
    therapist_id: str,
    prescribed_on: str = "2026-06-02",
    exercise_count: int = 5,
    weekly_frequency: int = 3,
) -> dict:
    res = api_client.create_home_exercise_program(
        create_home_exercise_program_payload(
            plan_of_care_id=poc_id,
            prescribed_by_therapist_id=therapist_id,
            exercise_count=exercise_count,
            weekly_frequency=weekly_frequency,
            prescribed_on=prescribed_on,
        ),
        make_therapist_headers(therapist_id),
    )
    return get_success_data(res)


def create_mips(
    patient_id: str,
    poc_id: str,
    therapist_id: str,
    measure_code: str = "MIPS128_FALL_RISK",
    performance_period_start: str = "2026-06-01",
    performance_period_end: str = "2026-06-30",
    numerator_met: bool = True,
) -> dict:
    res = api_client.create_mips_measure(
        create_mips_measure_payload(
            patient_id=patient_id,
            plan_of_care_id=poc_id,
            reporting_therapist_id=therapist_id,
            measure_code=measure_code,
            performance_period_start=performance_period_start,
            performance_period_end=performance_period_end,
            numerator_met=numerator_met,
        ),
        make_therapist_headers(therapist_id),
    )
    return get_success_data(res)
