"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so every helper builds its preconditions from scratch using
only PRD-declared endpoints. Helpers use get_success_data() (lenient) so setup
failures surface clearly.

Clinician is entity_backed: after a Clinician entity is created, any
ownership-gated call uses make_clinician_headers(clinician["id"]).
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_clinician_headers
from .constants import TEST_CLOCK
from . import factories as F

_INTAKE = TEST_USERS["intake_headers"]
_SUPER = TEST_USERS["supervisor_headers"]

# Unique NPI generator so multiple clinicians in one test never collide.
_npi_counter = itertools.count(1)


def _next_npi() -> str:
    return f"90000000{next(_npi_counter):02d}"[-10:]


# --- Clock -------------------------------------------------------------------

def reset_clock(api, iso=TEST_CLOCK):
    api.set_clock({"to_iso8601": iso}, _INTAKE)


# --- Primitive registrations -------------------------------------------------

def register_patient(api, **overrides):
    return get_success_data(api.create_patient(F.create_patient_payload(**overrides), _INTAKE))


def register_referral(api, patient_id, **overrides):
    return get_success_data(
        api.create_referral(F.create_referral_payload(patient_id, **overrides), _INTAKE)
    )


def register_clinician(api, **overrides):
    overrides.setdefault("npi", _next_npi())
    return get_success_data(api.create_clinician(F.create_clinician_payload(**overrides), _SUPER))


def register_room(api, **overrides):
    return get_success_data(api.create_room(F.create_room_payload(**overrides), _SUPER))


# --- Assessment tier: measured input recipes ---------------------------------
# HIGH-tier composite: gait 0.55 / tug 14.0 / berg 18 / meds 5 / falls 2 -> 110.
# LOW-tier composite:  gait 1.20 / tug 8.0 / berg 55 / meds 0 / falls 0 -> 0.
LOW_TIER_MEASURES = {
    "gait_speed_m_s": 1.20, "tug_seconds": 8.0, "berg_balance_score": 55,
    "medication_count": 0, "self_report_fall_count": 0,
}


def setup_finalized_assessment(api, assessment_overrides=None):
    """Clock reset + patient + referral + clinician + one FINALIZED assessment
    (HIGH tier by default). Returns a context dict."""
    reset_clock(api)
    patient = register_patient(api)
    referral = register_referral(api, patient["id"])
    clinician = register_clinician(api)
    ch = make_clinician_headers(clinician["id"])
    payload = F.create_assessment_payload(
        patient["id"], referral["id"], clinician["id"], **(assessment_overrides or {})
    )
    assessment = get_success_data(api.create_assessment(payload, ch))
    get_success_data(api.finalize_assessment(assessment["id"], ch))
    assessment = get_success_data(api.get_assessment(assessment["id"], ch))
    return {
        "patient": patient,
        "referral": referral,
        "clinician": clinician,
        "clinician_headers": ch,
        "assessment": assessment,
    }


def setup_active_care_plan(api, assessment_overrides=None):
    """FINALIZED assessment -> care plan created -> ACTIVE. Returns context with
    'care_plan' (freshly read, ACTIVE)."""
    ctx = setup_finalized_assessment(api, assessment_overrides)
    cp = get_success_data(
        api.create_care_plan(
            F.create_care_plan_payload(ctx["patient"]["id"], ctx["assessment"]["id"]), _INTAKE
        )
    )
    get_success_data(api.activate_care_plan(cp["id"], _SUPER))
    ctx["care_plan"] = get_success_data(api.get_care_plan(cp["id"], _INTAKE))
    return ctx


def setup_plan_with_approved_auth(api, assessment_overrides=None, auth_overrides=None):
    """ACTIVE plan + one BALANCE_GYM room + one APPROVED authorization.
    Returns context with 'room' and 'authorization' (APPROVED)."""
    ctx = setup_active_care_plan(api, assessment_overrides)
    ctx["room"] = register_room(api)
    auth = get_success_data(
        api.create_authorization(
            F.create_authorization_payload(
                ctx["patient"]["id"], ctx["care_plan"]["id"], **(auth_overrides or {})
            ),
            _INTAKE,
        )
    )
    get_success_data(api.decide_authorization(auth["id"], {"decision": "APPROVE"}, _SUPER))
    ctx["authorization"] = get_success_data(api.get_authorization(auth["id"], _INTAKE))
    return ctx


def schedule_session(api, ctx, room_id=None, actor=None, **session_overrides):
    """Schedule one session on ctx's plan/clinician/room/authorization.
    Returns the created Session (SCHEDULED)."""
    payload = F.create_session_payload(
        ctx["care_plan"]["id"],
        ctx["clinician"]["id"],
        room_id or ctx["room"]["id"],
        ctx["authorization"]["id"],
        **session_overrides,
    )
    return get_success_data(api.create_session(payload, actor or _INTAKE))


def attend_session(api, ctx, session_id):
    return get_success_data(api.attend_session(session_id, ctx["clinician_headers"]))


def plan_version(api, care_plan_id) -> int:
    return get_success_data(api.get_care_plan(care_plan_id, _INTAKE))["version"]


# --- Home safety -------------------------------------------------------------

def setup_active_plan_with_draft_home_safety(api, hazard_overrides=None):
    """ACTIVE plan + one DRAFT HomeSafetyEvaluation (all hazard counts 0 unless
    overridden). Returns context with 'evaluation'."""
    ctx = setup_active_care_plan(api)
    ev = get_success_data(
        api.create_home_safety_evaluation(
            F.create_home_safety_payload(
                ctx["patient"]["id"], ctx["care_plan"]["id"], **(hazard_overrides or {})
            ),
            ctx["clinician_headers"],
        )
    )
    ctx["evaluation"] = ev
    return ctx


# --- Reassessment ------------------------------------------------------------

def setup_plan_under_reassessment(api, reassessment_overrides=None):
    """ACTIVE HIGH plan -> open reassessment (plan now UNDER_REASSESSMENT).
    Returns context with 'reassessment' (DRAFT) and refreshed 'care_plan'."""
    ctx = setup_active_care_plan(api)
    payload = F.create_reassessment_payload(ctx["clinician"]["id"], **(reassessment_overrides or {}))
    re = get_success_data(api.create_reassessment(ctx["care_plan"]["id"], payload, ctx["clinician_headers"]))
    ctx["reassessment"] = re
    ctx["care_plan"] = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], _INTAKE))
    return ctx
