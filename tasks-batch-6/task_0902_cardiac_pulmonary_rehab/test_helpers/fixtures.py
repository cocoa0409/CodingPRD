"""Composite setup helpers.

The per-test-server harness gives each test an empty database, so every fixture
builds its preconditions from scratch through PRD-declared endpoints only.

The recurring preamble for almost every interesting behavior is:
    patient + physician + clinician + station
    -> referral -> ACCEPT decision -> program
    -> authorization -> approve
    -> BASELINE outcome -> finalize
    -> activate program (ACTIVE, ready to schedule)
`setup_active_program` runs this whole chain and returns a context dict.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as F
from .test_users import (
    make_coordinator_headers,
    make_billing_headers,
    make_physician_headers,
    make_clinician_headers,
)

_BASE_START = datetime(2026, 5, 4, 9, 0, 0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def interval_for_slot(slot: int, duration_minutes: int = 60):
    """Non-overlapping, buffer-safe interval: slots are spaced 2 hours apart so a
    60-minute session leaves a 60-minute gap (> the 15-minute clinician buffer and
    no station overlap)."""
    start = _BASE_START + timedelta(hours=2 * slot)
    end = start + timedelta(minutes=duration_minutes)
    return iso(start), iso(end)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def create_patient(api=api_client, **overrides) -> dict:
    coord = make_coordinator_headers()
    return get_success_data(api.create_patient(F.create_patient_payload(**overrides), coord))


def create_physician(api=api_client, **overrides) -> dict:
    coord = make_coordinator_headers()
    return get_success_data(api.create_physician(F.create_physician_payload(**overrides), coord))


def create_clinician(api=api_client, **overrides) -> dict:
    coord = make_coordinator_headers()
    return get_success_data(api.create_clinician(F.create_clinician_payload(**overrides), coord))


def create_station(api=api_client, station_type="TELEMETRY", **overrides) -> dict:
    coord = make_coordinator_headers()
    return get_success_data(
        api.create_station(F.create_station_payload(station_type=station_type, **overrides), coord)
    )


def create_accepted_referral(api=api_client, patient_id=None, physician_id=None,
                             program_type="CARDIAC", risk_stratification="MODERATE",
                             decision="ACCEPT", **overrides) -> dict:
    """Create a referral (as its owning physician) and disposition it. Returns the referral."""
    coord = make_coordinator_headers()
    if patient_id is None:
        patient_id = create_patient(api)["id"]
    if physician_id is None:
        physician_id = create_physician(api)["id"]
    phys = make_physician_headers(physician_id)
    referral = get_success_data(api.create_referral(
        F.create_referral_payload(patient_id, physician_id,
                                  program_type=program_type,
                                  risk_stratification=risk_stratification, **overrides),
        phys,
    ))
    if decision is not None:
        get_success_data(api.decide_referral(referral["id"], {"decision": decision}, coord))
    return referral


# ---------------------------------------------------------------------------
# Tier 1 / 2: build a DRAFT program, then an ACTIVE program
# ---------------------------------------------------------------------------
def setup_draft_program(
    api=api_client,
    program_type="CARDIAC",
    risk_stratification="MODERATE",
    station_type="TELEMETRY",
    authorized_session_cap=None,
    current_phase=None,
    baseline_distance=300,
    allowed_amount_cents=18000,
    copay_cents=2000,
    authorized_visits=10,
    with_authorization=True,
    approve_authorization=True,
    with_baseline=True,
    finalize_baseline=True,
) -> dict:
    """Build reference data + program in DRAFT, optionally with authorization and
    baseline outcome. Returns a context dict with ids and role headers."""
    coord = make_coordinator_headers()
    patient = create_patient(api)
    physician = create_physician(api)
    clinician = create_clinician(api)
    station = create_station(api, station_type=station_type)

    clin_headers = make_clinician_headers(clinician["id"])

    referral = create_accepted_referral(
        api, patient_id=patient["id"], physician_id=physician["id"],
        program_type=program_type, risk_stratification=risk_stratification,
    )

    prog_overrides = {}
    if authorized_session_cap is not None:
        prog_overrides["authorized_session_cap"] = authorized_session_cap
    if current_phase is not None:
        prog_overrides["current_phase"] = current_phase
    program = get_success_data(api.create_program(
        F.create_program_payload(referral["id"], **prog_overrides), coord
    ))

    ctx = {
        "api": api,
        "coord": coord,
        "billing": make_billing_headers(),
        "clin_headers": clin_headers,
        "phys_headers": make_physician_headers(physician["id"]),
        "patient_id": patient["id"],
        "physician_id": physician["id"],
        "clinician_id": clinician["id"],
        "station_id": station["id"],
        "referral_id": referral["id"],
        "program_id": program["id"],
        "authorization_id": None,
        "baseline_outcome_id": None,
        "version": program["version"],
        "_slot": 0,
    }

    if with_authorization:
        auth = get_success_data(api.create_authorization(
            F.create_authorization_payload(
                program["id"],
                allowed_amount_cents=allowed_amount_cents,
                copay_cents=copay_cents,
                authorized_visits=authorized_visits,
            ),
            coord,
        ))
        ctx["authorization_id"] = auth["id"]
        if approve_authorization:
            get_success_data(api.approve_authorization(auth["id"], coord))

    if with_baseline:
        base = get_success_data(api.create_outcome(
            F.create_outcome_payload(program["id"], "BASELINE", baseline_distance), clin_headers
        ))
        ctx["baseline_outcome_id"] = base["id"]
        if finalize_baseline:
            get_success_data(api.finalize_outcome(base["id"], {}, clin_headers))

    return ctx


def setup_active_program(api=api_client, **overrides) -> dict:
    """Full chain through ACTIVE. Returns a context dict; ctx['version'] is the
    program version observed right after activation."""
    ctx = setup_draft_program(api, **overrides)
    activated = get_success_data(api.activate_program(ctx["program_id"], ctx["coord"]))
    ctx["version"] = activated["version"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 / 4: sessions and cumulative session state
# ---------------------------------------------------------------------------
def _fresh_version(ctx) -> int:
    prog = get_success_data(ctx["api"].get_program(ctx["program_id"], ctx["coord"]))
    ctx["version"] = prog["version"]
    return prog["version"]


def schedule_session(ctx, session_type="MONITORED_EXERCISE", phase="PHASE_II",
                     clinician_id=None, station_id=None,
                     scheduled_start=None, scheduled_end=None,
                     expected_program_version=None, return_response=False):
    """Schedule a session on the ACTIVE program. Auto-derives a non-overlapping
    interval and the current program version unless overridden."""
    api = ctx["api"]
    if scheduled_start is None or scheduled_end is None:
        s, e = interval_for_slot(ctx["_slot"])
        ctx["_slot"] += 1
        scheduled_start = scheduled_start or s
        scheduled_end = scheduled_end or e
    if expected_program_version is None:
        expected_program_version = _fresh_version(ctx)
    payload = F.create_session_payload(
        ctx["program_id"],
        clinician_id or ctx["clinician_id"],
        station_id or ctx["station_id"],
        expected_program_version,
        session_type=session_type,
        phase=phase,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    resp = api.create_session(payload, ctx["coord"])
    if return_response:
        return resp
    return get_success_data(resp)


def complete_session(ctx, session_id, post_spo2=96, rpe=12, exercise_minutes=30,
                     return_response=False, **vitals):
    """Complete a scheduled session recording vitals (as the owning clinician)."""
    api = ctx["api"]
    payload = {"post_spo2": post_spo2, "rpe": rpe, "exercise_minutes": exercise_minutes}
    payload.update(vitals)
    resp = api.complete_session(session_id, payload, ctx["clin_headers"])
    if return_response:
        return resp
    return get_success_data(resp)


def create_completed_session(ctx, session_type="MONITORED_EXERCISE",
                             post_spo2=96, rpe=12, exercise_minutes=30, **sched):
    """Schedule then complete a non-adverse session. Returns the completed session."""
    session = schedule_session(ctx, session_type=session_type, **sched)
    return complete_session(ctx, session["id"], post_spo2=post_spo2, rpe=rpe,
                            exercise_minutes=exercise_minutes)


# ---------------------------------------------------------------------------
# Tier 3: billing claims
# ---------------------------------------------------------------------------
def create_claim(ctx, session_id, authorization_id=None, return_response=False):
    api = ctx["api"]
    resp = api.create_claim(
        F.create_claim_payload(ctx["program_id"], session_id,
                               authorization_id or ctx["authorization_id"]),
        ctx["billing"],
    )
    if return_response:
        return resp
    return get_success_data(resp)


def create_submitted_claim(ctx, session_id=None, **complete_kwargs):
    """Complete a session, create a claim against it, and submit it. Returns the claim."""
    if session_id is None:
        session_id = create_completed_session(ctx, **complete_kwargs)["id"]
    claim = create_claim(ctx, session_id)
    get_success_data(ctx["api"].submit_claim(claim["id"], ctx["billing"]))
    return get_success_data(ctx["api"].get_claim(claim["id"], ctx["billing"]))


# ---------------------------------------------------------------------------
# Tier 5: outcomes / discharge readiness
# ---------------------------------------------------------------------------
def add_finalized_discharge_outcome(ctx, distance_meters=380, final_distance_meters=None):
    """Add a DISCHARGE outcome and finalize it (optionally correcting distance)."""
    api = ctx["api"]
    disch = get_success_data(api.create_outcome(
        F.create_outcome_payload(ctx["program_id"], "DISCHARGE", distance_meters),
        ctx["clin_headers"],
    ))
    payload = {} if final_distance_meters is None else {"final_distance_meters": final_distance_meters}
    get_success_data(api.finalize_outcome(disch["id"], payload, ctx["clin_headers"]))
    return get_success_data(api.get_outcome(disch["id"], ctx["clin_headers"]))
