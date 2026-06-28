"""Composite setup helpers.

These encapsulate the multi-step API sequences that most test claims need to
reach an interesting state. They use get_success_data() (the lenient 2xx
validator) so a setup miss surfaces as a clear "Setup failed" rather than a
confusing assertion failure deep inside a test.

All roles are opaque operator identities (PRD §2.1), so headers come straight
from the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import ADMIN, INTAKE, CLINICIAN, DIETITIAN, REVIEWER
from . import factories as f


# ---------------------------------------------------------------------------
# Tier 0: physical substrate
# ---------------------------------------------------------------------------
def create_facility(name="Test Facility"):
    return get_success_data(
        api.create_facility(f.create_facility_payload(name=name), ADMIN)
    )


def create_program(facility_id, level_of_care="RESIDENTIAL", bed_capacity=5):
    return get_success_data(
        api.create_program(
            f.create_program_payload(
                facility_id,
                level_of_care=level_of_care,
                bed_capacity=bed_capacity,
            ),
            ADMIN,
        )
    )


def create_cohort(program_id, facility_id, age_band="ADULT", slot_capacity=5,
                  name="Adult AM"):
    return get_success_data(
        api.create_cohort(
            f.create_cohort_payload(
                program_id,
                facility_id,
                age_band=age_band,
                slot_capacity=slot_capacity,
                name=name,
            ),
            ADMIN,
        )
    )


def create_patient(facility_id, age_band="ADULT", bmi=17.0, full_name="Test Patient"):
    return get_success_data(
        api.create_patient(
            f.create_patient_payload(
                facility_id, age_band=age_band, bmi=bmi, full_name=full_name
            ),
            INTAKE,
        )
    )


def create_substrate(level_of_care="RESIDENTIAL", bed_capacity=5,
                     cohort_age_band="ADULT", slot_capacity=5):
    """Facility + program + cohort. Returns (facility, program, cohort)."""
    facility = create_facility()
    program = create_program(facility["id"], level_of_care, bed_capacity)
    cohort = create_cohort(
        program["id"], facility["id"], cohort_age_band, slot_capacity
    )
    return facility, program, cohort


# ---------------------------------------------------------------------------
# Tier 1: assessment / finalize (patient risk + posture seeding)
# ---------------------------------------------------------------------------
def create_finalized_assessment(patient, facility_id, med=5, beh=5, psy=4, mot=6):
    """Create a DRAFT assessment on the patient and finalize it (OCC-correct).
    Returns the finalized assessment data."""
    assessment = get_success_data(
        api.create_assessment(
            f.create_assessment_payload(
                patient["id"],
                facility_id,
                medical_severity=med,
                behavioral_severity=beh,
                psychiatric_severity=psy,
                motivation_level=mot,
            ),
            CLINICIAN,
        )
    )
    get_success_data(
        api.finalize_assessment(
            assessment["id"], {"expected_patient_version": patient["version"]}, CLINICIAN
        )
    )
    return assessment


# ---------------------------------------------------------------------------
# Tier 2: authorizations / reviews
# ---------------------------------------------------------------------------
def create_authorization(admission_id, facility_id, daily_rate_cents=100000,
                         coinsurance_pct=0.20):
    return get_success_data(
        api.create_authorization(
            f.create_authorization_payload(
                admission_id,
                facility_id,
                daily_rate_cents=daily_rate_cents,
                coinsurance_pct=coinsurance_pct,
            ),
            REVIEWER,
        )
    )


def approve_review(authorization_id, facility_id, window_start_iso, window_end_iso):
    return get_success_data(
        api.create_review(
            f.create_review_payload(
                authorization_id,
                facility_id,
                "APPROVE",
                window_start_iso=window_start_iso,
                window_end_iso=window_end_iso,
            ),
            REVIEWER,
        )
    )


def setup_substrate_minimal_for_auth(los_days=7,
                                     window_start_iso="2026-01-01T00:00:00Z",
                                     window_end_iso="2026-01-08T00:00:00Z",
                                     daily_rate_cents=100000, coinsurance_pct=0.20):
    """Minimal chain to an APPROVED authorization: facility -> program -> cohort
    -> patient -> admission -> authorization -> review(APPROVE). No assessment,
    no promote/admit (day-balance and billing reads do not require an admit).

    Returns a dict with keys facility, program, cohort, patient, admission,
    authorization (re-read after the approve).
    """
    facility = create_facility()
    program = create_program(facility["id"])
    cohort = create_cohort(program["id"], facility["id"])
    patient = create_patient(facility["id"])
    admission = create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"], los_days
    )
    auth = create_authorization(
        admission["id"], facility["id"], daily_rate_cents, coinsurance_pct
    )
    approve_review(auth["id"], facility["id"], window_start_iso, window_end_iso)
    auth = get_success_data(api.get_authorization(auth["id"], REVIEWER))
    return {
        "facility": facility,
        "program": program,
        "cohort": cohort,
        "patient": patient,
        "admission": admission,
        "authorization": auth,
    }


def create_approved_authorization(admission_id, facility_id,
                                  window_start_iso="2026-01-01T00:00:00Z",
                                  window_end_iso="2026-01-15T00:00:00Z",
                                  daily_rate_cents=100000, coinsurance_pct=0.20):
    """Authorization + first APPROVE review. Returns the authorization data
    (re-read after approve so day counters reflect the window)."""
    auth = create_authorization(
        admission_id, facility_id, daily_rate_cents, coinsurance_pct
    )
    approve_review(auth["id"], facility_id, window_start_iso, window_end_iso)
    return get_success_data(api.get_authorization(auth["id"], REVIEWER))


# ---------------------------------------------------------------------------
# Tier 3: admissions and lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_admission(patient_id, facility_id, program_id, cohort_id,
                     requested_length_of_stay_days=7):
    return get_success_data(
        api.create_admission(
            f.create_admission_payload(
                patient_id,
                facility_id,
                program_id,
                cohort_id,
                requested_length_of_stay_days=requested_length_of_stay_days,
            ),
            INTAKE,
        )
    )


def setup_admitted_admission(level_of_care="RESIDENTIAL", bed_capacity=5,
                             cohort_age_band="ADULT", patient_age_band="ADULT",
                             bmi=17.0, los_days=14, med=5, beh=5, psy=4, mot=6,
                             window_end_iso="2026-01-15T00:00:00Z",
                             daily_rate_cents=100000, coinsurance_pct=0.20):
    """Full standard chain to an ADMITTED admission.

    facility -> program -> cohort -> patient -> assessment -> finalize ->
    admission -> authorization -> review(APPROVE) -> promote -> admit.

    Returns a dict of all created entities (re-reading the admission and program
    after admit). Keys: facility, program, cohort, patient, assessment,
    admission, authorization.
    """
    facility = create_facility()
    program = create_program(facility["id"], level_of_care, bed_capacity)
    cohort = create_cohort(
        program["id"], facility["id"], cohort_age_band
    )
    patient = create_patient(facility["id"], patient_age_band, bmi)
    assessment = create_finalized_assessment(
        patient, facility["id"], med, beh, psy, mot
    )
    admission = create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"], los_days
    )
    auth = create_authorization(
        admission["id"], facility["id"], daily_rate_cents, coinsurance_pct
    )
    approve_review(auth["id"], facility["id"], "2026-01-01T00:00:00Z", window_end_iso)
    get_success_data(api.promote_admission(admission["id"], INTAKE))
    admission = get_success_data(api.admit_admission(admission["id"], INTAKE))
    program = get_success_data(api.get_program(program["id"], ADMIN))
    auth = get_success_data(api.get_authorization(auth["id"], REVIEWER))
    return {
        "facility": facility,
        "program": program,
        "cohort": cohort,
        "patient": patient,
        "assessment": assessment,
        "admission": admission,
        "authorization": auth,
    }


def setup_pending_admission(level_of_care="RESIDENTIAL", bed_capacity=5,
                            cohort_age_band="ADULT", patient_age_band="ADULT",
                            bmi=17.0, los_days=7, med=5, beh=5, psy=4, mot=6,
                            with_authorization=True, finalize_assessment=True,
                            window_end_iso="2026-01-08T00:00:00Z"):
    """Chain to a PENDING_ADMISSION admission (promoted, not yet admitted).

    Returns a dict with keys facility, program, cohort, patient, admission, and
    authorization (None when with_authorization is False).
    """
    facility = create_facility()
    program = create_program(facility["id"], level_of_care, bed_capacity)
    cohort = create_cohort(program["id"], facility["id"], cohort_age_band)
    patient = create_patient(facility["id"], patient_age_band, bmi)
    if finalize_assessment:
        create_finalized_assessment(patient, facility["id"], med, beh, psy, mot)
        patient = get_success_data(api.get_patient(patient["id"], INTAKE))
    admission = create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"], los_days
    )
    auth = None
    if with_authorization:
        auth = create_approved_authorization(
            admission["id"], facility["id"], window_end_iso=window_end_iso
        )
    get_success_data(api.promote_admission(admission["id"], INTAKE))
    admission = get_success_data(api.get_admission(admission["id"], INTAKE))
    return {
        "facility": facility,
        "program": program,
        "cohort": cohort,
        "patient": patient,
        "admission": admission,
        "authorization": auth,
    }


# ---------------------------------------------------------------------------
# Tier 3b: treatment plans
# ---------------------------------------------------------------------------
def create_active_treatment_plan(admission_id, facility_id, goals_total=5):
    """Create a treatment plan, sign all three disciplines, and activate it.
    Returns the activated plan data."""
    tp = get_success_data(
        api.create_treatment_plan(
            f.create_treatment_plan_payload(
                admission_id, facility_id, goals_total=goals_total
            ),
            CLINICIAN,
        )
    )
    get_success_data(
        api.sign_treatment_plan(tp["id"], {"discipline": "THERAPY"}, CLINICIAN)
    )
    get_success_data(
        api.sign_treatment_plan(tp["id"], {"discipline": "MEDICAL"}, CLINICIAN)
    )
    get_success_data(
        api.sign_treatment_plan(tp["id"], {"discipline": "DIETITIAN"}, DIETITIAN)
    )
    return get_success_data(api.activate_treatment_plan(tp["id"], CLINICIAN))


def mark_goals_met(tp_id, n):
    for _ in range(n):
        get_success_data(api.mark_goal_met(tp_id, CLINICIAN))


# ---------------------------------------------------------------------------
# Tier 3c: meal plans / events
# ---------------------------------------------------------------------------
def create_meal_plan(admission_id, facility_id, required_meals_per_day=4,
                     supervision_level="FULL"):
    return get_success_data(
        api.create_meal_plan(
            f.create_meal_plan_payload(
                admission_id,
                facility_id,
                required_meals_per_day=required_meals_per_day,
                supervision_level=supervision_level,
            ),
            DIETITIAN,
        )
    )


_MEAL_TYPES = ["BREAKFAST", "LUNCH", "DINNER", "SNACK"]


def log_meal_events(meal_plan_id, admission_id, fractions):
    """Log one meal event per entry in `fractions`. Returns the final
    re-read meal plan data."""
    for i, frac in enumerate(fractions):
        payload = f.create_meal_event_payload(
            meal_plan_id,
            admission_id,
            meal_type=_MEAL_TYPES[i % len(_MEAL_TYPES)],
            completion_fraction=frac,
        )
        get_success_data(api.create_meal_event(payload, DIETITIAN))
    return get_success_data(api.get_meal_plan(meal_plan_id, DIETITIAN))


def create_meal_plan_with_events(admission_id, facility_id, fractions,
                                 required_meals_per_day=4, supervision_level="FULL"):
    """Meal plan + N events. Returns (meal_plan, re-read)."""
    mp = create_meal_plan(
        admission_id, facility_id, required_meals_per_day, supervision_level
    )
    mp = log_meal_events(mp["id"], admission_id, fractions)
    return mp


# ---------------------------------------------------------------------------
# Tier 4: step-down readiness scenarios
# ---------------------------------------------------------------------------
def setup_step_down_ready(level_of_care="RESIDENTIAL", goals_total=5, goals_met=5,
                          meal_fractions=(0.9, 0.9, 0.8, 0.8), med=5, beh=5, psy=4,
                          mot=6, bmi=17.0):
    """ADMITTED admission with an ACTIVE treatment plan (goals marked met) and a
    meal plan with the given event fractions. Returns the same dict as
    setup_admitted_admission plus 'treatment_plan' and 'meal_plan' keys."""
    ctx = setup_admitted_admission(
        level_of_care=level_of_care, med=med, beh=beh, psy=psy, mot=mot, bmi=bmi
    )
    tp = create_active_treatment_plan(ctx["admission"]["id"], ctx["facility"]["id"],
                                      goals_total=goals_total)
    if goals_met:
        mark_goals_met(tp["id"], goals_met)
        tp = get_success_data(api.get_treatment_plan(tp["id"], CLINICIAN))
    mp = create_meal_plan_with_events(
        ctx["admission"]["id"], ctx["facility"]["id"], list(meal_fractions)
    )
    ctx["treatment_plan"] = tp
    ctx["meal_plan"] = mp
    ctx["patient"] = get_success_data(api.get_patient(ctx["patient"]["id"], INTAKE))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: family program + discharge plan + discharge-ready
# ---------------------------------------------------------------------------
def create_waived_family_program(admission_id, facility_id, sessions_required=1):
    fp = get_success_data(
        api.create_family_program(
            f.create_family_program_payload(
                admission_id, facility_id, sessions_required=sessions_required
            ),
            CLINICIAN,
        )
    )
    return get_success_data(api.waive_family_program(fp["id"], CLINICIAN))


def create_finalized_discharge_plan(admission_id, facility_id,
                                    aftercare_level_of_care="IOP"):
    dp = get_success_data(
        api.create_discharge_plan(
            f.create_discharge_plan_payload(
                admission_id,
                facility_id,
                aftercare_level_of_care=aftercare_level_of_care,
                relapse_plan_complete=True,
            ),
            CLINICIAN,
        )
    )
    return get_success_data(api.finalize_discharge_plan(dp["id"], CLINICIAN))


def setup_discharge_pending(bed_capacity=5, meal_fractions=(1.0, 1.0, 0.9, 0.9),
                            with_meal_plan=True):
    """ADMITTED admission carried to DISCHARGE_PENDING with a finalized discharge
    plan and a waived family program. Optionally with an ACTIVE meal plan still
    open (so the discharge cascade can close it). Returns the admitted-context
    dict plus 'meal_plan' (when created)."""
    ctx = setup_admitted_admission(bed_capacity=bed_capacity)
    if with_meal_plan:
        mp = create_meal_plan_with_events(
            ctx["admission"]["id"], ctx["facility"]["id"], list(meal_fractions)
        )
        ctx["meal_plan"] = mp
    create_waived_family_program(ctx["admission"]["id"], ctx["facility"]["id"])
    create_finalized_discharge_plan(ctx["admission"]["id"], ctx["facility"]["id"])
    ctx["admission"] = get_success_data(
        api.begin_discharge_admission(ctx["admission"]["id"], CLINICIAN)
    )
    ctx["patient"] = get_success_data(api.get_patient(ctx["patient"]["id"], INTAKE))
    return ctx
