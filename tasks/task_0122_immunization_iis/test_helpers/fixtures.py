"""Composite setup helpers - multi-step preambles that tests reuse.

The immunization workflow is long: register Patient -> register
ProviderOrganization -> register VaccineProduct -> create AntigenScheduleRule
-> register VaccineLot -> schedule dose -> administer dose -> ... ->
certificate flow / adverse event flow / recall cascade. Most
interesting test claims need the system in a late-pipeline state, and
several difficulty-design instances demand cross-entity state combos
that require dozens of API calls to construct.

PRD §2.1: all four roles are opaque. The fixtures here pass explicit
clinician ids into the schedule-dose payload's
administering_clinician_id so the downstream SoD check on AdverseEvent
(PRD §3.9) has a well-defined value to compare against.

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    administer_dose_payload,
    clock_advance_payload,
    conclude_review_payload,
    create_adverse_event_payload,
    create_allergy_payload,
    create_antigen_schedule_rule_payload,
    create_certificate_payload,
    create_patient_payload,
    create_provider_organization_payload,
    create_vaccine_lot_payload,
    create_vaccine_product_payload,
    invalidate_dose_payload,
    iso_anchor_offset,
    iso_utc,
    parse_anchor,
    parse_iso,
    recall_payload,
    schedule_dose_payload,
    submit_vaers_payload,
    vaers_ack_payload,
)
from .test_users import (
    PROVIDER_CLINICIAN_ID,
    PROVIDER_CLINICIAN_ID_ALT,
    REVIEWING_CLINICIAN_ID,
    TEST_USERS,
    make_provider_clinician_headers,
    make_reviewing_clinician_headers,
)


# ===========================================================================
# Clock helpers - PRD §2.10 / §4.
# ===========================================================================
def anchor_clock(to_timestamp: Optional[str] = None) -> Dict[str, Any]:
    """Pin the server clock to the deterministic test anchor.

    PRD §2.10: 'The first advances the server's logical clock to a
    supplied to_timestamp.' Restricted to PublicHealthOfficer.

    We default to CLOCK_ANCHOR + 1 day so that admin times computed via
    iso_anchor_offset() (which is anchored at the un-offset
    CLOCK_ANCHOR) are reliably in the past relative to the server's
    current time, satisfying PRD §3.3's "at most the server's current
    time" rule. Any test that needs a different anchor passes an
    explicit ``to_timestamp``.
    """
    if to_timestamp is None:
        target = iso_utc(parse_anchor() + timedelta(days=1))
    else:
        target = to_timestamp
    resp = api_client.clock_advance(
        clock_advance_payload(to_timestamp=target),
        TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def advance_clock_to(iso_timestamp: str) -> Dict[str, Any]:
    """POST /_clock/advance with an absolute target."""
    resp = api_client.clock_advance(
        clock_advance_payload(to_timestamp=iso_timestamp),
        TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1 - basic entity creators.
# ===========================================================================
def create_patient(date_of_birth: str = "2020-01-01",
                   medical_exemption_on_file: bool = False,
                   **overrides: Any) -> Dict[str, Any]:
    """Register a Patient. PRD §3.1."""
    payload = create_patient_payload(
        date_of_birth=date_of_birth,
        medical_exemption_on_file=medical_exemption_on_file,
        **overrides,
    )
    resp = api_client.create_patient(
        payload, TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def create_provider_organization(**overrides: Any) -> Dict[str, Any]:
    """Register a ProviderOrganization. PRD §3.2."""
    payload = create_provider_organization_payload(**overrides)
    resp = api_client.create_provider_organization(
        payload, TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def create_vaccine_product(antigens: Optional[List[str]] = None,
                           min_age_days: int = 0,
                           max_age_days: Optional[int] = 2555,
                           contraindication_flags: Optional[List[str]] = None,
                           **overrides: Any) -> Dict[str, Any]:
    """Register a VaccineProduct. PRD §3.2."""
    payload = create_vaccine_product_payload(
        antigens=antigens if antigens is not None else ["MMR_MEASLES"],
        min_age_days=min_age_days,
        max_age_days=max_age_days,
        contraindication_flags=(contraindication_flags
                                if contraindication_flags is not None
                                else []),
        **overrides,
    )
    resp = api_client.create_vaccine_product(
        payload, TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def create_vaccine_lot(vaccine_product_id: str,
                       provider_organization_id: str,
                       doses_on_hand: int = 10,
                       **overrides: Any) -> Dict[str, Any]:
    """Register a VaccineLot. PRD §3.2."""
    payload = create_vaccine_lot_payload(
        vaccine_product_id, provider_organization_id,
        doses_on_hand=doses_on_hand, **overrides,
    )
    resp = api_client.create_vaccine_lot(
        payload, TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def create_antigen_schedule_rule(
    antigen: str,
    dose_sequence_number: int = 1,
    routine_min_age_days: int = 0,
    routine_recommended_age_days: int = 0,
    routine_max_age_days: int = 365,
    catchup_min_interval_days: int = 0,
    prerequisite_rule_id: Optional[str] = None,
    school_enrollment_required: bool = False,
) -> Dict[str, Any]:
    """Register an AntigenScheduleRule. PRD §3.7."""
    payload = create_antigen_schedule_rule_payload(
        antigen=antigen,
        dose_sequence_number=dose_sequence_number,
        routine_min_age_days=routine_min_age_days,
        routine_recommended_age_days=routine_recommended_age_days,
        routine_max_age_days=routine_max_age_days,
        catchup_min_interval_days=catchup_min_interval_days,
        prerequisite_rule_id=prerequisite_rule_id,
        school_enrollment_required=school_enrollment_required,
    )
    resp = api_client.create_antigen_schedule_rule(
        payload, TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def create_allergy(patient_id: str, allergen_code: str = "EGG",
                   severity: str = "ANAPHYLAXIS") -> Dict[str, Any]:
    """Record an AllergyRecord. PRD §3.4 (ProviderClinician only)."""
    resp = api_client.create_allergy(
        patient_id,
        create_allergy_payload(allergen_code=allergen_code,
                               severity=severity),
        TEST_USERS["provider_clinician_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2 - dose lifecycle helpers.
# ===========================================================================
def schedule_dose(patient_id: str, vaccine_product_id: str, lot_id: str,
                  provider_organization_id: str,
                  administering_clinician_id: str = PROVIDER_CLINICIAN_ID,
                  acting_clinician_id: Optional[str] = None,
                  ) -> Dict[str, Any]:
    """Schedule a dose. PRD §3.3.

    The acting clinician (X-User-ID header) MUST match the
    administering_clinician_id by default - PRD §3.3 says the
    ProviderClinician 'schedules a future dose'. Tests that want the
    SoD-relevant id on the dose to be a SPECIFIC value pass it via
    administering_clinician_id; the acting header is built from the
    same id unless acting_clinician_id is explicitly overridden.
    """
    actor_id = acting_clinician_id or administering_clinician_id
    headers = make_provider_clinician_headers(actor_id)
    payload = schedule_dose_payload(
        vaccine_product_id=vaccine_product_id,
        lot_id=lot_id,
        provider_organization_id=provider_organization_id,
        administering_clinician_id=administering_clinician_id,
    )
    resp = api_client.schedule_dose(patient_id, payload, headers)
    return get_success_data(resp)


def administer_dose(patient_id: str, dose_id: str,
                    administered_at: str,
                    actor_id: str = PROVIDER_CLINICIAN_ID
                    ) -> Dict[str, Any]:
    """Administer a scheduled dose. PRD §3.3."""
    headers = make_provider_clinician_headers(actor_id)
    resp = api_client.administer_dose(
        patient_id, dose_id,
        administer_dose_payload(administered_at=administered_at),
        headers,
    )
    return get_success_data(resp)


def schedule_and_administer_dose(
    patient_id: str, vaccine_product_id: str, lot_id: str,
    provider_organization_id: str, administered_at: str,
    administering_clinician_id: str = PROVIDER_CLINICIAN_ID,
) -> Dict[str, Any]:
    """Convenience: schedule then immediately administer a dose."""
    dose = schedule_dose(
        patient_id, vaccine_product_id, lot_id,
        provider_organization_id, administering_clinician_id,
    )
    return administer_dose(
        patient_id, dose["id"], administered_at,
        actor_id=administering_clinician_id,
    )


def invalidate_dose(patient_id: str, dose_id: str,
                    reason: str = "DATA_ERROR") -> Dict[str, Any]:
    """Invalidate an administered dose. PRD §3.3
    (PublicHealthOfficer only)."""
    resp = api_client.invalidate_dose(
        patient_id, dose_id,
        invalidate_dose_payload(reason=reason),
        TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def recall_lot(lot_id: str,
               reason: str = "MANUFACTURER_DEFECT") -> Dict[str, Any]:
    """Recall a VaccineLot. PRD §3.5
    (PublicHealthOfficer only)."""
    resp = api_client.recall_vaccine_lot(
        lot_id, recall_payload(reason=reason),
        TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2 - adverse event lifecycle helpers.
# ===========================================================================
def create_adverse_event(patient_id: str, dose_id: str, onset_at: str,
                         seriousness: str = "NON_SERIOUS",
                         symptom_codes: Optional[List[str]] = None,
                         actor_role: str = "ProviderClinician"
                         ) -> Dict[str, Any]:
    """Create an AdverseEvent. PRD §3.9."""
    if actor_role == "ProviderClinician":
        headers = TEST_USERS["provider_clinician_headers"]
    else:
        headers = TEST_USERS["reviewing_clinician_headers"]
    payload = create_adverse_event_payload(
        patient_id=patient_id, dose_id=dose_id, onset_at=onset_at,
        symptom_codes=symptom_codes, seriousness=seriousness,
    )
    resp = api_client.create_adverse_event(payload, headers)
    return get_success_data(resp)


def start_review(adverse_event_id: str,
                 reviewer_id: str = REVIEWING_CLINICIAN_ID
                 ) -> Dict[str, Any]:
    """Open AE for review. PRD §3.9 (ReviewingClinician)."""
    headers = make_reviewing_clinician_headers(reviewer_id)
    resp = api_client.start_review(adverse_event_id, headers)
    return get_success_data(resp)


def conclude_review(adverse_event_id: str,
                    conclusion: str = "NOT_RELATED",
                    reviewer_id: str = REVIEWING_CLINICIAN_ID
                    ) -> Dict[str, Any]:
    """Conclude AE review. PRD §3.9 (ReviewingClinician)."""
    headers = make_reviewing_clinician_headers(reviewer_id)
    resp = api_client.conclude_review(
        adverse_event_id,
        conclude_review_payload(conclusion=conclusion),
        headers,
    )
    return get_success_data(resp)


def submit_vaers(adverse_event_id: str,
                 elective: Optional[bool] = None,
                 reviewer_id: str = REVIEWING_CLINICIAN_ID
                 ) -> Dict[str, Any]:
    """Submit AE to VAERS. PRD §3.9 (ReviewingClinician)."""
    headers = make_reviewing_clinician_headers(reviewer_id)
    resp = api_client.submit_vaers(
        adverse_event_id, headers,
        submit_vaers_payload(elective=elective),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2 - certificate helpers.
# ===========================================================================
def create_certificate(patient_id: str,
                       school_year: str = "2026-2027",
                       grade_level: str = "K") -> Dict[str, Any]:
    """Create a draft certificate. PRD §3.8 (SchoolRegistrar)."""
    resp = api_client.create_certificate(
        patient_id,
        create_certificate_payload(school_year=school_year,
                                   grade_level=grade_level),
        TEST_USERS["school_registrar_headers"],
    )
    return get_success_data(resp)


def issue_certificate(patient_id: str, cert_id: str) -> Dict[str, Any]:
    """Issue a certificate (runs school coverage evaluation). PRD §3.8."""
    resp = api_client.issue_certificate(
        patient_id, cert_id,
        TEST_USERS["school_registrar_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3 - re-read helpers.
# ===========================================================================
def re_get_dose(patient_id: str, dose_id: str) -> Dict[str, Any]:
    resp = api_client.get_dose(
        patient_id, dose_id,
        TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def re_get_lot(lot_id: str) -> Dict[str, Any]:
    resp = api_client.get_vaccine_lot(
        lot_id, TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def re_get_certificate(patient_id: str, cert_id: str) -> Dict[str, Any]:
    """List the patient's certificates and find the one matching."""
    resp = api_client.list_certificates(
        patient_id,
        TEST_USERS["public_health_officer_headers"],
    )
    data = get_success_data(resp)
    # PRD §2.2: list endpoints return data as array. Search for the
    # matching cert_id.
    if isinstance(data, list):
        items = data
    else:
        items = data
    for it in items:
        if it.get("id") == cert_id:
            return it
    raise AssertionError(
        f"Setup failed: certificate {cert_id} not found in list"
    )


def re_get_adverse_event(adverse_event_id: str) -> Dict[str, Any]:
    resp = api_client.get_adverse_event(
        adverse_event_id,
        TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def re_get_provider_organization(provider_org_id: str) -> Dict[str, Any]:
    resp = api_client.get_provider_organization(
        provider_org_id,
        TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


def re_get_patient(patient_id: str) -> Dict[str, Any]:
    resp = api_client.get_patient(
        patient_id,
        TEST_USERS["public_health_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4 - composite multi-entity setups.
# ===========================================================================
def setup_basic_scenario(
    antigen: str = "MMR_MEASLES",
    routine_min_age_days: int = 365,
    routine_recommended_age_days: int = 365,
    routine_max_age_days: int = 2190,
    catchup_min_interval_days: int = 0,
    school_enrollment_required: bool = False,
    product_min_age_days: int = 365,
    product_max_age_days: Optional[int] = 2555,
    product_antigens: Optional[List[str]] = None,
    contraindication_flags: Optional[List[str]] = None,
    doses_on_hand: int = 10,
    patient_dob: str = "2020-01-01",
    medical_exemption_on_file: bool = False,
) -> Dict[str, Any]:
    """Build a minimal complete stack:
    - PublicHealth creates Patient, ProviderOrganization,
      AntigenScheduleRule for `antigen` seq=1, VaccineProduct, VaccineLot.
    - Returns dict with keys: patient, provider_org, rule, product, lot.

    Used by tests that just need a scheduled or administered dose
    against MMR/HEPB/whatever antigen.
    """
    anchor_clock()
    patient = create_patient(
        date_of_birth=patient_dob,
        medical_exemption_on_file=medical_exemption_on_file,
    )
    provider_org = create_provider_organization()
    rule = create_antigen_schedule_rule(
        antigen=antigen,
        dose_sequence_number=1,
        routine_min_age_days=routine_min_age_days,
        routine_recommended_age_days=routine_recommended_age_days,
        routine_max_age_days=routine_max_age_days,
        catchup_min_interval_days=catchup_min_interval_days,
        school_enrollment_required=school_enrollment_required,
    )
    product = create_vaccine_product(
        antigens=product_antigens or [antigen],
        min_age_days=product_min_age_days,
        max_age_days=product_max_age_days,
        contraindication_flags=contraindication_flags,
    )
    lot = create_vaccine_lot(
        product["id"], provider_org["id"], doses_on_hand=doses_on_hand,
    )
    return {
        "patient": patient,
        "provider_org": provider_org,
        "rule": rule,
        "product": product,
        "lot": lot,
    }


def setup_scheduled_dose(
    administering_clinician_id: str = PROVIDER_CLINICIAN_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build setup_basic_scenario plus one SCHEDULED dose.
    Returns the same dict augmented with 'dose'."""
    ctx = setup_basic_scenario(**kwargs)
    dose = schedule_dose(
        ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
        ctx["provider_org"]["id"],
        administering_clinician_id=administering_clinician_id,
    )
    ctx["dose"] = dose
    return ctx


def setup_administered_dose(
    administered_at: Optional[str] = None,
    administering_clinician_id: str = PROVIDER_CLINICIAN_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build setup_scheduled_dose plus administer step. Returns dict
    with 'dose' now in ADMINISTERED state."""
    if administered_at is None:
        administered_at = iso_anchor_offset()
    ctx = setup_scheduled_dose(
        administering_clinician_id=administering_clinician_id,
        **kwargs,
    )
    dose = administer_dose(
        ctx["patient"]["id"], ctx["dose"]["id"], administered_at,
        actor_id=administering_clinician_id,
    )
    ctx["dose"] = dose
    return ctx


# ===========================================================================
# Difficulty-design-specific composite setups.
#
# Each fixture below targets one or more difficulty-design instances.
# Names track the recipe they implement.
# ===========================================================================
def setup_dtap_catchup_two_seqs(
    routine_min_age_days_seq1: int = 42,
    routine_recommended_age_days_seq1: int = 60,
    routine_max_age_days_seq1: int = 90,
    catchup_min_interval_days_seq1: int = 28,
    routine_min_age_days_seq2: int = 120,
    routine_recommended_age_days_seq2: int = 120,
    routine_max_age_days_seq2: int = 180,
    catchup_min_interval_days_seq2: int = 28,
    patient_dob: str = "2025-01-01",
) -> Dict[str, Any]:
    """Build the DTAP_DIPHTHERIA two-sequence rule set + product + lot
    for the dual-variant calculation tests
    (difficulty_design instance:
    catchup_vs_routine_next_due_on_patient_schedule).

    PRD §3.7 defines both variants of cdc_catchup_eligibility_decision;
    this fixture builds the scaffolding that lets a test trigger one
    or the other simply by choosing the patient's DOB.
    """
    anchor_clock()
    provider_org = create_provider_organization()
    seq1 = create_antigen_schedule_rule(
        antigen="DTAP_DIPHTHERIA",
        dose_sequence_number=1,
        routine_min_age_days=routine_min_age_days_seq1,
        routine_recommended_age_days=routine_recommended_age_days_seq1,
        routine_max_age_days=routine_max_age_days_seq1,
        catchup_min_interval_days=catchup_min_interval_days_seq1,
    )
    seq2 = create_antigen_schedule_rule(
        antigen="DTAP_DIPHTHERIA",
        dose_sequence_number=2,
        routine_min_age_days=routine_min_age_days_seq2,
        routine_recommended_age_days=routine_recommended_age_days_seq2,
        routine_max_age_days=routine_max_age_days_seq2,
        catchup_min_interval_days=catchup_min_interval_days_seq2,
        prerequisite_rule_id=seq1["id"],
    )
    product = create_vaccine_product(
        antigens=["DTAP_DIPHTHERIA"],
        min_age_days=42, max_age_days=2555,
    )
    lot = create_vaccine_lot(
        product["id"], provider_org["id"], doses_on_hand=10,
    )
    patient = create_patient(date_of_birth=patient_dob)
    return {
        "provider_org": provider_org,
        "seq1": seq1,
        "seq2": seq2,
        "product": product,
        "lot": lot,
        "patient": patient,
    }


def setup_school_required_full_set(
    patient_dob: str = "2020-01-01",
    medical_exemption_on_file: bool = False,
) -> Dict[str, Any]:
    """Build full school-required rule set:
    MMR_MEASLES, DTAP_DIPHTHERIA, HEPB seq=1 each
    school_enrollment_required=true; corresponding products and lots.

    For the recall->dose->cert cascade and other cert tests.
    """
    anchor_clock()
    provider_org = create_provider_organization()
    patient = create_patient(
        date_of_birth=patient_dob,
        medical_exemption_on_file=medical_exemption_on_file,
    )
    rule_mmr = create_antigen_schedule_rule(
        antigen="MMR_MEASLES", dose_sequence_number=1,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
        catchup_min_interval_days=0,
        school_enrollment_required=True,
    )
    rule_dtap = create_antigen_schedule_rule(
        antigen="DTAP_DIPHTHERIA", dose_sequence_number=1,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
        catchup_min_interval_days=0,
        school_enrollment_required=True,
    )
    rule_hepb = create_antigen_schedule_rule(
        antigen="HEPB", dose_sequence_number=1,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
        catchup_min_interval_days=0,
        school_enrollment_required=True,
    )
    product_mmr = create_vaccine_product(
        antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
    )
    product_dtap = create_vaccine_product(
        antigens=["DTAP_DIPHTHERIA"], min_age_days=0, max_age_days=None,
    )
    product_hepb = create_vaccine_product(
        antigens=["HEPB"], min_age_days=0, max_age_days=None,
    )
    lot_mmr = create_vaccine_lot(
        product_mmr["id"], provider_org["id"], doses_on_hand=5,
    )
    lot_dtap = create_vaccine_lot(
        product_dtap["id"], provider_org["id"], doses_on_hand=5,
    )
    lot_hepb = create_vaccine_lot(
        product_hepb["id"], provider_org["id"], doses_on_hand=5,
    )
    return {
        "provider_org": provider_org,
        "patient": patient,
        "rule_mmr": rule_mmr,
        "rule_dtap": rule_dtap,
        "rule_hepb": rule_hepb,
        "product_mmr": product_mmr,
        "product_dtap": product_dtap,
        "product_hepb": product_hepb,
        "lot_mmr": lot_mmr,
        "lot_dtap": lot_dtap,
        "lot_hepb": lot_hepb,
    }


def setup_issued_certificate_full_coverage(
    patient_dob: str = "2020-01-01",
    administered_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build setup_school_required_full_set, administer one dose of
    each antigen, then issue the certificate -> ISSUED.

    For the recall-cascade tests (recall MMR lot -> dose invalidated
    -> certificate auto-demotes to DEFICIENT).
    """
    if administered_at is None:
        administered_at = iso_anchor_offset()
    ctx = setup_school_required_full_set(patient_dob=patient_dob)
    # Administer one MMR, one DTAP, one HEPB.
    mmr_dose = schedule_and_administer_dose(
        ctx["patient"]["id"], ctx["product_mmr"]["id"],
        ctx["lot_mmr"]["id"], ctx["provider_org"]["id"],
        administered_at=administered_at,
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    dtap_dose = schedule_and_administer_dose(
        ctx["patient"]["id"], ctx["product_dtap"]["id"],
        ctx["lot_dtap"]["id"], ctx["provider_org"]["id"],
        administered_at=administered_at,
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    hepb_dose = schedule_and_administer_dose(
        ctx["patient"]["id"], ctx["product_hepb"]["id"],
        ctx["lot_hepb"]["id"], ctx["provider_org"]["id"],
        administered_at=administered_at,
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    cert_draft = create_certificate(ctx["patient"]["id"])
    cert = issue_certificate(ctx["patient"]["id"], cert_draft["id"])
    ctx["mmr_dose"] = mmr_dose
    ctx["dtap_dose"] = dtap_dose
    ctx["hepb_dose"] = hepb_dose
    ctx["certificate"] = cert
    return ctx


def setup_hepb_single_required_and_dose(
    patient_dob: str = "2020-01-01",
    lot_doses_on_hand: int = 1,
    administered_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a scenario where HEPB is the only school-required antigen
    and a patient has one dose covering it; certificate ISSUED.

    Used by the data-error invalidation cascade test (invalidating the
    one HEPB dose should demote the certificate to DEFICIENT).
    """
    if administered_at is None:
        administered_at = iso_anchor_offset()
    anchor_clock()
    provider_org = create_provider_organization()
    patient = create_patient(date_of_birth=patient_dob)
    rule_hepb = create_antigen_schedule_rule(
        antigen="HEPB", dose_sequence_number=1,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
        catchup_min_interval_days=0,
        school_enrollment_required=True,
    )
    product_hepb = create_vaccine_product(
        antigens=["HEPB"], min_age_days=0, max_age_days=None,
    )
    lot_hepb = create_vaccine_lot(
        product_hepb["id"], provider_org["id"],
        doses_on_hand=lot_doses_on_hand,
    )
    dose = schedule_and_administer_dose(
        patient["id"], product_hepb["id"], lot_hepb["id"],
        provider_org["id"], administered_at=administered_at,
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    cert_draft = create_certificate(patient["id"])
    cert = issue_certificate(patient["id"], cert_draft["id"])
    return {
        "provider_org": provider_org,
        "patient": patient,
        "rule_hepb": rule_hepb,
        "product_hepb": product_hepb,
        "lot_hepb": lot_hepb,
        "dose": dose,
        "certificate": cert,
    }


def setup_serious_ae(
    onset_offset_hours: float = 1.0,
    administering_clinician_id: str = PROVIDER_CLINICIAN_ID,
) -> Dict[str, Any]:
    """Build setup_administered_dose plus a SERIOUS AdverseEvent
    against it. PRD §3.9: 'seriousness IN {SERIOUS, DEATH}' makes
    vaers_required=true.
    """
    administered_at = iso_anchor_offset()
    ctx = setup_administered_dose(
        administered_at=administered_at,
        administering_clinician_id=administering_clinician_id,
    )
    onset_at = iso_utc(
        parse_iso(administered_at)
        + timedelta(hours=onset_offset_hours),
    )
    ae = create_adverse_event(
        ctx["patient"]["id"], ctx["dose"]["id"],
        onset_at=onset_at, seriousness="SERIOUS",
    )
    ctx["adverse_event"] = ae
    ctx["administered_at"] = administered_at
    return ctx


def setup_mmr_lot_recall_with_ae_pending(
    administering_clinician_id: str = PROVIDER_CLINICIAN_ID,
) -> Dict[str, Any]:
    """Build setup_issued_certificate_full_coverage plus an
    AdverseEvent against the MMR dose in PENDING_REVIEW state.

    For the three-hop cascade test:
    recall(MMR_LOT) -> MMR_DOSE INVALIDATED -> CERT DEFICIENT AND
    AE.clinical_review_status PENDING_REVIEW -> UNDER_REVIEW.
    """
    administered_at = iso_anchor_offset()
    ctx = setup_issued_certificate_full_coverage(
        administered_at=administered_at,
    )
    onset_at = iso_utc(
        parse_iso(administered_at) + timedelta(hours=1),
    )
    ae = create_adverse_event(
        ctx["patient"]["id"], ctx["mmr_dose"]["id"],
        onset_at=onset_at, seriousness="NON_SERIOUS",
    )
    ctx["adverse_event"] = ae
    return ctx


def setup_dose_for_age_boundary(
    product_min_age_days: int,
    patient_dob_old: str,
    patient_dob_young: str,
) -> Dict[str, Any]:
    """Build infrastructure and TWO patients (old and young) with one
    SCHEDULED dose each, sharing a single MMR product/lot with
    min_age_days=product_min_age_days.

    For the age-boundary tests
    (difficulty_design.age_min_inclusive_boundary_on_administer).

    PRD §3.1: date_of_birth must be strictly in the past relative to
    the server's current time. We advance the clock to a point after
    BOTH DOBs (one day after the younger of them) before registering
    the patients so the past-relative rule is satisfied even when the
    DOB lands on the clock anchor.
    """
    # Pick the latest of the two DOBs and advance clock to one day after.
    latest_dob = max(parse_iso(patient_dob_old + "T00:00:00.000Z"),
                     parse_iso(patient_dob_young + "T00:00:00.000Z"))
    advance_clock_to(iso_utc(latest_dob + timedelta(days=1)))
    provider_org = create_provider_organization()
    create_antigen_schedule_rule(
        antigen="MMR_MEASLES", dose_sequence_number=1,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
        catchup_min_interval_days=0,
    )
    product = create_vaccine_product(
        antigens=["MMR_MEASLES"],
        min_age_days=product_min_age_days,
        max_age_days=None,
    )
    lot = create_vaccine_lot(
        product["id"], provider_org["id"], doses_on_hand=5,
    )
    patient_old = create_patient(date_of_birth=patient_dob_old)
    patient_young = create_patient(date_of_birth=patient_dob_young)
    dose_old = schedule_dose(
        patient_old["id"], product["id"], lot["id"],
        provider_org["id"],
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    dose_young = schedule_dose(
        patient_young["id"], product["id"], lot["id"],
        provider_org["id"],
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    return {
        "provider_org": provider_org,
        "product": product,
        "lot": lot,
        "patient_old": patient_old,
        "patient_young": patient_young,
        "dose_old": dose_old,
        "dose_young": dose_young,
    }


def setup_dose_for_min_interval(
    routine_min_age_days_seq1: int = 42,
    routine_max_age_days_seq1: int = 90,
    catchup_min_interval_days_seq2: int = 28,
    patient_dob: str = "2026-01-01",
) -> Dict[str, Any]:
    """Build DTAP_PERTUSSIS seq1 + seq2 rules, one product covering
    them, a lot with several doses, and a patient who has already
    received seq=1.

    For the min-interval-boundary test
    (difficulty_design.dose_min_interval_closed_lower_bound).

    PRD §3.1: date_of_birth must be strictly in the past. Pin the
    clock to one day after patient_dob before patient registration.
    """
    advance_clock_to(iso_utc(
        parse_iso(patient_dob + "T00:00:00.000Z") + timedelta(days=1)
    ))
    provider_org = create_provider_organization()
    seq1 = create_antigen_schedule_rule(
        antigen="DTAP_PERTUSSIS", dose_sequence_number=1,
        routine_min_age_days=routine_min_age_days_seq1,
        routine_recommended_age_days=routine_min_age_days_seq1,
        routine_max_age_days=routine_max_age_days_seq1,
        catchup_min_interval_days=0,
    )
    seq2 = create_antigen_schedule_rule(
        antigen="DTAP_PERTUSSIS", dose_sequence_number=2,
        routine_min_age_days=120,
        routine_recommended_age_days=120,
        routine_max_age_days=180,
        catchup_min_interval_days=catchup_min_interval_days_seq2,
        prerequisite_rule_id=seq1["id"],
    )
    product = create_vaccine_product(
        antigens=["DTAP_PERTUSSIS"], min_age_days=42, max_age_days=2555,
    )
    lot = create_vaccine_lot(
        product["id"], provider_org["id"], doses_on_hand=5,
    )
    patient = create_patient(date_of_birth=patient_dob)
    # Administer seq=1 at age routine_min_age_days_seq1 (42 days).
    seq1_admin_at = iso_utc(
        parse_iso(patient_dob + "T00:00:00.000Z")
        + timedelta(days=routine_min_age_days_seq1),
    )
    # advance clock so admin time is <= now
    advance_clock_to(seq1_admin_at)
    dose_seq1 = schedule_and_administer_dose(
        patient["id"], product["id"], lot["id"], provider_org["id"],
        administered_at=seq1_admin_at,
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    return {
        "provider_org": provider_org,
        "seq1_rule": seq1,
        "seq2_rule": seq2,
        "product": product,
        "lot": lot,
        "patient": patient,
        "dose_seq1": dose_seq1,
        "seq1_admin_at": seq1_admin_at,
    }


def setup_dose_for_ae_onset_window(
    administered_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build administered dose for adverse-event onset-window tests
    (difficulty_design.adverse_event_onset_window_open_upper_bound)."""
    if administered_at is None:
        administered_at = iso_anchor_offset()
    advance_clock_to(administered_at)
    ctx = setup_administered_dose(
        administered_at=administered_at,
        product_min_age_days=0,
        product_max_age_days=None,
    )
    ctx["administered_at"] = administered_at
    return ctx


def setup_priority_pair_state_vs_safety(
    administered_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a scenario where BOTH would fail: lot is RECALLED AND the
    patient has anaphylactic egg allergy with product flagged EGG.

    For difficulty_design.state_vs_business_safety_on_administer.
    PRD §2.6 pins state precedence over business safety.
    """
    if administered_at is None:
        administered_at = iso_anchor_offset()
    anchor_clock()
    provider_org = create_provider_organization()
    create_antigen_schedule_rule(
        antigen="MMR_MEASLES", dose_sequence_number=1,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
        catchup_min_interval_days=0,
    )
    product = create_vaccine_product(
        antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        contraindication_flags=["EGG"],
    )
    lot = create_vaccine_lot(
        product["id"], provider_org["id"], doses_on_hand=5,
    )
    patient = create_patient(date_of_birth="2020-01-01")
    # Anaphylactic EGG allergy.
    allergy = create_allergy(
        patient["id"], allergen_code="EGG", severity="ANAPHYLAXIS",
    )
    dose = schedule_dose(
        patient["id"], product["id"], lot["id"], provider_org["id"],
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    # Recall the lot AFTER scheduling so the dose is SCHEDULED on a
    # lot whose status is now RECALLED.
    recall_lot(lot["id"], reason="CONTAMINATION")
    return {
        "provider_org": provider_org,
        "product": product,
        "lot": lot,
        "patient": patient,
        "allergy": allergy,
        "dose": dose,
        "administered_at": administered_at,
    }


def setup_priority_pair_safety_vs_constraint(
    patient_dob: str = "2026-04-01",
    administered_at: str = "2026-04-15T00:00:00.000Z",
) -> Dict[str, Any]:
    """Build scenario where BOTH would fail: patient age is below
    product.min_age_days AND patient has anaphylactic NEOMYCIN allergy
    on a product flagged NEOMYCIN.

    For difficulty_design.business_safety_vs_business_constraint_on_administer.
    PRD §2.6 pins business-safety precedence over business-constraint.

    PRD §3.1: date_of_birth must be strictly in the past. Advance the
    clock to one day after patient_dob before registering the patient
    so the rule is satisfied.
    """
    advance_clock_to(iso_utc(
        parse_iso(patient_dob + "T00:00:00.000Z") + timedelta(days=1)
    ))
    provider_org = create_provider_organization()
    create_antigen_schedule_rule(
        antigen="MMR_MEASLES", dose_sequence_number=1,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
        catchup_min_interval_days=0,
    )
    product = create_vaccine_product(
        antigens=["MMR_MEASLES"], min_age_days=42, max_age_days=2555,
        contraindication_flags=["NEOMYCIN"],
    )
    lot = create_vaccine_lot(
        product["id"], provider_org["id"], doses_on_hand=5,
    )
    patient = create_patient(date_of_birth=patient_dob)
    allergy = create_allergy(
        patient["id"], allergen_code="NEOMYCIN", severity="ANAPHYLAXIS",
    )
    dose = schedule_dose(
        patient["id"], product["id"], lot["id"], provider_org["id"],
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    advance_clock_to(administered_at)
    return {
        "provider_org": provider_org,
        "product": product,
        "lot": lot,
        "patient": patient,
        "allergy": allergy,
        "dose": dose,
        "administered_at": administered_at,
    }


def setup_compliance_score_two_doses(
    administered_at_1: str,
    reported_offset_hours_1: float,
    administered_at_2: str,
    reported_offset_hours_2: float,
) -> Dict[str, Any]:
    """Build two doses with controlled (administered_at, reported_at)
    offsets so the rolling compliance score lands on the target value.

    PRD §3.6: 'the reporting lag in hours as the wall-clock seconds
    between reported_at and administered_at divided by 3600'.

    reported_at is set at the moment the dose is first POSTed (the
    schedule call). We control it by advancing the clock to
    (administered_at - reported_offset_hours_*) BEFORE scheduling, then
    to administered_at BEFORE calling /administer.

    This fixture is used by the round-then-sum tie-break
    difficulty-design instance and other compliance-score tests.
    """
    anchor_clock()
    provider_org = create_provider_organization()
    patient = create_patient(date_of_birth="2020-01-01")
    create_antigen_schedule_rule(
        antigen="MMR_MEASLES", dose_sequence_number=1,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
        catchup_min_interval_days=0,
    )
    product = create_vaccine_product(
        antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
    )
    lot = create_vaccine_lot(
        product["id"], provider_org["id"], doses_on_hand=10,
    )

    # First dose: schedule at (administered_at_1 - offset_1).
    sched_ts_1 = iso_utc(
        parse_iso(administered_at_1)
        - timedelta(hours=reported_offset_hours_1),
    )
    advance_clock_to(sched_ts_1)
    dose1 = schedule_dose(
        patient["id"], product["id"], lot["id"], provider_org["id"],
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    advance_clock_to(administered_at_1)
    dose1 = administer_dose(
        patient["id"], dose1["id"], administered_at_1,
        actor_id=PROVIDER_CLINICIAN_ID,
    )

    # Second dose: similarly.
    sched_ts_2 = iso_utc(
        parse_iso(administered_at_2)
        - timedelta(hours=reported_offset_hours_2),
    )
    advance_clock_to(sched_ts_2)
    dose2 = schedule_dose(
        patient["id"], product["id"], lot["id"], provider_org["id"],
        administering_clinician_id=PROVIDER_CLINICIAN_ID,
    )
    advance_clock_to(administered_at_2)
    dose2 = administer_dose(
        patient["id"], dose2["id"], administered_at_2,
        actor_id=PROVIDER_CLINICIAN_ID,
    )
    return {
        "provider_org": provider_org,
        "patient": patient,
        "product": product,
        "lot": lot,
        "dose1": dose1,
        "dose2": dose2,
    }


def setup_inventory_conservation_dose(
    lot_doses_on_hand: int = 7,
) -> Dict[str, Any]:
    """Build infrastructure with a known lot doses_on_hand, a single
    SCHEDULED dose ready to administer.

    For difficulty_design.dose_inventory_conservation_under_data_error_invalidation.
    """
    return setup_scheduled_dose(
        doses_on_hand=lot_doses_on_hand,
        product_antigens=["MMR_MEASLES"],
        antigen="MMR_MEASLES",
        product_min_age_days=0,
        product_max_age_days=None,
        routine_min_age_days=0,
        routine_recommended_age_days=0,
        routine_max_age_days=3650,
    )


__all__ = [
    # Clock
    "anchor_clock",
    "advance_clock_to",
    # Tier 1 creators
    "create_patient",
    "create_provider_organization",
    "create_vaccine_product",
    "create_vaccine_lot",
    "create_antigen_schedule_rule",
    "create_allergy",
    # Tier 2 lifecycle
    "schedule_dose",
    "administer_dose",
    "schedule_and_administer_dose",
    "invalidate_dose",
    "recall_lot",
    "create_adverse_event",
    "start_review",
    "conclude_review",
    "submit_vaers",
    "create_certificate",
    "issue_certificate",
    # Re-reads
    "re_get_dose",
    "re_get_lot",
    "re_get_certificate",
    "re_get_adverse_event",
    "re_get_provider_organization",
    "re_get_patient",
    # Composite
    "setup_basic_scenario",
    "setup_scheduled_dose",
    "setup_administered_dose",
    "setup_dtap_catchup_two_seqs",
    "setup_school_required_full_set",
    "setup_issued_certificate_full_coverage",
    "setup_hepb_single_required_and_dose",
    "setup_serious_ae",
    "setup_mmr_lot_recall_with_ae_pending",
    "setup_dose_for_age_boundary",
    "setup_dose_for_min_interval",
    "setup_dose_for_ae_onset_window",
    "setup_priority_pair_state_vs_safety",
    "setup_priority_pair_safety_vs_constraint",
    "setup_compliance_score_two_doses",
    "setup_inventory_conservation_dose",
]
