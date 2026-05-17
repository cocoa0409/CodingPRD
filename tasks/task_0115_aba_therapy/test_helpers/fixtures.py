"""Composite setup helpers — multi-step preambles tests can reuse.

The ABA-therapy lifecycle is long: clinic bootstrap -> register BCBA and
RBT -> create patient -> schedule evaluation -> start/complete evaluation
-> draft treatment plan -> activate plan -> create authorization ->
PayerAdmin approves -> clock advances to effective_start (so
authorization auto-transitions APPROVED→ACTIVE) -> schedule sessions ->
start/complete sessions -> draft claim -> submit -> adjudicate -> pay
(or deny -> appeal cycle). Most interesting test claims need the system
to be in a late-pipeline state.

IDENTITY THREADING — PRD §2.1:

- BCBA and RBT are ENTITY-BACKED. Every BCBA- or RBT-driven call whose
  success depends on owning the targeted DiagnosticEvaluation or
  TherapySession (start, complete, dispute, resolve-dispute) MUST mint
  headers via make_bcba_headers(bcba["id"]) or
  make_rbt_headers(rbt["id"]) — never via the shared *_FALLBACK_ID
  constants. The fixtures here remember the acting Therapist.id and
  thread it through every ownership-gated call.

- ClinicAdmin and PayerAdmin are OPAQUE. Their shared TEST_USERS headers
  are canonical for every call.

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    PATIENT_RESPONSIBILITY_DEFAULT,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    TEST_DEFAULTS,
    TIERED_RATES_CENTS,
)
from .factories import (
    add_days,
    add_minutes,
    add_seconds,
    adjudicate_claim_payload,
    clock_advance_payload,
    clock_epoch,
    complete_evaluation_payload,
    complete_session_payload,
    create_authorization_payload,
    create_claim_payload,
    create_clinic_payload,
    create_evaluation_payload,
    create_patient_payload,
    create_session_payload,
    create_therapist_payload,
    create_treatment_plan_payload,
    dispute_session_payload,
    parse_iso,
    round_half_up,
    supersede_treatment_plan_payload,
)
from .test_users import (
    TEST_USERS,
    make_bcba_headers,
    make_rbt_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.5
# ===========================================================================
def advance_clock(
    clinic_id: str,
    seconds: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §2.5: ClinicAdmin only."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(clinic_id=clinic_id, seconds=seconds),
        headers,
    )
    return get_success_data(resp)


def advance_clock_to(
    clinic_id: str,
    current_now_ts: str,
    target_iso_ts: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Advance the clinic clock to the supplied target instant by
    computing the delta in whole seconds from the supplied current
    now_ts. The caller is responsible for passing a target strictly
    after current_now_ts (PRD §2.5: seconds must be positive)."""
    cur = parse_iso(current_now_ts)
    tgt = parse_iso(target_iso_ts)
    delta = int((tgt - cur).total_seconds())
    if delta <= 0:
        return {"now_ts": current_now_ts}
    return advance_clock(clinic_id, delta, headers)


# ===========================================================================
# Tier 0: clinic bootstrap and roster.
# ===========================================================================
def create_clinic(
    *,
    name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /clinics — ClinicAdmin only."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.create_clinic(
        create_clinic_payload(name=name), headers,
    )
    return get_success_data(resp)


def create_therapist(
    *,
    clinic_id: str,
    credential: str = "BCBA",
    legal_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /therapists — ClinicAdmin only."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.create_therapist(
        create_therapist_payload(
            clinic_id=clinic_id,
            credential=credential,
            legal_name=legal_name,
        ),
        headers,
    )
    return get_success_data(resp)


def create_patient(
    *,
    clinic_id: str,
    legal_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients — ClinicAdmin or BCBA."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.create_patient(
        create_patient_payload(
            clinic_id=clinic_id, legal_name=legal_name,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_clinic_with_roster(
    *,
    num_bcbas: int = 1,
    num_rbts: int = 1,
) -> Dict[str, Any]:
    """Compose: clinic + N BCBAs + N RBTs + 1 patient. Returns dict with
    keys clinic, bcbas (list), rbts (list), patient. Indexes 0 of the
    lists are the canonical actors."""
    clinic = create_clinic()
    bcbas = [
        create_therapist(clinic_id=clinic["id"], credential="BCBA")
        for _ in range(num_bcbas)
    ]
    rbts = [
        create_therapist(clinic_id=clinic["id"], credential="RBT")
        for _ in range(num_rbts)
    ]
    patient = create_patient(clinic_id=clinic["id"])
    return {
        "clinic": clinic,
        "bcbas": bcbas,
        "rbts": rbts,
        "patient": patient,
    }


# ===========================================================================
# Tier 1: evaluation lifecycle.
# ===========================================================================
def schedule_evaluation(
    *,
    patient_id: str,
    evaluator_therapist_id: str,
    scheduled_at: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/evaluations — BCBA or ClinicAdmin."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.create_evaluation(
        patient_id,
        create_evaluation_payload(
            evaluator_therapist_id=evaluator_therapist_id,
            scheduled_at=scheduled_at,
        ),
        headers,
    )
    return get_success_data(resp)


def start_evaluation(evaluation_id: str, *, bcba_id: str) -> Dict[str, Any]:
    """POST /evaluations/{id}/start — BCBA acting as themselves.

    PRD §3.2 / §2.1: evaluator_therapist_id must equal X-User-ID; mint
    per-instance BCBA headers.
    """
    headers = make_bcba_headers(bcba_id)
    resp = api_client.start_evaluation(evaluation_id, headers)
    return get_success_data(resp)


def complete_evaluation(
    evaluation_id: str,
    *,
    bcba_id: str,
    diagnosis_code: Optional[str] = None,
    severity_level: str = "LEVEL_2",
    recommended_weekly_hours: int = 20,
) -> Dict[str, Any]:
    """POST /evaluations/{id}/complete — BCBA acting as themselves."""
    headers = make_bcba_headers(bcba_id)
    resp = api_client.complete_evaluation(
        evaluation_id,
        complete_evaluation_payload(
            diagnosis_code=diagnosis_code,
            severity_level=severity_level,
            recommended_weekly_hours=recommended_weekly_hours,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_completed_evaluation(
    *,
    clinic: Dict[str, Any],
    patient: Dict[str, Any],
    bcba: Dict[str, Any],
    scheduled_offset_seconds: int = 3600,
    recommended_weekly_hours: int = 20,
) -> Dict[str, Any]:
    """Schedule -> advance clock to scheduled_at -> start -> complete.
    Returns the COMPLETED evaluation."""
    scheduled_at = add_seconds(
        clinic["now_ts"], seconds=scheduled_offset_seconds,
    )
    evaluation = schedule_evaluation(
        patient_id=patient["id"],
        evaluator_therapist_id=bcba["id"],
        scheduled_at=scheduled_at,
    )
    # Advance clock so clinic.now_ts >= scheduled_at (PRD §3.2).
    advance_clock(clinic["id"], scheduled_offset_seconds)
    start_evaluation(evaluation["id"], bcba_id=bcba["id"])
    return complete_evaluation(
        evaluation["id"], bcba_id=bcba["id"],
        recommended_weekly_hours=recommended_weekly_hours,
    )


# ===========================================================================
# Tier 2: treatment plan.
# ===========================================================================
def draft_treatment_plan(
    *,
    patient_id: str,
    source_evaluation_id: str,
    weekly_direct_hours_target: int,
    weekly_supervision_hours_target: float,
    weekly_parent_training_hours_target: float = 1.0,
    bcba_id: str,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/treatment-plans — BCBA."""
    headers = make_bcba_headers(bcba_id)
    resp = api_client.create_treatment_plan(
        patient_id,
        create_treatment_plan_payload(
            source_evaluation_id=source_evaluation_id,
            weekly_direct_hours_target=weekly_direct_hours_target,
            weekly_supervision_hours_target=(
                weekly_supervision_hours_target
            ),
            weekly_parent_training_hours_target=(
                weekly_parent_training_hours_target
            ),
        ),
        headers,
    )
    return get_success_data(resp)


def activate_treatment_plan(
    plan_id: str,
    *,
    bcba_id: str,
) -> Dict[str, Any]:
    """POST /treatment-plans/{id}/activate — BCBA."""
    headers = make_bcba_headers(bcba_id)
    resp = api_client.activate_treatment_plan(plan_id, headers)
    return get_success_data(resp)


def supersede_treatment_plan(
    new_plan_id: str,
    *,
    previous_plan_id: str,
    bcba_id: str,
) -> Dict[str, Any]:
    """POST /treatment-plans/{new_id}/supersede — BCBA."""
    headers = make_bcba_headers(bcba_id)
    resp = api_client.supersede_treatment_plan(
        new_plan_id,
        supersede_treatment_plan_payload(
            previous_plan_id=previous_plan_id,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_active_treatment_plan(
    *,
    clinic: Dict[str, Any],
    patient: Dict[str, Any],
    bcba: Dict[str, Any],
    weekly_direct_hours_target: int = 20,
    weekly_supervision_hours_target: float = 2.0,
    weekly_parent_training_hours_target: float = 1.0,
) -> Dict[str, Any]:
    """Completed eval -> draft plan -> activate plan. Returns ACTIVE plan."""
    evaluation = setup_completed_evaluation(
        clinic=clinic, patient=patient, bcba=bcba,
        recommended_weekly_hours=weekly_direct_hours_target,
    )
    plan = draft_treatment_plan(
        patient_id=patient["id"],
        source_evaluation_id=evaluation["id"],
        weekly_direct_hours_target=weekly_direct_hours_target,
        weekly_supervision_hours_target=weekly_supervision_hours_target,
        weekly_parent_training_hours_target=(
            weekly_parent_training_hours_target
        ),
        bcba_id=bcba["id"],
    )
    return activate_treatment_plan(plan["id"], bcba_id=bcba["id"])


# ===========================================================================
# Tier 3: authorization lifecycle.
# ===========================================================================
def request_authorization(
    *,
    patient_id: str,
    treatment_plan_id: str,
    cpt_code: str = "97153",
    approved_units: int = 240,
    payer_name: Optional[str] = None,
    effective_start: str,
    effective_end: str,
    renewed_from_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/authorizations — ClinicAdmin."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.create_authorization(
        patient_id,
        create_authorization_payload(
            treatment_plan_id=treatment_plan_id,
            cpt_code=cpt_code,
            approved_units=approved_units,
            payer_name=payer_name,
            effective_start=effective_start,
            effective_end=effective_end,
            renewed_from_id=renewed_from_id,
        ),
        headers,
    )
    return get_success_data(resp)


def approve_authorization(
    authorization_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorizations/{id}/approve — PayerAdmin."""
    headers = headers or TEST_USERS["payer_admin_headers"]
    resp = api_client.approve_authorization(authorization_id, headers)
    return get_success_data(resp)


def deny_authorization(
    authorization_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /authorizations/{id}/deny — PayerAdmin."""
    headers = headers or TEST_USERS["payer_admin_headers"]
    resp = api_client.deny_authorization(authorization_id, headers)
    return get_success_data(resp)


def get_authorization(
    authorization_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.get_authorization(authorization_id, headers)
    return get_success_data(resp)


def get_supervision_ratio(
    authorization_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.get_supervision_ratio(authorization_id, headers)
    return get_success_data(resp)


def get_clinic(clinic_id: str, headers: Optional[Dict[str, str]] = None
               ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.get_clinic(clinic_id, headers)
    return get_success_data(resp)


def get_patient(patient_id: str, headers: Optional[Dict[str, str]] = None
                ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.get_patient(patient_id, headers)
    return get_success_data(resp)


def setup_active_authorization(
    *,
    clinic: Dict[str, Any],
    patient: Dict[str, Any],
    plan: Dict[str, Any],
    cpt_code: str = "97153",
    approved_units: int = 240,
    payer_name: Optional[str] = None,
    effective_start_offset_seconds: int = 24 * SECONDS_PER_HOUR,
    window_days: int = 180,
) -> Tuple[Dict[str, Any], str]:
    """Create authorization in PENDING -> approve -> advance clock past
    effective_start so it auto-transitions APPROVED->ACTIVE. Returns
    (authorization, clinic_now_ts_after_advance).

    Internally uses effective_start_offset_seconds from the current
    clinic.now_ts so the test controls how far in the future the window
    starts.
    """
    # Read current now_ts so we can synthesise a future window.
    clinic_state = get_clinic(clinic["id"])
    base_now_ts = clinic_state["now_ts"]
    effective_start = add_seconds(
        base_now_ts, seconds=effective_start_offset_seconds,
    )
    effective_end = add_days(effective_start, days=window_days)
    auth = request_authorization(
        patient_id=patient["id"],
        treatment_plan_id=plan["id"],
        cpt_code=cpt_code,
        approved_units=approved_units,
        payer_name=payer_name,
        effective_start=effective_start,
        effective_end=effective_end,
    )
    approve_authorization(auth["id"])
    # Advance clock past effective_start so the system auto-transitions
    # APPROVED -> ACTIVE (PRD §3.4 / §3.8).
    advance_clock(
        clinic["id"], effective_start_offset_seconds + 1,
    )
    # Re-read so caller observes the latest now_ts and the ACTIVE auth.
    return get_authorization(auth["id"]), get_clinic(clinic["id"])["now_ts"]


# ===========================================================================
# Tier 4: session lifecycle.
# ===========================================================================
def schedule_session(
    *,
    patient_id: str,
    authorization_id: str,
    therapist_id: str,
    session_type: str,
    planned_start: str,
    planned_end: str,
    supervising_therapist_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/sessions — ClinicAdmin or BCBA."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.create_session(
        patient_id,
        create_session_payload(
            authorization_id=authorization_id,
            therapist_id=therapist_id,
            session_type=session_type,
            planned_start=planned_start,
            planned_end=planned_end,
            supervising_therapist_id=supervising_therapist_id,
        ),
        headers,
    )
    return get_success_data(resp)


def start_session(
    session_id: str,
    *,
    therapist_id: str,
    therapist_role: str = "BCBA",
) -> Dict[str, Any]:
    """POST /sessions/{id}/start — BCBA or RBT acting as themselves."""
    if therapist_role == "RBT":
        headers = make_rbt_headers(therapist_id)
    else:
        headers = make_bcba_headers(therapist_id)
    resp = api_client.start_session(session_id, headers)
    return get_success_data(resp)


def complete_session(
    session_id: str,
    *,
    therapist_id: str,
    therapist_role: str = "BCBA",
    progress_rating: int = 4,
) -> Dict[str, Any]:
    """POST /sessions/{id}/complete — BCBA or RBT acting as themselves."""
    if therapist_role == "RBT":
        headers = make_rbt_headers(therapist_id)
    else:
        headers = make_bcba_headers(therapist_id)
    resp = api_client.complete_session(
        session_id,
        complete_session_payload(progress_rating=progress_rating),
        headers,
    )
    return get_success_data(resp)


def dispute_session(
    session_id: str,
    *,
    bcba_id: str,
    dispute_reason: str = "review_pending",
) -> Dict[str, Any]:
    """POST /sessions/{id}/dispute — BCBA. Note: dispute is NOT
    ownership-gated by therapist_id in PRD §3.5; BCBA role suffices.
    For robustness, fixtures still mint per-instance BCBA headers using
    the supervising/recording BCBA's id."""
    headers = make_bcba_headers(bcba_id)
    resp = api_client.dispute_session(
        session_id,
        dispute_session_payload(dispute_reason=dispute_reason),
        headers,
    )
    return get_success_data(resp)


def resolve_session_dispute(
    session_id: str,
    *,
    bcba_id: str,
) -> Dict[str, Any]:
    """POST /sessions/{id}/resolve-dispute — BCBA."""
    headers = make_bcba_headers(bcba_id)
    resp = api_client.resolve_session_dispute(session_id, headers)
    return get_success_data(resp)


def cancel_session(
    session_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /sessions/{id}/cancel — ClinicAdmin or BCBA."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.cancel_session(session_id, headers)
    return get_success_data(resp)


def setup_completed_session(
    *,
    clinic: Dict[str, Any],
    patient: Dict[str, Any],
    authorization: Dict[str, Any],
    therapist: Dict[str, Any],
    therapist_role: str = "RBT",
    session_type: str = "DIRECT_RBT",
    duration_minutes: int = 60,
    progress_rating: int = 4,
    supervising_therapist_id: Optional[str] = None,
    base_now_ts: Optional[str] = None,
    planned_start_offset_seconds: int = 60,
    planned_duration_minutes: Optional[int] = None,
) -> Tuple[Dict[str, Any], str]:
    """Create a session, advance to planned_start, start it, advance
    again to past actual_start, complete it.

    PRD §3.5 requires the PLANNED interval length to be in the inclusive
    range [15, 480] minutes. PRD §2.10 / §3.5 compute supervision-ratio
    minutes and billed_units from the ACTUAL elapsed minutes (actual_end
    minus actual_start). These two quantities are independent — the
    fixture lets tests drive a small ACTUAL elapsed (for supervision-ratio
    arithmetic) while keeping the PLANNED interval PRD-valid.

    `duration_minutes` controls the ACTUAL elapsed minutes between
    start and complete (the clock advance after start_session). When
    `planned_duration_minutes` is None, the planned interval defaults to
    max(duration_minutes, 15) so PRD's [15, 480] minimum is respected
    even when the test wants an actual elapsed of less than 15 minutes.

    Returns (completed_session, final_now_ts).
    """
    if base_now_ts is None:
        base_now_ts = get_clinic(clinic["id"])["now_ts"]
    # PRD §3.5: planned interval must be in [15, 480] minutes. When the
    # caller hasn't specified a planned duration explicitly, derive it
    # from the requested actual duration but clamp to the PRD minimum.
    if planned_duration_minutes is None:
        planned_duration_minutes = max(duration_minutes, 15)
    planned_start = add_seconds(
        base_now_ts, seconds=planned_start_offset_seconds,
    )
    planned_end = add_minutes(
        planned_start, minutes=planned_duration_minutes,
    )
    session = schedule_session(
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        therapist_id=therapist["id"],
        session_type=session_type,
        planned_start=planned_start,
        planned_end=planned_end,
        supervising_therapist_id=supervising_therapist_id,
    )
    # Advance clock to planned_start, start session.
    advance_clock(
        clinic["id"], planned_start_offset_seconds,
    )
    start_session(
        session["id"], therapist_id=therapist["id"],
        therapist_role=therapist_role,
    )
    # Advance clock by duration_minutes so actual_end > actual_start.
    advance_clock(
        clinic["id"], duration_minutes * SECONDS_PER_MINUTE,
    )
    completed = complete_session(
        session["id"],
        therapist_id=therapist["id"],
        therapist_role=therapist_role,
        progress_rating=progress_rating,
    )
    final_now_ts = get_clinic(clinic["id"])["now_ts"]
    return completed, final_now_ts


# ===========================================================================
# Tier 5: claim lifecycle.
# ===========================================================================
def draft_claim(
    *,
    patient_id: str,
    authorization_id: str,
    session_ids: List[str],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/claims — ClinicAdmin."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.create_claim(
        patient_id,
        create_claim_payload(
            authorization_id=authorization_id,
            session_ids=session_ids,
        ),
        headers,
    )
    return get_success_data(resp)


def submit_claim(claim_id: str,
                 headers: Optional[Dict[str, str]] = None
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.submit_claim(claim_id, headers)
    return get_success_data(resp)


def adjudicate_claim(
    claim_id: str,
    *,
    denial_reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["payer_admin_headers"]
    resp = api_client.adjudicate_claim(
        claim_id,
        adjudicate_claim_payload(denial_reason=denial_reason),
        headers,
    )
    return get_success_data(resp)


def pay_claim(claim_id: str,
              headers: Optional[Dict[str, str]] = None
              ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["payer_admin_headers"]
    resp = api_client.pay_claim(claim_id, headers)
    return get_success_data(resp)


def deny_claim(claim_id: str,
               headers: Optional[Dict[str, str]] = None
               ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["payer_admin_headers"]
    resp = api_client.deny_claim(claim_id, headers)
    return get_success_data(resp)


def appeal_claim(claim_id: str,
                 headers: Optional[Dict[str, str]] = None
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.appeal_claim(claim_id, headers)
    return get_success_data(resp)


def get_claim(claim_id: str,
              headers: Optional[Dict[str, str]] = None
              ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.get_claim(claim_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Top-level composite fixtures (difficulty-design-aligned).
# ===========================================================================
def setup_basic_environment(
    *,
    num_bcbas: int = 1,
    num_rbts: int = 1,
    weekly_direct_hours_target: int = 20,
    weekly_supervision_hours_target: float = 2.0,
    weekly_parent_training_hours_target: float = 1.0,
    cpt_code: str = "97153",
    approved_units: int = 240,
    payer_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Clinic + roster + patient + ACTIVE plan + ACTIVE authorization.

    Returns dict with keys: clinic, bcbas, rbts, patient, plan,
    authorization, now_ts (the clinic's current now_ts after setup is
    complete).
    """
    roster = setup_clinic_with_roster(
        num_bcbas=num_bcbas, num_rbts=num_rbts,
    )
    clinic = roster["clinic"]
    bcba = roster["bcbas"][0]
    patient = roster["patient"]
    plan = setup_active_treatment_plan(
        clinic=clinic, patient=patient, bcba=bcba,
        weekly_direct_hours_target=weekly_direct_hours_target,
        weekly_supervision_hours_target=weekly_supervision_hours_target,
        weekly_parent_training_hours_target=(
            weekly_parent_training_hours_target
        ),
    )
    authorization, now_ts = setup_active_authorization(
        clinic=clinic, patient=patient, plan=plan,
        cpt_code=cpt_code, approved_units=approved_units,
        payer_name=payer_name,
    )
    return {
        **roster,
        "plan": plan,
        "authorization": authorization,
        "now_ts": now_ts,
    }


def setup_environment_with_two_authorizations(
    *,
    cpt_codes: Tuple[str, str] = ("97153", "97155"),
    approved_units: Tuple[int, int] = (240, 240),
    weekly_supervision_hours_target: float = 2.0,
) -> Dict[str, Any]:
    """Like setup_basic_environment but creates TWO authorizations under
    one plan (one per CPT code). Returns the same keys plus
    `authorizations` (list)."""
    env = setup_basic_environment(
        cpt_code=cpt_codes[0],
        approved_units=approved_units[0],
        weekly_supervision_hours_target=weekly_supervision_hours_target,
    )
    # Second authorization is created against the same plan with a fresh
    # effective window, then approved + clock-advanced to ACTIVE.
    clinic_state = get_clinic(env["clinic"]["id"])
    base_now_ts = clinic_state["now_ts"]
    second_start = add_seconds(base_now_ts, seconds=60)
    second_end = add_days(second_start, days=180)
    second_auth = request_authorization(
        patient_id=env["patient"]["id"],
        treatment_plan_id=env["plan"]["id"],
        cpt_code=cpt_codes[1],
        approved_units=approved_units[1],
        effective_start=second_start,
        effective_end=second_end,
    )
    approve_authorization(second_auth["id"])
    advance_clock(env["clinic"]["id"], 60 + 1)
    second_auth = get_authorization(second_auth["id"])
    env["authorizations"] = [env["authorization"], second_auth]
    env["now_ts"] = get_clinic(env["clinic"]["id"])["now_ts"]
    return env


# ---------------------------------------------------------------------------
# Difficulty-aligned composite fixtures.
# ---------------------------------------------------------------------------
def setup_completed_sessions_for_supervision_ratio(
    *,
    rbt_minutes_total: int = 100,
    bcba_minutes_total: int = 10,
    num_rbt_sessions: int = 5,
    weekly_supervision_hours_target: float = 2.0,
) -> Dict[str, Any]:
    """Build environment + N DIRECT_RBT sessions totalling rbt_minutes_total
    minutes (split evenly) + one BCBA_SUPERVISION session of
    bcba_minutes_total minutes. All sessions completed within the
    trailing 30 days. Returns dict with the standard env keys plus
    `rbt_sessions`, `bcba_session`, and `now_ts`.

    Used by difficulty rule 2 (combinatorial_formula) mode (a) and rule
    6 (boundary_precision_check) supervision_ratio_at_exact_0_10.
    """
    env = setup_environment_with_two_authorizations(
        cpt_codes=("97153", "97155"),
        weekly_supervision_hours_target=weekly_supervision_hours_target,
    )
    clinic = env["clinic"]
    patient = env["patient"]
    rbt = env["rbts"][0]
    bcba = env["bcbas"][0]
    rbt_auth = env["authorizations"][0]
    bcba_auth = env["authorizations"][1]

    per_session_rbt = rbt_minutes_total // num_rbt_sessions
    rbt_sessions: List[Dict[str, Any]] = []
    # Create RBT sessions back-to-back from current now_ts + small offset.
    for i in range(num_rbt_sessions):
        # Each iteration: schedule (offset), advance, start, advance,
        # complete. After each completion, now_ts moves forward by
        # planned_start_offset + per_session_rbt minutes.
        completed, _ = setup_completed_session(
            clinic=clinic, patient=patient,
            authorization=rbt_auth, therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=per_session_rbt,
            progress_rating=4,
            planned_start_offset_seconds=60,
        )
        rbt_sessions.append(completed)

    # Final BCBA_SUPERVISION session — supervising_therapist_id is the RBT
    # who has completed RBT sessions with this patient in the last 30 days.
    bcba_session, _ = setup_completed_session(
        clinic=clinic, patient=patient,
        authorization=bcba_auth, therapist=bcba,
        therapist_role="BCBA", session_type="BCBA_SUPERVISION",
        duration_minutes=bcba_minutes_total,
        progress_rating=2,
        supervising_therapist_id=rbt["id"],
        planned_start_offset_seconds=60,
    )

    env["rbt_sessions"] = rbt_sessions
    env["bcba_session"] = bcba_session
    env["rbt_auth"] = rbt_auth
    env["bcba_auth"] = bcba_auth
    env["rbt"] = rbt
    env["bcba"] = bcba
    env["now_ts"] = get_clinic(clinic["id"])["now_ts"]
    return env


def setup_adjudicated_claim_for_rbt_session(
    *,
    rbt_minutes_total: int = 100,
    bcba_minutes_total: int = 10,
    num_rbt_sessions: int = 5,
) -> Dict[str, Any]:
    """Standard env with completed RBT+BCBA sessions, then DRAFT claim
    referencing one of the RBT sessions, SUBMIT -> ADJUDICATE (no
    denial_reason). Returns env dict plus `claim` and `claimed_session`.
    """
    env = setup_completed_sessions_for_supervision_ratio(
        rbt_minutes_total=rbt_minutes_total,
        bcba_minutes_total=bcba_minutes_total,
        num_rbt_sessions=num_rbt_sessions,
    )
    claimed_session = env["rbt_sessions"][0]
    claim = draft_claim(
        patient_id=env["patient"]["id"],
        authorization_id=env["rbt_auth"]["id"],
        session_ids=[claimed_session["id"]],
    )
    claim = submit_claim(claim["id"])
    claim = adjudicate_claim(claim["id"])
    env["claim"] = claim
    env["claimed_session"] = claimed_session
    return env


def setup_completed_session_with_billed_units(
    *,
    billed_units: int = 4,
) -> Dict[str, Any]:
    """Build environment + one DIRECT_RBT session completed with exactly
    `billed_units` units of billed time (15 minutes per unit). Returns
    env dict + `session`.

    Used by rule 3 (therapy_session_dispute_cycle), rule 4
    (session_dispute_depth_2_cascade), rule 9
    (session_complete_dispute_zero_net_provisional_units).
    """
    env = setup_basic_environment()
    duration_minutes = billed_units * 15
    session, _ = setup_completed_session(
        clinic=env["clinic"], patient=env["patient"],
        authorization=env["authorization"], therapist=env["rbts"][0],
        therapist_role="RBT", session_type="DIRECT_RBT",
        duration_minutes=duration_minutes,
        progress_rating=4,
    )
    env["session"] = session
    env["rbt"] = env["rbts"][0]
    env["bcba"] = env["bcbas"][0]
    return env


def setup_two_completed_sessions_one_claim_draft(
    *,
    billed_units_per_session: Tuple[int, int] = (4, 4),
) -> Dict[str, Any]:
    """Build environment + two DIRECT_RBT sessions completed with
    specified billed_units each + one DRAFT claim referencing both
    sessions. Returns env dict + `sessions` and `claim`.

    Used by rule 9 (claim_submit_deny_zero_net_billed_session_count) and
    submission tests.
    """
    env = setup_basic_environment()
    sessions: List[Dict[str, Any]] = []
    for billed_units in billed_units_per_session:
        s, _ = setup_completed_session(
            clinic=env["clinic"], patient=env["patient"],
            authorization=env["authorization"], therapist=env["rbts"][0],
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=billed_units * 15,
            progress_rating=4,
        )
        sessions.append(s)
    claim = draft_claim(
        patient_id=env["patient"]["id"],
        authorization_id=env["authorization"]["id"],
        session_ids=[s["id"] for s in sessions],
    )
    env["sessions"] = sessions
    env["claim"] = claim
    env["rbt"] = env["rbts"][0]
    env["bcba"] = env["bcbas"][0]
    return env


def setup_pending_authorization_unapproved(
    *,
    cpt_code: str = "97153",
    approved_units: int = 240,
) -> Dict[str, Any]:
    """Build environment up to plan ACTIVE + AUTHORIZATION CREATED IN
    PENDING (not approved, clock not advanced).

    The Authorization remains PENDING; its effective_start sits in the
    near future. Used by rule 7 (session_start_requires_authorization_active):
    a TherapySession is scheduled under this Authorization, the clock is
    advanced only enough to reach planned_start (NOT effective_start),
    so the start attempt sees an Authorization still in APPROVED/PENDING.
    """
    roster = setup_clinic_with_roster()
    clinic = roster["clinic"]
    bcba = roster["bcbas"][0]
    rbt = roster["rbts"][0]
    patient = roster["patient"]
    plan = setup_active_treatment_plan(
        clinic=clinic, patient=patient, bcba=bcba,
    )
    clinic_state = get_clinic(clinic["id"])
    base_now_ts = clinic_state["now_ts"]
    effective_start = add_days(base_now_ts, days=10)
    effective_end = add_days(effective_start, days=180)
    auth = request_authorization(
        patient_id=patient["id"], treatment_plan_id=plan["id"],
        cpt_code=cpt_code, approved_units=approved_units,
        effective_start=effective_start, effective_end=effective_end,
    )
    # Approve the authorization (PENDING -> APPROVED) but DO NOT advance
    # the clock past effective_start, so the auth stays APPROVED.
    auth = approve_authorization(auth["id"])
    return {
        "clinic": clinic, "bcbas": roster["bcbas"], "rbts": roster["rbts"],
        "patient": patient, "plan": plan, "authorization": auth,
        "rbt": rbt, "bcba": bcba,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "now_ts": base_now_ts,
    }


def setup_drafted_plan_with_in_progress_evaluation(
) -> Dict[str, Any]:
    """Build clinic + roster + patient + IN_PROGRESS evaluation (not
    completed) + DRAFT plan whose source_evaluation_id points at that
    evaluation.

    Used by rule 7 (plan_activate_requires_evaluation_completed).
    """
    roster = setup_clinic_with_roster()
    clinic = roster["clinic"]
    bcba = roster["bcbas"][0]
    patient = roster["patient"]
    # Schedule evaluation, advance to scheduled_at, start it (becomes
    # IN_PROGRESS), but do NOT complete.
    scheduled_at = add_seconds(clinic["now_ts"], seconds=3600)
    evaluation = schedule_evaluation(
        patient_id=patient["id"],
        evaluator_therapist_id=bcba["id"],
        scheduled_at=scheduled_at,
    )
    advance_clock(clinic["id"], 3600)
    evaluation = start_evaluation(evaluation["id"], bcba_id=bcba["id"])
    # PRD §3.3 plan can be drafted only after eval is COMPLETED; while
    # IN_PROGRESS, the draft itself is rejected. So this fixture only
    # returns the IN_PROGRESS evaluation; the test will attempt the
    # draft+activate flow against it.
    return {
        "clinic": clinic, "bcbas": roster["bcbas"], "rbts": roster["rbts"],
        "patient": patient, "evaluation": evaluation, "bcba": bcba,
    }


def setup_two_claims_for_concurrency() -> Dict[str, Any]:
    """Build environment + two completed sessions (each on its own
    therapist, each fully completed) + two DRAFT claims, each
    referencing one of those sessions. Returns env + `claim_a`,
    `claim_b`, `sessions`."""
    env = setup_basic_environment(num_rbts=2)
    rbt_a = env["rbts"][0]
    rbt_b = env["rbts"][1]

    s_a, _ = setup_completed_session(
        clinic=env["clinic"], patient=env["patient"],
        authorization=env["authorization"], therapist=rbt_a,
        therapist_role="RBT", session_type="DIRECT_RBT",
        duration_minutes=60, progress_rating=4,
    )
    s_b, _ = setup_completed_session(
        clinic=env["clinic"], patient=env["patient"],
        authorization=env["authorization"], therapist=rbt_b,
        therapist_role="RBT", session_type="DIRECT_RBT",
        duration_minutes=60, progress_rating=4,
    )
    claim_a = draft_claim(
        patient_id=env["patient"]["id"],
        authorization_id=env["authorization"]["id"],
        session_ids=[s_a["id"]],
    )
    claim_b = draft_claim(
        patient_id=env["patient"]["id"],
        authorization_id=env["authorization"]["id"],
        session_ids=[s_b["id"]],
    )
    env["claim_a"] = claim_a
    env["claim_b"] = claim_b
    env["sessions"] = [s_a, s_b]
    return env


def setup_ledger_for_authorization(
    authorization_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Read all ledger entries for an authorization (paginated)."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    rows: List[Dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        resp = api_client.list_authorization_ledger(
            authorization_id, headers,
            params={"limit": limit, "offset": offset},
        )
        body = resp.json() if hasattr(resp, "json") else {}
        data = body.get("data", [])
        rows.extend(data)
        meta = body.get("meta", {})
        if not meta.get("has_more"):
            break
        offset += limit
    return rows


# ---------------------------------------------------------------------------
# Helper: compute expected reimbursement and submitted amounts.
# These mirror the PRD §3.6 calculation so tests can pin the expected
# integer-cents output without re-doing the math inline.
# ---------------------------------------------------------------------------
def expected_per_line_submitted_cents(
    billed_units: int,
    session_type: str,
    patient_responsibility_pct: float = PATIENT_RESPONSIBILITY_DEFAULT,
) -> int:
    """PRD §3.6 per-line submitted amount: raw_line_dollars =
    (billed_units * rate_cents / 100) * (1 - patient_resp_pct), then
    round_half_up((raw * 100)) to whole cents."""
    rate = TIERED_RATES_CENTS[session_type]
    raw_line_dollars = (billed_units * rate / 100) * (
        1 - patient_responsibility_pct
    )
    return round_half_up(raw_line_dollars * 100)


def expected_submitted_amount_cents(
    sessions: List[Dict[str, Any]],
    patient_responsibility_pct: float = PATIENT_RESPONSIBILITY_DEFAULT,
) -> int:
    """Sum per-line rounded amounts. PRD §3.6: "round each line to
    whole cents first, then sum."""
    return sum(
        expected_per_line_submitted_cents(
            billed_units=s["billed_units"],
            session_type=s["session_type"],
            patient_responsibility_pct=patient_responsibility_pct,
        )
        for s in sessions
    )


__all__ = [
    # clock
    "advance_clock",
    "advance_clock_to",
    # bootstrap
    "create_clinic",
    "create_therapist",
    "create_patient",
    "setup_clinic_with_roster",
    # evaluation
    "schedule_evaluation",
    "start_evaluation",
    "complete_evaluation",
    "setup_completed_evaluation",
    # plan
    "draft_treatment_plan",
    "activate_treatment_plan",
    "supersede_treatment_plan",
    "setup_active_treatment_plan",
    # authorization
    "request_authorization",
    "approve_authorization",
    "deny_authorization",
    "get_authorization",
    "get_supervision_ratio",
    "get_clinic",
    "get_patient",
    "setup_active_authorization",
    # session
    "schedule_session",
    "start_session",
    "complete_session",
    "dispute_session",
    "resolve_session_dispute",
    "cancel_session",
    "setup_completed_session",
    # claim
    "draft_claim",
    "submit_claim",
    "adjudicate_claim",
    "pay_claim",
    "deny_claim",
    "appeal_claim",
    "get_claim",
    # composite
    "setup_basic_environment",
    "setup_environment_with_two_authorizations",
    "setup_completed_sessions_for_supervision_ratio",
    "setup_adjudicated_claim_for_rbt_session",
    "setup_completed_session_with_billed_units",
    "setup_two_completed_sessions_one_claim_draft",
    "setup_pending_authorization_unapproved",
    "setup_drafted_plan_with_in_progress_evaluation",
    "setup_two_claims_for_concurrency",
    "setup_ledger_for_authorization",
    # calculation helpers
    "expected_per_line_submitted_cents",
    "expected_submitted_amount_cents",
]
