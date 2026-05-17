"""Composite setup helpers — multi-step preambles that tests reuse.

The clinical workflow is long: register Therapist + Patient -> open
Episode -> create + finalize Evaluation -> create + certify Plan of
Care (with Authorization that covers the cert window) -> schedule
Visit -> start Visit -> sign Visit -> submit Claim, with optional HEP,
MIPS, and Discharge flows on top.

IDENTITY THREADING — PRD §2.1.

- Therapist is ENTITY-BACKED. Every Therapist-driven call whose
  success depends on the acting therapist's id matching the targeted
  resource MUST mint headers via make_therapist_headers(therapist["id"])
  — never via the shared THERAPIST_FALLBACK_ID constant. Concretely:
  finalize/amend Evaluation (clinician_id check + can_evaluate check),
  sign Visit (clinician_id check), sign Discharge (segregation-of-
  duties check), issue HEP (prescribing_clinician_id check).

- Patient is ENTITY-BACKED. PRD §2.1: "the patient can read only their
  own Patient record and acknowledge HEPs whose anchoring episode
  belongs to that patient." Every Patient call MUST mint headers via
  make_patient_headers(patient["id"]).

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CAP_HARD_CENTS,
    KX_THRESHOLD_CENTS,
    REEVAL_DUE_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    amend_evaluation_payload,
    clock_advance_payload,
    create_authorization_payload,
    create_discharge_assessment_payload,
    create_episode_payload,
    create_evaluation_payload,
    create_home_exercise_program_payload,
    create_mips_measure_payload,
    create_patient_payload,
    create_plan_of_care_payload,
    create_therapist_payload,
    create_veteran_referral_payload,
    create_visit_payload,
    iso_anchor_offset,
    iso_date_anchor_offset,
    parse_anchor,
    parse_iso,
    sign_visit_payload,
)
from .test_users import (
    TEST_USERS,
    make_patient_headers,
    make_therapist_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.10.
# ===========================================================================
def anchor_clock() -> Dict[str, Any]:
    """Pin the server clock to the deterministic test anchor.

    PRD §3.10: "the platform exposes a test-only capability for an
    admin operator to advance the logical clock to a supplied to
    instant."
    """
    resp = api_client.clock_advance(
        clock_advance_payload(to=TEST_DEFAULTS["CLOCK_ANCHOR"]),
        TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


def advance_clock_to(iso_timestamp: str) -> Dict[str, Any]:
    """POST /_clock/advance with an absolute target."""
    resp = api_client.clock_advance(
        clock_advance_payload(to=iso_timestamp),
        TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


def advance_clock_days(days: int) -> Dict[str, Any]:
    """Advance the clock by the supplied integer days from the anchor."""
    target = iso_anchor_offset(days=days)
    return advance_clock_to(target)


# ===========================================================================
# Therapists — PRD §3.1.
# ===========================================================================
def create_therapist(*,
                     full_name: str = "Dr. Test Therapist",
                     credential: str = "DPT",
                     npi: Optional[str] = None,
                     ) -> Dict[str, Any]:
    """POST /therapists as ClinicAdmin."""
    payload = create_therapist_payload(
        full_name=full_name, credential=credential, npi=npi,
    )
    resp = api_client.create_therapist(
        payload, TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


def create_pt_therapist(**overrides: Any) -> Dict[str, Any]:
    """Convenience: PT-credential therapist (can_evaluate=true)."""
    overrides.setdefault("credential", "PT")
    return create_therapist(**overrides)


def create_dpt_therapist(**overrides: Any) -> Dict[str, Any]:
    """Convenience: DPT-credential therapist (can_evaluate=true)."""
    overrides.setdefault("credential", "DPT")
    return create_therapist(**overrides)


def create_pta_therapist(**overrides: Any) -> Dict[str, Any]:
    """Convenience: PTA-credential therapist (can_evaluate=false)."""
    overrides.setdefault("credential", "PTA")
    return create_therapist(**overrides)


# ===========================================================================
# Patients — PRD §3.1.
# ===========================================================================
def create_patient(*,
                   insurance_type: str = "COMMERCIAL",
                   full_name: str = "Test Patient",
                   date_of_birth: str = "1985-06-15",
                   medicare_beneficiary_id: Optional[str] = None,
                   va_referral_id: Optional[str] = None,
                   ) -> Dict[str, Any]:
    """POST /patients as ClinicAdmin."""
    payload = create_patient_payload(
        full_name=full_name,
        date_of_birth=date_of_birth,
        insurance_type=insurance_type,
        medicare_beneficiary_id=medicare_beneficiary_id,
        va_referral_id=va_referral_id,
    )
    resp = api_client.create_patient(
        payload, TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


def re_get_patient(patient_id: str,
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    """GET /patients/{id} after a mutation."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.get_patient(patient_id, headers)
    return get_success_data(resp)


def get_cap_status(patient_id: str) -> Dict[str, Any]:
    """GET /patients/{id}/cap-status as ClinicAdmin."""
    resp = api_client.get_patient_cap_status(
        patient_id, TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Veteran Referrals — PRD §3.1.
# ===========================================================================
def create_veteran_referral(*,
                            patient_id: str,
                            authorized_units: int = 60,
                            valid_from: Optional[str] = None,
                            valid_through: Optional[str] = None,
                            ) -> Dict[str, Any]:
    """POST /veteran-referrals as ClinicAdmin."""
    payload = create_veteran_referral_payload(
        patient_id=patient_id,
        authorized_units=authorized_units,
        valid_from=valid_from,
        valid_through=valid_through,
    )
    resp = api_client.create_veteran_referral(
        payload, TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Episodes — PRD §3.2.
# ===========================================================================
def create_episode(*,
                   patient_id: str,
                   acting_therapist_id: str,
                   body_region: str = "LUMBAR",
                   referring_provider_npi: Optional[str] = None,
                   ) -> Dict[str, Any]:
    """POST /episodes as the acting Therapist.

    PRD §2.1: Therapist is entity-backed; X-User-ID must equal a real
    Therapist.id.
    """
    payload = create_episode_payload(
        patient_id=patient_id,
        body_region=body_region,
        referring_provider_npi=referring_provider_npi,
    )
    resp = api_client.create_episode(
        payload, make_therapist_headers(acting_therapist_id),
    )
    return get_success_data(resp)


def re_get_episode(episode_id: str,
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    """GET /episodes/{id} after a mutation."""
    headers = headers or TEST_USERS["clinic_admin_headers"]
    resp = api_client.get_episode(episode_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Evaluations — PRD §3.2.
# ===========================================================================
def create_evaluation(*,
                      episode_id: str,
                      evaluation_type: str = "INITIAL",
                      clinician_id: str,
                      complexity: str = "MODERATE",
                      functional_baseline_score: int = 50,
                      acting_therapist_id: Optional[str] = None,
                      ) -> Dict[str, Any]:
    """POST /episodes/{id}/evaluations as the acting Therapist.

    The Therapist call is ownership-gated by the platform on
    clinician_id at finalize/amend time, so we default the acting
    therapist to the evaluation's clinician_id.
    """
    acting = (acting_therapist_id
              if acting_therapist_id is not None else clinician_id)
    payload = create_evaluation_payload(
        evaluation_type=evaluation_type,
        clinician_id=clinician_id,
        complexity=complexity,
        functional_baseline_score=functional_baseline_score,
    )
    resp = api_client.create_evaluation(
        episode_id, payload, make_therapist_headers(acting),
    )
    return get_success_data(resp)


def finalize_evaluation(*,
                        evaluation_id: str,
                        acting_therapist_id: str,
                        version: Optional[int] = None,
                        ) -> Dict[str, Any]:
    """POST /evaluations/{id}/finalize as the acting Therapist.

    PRD §3.2: "Finalizing a draft evaluation ... requires that the
    acting therapist's can_evaluate flag is true." The acting therapist
    id MUST equal the Evaluation.clinician_id (PRD §2.1 ownership).
    """
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    resp = api_client.finalize_evaluation(
        evaluation_id,
        make_therapist_headers(acting_therapist_id),
        payload if payload else None,
    )
    return get_success_data(resp)


def amend_evaluation(*,
                     evaluation_id: str,
                     acting_therapist_id: str,
                     functional_baseline_score: Optional[int] = None,
                     complexity: Optional[str] = None,
                     version: Optional[int] = None,
                     ) -> Dict[str, Any]:
    """POST /evaluations/{id}/amend as the acting Therapist."""
    payload = amend_evaluation_payload(
        functional_baseline_score=functional_baseline_score,
        complexity=complexity,
        version=version,
    )
    resp = api_client.amend_evaluation(
        evaluation_id, payload,
        make_therapist_headers(acting_therapist_id),
    )
    return get_success_data(resp)


# ===========================================================================
# Plan of Care — PRD §3.3.
# ===========================================================================
def create_plan_of_care(*,
                        episode_id: str,
                        evaluation_id: str,
                        acting_therapist_id: str,
                        planned_visit_count: int = TEST_DEFAULTS[
                            "DEFAULT_PLANNED_VISIT_COUNT"],
                        planned_units_per_visit: int = TEST_DEFAULTS[
                            "DEFAULT_PLANNED_UNITS_PER_VISIT"],
                        cert_period_start: Optional[str] = None,
                        cert_period_end: Optional[str] = None,
                        certifying_physician_npi: Optional[str] = None,
                        ) -> Dict[str, Any]:
    """POST /episodes/{id}/plan-of-cares as the acting Therapist."""
    payload = create_plan_of_care_payload(
        evaluation_id=evaluation_id,
        certifying_physician_npi=certifying_physician_npi,
        planned_visit_count=planned_visit_count,
        planned_units_per_visit=planned_units_per_visit,
        cert_period_start=cert_period_start,
        cert_period_end=cert_period_end,
    )
    resp = api_client.create_plan_of_care(
        episode_id, payload,
        make_therapist_headers(acting_therapist_id),
    )
    return get_success_data(resp)


def certify_plan_of_care(*,
                         poc_id: str,
                         acting_therapist_id: str,
                         version: Optional[int] = None,
                         ) -> Dict[str, Any]:
    """POST /plan-of-cares/{id}/certify as Therapist."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    resp = api_client.certify_plan_of_care(
        poc_id, make_therapist_headers(acting_therapist_id),
        payload if payload else None,
    )
    return get_success_data(resp)


# ===========================================================================
# Authorizations — PRD §3.4.
# ===========================================================================
def create_authorization(*,
                         episode_id: str,
                         plan_of_care_id: str,
                         source: str = "COMMERCIAL_PAYER",
                         external_reference: Optional[str] = None,
                         unit_quota: int = TEST_DEFAULTS["DEFAULT_UNIT_QUOTA"],
                         valid_from: Optional[str] = None,
                         valid_through: Optional[str] = None,
                         acting_therapist_id: Optional[str] = None,
                         ) -> Dict[str, Any]:
    """POST /episodes/{id}/authorizations.

    PRD §4 / §1.7 allow both ClinicAdmin and Therapist to create
    authorizations. We default to ClinicAdmin (opaque) so the call does
    not require the caller to be a specific therapist.
    """
    payload = create_authorization_payload(
        plan_of_care_id=plan_of_care_id,
        source=source,
        external_reference=external_reference,
        unit_quota=unit_quota,
        valid_from=valid_from,
        valid_through=valid_through,
    )
    if acting_therapist_id is not None:
        headers = make_therapist_headers(acting_therapist_id)
    else:
        headers = TEST_USERS["clinic_admin_headers"]
    resp = api_client.create_authorization(episode_id, payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Visits — PRD §3.5.
# ===========================================================================
def create_visit(*,
                 episode_id: str,
                 plan_of_care_id: str,
                 authorization_id: str,
                 clinician_id: str,
                 scheduled_start: Optional[str] = None,
                 scheduled_end: Optional[str] = None,
                 units_planned: int = 3,
                 acting_therapist_id: Optional[str] = None,
                 ) -> Dict[str, Any]:
    """POST /episodes/{id}/visits as a Therapist."""
    acting = (acting_therapist_id
              if acting_therapist_id is not None else clinician_id)
    payload = create_visit_payload(
        plan_of_care_id=plan_of_care_id,
        authorization_id=authorization_id,
        clinician_id=clinician_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        units_planned=units_planned,
    )
    resp = api_client.create_visit(
        episode_id, payload, make_therapist_headers(acting),
    )
    return get_success_data(resp)


def start_visit(*, visit_id: str,
                acting_therapist_id: str,
                version: Optional[int] = None,
                ) -> Dict[str, Any]:
    """POST /visits/{id}/start as the acting Therapist."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    resp = api_client.start_visit(
        visit_id, make_therapist_headers(acting_therapist_id),
        payload if payload else None,
    )
    return get_success_data(resp)


def sign_visit(*, visit_id: str,
               acting_therapist_id: str,
               timed_minutes: int = 45,
               version: Optional[int] = None,
               ) -> Dict[str, Any]:
    """POST /visits/{id}/sign as the acting Therapist.

    PRD §2.1: Therapist ownership applies — the acting therapist id
    must equal Visit.clinician_id.
    """
    payload = sign_visit_payload(
        timed_minutes=timed_minutes, version=version,
    )
    resp = api_client.sign_visit(
        visit_id, payload,
        make_therapist_headers(acting_therapist_id),
    )
    return get_success_data(resp)


def submit_claim(*, visit_id: str) -> Dict[str, Any]:
    """POST /visits/{id}/submit-claim as Biller."""
    resp = api_client.submit_claim(visit_id, TEST_USERS["biller_headers"])
    return get_success_data(resp)


def cancel_visit(*, visit_id: str,
                 acting_therapist_id: str,
                 ) -> Dict[str, Any]:
    """POST /visits/{id}/cancel as the acting Therapist."""
    resp = api_client.cancel_visit(
        visit_id, make_therapist_headers(acting_therapist_id),
    )
    return get_success_data(resp)


# ===========================================================================
# Home Exercise Program — PRD §3.7.
# ===========================================================================
def create_home_exercise_program(*,
                                 episode_id: str,
                                 plan_of_care_id: str,
                                 prescribing_clinician_id: str,
                                 acting_therapist_id: Optional[str] = None,
                                 exercise_items: Optional[
                                     List[Dict[str, Any]]] = None,
                                 ) -> Dict[str, Any]:
    """POST /episodes/{id}/home-exercise-programs as a Therapist."""
    acting = (acting_therapist_id
              if acting_therapist_id is not None
              else prescribing_clinician_id)
    payload = create_home_exercise_program_payload(
        plan_of_care_id=plan_of_care_id,
        prescribing_clinician_id=prescribing_clinician_id,
        exercise_items=exercise_items,
    )
    resp = api_client.create_home_exercise_program(
        episode_id, payload, make_therapist_headers(acting),
    )
    return get_success_data(resp)


def issue_home_exercise_program(*,
                                hep_id: str,
                                acting_therapist_id: str,
                                ) -> Dict[str, Any]:
    """POST /home-exercise-programs/{id}/issue as Therapist."""
    resp = api_client.issue_home_exercise_program(
        hep_id, make_therapist_headers(acting_therapist_id),
    )
    return get_success_data(resp)


def acknowledge_home_exercise_program(*,
                                      hep_id: str,
                                      acting_patient_id: str,
                                      ) -> Dict[str, Any]:
    """POST /home-exercise-programs/{id}/acknowledge as Patient.

    PRD §2.1: Patient is entity-backed; X-User-ID must be the actual
    Patient.id whose episode owns this HEP.
    """
    resp = api_client.acknowledge_home_exercise_program(
        hep_id, make_patient_headers(acting_patient_id),
    )
    return get_success_data(resp)


# ===========================================================================
# MIPS — PRD §3.8.
# ===========================================================================
def create_mips_measure(*,
                        episode_id: str,
                        measure_code: str,
                        visit_id: str,
                        numerator_met: bool,
                        exception_reason: str,
                        acting_therapist_id: str,
                        ) -> Dict[str, Any]:
    """POST /episodes/{id}/mips-measures as a Therapist."""
    payload = create_mips_measure_payload(
        measure_code=measure_code,
        visit_id=visit_id,
        numerator_met=numerator_met,
        exception_reason=exception_reason,
    )
    resp = api_client.create_mips_measure(
        episode_id, payload,
        make_therapist_headers(acting_therapist_id),
    )
    return get_success_data(resp)


# ===========================================================================
# Discharge — PRD §3.9.
# ===========================================================================
def create_discharge_assessment(*,
                                episode_id: str,
                                discharging_clinician_id: str,
                                discharge_outcome: str = "GOALS_MET",
                                final_functional_score: int = 80,
                                acting_therapist_id: Optional[str] = None,
                                ) -> Dict[str, Any]:
    """POST /episodes/{id}/discharge-assessments as Therapist."""
    acting = (acting_therapist_id
              if acting_therapist_id is not None
              else discharging_clinician_id)
    payload = create_discharge_assessment_payload(
        discharging_clinician_id=discharging_clinician_id,
        discharge_outcome=discharge_outcome,
        final_functional_score=final_functional_score,
    )
    resp = api_client.create_discharge_assessment(
        episode_id, payload, make_therapist_headers(acting),
    )
    return get_success_data(resp)


def sign_discharge_assessment(*,
                              discharge_id: str,
                              acting_therapist_id: str,
                              version: Optional[int] = None,
                              ) -> Dict[str, Any]:
    """POST /discharge-assessments/{id}/sign as Therapist.

    PRD §2.1 / §3.9: discharging_clinician_id ownership is enforced;
    the acting therapist id must equal the recorded
    discharging_clinician_id.
    """
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    resp = api_client.sign_discharge_assessment(
        discharge_id, make_therapist_headers(acting_therapist_id),
        payload if payload else None,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2 — Scenario fixtures (frequently reused multi-call setups).
# ===========================================================================
def setup_evaluated_episode(*,
                            insurance_type: str = "COMMERCIAL",
                            complexity: str = "MODERATE",
                            functional_baseline_score: int = 50,
                            therapist_credential: str = "DPT",
                            body_region: str = "LUMBAR",
                            ) -> Dict[str, Any]:
    """Anchor clock, create therapist + patient + episode + initial
    evaluation + finalize.

    Returns a dict with keys: therapist, patient, episode, evaluation.
    Episode.status == EVALUATED after this call; Episode.cap_policy is
    set per PRD §3.2 from Patient.insurance_type.
    """
    anchor_clock()
    therapist = create_therapist(credential=therapist_credential)
    patient = create_patient(insurance_type=insurance_type)
    episode = create_episode(
        patient_id=patient["id"],
        acting_therapist_id=therapist["id"],
        body_region=body_region,
    )
    evaluation = create_evaluation(
        episode_id=episode["id"],
        evaluation_type="INITIAL",
        clinician_id=therapist["id"],
        complexity=complexity,
        functional_baseline_score=functional_baseline_score,
    )
    evaluation = finalize_evaluation(
        evaluation_id=evaluation["id"],
        acting_therapist_id=therapist["id"],
    )
    return {
        "therapist": therapist,
        "patient": patient,
        "episode": re_get_episode(episode["id"]),
        "evaluation": evaluation,
    }


def setup_active_episode(*,
                         insurance_type: str = "COMMERCIAL",
                         complexity: str = "MODERATE",
                         functional_baseline_score: int = 50,
                         therapist_credential: str = "DPT",
                         planned_visit_count: Optional[int] = None,
                         planned_units_per_visit: Optional[int] = None,
                         unit_quota: int = TEST_DEFAULTS["DEFAULT_UNIT_QUOTA"],
                         cert_period_days: int = 60,
                         authorization_source: str = "COMMERCIAL_PAYER",
                         body_region: str = "LUMBAR",
                         veteran_referral_id: Optional[str] = None,
                         ) -> Dict[str, Any]:
    """Build an episode all the way to Episode.status == ACTIVE.

    Pipeline: therapist + patient + episode + INITIAL evaluation
    finalized + plan of care drafted + authorization issued covering
    the cert window + plan of care certified.

    PRD §3.3 requires that certify only succeeds when the bound
    authorization's `unit_quota >= planned_visit_count *
    planned_units_per_visit`. When the caller supplies a smaller
    `unit_quota` without overriding the planned counts, the planned
    counts are auto-scaled down so the certify check passes.

    Returns: {therapist, patient, episode, evaluation, plan_of_care,
              authorization}.
    """
    # Auto-fit planned counts to unit_quota when only unit_quota is
    # narrowed (PRD §3.3 unit-coverage rule).
    if planned_units_per_visit is None:
        planned_units_per_visit = TEST_DEFAULTS[
            "DEFAULT_PLANNED_UNITS_PER_VISIT"]
    if planned_visit_count is None:
        default_count = TEST_DEFAULTS["DEFAULT_PLANNED_VISIT_COUNT"]
        if default_count * planned_units_per_visit <= unit_quota:
            planned_visit_count = default_count
        else:
            planned_visit_count = max(
                1, unit_quota // planned_units_per_visit,
            )
    # PRD §3.3 hard rule: unit_quota >= planned_visit_count *
    # planned_units_per_visit at certify time. If caller pinned both
    # planned counts (e.g., to drive a band test) and supplied a smaller
    # unit_quota, raise the quota so certify succeeds. Tests that need
    # to assert on an exact unit_quota override do so by passing
    # `unit_quota` consistent with the planned product.
    needed = planned_visit_count * planned_units_per_visit
    if unit_quota < needed:
        unit_quota = needed

    setup = setup_evaluated_episode(
        insurance_type=insurance_type,
        complexity=complexity,
        functional_baseline_score=functional_baseline_score,
        therapist_credential=therapist_credential,
        body_region=body_region,
    )
    therapist = setup["therapist"]
    patient = setup["patient"]
    episode = setup["episode"]
    evaluation = setup["evaluation"]

    cert_start = iso_date_anchor_offset(days=0)
    cert_end = iso_date_anchor_offset(days=cert_period_days)
    plan_of_care = create_plan_of_care(
        episode_id=episode["id"],
        evaluation_id=evaluation["id"],
        acting_therapist_id=therapist["id"],
        planned_visit_count=planned_visit_count,
        planned_units_per_visit=planned_units_per_visit,
        cert_period_start=cert_start,
        cert_period_end=cert_end,
    )

    ext_ref = veteran_referral_id if authorization_source == "VA_REFERRAL" \
        else None
    authorization = create_authorization(
        episode_id=episode["id"],
        plan_of_care_id=plan_of_care["id"],
        source=authorization_source,
        external_reference=ext_ref,
        unit_quota=unit_quota,
        valid_from=iso_date_anchor_offset(days=-1),
        valid_through=iso_date_anchor_offset(days=cert_period_days + 1),
    )

    plan_of_care = certify_plan_of_care(
        poc_id=plan_of_care["id"],
        acting_therapist_id=therapist["id"],
    )

    return {
        "therapist": therapist,
        "patient": re_get_patient(patient["id"]),
        "episode": re_get_episode(episode["id"]),
        "evaluation": evaluation,
        "plan_of_care": plan_of_care,
        "authorization": authorization,
    }


def setup_va_active_episode(*,
                            authorized_units: int = 60,
                            **active_kwargs: Any,
                            ) -> Dict[str, Any]:
    """ACTIVE episode for a VA patient with a registered VeteranReferral.

    PRD §3.4: the first visit on a VA episode requires an Authorization
    with source=VA_REFERRAL referencing an ACTIVE VeteranReferral and
    its external_reference must equal both the VeteranReferral.id and
    Patient.va_referral_id.
    """
    anchor_clock()
    therapist = create_therapist(
        credential=active_kwargs.pop("therapist_credential", "DPT"),
    )
    # PRD §3.1 requires va_referral_id at patient creation; PRD §3.4
    # mirrors the actual VeteranReferral.id onto Patient.va_referral_id
    # at VA-sourced authorization create time. We create the patient
    # with a placeholder VA id (server requires the field non-empty
    # because insurance_type == "VA"), then create the referral, then
    # rely on the platform's mirror to align Patient.va_referral_id with
    # the referral id on the first VA-sourced auth.
    patient = create_patient(insurance_type="VA")
    veteran_referral = create_veteran_referral(
        patient_id=patient["id"],
        authorized_units=authorized_units,
    )
    # PRD §3.4: external_reference must equal both VeteranReferral.id
    # and Patient.va_referral_id; the platform mirrors the id onto
    # Patient.va_referral_id on authorization creation.
    episode = create_episode(
        patient_id=patient["id"],
        acting_therapist_id=therapist["id"],
        body_region=active_kwargs.pop("body_region", "LUMBAR"),
    )
    evaluation = create_evaluation(
        episode_id=episode["id"],
        evaluation_type="INITIAL",
        clinician_id=therapist["id"],
        complexity=active_kwargs.pop("complexity", "MODERATE"),
        functional_baseline_score=active_kwargs.pop(
            "functional_baseline_score", 50,
        ),
    )
    evaluation = finalize_evaluation(
        evaluation_id=evaluation["id"],
        acting_therapist_id=therapist["id"],
    )
    cert_period_days = active_kwargs.pop("cert_period_days", 60)
    cert_start = iso_date_anchor_offset(days=0)
    cert_end = iso_date_anchor_offset(days=cert_period_days)
    unit_quota_v = active_kwargs.pop(
        "unit_quota", TEST_DEFAULTS["DEFAULT_UNIT_QUOTA"],
    )
    planned_upv = active_kwargs.pop(
        "planned_units_per_visit",
        TEST_DEFAULTS["DEFAULT_PLANNED_UNITS_PER_VISIT"],
    )
    planned_vc_arg = active_kwargs.pop("planned_visit_count", None)
    if planned_vc_arg is None:
        default_count = TEST_DEFAULTS["DEFAULT_PLANNED_VISIT_COUNT"]
        planned_vc = (default_count
                      if default_count * planned_upv <= unit_quota_v
                      else max(1, unit_quota_v // planned_upv))
    else:
        planned_vc = planned_vc_arg
    # PRD §3.3 certify rule: unit_quota >= planned product.
    needed_va = planned_vc * planned_upv
    if unit_quota_v < needed_va:
        unit_quota_v = needed_va
    plan_of_care = create_plan_of_care(
        episode_id=episode["id"],
        evaluation_id=evaluation["id"],
        acting_therapist_id=therapist["id"],
        planned_visit_count=planned_vc,
        planned_units_per_visit=planned_upv,
        cert_period_start=cert_start,
        cert_period_end=cert_end,
    )
    authorization = create_authorization(
        episode_id=episode["id"],
        plan_of_care_id=plan_of_care["id"],
        source="VA_REFERRAL",
        external_reference=veteran_referral["id"],
        unit_quota=unit_quota_v,
        valid_from=iso_date_anchor_offset(days=-1),
        valid_through=iso_date_anchor_offset(days=cert_period_days + 1),
    )
    plan_of_care = certify_plan_of_care(
        poc_id=plan_of_care["id"],
        acting_therapist_id=therapist["id"],
    )
    return {
        "therapist": therapist,
        "patient": re_get_patient(patient["id"]),
        "episode": re_get_episode(episode["id"]),
        "evaluation": evaluation,
        "plan_of_care": plan_of_care,
        "authorization": authorization,
        "veteran_referral": veteran_referral,
    }


# ===========================================================================
# Tier 3 — Visit lifecycle shortcuts.
# ===========================================================================
def setup_scheduled_visit(*,
                          units_planned: int = 3,
                          visit_offset_hours: int = 2,
                          visit_duration_minutes: int = 60,
                          **active_kwargs: Any,
                          ) -> Dict[str, Any]:
    """ACTIVE episode + one SCHEDULED visit on it."""
    setup = setup_active_episode(**active_kwargs)
    therapist = setup["therapist"]
    start = iso_anchor_offset(hours=visit_offset_hours)
    end = iso_anchor_offset(
        hours=visit_offset_hours,
        minutes=visit_duration_minutes,
    )
    visit = create_visit(
        episode_id=setup["episode"]["id"],
        plan_of_care_id=setup["plan_of_care"]["id"],
        authorization_id=setup["authorization"]["id"],
        clinician_id=therapist["id"],
        scheduled_start=start,
        scheduled_end=end,
        units_planned=units_planned,
        acting_therapist_id=therapist["id"],
    )
    setup["visit"] = visit
    setup["episode"] = re_get_episode(setup["episode"]["id"])
    return setup


def setup_in_session_visit(**kwargs: Any) -> Dict[str, Any]:
    """ACTIVE episode + visit advanced to IN_SESSION."""
    setup = setup_scheduled_visit(**kwargs)
    setup["visit"] = start_visit(
        visit_id=setup["visit"]["id"],
        acting_therapist_id=setup["therapist"]["id"],
    )
    setup["episode"] = re_get_episode(setup["episode"]["id"])
    return setup


def setup_signed_visit(*, timed_minutes: int = 45,
                       **kwargs: Any) -> Dict[str, Any]:
    """ACTIVE episode + visit signed (SIGNED)."""
    setup = setup_in_session_visit(**kwargs)
    setup["visit"] = sign_visit(
        visit_id=setup["visit"]["id"],
        acting_therapist_id=setup["therapist"]["id"],
        timed_minutes=timed_minutes,
    )
    setup["episode"] = re_get_episode(setup["episode"]["id"])
    setup["patient"] = re_get_patient(setup["patient"]["id"])
    return setup


# ===========================================================================
# Tier 4 — Threshold / boundary targeting.
# ===========================================================================
def visit_duration_for_minutes(timed_minutes: int) -> int:
    """Return a scheduled-window duration in minutes that comfortably
    contains `timed_minutes` of treatment."""
    return max(60, timed_minutes + 15)


def _sign_calibrated_visit(*,
                           episode_id: str,
                           plan_of_care_id: str,
                           authorization_id: str,
                           therapist_id: str,
                           day_offset: int,
                           units_planned: int,
                           timed_minutes: int,
                           ) -> Dict[str, Any]:
    """Schedule + start + sign a visit on the given episode well
    outside the evaluation window (so no eval surcharge applies)."""
    start = iso_anchor_offset(days=day_offset, hours=10)
    end = iso_anchor_offset(
        days=day_offset, hours=10,
        minutes=visit_duration_for_minutes(timed_minutes),
    )
    v = create_visit(
        episode_id=episode_id,
        plan_of_care_id=plan_of_care_id,
        authorization_id=authorization_id,
        clinician_id=therapist_id,
        scheduled_start=start, scheduled_end=end,
        units_planned=units_planned,
        acting_therapist_id=therapist_id,
    )
    start_visit(visit_id=v["id"], acting_therapist_id=therapist_id)
    return sign_visit(
        visit_id=v["id"], acting_therapist_id=therapist_id,
        timed_minutes=timed_minutes,
    )


def setup_capped_episode_with_ytd(*,
                                  ytd_cents: int,
                                  complexity: str = "MODERATE",
                                  planned_visit_count: int = 60,
                                  planned_units_per_visit: int = 5,
                                  unit_quota: int = 200,
                                  ) -> Dict[str, Any]:
    """Capped ACTIVE episode for a MEDICARE_PART_B patient whose
    ytd_capped_amount_cents has been driven up to `ytd_cents` exactly
    by signing one or more prior visits.

    Strategy: drive ytd by signing N visits, each producing a charge
    that is a multiple of 4,200 cents (DPT credential, no
    eval-in-window). For 3 units / visit, charge_cents = 12,600. We
    sign as many 3-unit visits as needed for the largest multiple of
    12,600 less than `ytd_cents`, then a smaller visit to make up the
    remainder. Each multiple of 4,200 cents matches exactly 1 unit of
    DPT-credentialed delivery.

    Constraint: ytd_cents must be a non-negative multiple of 4,200
    less than CAP_HARD_CENTS so it can be reached exactly.
    """
    if ytd_cents < 0 or ytd_cents >= CAP_HARD_CENTS:
        raise ValueError(
            f"ytd_cents must be in [0, {CAP_HARD_CENTS}), got "
            f"{ytd_cents}",
        )
    if ytd_cents % 4_200 != 0:
        raise ValueError(
            f"ytd_cents must be a multiple of 4200; got {ytd_cents}",
        )

    setup = setup_active_episode(
        insurance_type="MEDICARE_PART_B",
        complexity=complexity,
        therapist_credential="DPT",
        unit_quota=unit_quota,
        planned_visit_count=planned_visit_count,
        planned_units_per_visit=planned_units_per_visit,
        cert_period_days=60,
    )

    if ytd_cents == 0:
        return setup

    therapist = setup["therapist"]
    episode = setup["episode"]
    plan_of_care = setup["plan_of_care"]
    authorization = setup["authorization"]

    units_remaining = ytd_cents // 4_200
    day_offset = 1
    while units_remaining > 0:
        # Cap at 6 units / visit. units = (timed-8)//15 + 1, so
        # 6 units -> timed_minutes 83-97; we use 83.
        units_this = min(6, units_remaining)
        timed = 8 + (units_this - 1) * 15
        _sign_calibrated_visit(
            episode_id=episode["id"],
            plan_of_care_id=plan_of_care["id"],
            authorization_id=authorization["id"],
            therapist_id=therapist["id"],
            day_offset=day_offset,
            units_planned=units_this,
            timed_minutes=timed,
        )
        units_remaining -= units_this
        day_offset += 1

    setup["patient"] = re_get_patient(setup["patient"]["id"])
    setup["episode"] = re_get_episode(setup["episode"]["id"])
    return setup


def setup_reeval_due_episode(**active_kwargs: Any) -> Dict[str, Any]:
    """ACTIVE episode that has been clock-advanced past the 30-day
    reeval threshold, yielding Episode.status == REEVAL_DUE.

    PRD §3.6: "When the test clock is advanced and the gap reaches 30
    days or more on an ACTIVE episode, the episode is swept to
    REEVAL_DUE."
    """
    setup = setup_active_episode(**active_kwargs)
    advance_clock_days(REEVAL_DUE_DAYS + 1)
    setup["episode"] = re_get_episode(setup["episode"]["id"])
    return setup


def setup_discharge_pending_episode(**active_kwargs: Any) -> Dict[str, Any]:
    """ACTIVE episode + draft DischargeAssessment.

    Returns the setup dict augmented with a separate DISCHARGER
    therapist (distinct from the evaluator) and the draft discharge
    assessment. PRD §3.9: "no visit on the episode remains in
    SCHEDULED or IN_SESSION; ..."  This fixture skips visits entirely
    to satisfy that requirement.
    """
    setup = setup_active_episode(**active_kwargs)
    discharger = create_therapist(credential="DPT")
    discharge_assessment = create_discharge_assessment(
        episode_id=setup["episode"]["id"],
        discharging_clinician_id=discharger["id"],
        acting_therapist_id=discharger["id"],
        discharge_outcome="GOALS_MET",
        final_functional_score=80,
    )
    setup["discharger"] = discharger
    setup["discharge_assessment"] = discharge_assessment
    setup["episode"] = re_get_episode(setup["episode"]["id"])
    return setup


# ===========================================================================
# Tier 5 — Difficulty-design specific composite fixtures.
# ===========================================================================
def setup_capped_active_via_three_visits(
        *,
        per_visit_charge_cents: int = 7_500,
        n_visits: int = 3,
        complexity: str = "MODERATE",
        ) -> Dict[str, Any]:
    """For MIPS aggregate-then-round (difficulty-design mode_b):
    create three signed visits by the same evaluator, ready to receive
    nine MipsMeasure rows and a discharge signed by a DIFFERENT
    therapist.

    Returns: {evaluator, discharger, patient, episode, plan_of_care,
              authorization, visits: List[Visit]}.
    """
    setup = setup_active_episode(
        insurance_type="COMMERCIAL",
        complexity=complexity,
        therapist_credential="DPT",
        unit_quota=60,
        planned_visit_count=10,
        planned_units_per_visit=3,
        cert_period_days=60,
    )
    therapist = setup["therapist"]  # evaluator
    visits: List[Dict[str, Any]] = []
    for i in range(n_visits):
        start = iso_anchor_offset(days=1 + i, hours=10)
        end = iso_anchor_offset(days=1 + i, hours=11)
        v = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=start,
            scheduled_end=end,
            units_planned=3,
            acting_therapist_id=therapist["id"],
        )
        start_visit(
            visit_id=v["id"], acting_therapist_id=therapist["id"],
        )
        v = sign_visit(
            visit_id=v["id"],
            acting_therapist_id=therapist["id"],
            timed_minutes=45,  # 3 units @ DPT, no eval surcharge here
        )
        visits.append(v)
    # Create a SECOND therapist who will sign discharge (segregation
    # of duties — PRD §3.9).
    discharger = create_therapist(credential="DPT")
    setup["evaluator"] = therapist
    setup["discharger"] = discharger
    setup["visits"] = visits
    setup["episode"] = re_get_episode(setup["episode"]["id"])
    return setup


def setup_kx_boundary_capped_episode() -> Dict[str, Any]:
    """Capped ACTIVE episode positioned so a 12,600-cent visit
    (3 units * 4200, no eval surcharge) will strictly cross
    KX_THRESHOLD_CENTS.

    ytd_capped_amount_cents = 235,200 cents (56 units * 4,200).
    After a 3-unit visit at 12,600: ytd = 247,800 > 241,000.
    The next adjacent multiple-of-4,200 ytd below threshold is
    239,400 cents (still below 241,000); both starting points cross
    the threshold but 235,200 leaves clear daylight for the test.

    Used for visit_sign_cascade_kx_depth_2 difficulty instance and
    related KX-flip tests.

    Uses complexity=LOW + small planned-product so the certify-time
    projection (planned_visit_count * planned_units_per_visit * 4200
    + 5000) stays under the 241,000-cent KX threshold; otherwise PRD
    §3.3 would flip Episode.kx_modifier_required to true at certify
    time and the pre-state required by KX-flip-on-sign tests would
    not hold.
    """
    return setup_capped_episode_with_ytd(
        ytd_cents=235_200,
        complexity="LOW",
        planned_visit_count=20,
        planned_units_per_visit=2,
        unit_quota=100,
    )


def setup_mergeable_clinician_schedule_pair(
        *,
        gap_minutes: int = 0,
        ) -> Dict[str, Any]:
    """For clinician_double_booking_half_open: two episodes on
    different patients but the SAME clinician, with one pre-existing
    SCHEDULED visit 10:00–11:00 on episode A. Returns the setup plus
    plan/auth references for episode B so the test can schedule a
    second visit at 11:00 (no overlap under half-open) or 10:59 (overlap).

    gap_minutes is informational; the caller chooses the actual visit
    start.
    """
    anchor_clock()
    clinician = create_therapist(credential="DPT")
    # Patient A + episode_a
    patient_a = create_patient(insurance_type="COMMERCIAL")
    episode_a = create_episode(
        patient_id=patient_a["id"],
        acting_therapist_id=clinician["id"],
        body_region="LUMBAR",
    )
    eval_a = create_evaluation(
        episode_id=episode_a["id"], evaluation_type="INITIAL",
        clinician_id=clinician["id"], complexity="MODERATE",
        functional_baseline_score=50,
    )
    eval_a = finalize_evaluation(
        evaluation_id=eval_a["id"],
        acting_therapist_id=clinician["id"],
    )
    cert_start = iso_date_anchor_offset(days=0)
    cert_end = iso_date_anchor_offset(days=60)
    poc_a = create_plan_of_care(
        episode_id=episode_a["id"], evaluation_id=eval_a["id"],
        acting_therapist_id=clinician["id"],
        planned_visit_count=20, planned_units_per_visit=3,
        cert_period_start=cert_start, cert_period_end=cert_end,
    )
    auth_a = create_authorization(
        episode_id=episode_a["id"], plan_of_care_id=poc_a["id"],
        source="COMMERCIAL_PAYER", unit_quota=60,
        valid_from=iso_date_anchor_offset(days=-1),
        valid_through=iso_date_anchor_offset(days=61),
    )
    poc_a = certify_plan_of_care(
        poc_id=poc_a["id"], acting_therapist_id=clinician["id"],
    )
    # Pre-existing visit 10:00 - 11:00 (relative to anchor +1 day for
    # clarity).
    pre_start = iso_anchor_offset(days=1, hours=0)  # anchor + 1d 00:00
    pre_end = iso_anchor_offset(days=1, hours=1)    # anchor + 1d 01:00
    pre_visit = create_visit(
        episode_id=episode_a["id"], plan_of_care_id=poc_a["id"],
        authorization_id=auth_a["id"], clinician_id=clinician["id"],
        scheduled_start=pre_start, scheduled_end=pre_end,
        units_planned=3, acting_therapist_id=clinician["id"],
    )

    # Patient B + episode_b for the second visit on the same clinician.
    patient_b = create_patient(insurance_type="COMMERCIAL")
    episode_b = create_episode(
        patient_id=patient_b["id"],
        acting_therapist_id=clinician["id"],
        body_region="KNEE",
    )
    eval_b = create_evaluation(
        episode_id=episode_b["id"], evaluation_type="INITIAL",
        clinician_id=clinician["id"], complexity="MODERATE",
        functional_baseline_score=50,
    )
    eval_b = finalize_evaluation(
        evaluation_id=eval_b["id"],
        acting_therapist_id=clinician["id"],
    )
    poc_b = create_plan_of_care(
        episode_id=episode_b["id"], evaluation_id=eval_b["id"],
        acting_therapist_id=clinician["id"],
        planned_visit_count=20, planned_units_per_visit=3,
        cert_period_start=cert_start, cert_period_end=cert_end,
    )
    auth_b = create_authorization(
        episode_id=episode_b["id"], plan_of_care_id=poc_b["id"],
        source="COMMERCIAL_PAYER", unit_quota=60,
        valid_from=iso_date_anchor_offset(days=-1),
        valid_through=iso_date_anchor_offset(days=61),
    )
    poc_b = certify_plan_of_care(
        poc_id=poc_b["id"], acting_therapist_id=clinician["id"],
    )

    return {
        "clinician": clinician,
        "patient_a": patient_a,
        "episode_a": re_get_episode(episode_a["id"]),
        "plan_of_care_a": poc_a,
        "authorization_a": auth_a,
        "pre_existing_visit": pre_visit,
        "pre_existing_start": pre_start,
        "pre_existing_end": pre_end,
        "patient_b": patient_b,
        "episode_b": re_get_episode(episode_b["id"]),
        "plan_of_care_b": poc_b,
        "authorization_b": auth_b,
    }


def setup_patient_overlap_pair() -> Dict[str, Any]:
    """For patient_double_booking_closed: one patient on two episodes
    with two different clinicians; one pre-existing visit 14:00–15:00
    on episode A. Caller schedules at 15:00 on episode B to provoke
    ERR_PATIENT_DOUBLE_BOOKED under closed-interval semantics.
    """
    anchor_clock()
    clinician_a = create_therapist(credential="DPT")
    clinician_b = create_therapist(credential="DPT")
    patient = create_patient(insurance_type="COMMERCIAL")
    # Episode A
    episode_a = create_episode(
        patient_id=patient["id"],
        acting_therapist_id=clinician_a["id"],
        body_region="LUMBAR",
    )
    eval_a = create_evaluation(
        episode_id=episode_a["id"], evaluation_type="INITIAL",
        clinician_id=clinician_a["id"], complexity="MODERATE",
        functional_baseline_score=50,
    )
    eval_a = finalize_evaluation(
        evaluation_id=eval_a["id"],
        acting_therapist_id=clinician_a["id"],
    )
    cert_start = iso_date_anchor_offset(days=0)
    cert_end = iso_date_anchor_offset(days=60)
    poc_a = create_plan_of_care(
        episode_id=episode_a["id"], evaluation_id=eval_a["id"],
        acting_therapist_id=clinician_a["id"],
        planned_visit_count=20, planned_units_per_visit=3,
        cert_period_start=cert_start, cert_period_end=cert_end,
    )
    auth_a = create_authorization(
        episode_id=episode_a["id"], plan_of_care_id=poc_a["id"],
        source="COMMERCIAL_PAYER", unit_quota=60,
        valid_from=iso_date_anchor_offset(days=-1),
        valid_through=iso_date_anchor_offset(days=61),
    )
    poc_a = certify_plan_of_care(
        poc_id=poc_a["id"], acting_therapist_id=clinician_a["id"],
    )

    pre_start = iso_anchor_offset(days=1, hours=4)  # anchor + 1d 04:00
    pre_end = iso_anchor_offset(days=1, hours=5)    # anchor + 1d 05:00
    pre_visit = create_visit(
        episode_id=episode_a["id"], plan_of_care_id=poc_a["id"],
        authorization_id=auth_a["id"], clinician_id=clinician_a["id"],
        scheduled_start=pre_start, scheduled_end=pre_end,
        units_planned=3, acting_therapist_id=clinician_a["id"],
    )

    # Episode B (same patient, different clinician).
    episode_b = create_episode(
        patient_id=patient["id"],
        acting_therapist_id=clinician_b["id"],
        body_region="KNEE",
    )
    eval_b = create_evaluation(
        episode_id=episode_b["id"], evaluation_type="INITIAL",
        clinician_id=clinician_b["id"], complexity="MODERATE",
        functional_baseline_score=50,
    )
    eval_b = finalize_evaluation(
        evaluation_id=eval_b["id"],
        acting_therapist_id=clinician_b["id"],
    )
    poc_b = create_plan_of_care(
        episode_id=episode_b["id"], evaluation_id=eval_b["id"],
        acting_therapist_id=clinician_b["id"],
        planned_visit_count=20, planned_units_per_visit=3,
        cert_period_start=cert_start, cert_period_end=cert_end,
    )
    auth_b = create_authorization(
        episode_id=episode_b["id"], plan_of_care_id=poc_b["id"],
        source="COMMERCIAL_PAYER", unit_quota=60,
        valid_from=iso_date_anchor_offset(days=-1),
        valid_through=iso_date_anchor_offset(days=61),
    )
    poc_b = certify_plan_of_care(
        poc_id=poc_b["id"], acting_therapist_id=clinician_b["id"],
    )

    return {
        "clinician_a": clinician_a,
        "clinician_b": clinician_b,
        "patient": patient,
        "episode_a": re_get_episode(episode_a["id"]),
        "plan_of_care_a": poc_a,
        "authorization_a": auth_a,
        "pre_existing_visit": pre_visit,
        "pre_existing_start": pre_start,
        "pre_existing_end": pre_end,
        "episode_b": re_get_episode(episode_b["id"]),
        "plan_of_care_b": poc_b,
        "authorization_b": auth_b,
    }


def setup_reeval_due_with_full_units() -> Dict[str, Any]:
    """For state_vs_business_fiscal_pair: REEVAL_DUE episode whose
    Authorization unit_quota is fully reserved by a single existing
    SCHEDULED visit, so a new visit request will simultaneously trigger
    ERR_REEVAL_DUE (state, priority 7) and ERR_INSUFFICIENT_UNITS
    (business_fiscal, priority 17). PRD §2.6 declares the state class
    wins.
    """
    # Build ACTIVE episode with planned_visit_count * planned_units_per_visit
    # == unit_quota (PRD §3.3 certify rule), then reserve enough units via
    # an existing SCHEDULED visit that any new visit with units_planned=4
    # also fails ERR_INSUFFICIENT_UNITS.
    anchor_clock()
    therapist = create_therapist(credential="DPT")
    patient = create_patient(insurance_type="COMMERCIAL")
    episode = create_episode(
        patient_id=patient["id"],
        acting_therapist_id=therapist["id"],
        body_region="LUMBAR",
    )
    evaluation = create_evaluation(
        episode_id=episode["id"], evaluation_type="INITIAL",
        clinician_id=therapist["id"], complexity="MODERATE",
        functional_baseline_score=50,
    )
    evaluation = finalize_evaluation(
        evaluation_id=evaluation["id"],
        acting_therapist_id=therapist["id"],
    )
    cert_start = iso_date_anchor_offset(days=0)
    cert_end = iso_date_anchor_offset(days=60)
    poc = create_plan_of_care(
        episode_id=episode["id"], evaluation_id=evaluation["id"],
        acting_therapist_id=therapist["id"],
        planned_visit_count=2,
        planned_units_per_visit=5,
        cert_period_start=cert_start, cert_period_end=cert_end,
    )
    auth = create_authorization(
        episode_id=episode["id"], plan_of_care_id=poc["id"],
        source="COMMERCIAL_PAYER", unit_quota=10,
        valid_from=iso_date_anchor_offset(days=-1),
        valid_through=iso_date_anchor_offset(days=61),
    )
    poc = certify_plan_of_care(
        poc_id=poc["id"], acting_therapist_id=therapist["id"],
    )

    # Existing SCHEDULED visit reserving 8 of 10 units; a new request
    # with units_planned=4 will overflow (8 + 4 > 10).
    visit_start = iso_anchor_offset(days=1, hours=0)
    visit_end = iso_anchor_offset(days=1, hours=1)
    pre_visit = create_visit(
        episode_id=episode["id"], plan_of_care_id=poc["id"],
        authorization_id=auth["id"], clinician_id=therapist["id"],
        scheduled_start=visit_start, scheduled_end=visit_end,
        units_planned=8, acting_therapist_id=therapist["id"],
    )

    # Now advance clock past reeval threshold.
    advance_clock_days(REEVAL_DUE_DAYS + 1)

    return {
        "therapist": therapist,
        "patient": patient,
        "episode": re_get_episode(episode["id"]),
        "evaluation": evaluation,
        "plan_of_care": poc,
        "authorization": auth,
        "pre_existing_visit": pre_visit,
    }


def setup_unit_pool_snapshot() -> Dict[str, Any]:
    """For unit_reservation_release_invariant difficulty instance:
    ACTIVE episode with unit_quota=10 and a fresh roll-up snapshot
    {authorized=10, reserved=0, committed=0}.
    """
    return setup_active_episode(
        insurance_type="COMMERCIAL",
        complexity="MODERATE",
        therapist_credential="DPT",
        unit_quota=10,
        planned_visit_count=5,
        planned_units_per_visit=2,
        cert_period_days=60,
    )


def setup_va_referral_partial_consumed(
        *,
        authorized_units: int = 50,
        first_quota: int = 40,
        ) -> Dict[str, Any]:
    """For VA referral exhaustion testing: a VeteranReferral with
    `authorized_units` and one Authorization already drawing
    first_quota. Returns the setup; caller can then attempt to create
    a second authorization that would push the total over
    authorized_units.
    """
    setup = setup_va_active_episode(
        authorized_units=authorized_units,
        unit_quota=first_quota,
    )
    return setup


# Re-export for convenience.
__all__ = [
    # Clock helpers
    "anchor_clock",
    "advance_clock_to",
    "advance_clock_days",
    # Atomic creators
    "create_therapist",
    "create_pt_therapist",
    "create_dpt_therapist",
    "create_pta_therapist",
    "create_patient",
    "re_get_patient",
    "get_cap_status",
    "create_veteran_referral",
    "create_episode",
    "re_get_episode",
    "create_evaluation",
    "finalize_evaluation",
    "amend_evaluation",
    "create_plan_of_care",
    "certify_plan_of_care",
    "create_authorization",
    "create_visit",
    "start_visit",
    "sign_visit",
    "submit_claim",
    "cancel_visit",
    "create_home_exercise_program",
    "issue_home_exercise_program",
    "acknowledge_home_exercise_program",
    "create_mips_measure",
    "create_discharge_assessment",
    "sign_discharge_assessment",
    "visit_duration_for_minutes",
    # Tier 2-5 fixtures
    "setup_evaluated_episode",
    "setup_active_episode",
    "setup_va_active_episode",
    "setup_scheduled_visit",
    "setup_in_session_visit",
    "setup_signed_visit",
    "setup_capped_episode_with_ytd",
    "setup_reeval_due_episode",
    "setup_discharge_pending_episode",
    "setup_capped_active_via_three_visits",
    "setup_kx_boundary_capped_episode",
    "setup_mergeable_clinician_schedule_pair",
    "setup_patient_overlap_pair",
    "setup_reeval_due_with_full_units",
    "setup_unit_pool_snapshot",
    "setup_va_referral_partial_consumed",
]
