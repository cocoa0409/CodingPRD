"""Composite setup helpers — multi-step preambles that tests reuse.

The clinical workflow is long: register Provider -> register Patient ->
bind Patient to PCP -> schedule Encounter -> check it in -> add
CptLineItems -> PATCH vital_signs -> complete the Encounter -> draft a
Prescription -> sign -> transmit -> dispense. Most interesting test
claims need the system in a late-pipeline state, and several
difficulty-design instances demand cross-entity state combos that
require dozens of API calls to construct.

IDENTITY THREADING — PRD §2.1.

- Provider is ENTITY-BACKED. Every Provider-driven call whose success
  depends on owning the targeted resource MUST mint headers via
  make_provider_headers(provider["id"]) — never via the shared
  PROVIDER_FALLBACK_ID constant. Fixtures here remember the actual
  Provider.id of the acting clinician and pass it through to ownership-
  gated calls (sign, transmit, cancel-prescription, accept-referral,
  return-to-pcp, complete-referral, complete-encounter).

- PatientPortalUser is ENTITY-BACKED. Every PatientPortalUser-driven
  call whose success depends on owning the targeted patient resource
  MUST mint headers via make_patient_portal_headers(patient["id"]).

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    bind_pcp_payload,
    clock_advance_payload,
    create_cpt_code_payload,
    create_cpt_line_item_payload,
    create_encounter_payload,
    create_patient_payload,
    create_portal_message_payload,
    create_prescription_payload,
    create_provider_payload,
    create_referral_payload,
    default_vital_signs,
    iso_anchor_offset,
    patch_encounter_payload,
    random_dea_number,
    referral_action_payload,
    sign_prescription_payload,
)
from .test_users import (
    TEST_USERS,
    make_patient_portal_headers,
    make_provider_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.9.
# ===========================================================================
def anchor_clock() -> Dict[str, Any]:
    """Pin the server clock to the deterministic test anchor.

    PRD §2.9: 'an admin-only clock-advance capability advances the
    server clock by a supplied number of seconds or directly to a
    supplied absolute ISO instant via a to parameter.' The TestHarness
    role is exempt from the auth header check.
    """
    resp = api_client.clock_advance(
        clock_advance_payload(to=TEST_DEFAULTS["CLOCK_ANCHOR"]),
        TEST_USERS["test_harness_headers"],
    )
    return get_success_data(resp)


def advance_clock_to(iso_timestamp: str) -> Dict[str, Any]:
    """POST /_clock/advance with an absolute target."""
    resp = api_client.clock_advance(
        clock_advance_payload(to=iso_timestamp),
        TEST_USERS["test_harness_headers"],
    )
    return get_success_data(resp)


def advance_clock_seconds(seconds: int) -> Dict[str, Any]:
    """POST /_clock/advance with a relative seconds delta."""
    resp = api_client.clock_advance(
        clock_advance_payload(seconds=seconds),
        TEST_USERS["test_harness_headers"],
    )
    return get_success_data(resp)


def run_sweep() -> Dict[str, Any]:
    """POST /_sweep/run."""
    resp = api_client.sweep_run(TEST_USERS["test_harness_headers"])
    return get_success_data(resp)


# ===========================================================================
# Providers — PRD §3.2.
# ===========================================================================
def create_provider(*,
                    role_type: str = "PCP_ONLY",
                    epcs_enrolled: bool = True,
                    dea_number: Optional[str] = None,
                    panel_cap: Optional[int] = None,
                    specialty: Optional[str] = None,
                    full_name: str = "Dr. Test Provider",
                    ) -> Dict[str, Any]:
    """POST /providers as ClinicAdmin.

    Defaults: epcs_enrolled=true and a non-null dea_number so the
    provider can sign controlled prescriptions out-of-the-box. Tests
    that need an unenrolled provider pass epcs_enrolled=False and
    dea_number=None explicitly.
    """
    payload = create_provider_payload(
        role_type=role_type,
        full_name=full_name,
        specialty=specialty,
        dea_number=dea_number if dea_number is not None
        else random_dea_number(),
        epcs_enrolled=epcs_enrolled,
        panel_cap=panel_cap,
    )
    resp = api_client.create_provider(
        payload, TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


def create_pcp_provider(**overrides: Any) -> Dict[str, Any]:
    """Convenience: PCP-only provider."""
    overrides.setdefault("role_type", "PCP_ONLY")
    return create_provider(**overrides)


def create_specialist_provider(**overrides: Any) -> Dict[str, Any]:
    """Convenience: specialist-only provider."""
    overrides.setdefault("role_type", "SPECIALIST_ONLY")
    overrides.setdefault("specialty", "Cardiology")
    return create_provider(**overrides)


def create_both_role_provider(**overrides: Any) -> Dict[str, Any]:
    """Convenience: BOTH-role provider."""
    overrides.setdefault("role_type", "BOTH")
    overrides.setdefault("specialty", "Internal Medicine")
    return create_provider(**overrides)


# ===========================================================================
# Patients — PRD §3.1.
# ===========================================================================
def create_patient(**overrides: Any) -> Dict[str, Any]:
    """POST /patients as Receptionist."""
    payload = create_patient_payload(**overrides)
    resp = api_client.create_patient(
        payload, TEST_USERS["receptionist_headers"],
    )
    return get_success_data(resp)


def bind_patient_to_pcp(patient_id: str, provider_id: str
                        ) -> Dict[str, Any]:
    """POST /patients/{patient_id}/bind-pcp as Receptionist."""
    resp = api_client.bind_pcp(
        patient_id,
        bind_pcp_payload(provider_id=provider_id),
        TEST_USERS["receptionist_headers"],
    )
    return get_success_data(resp)


def unbind_patient_pcp(patient_id: str) -> Dict[str, Any]:
    """POST /patients/{id}/unbind-pcp as ClinicAdmin (only role
    authorized per PRD §3.1)."""
    resp = api_client.unbind_pcp(
        patient_id, TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


def re_get_patient(patient_id: str,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    """GET /patients/{id} after a mutation, defaulting to receptionist
    headers."""
    headers = headers or TEST_USERS["receptionist_headers"]
    resp = api_client.get_patient(patient_id, headers)
    return get_success_data(resp)


def re_get_provider(provider_id: str,
                    headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    """GET /providers/{id} (used to read derived panel_size)."""
    headers = headers or TEST_USERS["receptionist_headers"]
    resp = api_client.get_provider(provider_id, headers)
    return get_success_data(resp)


def setup_patient_with_pcp(*,
                           role_type: str = "PCP_ONLY",
                           portal_enabled: Optional[bool] = None,
                           smoking_status: Optional[str] = None,
                           chronic_conditions: Optional[List[str]] = None,
                           date_of_birth: str = "1986-01-15",
                           sex_at_birth: str = "MALE",
                           panel_cap: Optional[int] = None,
                           epcs_enrolled: bool = True,
                           ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Provider (PCP) and a Patient, then bind the patient to
    the provider. Returns (patient, provider) where the patient already
    has pcp_provider_id == provider['id']."""
    provider = create_provider(
        role_type=role_type,
        panel_cap=panel_cap,
        epcs_enrolled=epcs_enrolled,
    )
    patient_kwargs: Dict[str, Any] = {
        "date_of_birth": date_of_birth,
        "sex_at_birth": sex_at_birth,
    }
    if portal_enabled is not None:
        patient_kwargs["portal_enabled"] = portal_enabled
    if smoking_status is not None:
        patient_kwargs["smoking_status"] = smoking_status
    if chronic_conditions is not None:
        patient_kwargs["chronic_conditions"] = chronic_conditions
    patient = create_patient(**patient_kwargs)
    patient = bind_patient_to_pcp(patient["id"], provider["id"])
    return patient, provider


# ===========================================================================
# CPT fee catalog — PRD §3.7.
# ===========================================================================
def create_cpt_code_entry(*,
                          cpt_code: Optional[str] = None,
                          list_price_cents: int = TEST_DEFAULTS[
                              "CPT_LIST_PRICE_CENTS"],
                          allowed_price_cents: int = TEST_DEFAULTS[
                              "CPT_ALLOWED_PRICE_CENTS"],
                          is_preventive: Optional[bool] = None,
                          is_telehealth_eligible: Optional[bool] = None,
                          description: str = "Office visit",
                          ) -> Dict[str, Any]:
    """POST /cpt-codes as ClinicAdmin."""
    payload = create_cpt_code_payload(
        cpt_code=cpt_code,
        list_price_cents=list_price_cents,
        allowed_price_cents=allowed_price_cents,
        is_preventive=is_preventive,
        is_telehealth_eligible=is_telehealth_eligible,
        description=description,
    )
    resp = api_client.create_cpt_code(
        payload, TEST_USERS["clinic_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Encounters — PRD §3.3.
# ===========================================================================
def schedule_encounter(patient_id: str, provider_id: str, *,
                       encounter_type: str = "CONSULTATION",
                       scheduled_start: Optional[str] = None,
                       scheduled_end: Optional[str] = None,
                       chief_complaint: Optional[str] = "Routine visit",
                       ) -> Dict[str, Any]:
    """POST /patients/{patient_id}/encounters as Receptionist."""
    payload = create_encounter_payload(
        provider_id=provider_id,
        encounter_type=encounter_type,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        chief_complaint=chief_complaint,
    )
    resp = api_client.create_encounter(
        patient_id, payload, TEST_USERS["receptionist_headers"],
    )
    return get_success_data(resp)


def checkin_encounter(encounter_id: str) -> Dict[str, Any]:
    """POST /encounters/{id}/check-in as Nurse."""
    resp = api_client.checkin_encounter(
        encounter_id, TEST_USERS["nurse_headers"],
    )
    return get_success_data(resp)


def patch_encounter_vitals(encounter_id: str, *,
                           vital_signs: Optional[Dict[str, Any]] = None,
                           chief_complaint: Optional[str] = None,
                           ) -> Dict[str, Any]:
    """PATCH /encounters/{id} as Nurse — populate or revise vital_signs
    / chief_complaint."""
    payload = patch_encounter_payload(
        vital_signs=vital_signs if vital_signs is not None
        else default_vital_signs(),
        chief_complaint=chief_complaint,
    )
    resp = api_client.patch_encounter(
        encounter_id, payload, TEST_USERS["nurse_headers"],
    )
    return get_success_data(resp)


def add_cpt_line_item(encounter_id: str, cpt_code: str, *,
                      units: int = 1,
                      modifier: Optional[str] = None,
                      headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    """POST /encounters/{id}/cpt-line-items as BillingClerk by default.

    PRD §3.3: 'A BillingClerk or Provider may append CPT line items in
    this window.'
    """
    headers = headers or TEST_USERS["billing_clerk_headers"]
    payload = create_cpt_line_item_payload(
        cpt_code=cpt_code, units=units, modifier=modifier,
    )
    resp = api_client.create_cpt_line_item(encounter_id, payload, headers)
    return get_success_data(resp)


def complete_encounter(encounter_id: str, provider_id: str
                       ) -> Dict[str, Any]:
    """POST /encounters/{id}/complete as the encounter's provider.

    PRD §2.1 / §3.3: 'A Provider completes the encounter ... When
    X-User-Role is Provider, X-User-ID is the id of the acting
    Provider; ownership checks on resources that reference a provider
    (for instance, the provider_id on an Encounter ...) compare the
    relevant foreign key to X-User-ID.' We mint Provider headers from
    the encounter's actual provider_id.
    """
    resp = api_client.complete_encounter(
        encounter_id, make_provider_headers(provider_id),
    )
    return get_success_data(resp)


def cancel_encounter(encounter_id: str, provider_id: str
                     ) -> Dict[str, Any]:
    """POST /encounters/{id}/cancel as the encounter's provider.

    Provider is one of the authorized roles per PRD §3.3; we use it
    rather than Receptionist so the same fixture works for both
    SCHEDULED-state cancellations (allowed before scheduled_start) and
    CHECKED_IN-state cancellations (allowed only when there are no
    CptLineItems).
    """
    resp = api_client.cancel_encounter(
        encounter_id, make_provider_headers(provider_id),
    )
    return get_success_data(resp)


def setup_checked_in_encounter(*,
                               encounter_type: str = "CONSULTATION",
                               minutes_after_anchor_start: int = 60,
                               duration_minutes: int = 30,
                               chief_complaint: str = "Routine visit",
                               patient_overrides: Optional[
                                   Dict[str, Any]] = None,
                               ) -> Tuple[Dict[str, Any], Dict[str, Any],
                                          Dict[str, Any]]:
    """Build: clock anchored -> Provider (PCP) -> Patient bound to PCP
    -> Encounter scheduled in the future -> clock advanced to within
    the 30-minute pre-start check-in window -> Encounter CHECKED_IN.

    Returns (patient, provider, encounter).
    """
    anchor_clock()
    pkwargs = dict(patient_overrides or {})
    patient, provider = setup_patient_with_pcp(**pkwargs)
    sched_start = iso_anchor_offset(minutes=minutes_after_anchor_start)
    sched_end = iso_anchor_offset(
        minutes=minutes_after_anchor_start + duration_minutes,
    )
    encounter = schedule_encounter(
        patient["id"], provider["id"],
        encounter_type=encounter_type,
        scheduled_start=sched_start, scheduled_end=sched_end,
        chief_complaint=chief_complaint,
    )
    # Advance the clock to inside the [scheduled_start - 30min,
    # scheduled_start] check-in window.
    advance_clock_to(iso_anchor_offset(
        minutes=minutes_after_anchor_start - 5,
    ))
    encounter = checkin_encounter(encounter["id"])
    return patient, provider, encounter


def setup_completed_encounter(*,
                              encounter_type: str = "CONSULTATION",
                              cpt_code: Optional[str] = None,
                              list_price_cents: int = TEST_DEFAULTS[
                                  "CPT_LIST_PRICE_CENTS"],
                              allowed_price_cents: int = TEST_DEFAULTS[
                                  "CPT_ALLOWED_PRICE_CENTS"],
                              is_preventive: bool = False,
                              units: int = 1,
                              modifier: Optional[str] = None,
                              patient_overrides: Optional[
                                  Dict[str, Any]] = None,
                              ) -> Tuple[Dict[str, Any], Dict[str, Any],
                                         Dict[str, Any], Dict[str, Any],
                                         Dict[str, Any]]:
    """Build: anchored clock -> Patient bound to PCP -> CPT catalog
    entry -> Encounter scheduled / checked-in -> vital_signs PATCHed
    (for PHYSICAL) -> one CptLineItem added -> Encounter COMPLETED.

    Returns (patient, provider, encounter, cpt_entry, line_item).
    """
    patient, provider, encounter = setup_checked_in_encounter(
        encounter_type=encounter_type,
        chief_complaint="Visit complete",
        patient_overrides=patient_overrides,
    )
    cpt_entry = create_cpt_code_entry(
        cpt_code=cpt_code,
        list_price_cents=list_price_cents,
        allowed_price_cents=allowed_price_cents,
        is_preventive=is_preventive,
    )
    if encounter_type == "PHYSICAL":
        # PRD §3.3: PHYSICAL completion requires fully-populated
        # vital_signs.
        encounter = patch_encounter_vitals(encounter["id"])
    line_item = add_cpt_line_item(
        encounter["id"], cpt_entry["cpt_code"],
        units=units, modifier=modifier,
    )
    encounter = complete_encounter(encounter["id"], provider["id"])
    return patient, provider, encounter, cpt_entry, line_item


# ===========================================================================
# Prescriptions — PRD §3.4.
# ===========================================================================
def create_prescription(patient_id: str, provider_id: str,
                        encounter_id: str, *,
                        drug_name: str = "Amoxicillin",
                        is_controlled: bool = False,
                        dea_schedule: Optional[str] = None,
                        refills_authorized: int = 1,
                        dose_mg: float = 500.0,
                        quantity: int = 20,
                        ) -> Dict[str, Any]:
    """POST /patients/{patient_id}/prescriptions as the prescribing
    Provider.

    PRD §3.4: 'The signing Provider must match the prescription's
    recorded provider_id.' Authoring is also a Provider-only action;
    we mint Provider headers from the authoring provider's id so
    ownership-gated state transitions later (sign / transmit / cancel)
    can reuse the same id.
    """
    payload = create_prescription_payload(
        provider_id=provider_id,
        encounter_id=encounter_id,
        drug_name=drug_name,
        is_controlled=is_controlled,
        dea_schedule=dea_schedule,
        refills_authorized=refills_authorized,
        dose_mg=dose_mg,
        quantity=quantity,
    )
    resp = api_client.create_prescription(
        patient_id, payload, make_provider_headers(provider_id),
    )
    return get_success_data(resp)


def sign_prescription(prescription_id: str, provider_id: str, *,
                      epcs_two_factor_token: Optional[str] = None,
                      ) -> Dict[str, Any]:
    """POST /prescriptions/{id}/sign as the authoring Provider."""
    payload = sign_prescription_payload(
        epcs_two_factor_token=epcs_two_factor_token,
    )
    resp = api_client.sign_prescription(
        prescription_id, make_provider_headers(provider_id), payload,
    )
    return get_success_data(resp)


def transmit_prescription(prescription_id: str, provider_id: str
                          ) -> Dict[str, Any]:
    """POST /prescriptions/{id}/transmit as the authoring Provider."""
    resp = api_client.transmit_prescription(
        prescription_id, make_provider_headers(provider_id),
    )
    return get_success_data(resp)


def dispense_prescription(prescription_id: str,
                          pharmacist_headers: Optional[
                              Dict[str, str]] = None,
                          ) -> Dict[str, Any]:
    """POST /prescriptions/{id}/dispense as Pharmacist.

    PRD §2.12: the dispenser's X-User-ID must not equal the
    prescription's recorded provider_id. The default
    TEST_USERS['pharmacist_headers'] is a deliberately distinct opaque
    id, so the SoD check passes by default.
    """
    headers = pharmacist_headers or TEST_USERS["pharmacist_headers"]
    resp = api_client.dispense_prescription(prescription_id, headers)
    return get_success_data(resp)


def cancel_prescription(prescription_id: str, provider_id: str
                        ) -> Dict[str, Any]:
    """POST /prescriptions/{id}/cancel as the authoring Provider."""
    resp = api_client.cancel_prescription(
        prescription_id, make_provider_headers(provider_id),
    )
    return get_success_data(resp)


def re_get_prescription(prescription_id: str, provider_id: str
                        ) -> Dict[str, Any]:
    """GET /prescriptions/{id} as the authoring Provider."""
    resp = api_client.get_prescription(
        prescription_id, make_provider_headers(provider_id),
    )
    return get_success_data(resp)


# ===========================================================================
# Referrals — PRD §3.5.
# ===========================================================================
def create_referral(patient_id: str, *,
                    referring_provider_id: str,
                    referred_to_provider_id: str,
                    encounter_id: str,
                    reason: str = "Specialist consultation",
                    priority: Optional[str] = None,
                    ) -> Dict[str, Any]:
    """POST /patients/{patient_id}/referrals as the referring Provider
    (PCP)."""
    payload = create_referral_payload(
        referring_provider_id=referring_provider_id,
        referred_to_provider_id=referred_to_provider_id,
        encounter_id=encounter_id,
        reason=reason,
        priority=priority,
    )
    resp = api_client.create_referral(
        patient_id, payload,
        make_provider_headers(referring_provider_id),
    )
    return get_success_data(resp)


def accept_referral(referral_id: str,
                    referred_to_provider_id: str,
                    *,
                    response_note: Optional[str] = None,
                    ) -> Dict[str, Any]:
    """POST /referrals/{id}/accept as the referred-to specialist."""
    payload = referral_action_payload(response_note=response_note)
    resp = api_client.accept_referral(
        referral_id,
        make_provider_headers(referred_to_provider_id),
        payload,
    )
    return get_success_data(resp)


def return_referral_to_pcp(referral_id: str,
                           referred_to_provider_id: str,
                           ) -> Dict[str, Any]:
    """POST /referrals/{id}/return-to-pcp as the specialist."""
    resp = api_client.return_referral_to_pcp(
        referral_id, make_provider_headers(referred_to_provider_id),
    )
    return get_success_data(resp)


# ===========================================================================
# Portal messages — PRD §3.6.
# ===========================================================================
def post_portal_message_as_patient(patient_id: str, provider_id: str,
                                   *,
                                   body: str = "Hello provider.",
                                   ) -> Dict[str, Any]:
    """POST /portal/messages as the patient themselves.

    PRD §2.1: PatientPortalUser X-User-ID == Patient.id. PRD §2.12:
    Patient.portal_enabled must be true for portal write operations.
    Callers must ensure the patient was created with
    portal_enabled=True.
    """
    payload = create_portal_message_payload(
        patient_id=patient_id,
        provider_id=provider_id,
        body=body,
    )
    resp = api_client.create_portal_message(
        payload, make_patient_portal_headers(patient_id),
    )
    return get_success_data(resp)


# ===========================================================================
# DIFFICULTY-DESIGN composite fixtures — pre-built setups for the
# scaffold_difficulty_design instances that need state several API
# calls deep.
# ===========================================================================
def setup_billing_dual_variant_encounter() -> Dict[str, Any]:
    """For 'cpt_billing_charge_vs_allowed_on_encounter' (dual-variant).

    Builds: anchored clock -> PCP -> Patient bound -> CPT 99213 (list
    12000, allowed 8000) -> CPT 90471 (list 3000, allowed 2000) ->
    Encounter (CONSULTATION) checked-in -> CptLineItem(99213, units=1,
    modifier='25') -> CptLineItem(90471, units=2) -> Encounter
    COMPLETED.

    Returns a dict with keys: patient, provider, encounter, cpt_a (the
    99213 catalog row), cpt_b (the 90471 catalog row), line_a, line_b.
    Line dicts are the post-creation snapshots; the test re-fetches
    after completion to get allowed_amount_cents.
    """
    patient, provider, encounter = setup_checked_in_encounter(
        encounter_type="CONSULTATION",
        chief_complaint="Billing test",
    )
    cpt_a = create_cpt_code_entry(
        cpt_code="99213",
        list_price_cents=12000,
        allowed_price_cents=8000,
    )
    cpt_b = create_cpt_code_entry(
        cpt_code="90471",
        list_price_cents=3000,
        allowed_price_cents=2000,
    )
    line_a = add_cpt_line_item(
        encounter["id"], "99213", units=1, modifier="25",
    )
    line_b = add_cpt_line_item(
        encounter["id"], "90471", units=2,
    )
    encounter = complete_encounter(encounter["id"], provider["id"])
    return {
        "patient": patient, "provider": provider,
        "encounter": encounter,
        "cpt_a": cpt_a, "cpt_b": cpt_b,
        "line_a": line_a, "line_b": line_b,
    }


def setup_billing_apportion_residual_encounter() -> Dict[str, Any]:
    """For 'cpt_billing_allowed_round_per_line_then_apportion'.

    Builds: encounter with three CPT lines whose pre-tier allowed
    values are 33334, 33333, 33335 (summing to 99999, tier-3 territory
    at >200000? No — total is 99999 which is in tier-2 band 50001..
    200000 — factor 0.95). After completion the three lines'
    allowed_amount_cents should be 31667, 31666, 31669 with residual
    +1 cent assigned to the line with the greatest pre-apportion
    per_line_cents (cpt C, allowed 33335).

    Returns a dict with the encounter and a list of (cpt_code, units,
    catalog row, line row) tuples for the three lines.
    """
    patient, provider, encounter = setup_checked_in_encounter(
        encounter_type="CONSULTATION",
        chief_complaint="Apportion test",
    )
    cpt_a = create_cpt_code_entry(
        cpt_code="11111",
        list_price_cents=33334,
        allowed_price_cents=33334,
    )
    cpt_b = create_cpt_code_entry(
        cpt_code="11112",
        list_price_cents=33333,
        allowed_price_cents=33333,
    )
    cpt_c = create_cpt_code_entry(
        cpt_code="11113",
        list_price_cents=33335,
        allowed_price_cents=33335,
    )
    line_a = add_cpt_line_item(encounter["id"], "11111", units=1)
    line_b = add_cpt_line_item(encounter["id"], "11112", units=1)
    line_c = add_cpt_line_item(encounter["id"], "11113", units=1)
    encounter = complete_encounter(encounter["id"], provider["id"])
    return {
        "patient": patient, "provider": provider,
        "encounter": encounter,
        "cpt_a": cpt_a, "cpt_b": cpt_b, "cpt_c": cpt_c,
        "line_a": line_a, "line_b": line_b, "line_c": line_c,
    }


def setup_three_prescriptions_for_expiry(*,
                                         provider: Optional[
                                             Dict[str, Any]] = None,
                                         patient: Optional[
                                             Dict[str, Any]] = None,
                                         ) -> Dict[str, Any]:
    """For 'prescription_expiry_tiered_branching_three_inputs'.

    Builds three DRAFT prescriptions on the same patient/encounter:
    one non-controlled (refills=2), one schedule IV (refills=2), one
    schedule II (refills=0). All ready to sign.
    """
    if patient is None or provider is None:
        patient, provider, encounter = setup_checked_in_encounter(
            encounter_type="CONSULTATION",
            chief_complaint="Tri-rx",
        )
    else:
        # Caller supplied existing patient/provider — schedule a new
        # encounter rather than reusing an arbitrary one.
        anchor_clock()
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        encounter = schedule_encounter(
            patient["id"], provider["id"],
            encounter_type="CONSULTATION",
            scheduled_start=sched_start, scheduled_end=sched_end,
            chief_complaint="Tri-rx",
        )
        advance_clock_to(iso_anchor_offset(minutes=55))
        encounter = checkin_encounter(encounter["id"])

    rx_nc = create_prescription(
        patient["id"], provider["id"], encounter["id"],
        drug_name="Amoxicillin", is_controlled=False,
        refills_authorized=2,
    )
    rx_iv = create_prescription(
        patient["id"], provider["id"], encounter["id"],
        drug_name="Alprazolam", is_controlled=True,
        dea_schedule="IV", refills_authorized=2,
    )
    rx_ii = create_prescription(
        patient["id"], provider["id"], encounter["id"],
        drug_name="Oxycodone", is_controlled=True,
        dea_schedule="II", refills_authorized=0,
    )
    return {
        "patient": patient, "provider": provider,
        "encounter": encounter,
        "rx_nc": rx_nc, "rx_iv": rx_iv, "rx_ii": rx_ii,
    }


def setup_referral_for_cycle() -> Dict[str, Any]:
    """For 'referral_cyclic_accepted_to_pending'.

    Builds: anchored clock -> PCP (PR1) -> Specialist (PR2, BOTH) ->
    Patient bound to PR1 -> Encounter E1 COMPLETED on PR1 (with a CPT
    line item) -> Referral R (ROUTINE) on E1 to PR2.

    Returns patient, pcp, specialist, encounter, referral.
    """
    anchor_clock()
    pcp = create_pcp_provider()
    specialist = create_both_role_provider(specialty="Cardiology")
    patient = create_patient()
    patient = bind_patient_to_pcp(patient["id"], pcp["id"])
    # Encounter on PCP, must complete before issuing the referral.
    sched_start = iso_anchor_offset(minutes=60)
    sched_end = iso_anchor_offset(minutes=90)
    encounter = schedule_encounter(
        patient["id"], pcp["id"],
        encounter_type="CONSULTATION",
        scheduled_start=sched_start, scheduled_end=sched_end,
        chief_complaint="PCP visit",
    )
    advance_clock_to(iso_anchor_offset(minutes=55))
    encounter = checkin_encounter(encounter["id"])
    cpt_entry = create_cpt_code_entry(
        cpt_code="99201",
        list_price_cents=10000,
        allowed_price_cents=8000,
    )
    add_cpt_line_item(encounter["id"], cpt_entry["cpt_code"], units=1)
    encounter = complete_encounter(encounter["id"], pcp["id"])
    referral = create_referral(
        patient["id"],
        referring_provider_id=pcp["id"],
        referred_to_provider_id=specialist["id"],
        encounter_id=encounter["id"],
        reason="Cardiology eval",
        priority="ROUTINE",
    )
    return {
        "patient": patient, "pcp": pcp, "specialist": specialist,
        "encounter": encounter, "referral": referral,
    }


def setup_portal_message_for_parallel_dimensions() -> Dict[str, Any]:
    """For 'portal_message_parallel_status_and_triage_dimensions'.

    Builds: anchored clock -> PCP -> Patient (portal_enabled=true)
    bound to PCP -> PatientPortalUser posts a PortalMessage M
    (sender_role=PATIENT) to PCP.

    Returns patient, provider, message.
    """
    anchor_clock()
    patient, provider = setup_patient_with_pcp(portal_enabled=True)
    message = post_portal_message_as_patient(
        patient["id"], provider["id"],
        body="Question about my medication.",
    )
    return {
        "patient": patient, "provider": provider, "message": message,
    }


def setup_encounter_with_preventive_lines(*,
                                          patient_dob: str = "1995-06-15",
                                          ) -> Dict[str, Any]:
    """For 'encounter_complete_to_cpt_allowed_to_hedis_snapshot'.

    Builds: anchored clock at 2026-06-15T10:00:00Z -> Patient (age 30
    in 2026), ACTIVE, no chronic -> PCP bound -> CPT 99395 (preventive
    true), CPT 99213 (preventive false) -> Encounter (PHYSICAL),
    checked-in with vital_signs PATCHed -> both line items added ->
    encounter NOT YET completed.

    Returns patient, provider, encounter, cpt_99395, cpt_99213.
    """
    anchor_clock()
    advance_clock_to("2026-06-15T10:00:00.000Z")
    patient, provider = setup_patient_with_pcp(
        date_of_birth=patient_dob,
        sex_at_birth="FEMALE",
    )
    sched_start = "2026-06-15T11:00:00.000Z"
    sched_end = "2026-06-15T11:30:00.000Z"
    encounter = schedule_encounter(
        patient["id"], provider["id"],
        encounter_type="PHYSICAL",
        scheduled_start=sched_start, scheduled_end=sched_end,
        chief_complaint="Annual wellness exam",
    )
    advance_clock_to("2026-06-15T10:50:00.000Z")
    encounter = checkin_encounter(encounter["id"])
    encounter = patch_encounter_vitals(encounter["id"])
    cpt_99395 = create_cpt_code_entry(
        cpt_code="99395",
        list_price_cents=20000,
        allowed_price_cents=15000,
        is_preventive=True,
        description="Preventive medicine annual",
    )
    cpt_99213 = create_cpt_code_entry(
        cpt_code="99213",
        list_price_cents=12000,
        allowed_price_cents=8000,
        is_preventive=False,
        description="Office visit established",
    )
    add_cpt_line_item(encounter["id"], "99395", units=1)
    add_cpt_line_item(encounter["id"], "99213", units=1)
    return {
        "patient": patient, "provider": provider,
        "encounter": encounter,
        "cpt_99395": cpt_99395, "cpt_99213": cpt_99213,
    }


def setup_checked_in_with_draft_prescriptions() -> Dict[str, Any]:
    """For 'encounter_cancel_to_draft_prescription_cancel'.

    Builds: Patient bound to PCP -> Encounter E1 CHECKED_IN with NO
    line items -> two DRAFT prescriptions RX1 and RX2 on E1.
    Additionally, builds a separate TRANSMITTED prescription RX3 on a
    DIFFERENT encounter (E_OTHER, COMPLETED) so the test can verify
    cascade scope.

    Returns patient, provider, encounter, rx1, rx2, other_encounter,
    rx3.
    """
    anchor_clock()
    patient, provider = setup_patient_with_pcp()
    # First encounter — completes so we can sign/transmit RX3.
    sched_start_a = iso_anchor_offset(minutes=60)
    sched_end_a = iso_anchor_offset(minutes=90)
    e_other = schedule_encounter(
        patient["id"], provider["id"],
        encounter_type="CONSULTATION",
        scheduled_start=sched_start_a, scheduled_end=sched_end_a,
        chief_complaint="First visit",
    )
    advance_clock_to(iso_anchor_offset(minutes=55))
    e_other = checkin_encounter(e_other["id"])
    rx3 = create_prescription(
        patient["id"], provider["id"], e_other["id"],
        drug_name="Lisinopril", is_controlled=False,
        refills_authorized=0,
    )
    rx3 = sign_prescription(rx3["id"], provider["id"])
    rx3 = transmit_prescription(rx3["id"], provider["id"])
    cpt_entry = create_cpt_code_entry(
        cpt_code="99202",
        list_price_cents=11000,
        allowed_price_cents=9000,
    )
    add_cpt_line_item(e_other["id"], cpt_entry["cpt_code"], units=1)
    e_other = complete_encounter(e_other["id"], provider["id"])
    # Second encounter — CHECKED_IN with no line items.
    sched_start_b = iso_anchor_offset(minutes=180)
    sched_end_b = iso_anchor_offset(minutes=210)
    encounter = schedule_encounter(
        patient["id"], provider["id"],
        encounter_type="CONSULTATION",
        scheduled_start=sched_start_b, scheduled_end=sched_end_b,
        chief_complaint="Follow-up visit",
    )
    advance_clock_to(iso_anchor_offset(minutes=175))
    encounter = checkin_encounter(encounter["id"])
    rx1 = create_prescription(
        patient["id"], provider["id"], encounter["id"],
        drug_name="Ibuprofen", is_controlled=False,
        refills_authorized=2,
    )
    rx2 = create_prescription(
        patient["id"], provider["id"], encounter["id"],
        drug_name="Metformin", is_controlled=False,
        refills_authorized=3,
    )
    return {
        "patient": patient, "provider": provider,
        "encounter": encounter, "rx1": rx1, "rx2": rx2,
        "other_encounter": e_other, "rx3": rx3,
    }


def setup_signed_prescription_for_state_vs_safety() -> Dict[str, Any]:
    """For 'state_vs_business_safety_on_prescription_sign'.

    Builds: anchored clock -> PCP-Provider PR_OK (epcs_enrolled=true,
    dea set) -> Patient bound -> Encounter CHECKED_IN -> Prescription
    RX (non-controlled, refills=0) -> RX signed by PR_OK so it is in
    SIGNED.

    Separately, also creates Provider PR_UNENROLLED (epcs_enrolled=
    false, dea=null). The test then attempts to sign RX again as
    PR_UNENROLLED — the state check fires first (RX no longer DRAFT)
    yielding ERR_INVALID_PRESCRIPTION_STATE rather than
    ERR_EPCS_NOT_ENROLLED.

    Returns patient, pr_ok, pr_unenrolled, encounter, rx.
    """
    anchor_clock()
    pr_ok = create_provider(
        role_type="PCP_ONLY", epcs_enrolled=True,
    )
    pr_unenrolled = create_provider(
        role_type="PCP_ONLY", epcs_enrolled=False, dea_number=None,
    )
    patient = create_patient()
    patient = bind_patient_to_pcp(patient["id"], pr_ok["id"])
    sched_start = iso_anchor_offset(minutes=60)
    sched_end = iso_anchor_offset(minutes=90)
    encounter = schedule_encounter(
        patient["id"], pr_ok["id"],
        encounter_type="CONSULTATION",
        scheduled_start=sched_start, scheduled_end=sched_end,
        chief_complaint="Visit",
    )
    advance_clock_to(iso_anchor_offset(minutes=55))
    encounter = checkin_encounter(encounter["id"])
    rx = create_prescription(
        patient["id"], pr_ok["id"], encounter["id"],
        drug_name="Atorvastatin", is_controlled=False,
        refills_authorized=0,
    )
    rx = sign_prescription(rx["id"], pr_ok["id"])
    return {
        "patient": patient, "pr_ok": pr_ok,
        "pr_unenrolled": pr_unenrolled,
        "encounter": encounter, "rx": rx,
    }


def setup_two_patients_for_cbp_boundary() -> Dict[str, Any]:
    """For 'hedis_cbp_systolic_140_exclusive_boundary'.

    Builds: clock at 2026-12-31T12:00:00Z -> PCP -> two Patients age 50
    sex MALE with chronic_conditions=['I10'] -> bind both -> Encounter
    EA COMPLETED on P_A with vital_signs bp_systolic=139, bp_diastolic
    =89 (passes numerator), Encounter EB COMPLETED on P_B with
    bp_systolic=140, bp_diastolic=89 (fails numerator).

    Returns patient_a, patient_b, provider.
    """
    anchor_clock()
    advance_clock_to("2026-06-15T10:00:00.000Z")
    provider = create_pcp_provider()

    patient_a = create_patient(
        date_of_birth="1976-06-15",  # 50 in 2026
        sex_at_birth="MALE",
        chronic_conditions=["I10"],
    )
    patient_a = bind_patient_to_pcp(patient_a["id"], provider["id"])
    patient_b = create_patient(
        date_of_birth="1976-06-15",
        sex_at_birth="MALE",
        chronic_conditions=["I10"],
    )
    patient_b = bind_patient_to_pcp(patient_b["id"], provider["id"])

    cpt_entry = create_cpt_code_entry(
        cpt_code="99214",
        list_price_cents=15000,
        allowed_price_cents=12000,
    )

    def _complete_physical(patient_id: str, systolic: int,
                           diastolic: int, time_min: int) -> Dict[str, Any]:
        sched_start = iso_anchor_offset(minutes=time_min)
        sched_end = iso_anchor_offset(minutes=time_min + 30)
        enc = schedule_encounter(
            patient_id, provider["id"],
            encounter_type="PHYSICAL",
            scheduled_start=sched_start, scheduled_end=sched_end,
            chief_complaint="CBP measurement",
        )
        advance_clock_to(iso_anchor_offset(minutes=time_min - 5))
        enc = checkin_encounter(enc["id"])
        enc = patch_encounter_vitals(
            enc["id"], vital_signs=default_vital_signs(
                bp_systolic=systolic, bp_diastolic=diastolic,
            ),
        )
        add_cpt_line_item(enc["id"], cpt_entry["cpt_code"], units=1)
        enc = complete_encounter(enc["id"], provider["id"])
        return enc

    encounter_a = _complete_physical(
        patient_a["id"], systolic=139, diastolic=89, time_min=60,
    )
    encounter_b = _complete_physical(
        patient_b["id"], systolic=140, diastolic=89, time_min=240,
    )
    advance_clock_to("2026-12-31T12:00:00.000Z")
    return {
        "patient_a": patient_a, "patient_b": patient_b,
        "provider": provider,
        "encounter_a": encounter_a, "encounter_b": encounter_b,
    }


def setup_patient_for_tsc_provisional_vs_final() -> Dict[str, Any]:
    """For 'hedis_provisional_ytd_vs_final_year_end_on_patient'.

    Builds: clock at 2026-11-15T12:00:00Z -> Patient age 40,
    smoking_status=CURRENT, ACTIVE -> PCP bound -> one COMPLETED
    CONSULTATION in 2026 with a non-99406/99407 CPT line.

    Returns patient, provider, encounter.
    """
    anchor_clock()
    advance_clock_to("2026-06-15T10:00:00.000Z")
    provider = create_pcp_provider()
    patient = create_patient(
        date_of_birth="1986-06-15",  # 40 in 2026
        sex_at_birth="MALE",
        smoking_status="CURRENT",
    )
    patient = bind_patient_to_pcp(patient["id"], provider["id"])
    sched_start = iso_anchor_offset(minutes=60)
    sched_end = iso_anchor_offset(minutes=90)
    encounter = schedule_encounter(
        patient["id"], provider["id"],
        encounter_type="CONSULTATION",
        scheduled_start=sched_start, scheduled_end=sched_end,
        chief_complaint="TSC test",
    )
    advance_clock_to(iso_anchor_offset(minutes=55))
    encounter = checkin_encounter(encounter["id"])
    cpt_entry = create_cpt_code_entry(
        cpt_code="99213",
        list_price_cents=12000,
        allowed_price_cents=8000,
    )
    add_cpt_line_item(encounter["id"], cpt_entry["cpt_code"], units=1)
    encounter = complete_encounter(encounter["id"], provider["id"])
    advance_clock_to("2026-11-15T12:00:00.000Z")
    return {
        "patient": patient, "provider": provider, "encounter": encounter,
    }


def setup_panel_with_n_active_patients(*, n: int = 3,
                                       panel_cap: int = 2000,
                                       ) -> Dict[str, Any]:
    """For 'pcp_bind_unbind_panel_size_invariant'.

    Build a PCP provider and bind `n` active patients to them.
    Returns provider, patients (list of bound patient dicts).
    """
    provider = create_pcp_provider(panel_cap=panel_cap)
    patients: List[Dict[str, Any]] = []
    for _ in range(n):
        p = create_patient()
        p = bind_patient_to_pcp(p["id"], provider["id"])
        patients.append(p)
    return {"provider": provider, "patients": patients}


def setup_signed_then_transmitted_prescription_for_dispense_invariant(
) -> Dict[str, Any]:
    """For 'prescription_refills_remaining_dispense_cancel_invariant'.

    Builds: Patient bound to PCP -> Encounter CHECKED_IN -> RX
    (non-controlled, refills_authorized=2) -> SIGN -> TRANSMIT, so
    refills_remaining starts at 2 and the prescription is ready to
    dispense.

    Returns patient, provider, encounter, rx.
    """
    anchor_clock()
    patient, provider, encounter = setup_checked_in_encounter(
        encounter_type="CONSULTATION",
        chief_complaint="RX visit",
    )
    rx = create_prescription(
        patient["id"], provider["id"], encounter["id"],
        drug_name="Metoprolol", is_controlled=False,
        refills_authorized=2,
    )
    rx = sign_prescription(rx["id"], provider["id"])
    rx = transmit_prescription(rx["id"], provider["id"])
    return {
        "patient": patient, "provider": provider,
        "encounter": encounter, "rx": rx,
    }


def setup_inactive_patient_for_checkin_block() -> Dict[str, Any]:
    """For 'encounter_checkin_requires_patient_and_provider_active'.

    Builds: Patient bound -> Encounter SCHEDULED for now+10min ->
    clock advanced to within the check-in window. Patient is left in
    ACTIVE — the consuming test must flip Patient.status to INACTIVE
    by whatever mechanism the PRD allows (PRD §3.1: status is system-
    managed and not client-mutable; the test should instead drive
    INACTIVE via the documented panel-recompute pathway or, if not
    expressible from the API surface, skip).

    Returns patient, provider, encounter — and the clock is positioned
    so a check-in attempt would otherwise succeed.
    """
    anchor_clock()
    patient, provider = setup_patient_with_pcp()
    sched_start = iso_anchor_offset(minutes=60)
    sched_end = iso_anchor_offset(minutes=90)
    encounter = schedule_encounter(
        patient["id"], provider["id"],
        encounter_type="CONSULTATION",
        scheduled_start=sched_start, scheduled_end=sched_end,
        chief_complaint="Checkin block test",
    )
    advance_clock_to(iso_anchor_offset(minutes=55))
    return {
        "patient": patient, "provider": provider, "encounter": encounter,
    }


def setup_scheduled_encounter_for_rx_state_dependency() -> Dict[str, Any]:
    """For 'prescription_sign_requires_encounter_active'.

    Builds: Patient bound -> PCP -> Encounter SCHEDULED (NOT yet
    checked-in). A test then creates a DRAFT prescription referencing
    this encounter and attempts to SIGN — expected to be rejected with
    ERR_INVALID_PRESCRIPTION_STATE because the encounter is neither
    CHECKED_IN nor COMPLETED.

    Returns patient, provider, encounter.
    """
    anchor_clock()
    patient, provider = setup_patient_with_pcp()
    sched_start = iso_anchor_offset(hours=2)
    sched_end = iso_anchor_offset(hours=2, minutes=30)
    encounter = schedule_encounter(
        patient["id"], provider["id"],
        encounter_type="CONSULTATION",
        scheduled_start=sched_start, scheduled_end=sched_end,
        chief_complaint="Pre-checkin",
    )
    return {
        "patient": patient, "provider": provider, "encounter": encounter,
    }


def setup_existing_provider_encounter_for_overlap(
    *,
    start_iso: str = "2026-07-01T10:00:00.000Z",
    end_iso: str = "2026-07-01T10:30:00.000Z",
) -> Dict[str, Any]:
    """For 'provider_closed_open_overlap'.

    Builds: anchored clock -> PCP -> two Patients bound to PCP ->
    existing SCHEDULED Encounter EA on PCP from start_iso..end_iso.
    The test can then attempt to schedule additional encounters
    against the same Provider to probe boundary semantics.
    """
    anchor_clock()
    provider = create_pcp_provider()
    p_x = create_patient()
    p_x = bind_patient_to_pcp(p_x["id"], provider["id"])
    p_y = create_patient()
    # bind_patient_to_pcp would fail with ERR_PCP_ALREADY_BOUND on a
    # different provider — for this overlap test we don't need P_Y
    # bound to provider; the rule keys off provider_id on the
    # encounter, not on PCP binding. Leave P_Y unbound.
    ea = schedule_encounter(
        p_x["id"], provider["id"],
        encounter_type="CONSULTATION",
        scheduled_start=start_iso, scheduled_end=end_iso,
        chief_complaint="EA",
    )
    return {
        "provider": provider, "patient_x": p_x, "patient_y": p_y,
        "encounter_a": ea,
    }


def setup_existing_patient_encounter_for_buffer(
    *,
    start_iso: str = "2026-07-01T10:00:00.000Z",
    end_iso: str = "2026-07-01T10:30:00.000Z",
) -> Dict[str, Any]:
    """For 'patient_closed_closed_15min_buffer_overlap'.

    Builds: anchored clock -> Provider PR1 (PCP) -> Provider PR2
    (BOTH) -> Patient P bound to PR1 -> existing SCHEDULED Encounter
    EA for PR1 on P from start_iso..end_iso.

    Returns provider_a (PR1), provider_b (PR2), patient, encounter_a.
    """
    anchor_clock()
    pr1 = create_pcp_provider()
    pr2 = create_both_role_provider()
    patient = create_patient()
    patient = bind_patient_to_pcp(patient["id"], pr1["id"])
    ea = schedule_encounter(
        patient["id"], pr1["id"],
        encounter_type="CONSULTATION",
        scheduled_start=start_iso, scheduled_end=end_iso,
        chief_complaint="EA",
    )
    return {
        "provider_a": pr1, "provider_b": pr2,
        "patient": patient, "encounter_a": ea,
    }


def setup_existing_provider_encounter_for_priority_pair(
) -> Dict[str, Any]:
    """For 'business_referential_vs_business_temporal_on_referral_create'
    (re-cast as ERR_INVALID_TIME_RANGE vs ERR_PROVIDER_TIME_CONFLICT on
    /encounters create).

    Builds: clock at 2026-06-01T08:00:00Z -> PCP -> Patient bound to
    PCP -> existing SCHEDULED Encounter E0 for PCP at
    2026-06-01T10:00..10:30. The test then attempts to schedule a
    NEW encounter at start==end (invalid time range) AND inside the
    existing window: priority-12 ERR_INVALID_TIME_RANGE should win
    over priority-13 ERR_PROVIDER_TIME_CONFLICT.

    Returns provider, patient, encounter_zero.
    """
    anchor_clock()
    advance_clock_to("2026-06-01T08:00:00.000Z")
    provider = create_pcp_provider()
    patient = create_patient()
    patient = bind_patient_to_pcp(patient["id"], provider["id"])
    e0 = schedule_encounter(
        patient["id"], provider["id"],
        encounter_type="CONSULTATION",
        scheduled_start="2026-06-01T10:00:00.000Z",
        scheduled_end="2026-06-01T10:30:00.000Z",
        chief_complaint="E0",
    )
    return {"provider": provider, "patient": patient, "encounter_zero": e0}


__all__ = [
    # clock
    "anchor_clock",
    "advance_clock_to",
    "advance_clock_seconds",
    "run_sweep",
    # providers
    "create_provider",
    "create_pcp_provider",
    "create_specialist_provider",
    "create_both_role_provider",
    # patients
    "create_patient",
    "bind_patient_to_pcp",
    "unbind_patient_pcp",
    "re_get_patient",
    "re_get_provider",
    "setup_patient_with_pcp",
    # catalog
    "create_cpt_code_entry",
    # encounters
    "schedule_encounter",
    "checkin_encounter",
    "patch_encounter_vitals",
    "add_cpt_line_item",
    "complete_encounter",
    "cancel_encounter",
    "setup_checked_in_encounter",
    "setup_completed_encounter",
    # prescriptions
    "create_prescription",
    "sign_prescription",
    "transmit_prescription",
    "dispense_prescription",
    "cancel_prescription",
    "re_get_prescription",
    # referrals
    "create_referral",
    "accept_referral",
    "return_referral_to_pcp",
    # portal
    "post_portal_message_as_patient",
    # difficulty-design composite fixtures
    "setup_billing_dual_variant_encounter",
    "setup_billing_apportion_residual_encounter",
    "setup_three_prescriptions_for_expiry",
    "setup_referral_for_cycle",
    "setup_portal_message_for_parallel_dimensions",
    "setup_encounter_with_preventive_lines",
    "setup_checked_in_with_draft_prescriptions",
    "setup_signed_prescription_for_state_vs_safety",
    "setup_two_patients_for_cbp_boundary",
    "setup_patient_for_tsc_provisional_vs_final",
    "setup_panel_with_n_active_patients",
    "setup_signed_then_transmitted_prescription_for_dispense_invariant",
    "setup_inactive_patient_for_checkin_block",
    "setup_scheduled_encounter_for_rx_state_dependency",
    "setup_existing_provider_encounter_for_overlap",
    "setup_existing_patient_encounter_for_buffer",
    "setup_existing_provider_encounter_for_priority_pair",
]
