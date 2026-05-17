"""Composite setup helpers — multi-step preambles tests can reuse.

The telemedicine consult workflow is long. Reaching a meaningful
testable state typically requires: register physician -> register
license -> register patient -> create consult -> route -> start ->
(optionally) draft+issue prescription -> complete -> (optionally)
approve/deny+pay claim -> close.

Most interesting test claims need the system in a late-pipeline state,
or in a precisely-tuned threshold state (score at exactly 80, waterfall
arithmetic on uneven inputs).

IDENTITY THREADING — PRD §2.1:

- Physician is ENTITY-BACKED. Every Physician-driven call (start,
  complete, create prescription, patch prescription, issue, transmit,
  void, complete follow-up) MUST mint headers via
  make_physician_headers(physician["id"]) — never via the shared
  PHYSICIAN_FALLBACK_ID constant. The fixtures here remember the acting
  Physician's id and thread it through every Physician call.

- PlatformAdmin, ComplianceOfficer, Payer are OPAQUE. Their shared
  TEST_USERS headers are canonical for every call.

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
    clock_advance_payload,
    create_consult_payload,
    create_patient_payload,
    create_physician_payload,
    create_prescription_payload,
    create_state_license_payload,
    deny_claim_payload,
    occ_payload,
    random_dea_number,
    random_member_id,
    random_npi_number,
    random_payer_id,
    route_consult_payload,
    void_prescription_payload,
)
from .test_users import TEST_USERS, make_physician_headers


# ===========================================================================
# Clock helpers — PRD §2.9 (PlatformAdmin only)
# ===========================================================================
def advance_clock_to(iso_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /telemed/_clock/advance. PRD §3.7: "the platform's notion of
    'now' is a simulated clock that advances only when an operator calls
    the clock-advancement utility." PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=iso_timestamp), headers,
    )
    return get_success_data(resp)


def run_sweep(headers: Optional[Dict[str, str]] = None
              ) -> Dict[str, Any]:
    """POST /telemed/_sweep/run. PRD §3.7: nightly sweep MISSED
    transition driver. PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.sweep_run(headers)
    return get_success_data(resp)


def anchor_clock(iso_ts: Optional[str] = None) -> None:
    """Pin the server clock to a known anchor so all
    deadline calculations are deterministic. Most fixtures call this
    at the start of a setup."""
    advance_clock_to(iso_ts or TEST_DEFAULTS["CLOCK_ANCHOR"])


# ===========================================================================
# Tier 0: reference-data factories.
# ===========================================================================
def create_physician(
    *,
    full_name: Optional[str] = None,
    npi_number: Optional[str] = None,
    imlc_compact_member: Optional[bool] = None,
    imlc_home_state: Optional[str] = None,
    dea_number: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /telemed/physicians — PlatformAdmin only (PRD §4)."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_physician(
        create_physician_payload(
            full_name=full_name,
            npi_number=npi_number,
            imlc_compact_member=imlc_compact_member,
            imlc_home_state=imlc_home_state,
            dea_number=dea_number,
        ),
        headers,
    )
    return get_success_data(resp)


def create_state_license(
    physician: Dict[str, Any],
    *,
    state_code: str = "CA",
    license_type: str = "FULL",
    issued_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    license_number: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /telemed/physicians/{id}/licenses — PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_state_license(
        physician["id"],
        create_state_license_payload(
            state_code=state_code,
            license_type=license_type,
            issued_at=issued_at or TEST_DEFAULTS["DEFAULT_LICENSE_ISSUED_AT"],
            expires_at=(
                expires_at or TEST_DEFAULTS["DEFAULT_LICENSE_EXPIRES_AT"]
            ),
            license_number=license_number,
        ),
        headers,
    )
    return get_success_data(resp)


def revoke_state_license(physician_id: str, license_id: str,
                         headers: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    """POST /telemed/physicians/{pid}/licenses/{lid}/revoke."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.revoke_state_license(
        physician_id, license_id, headers,
    )
    return get_success_data(resp)


def create_patient(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    home_state_code: str = "CA",
    present_state_code: Optional[str] = None,
    insurance_payer_id: Optional[str] = None,
    insurance_member_id: Optional[str] = None,
    insurance_deductible_remaining_cents: Optional[int] = None,
    insurance_copay_cents: Optional[int] = None,
    insurance_coinsurance_bps: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /telemed/patients — PlatformAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_patient(
        create_patient_payload(
            full_name=full_name,
            date_of_birth=date_of_birth,
            home_state_code=home_state_code,
            present_state_code=present_state_code,
            insurance_payer_id=insurance_payer_id,
            insurance_member_id=insurance_member_id,
            insurance_deductible_remaining_cents=(
                insurance_deductible_remaining_cents
            ),
            insurance_copay_cents=insurance_copay_cents,
            insurance_coinsurance_bps=insurance_coinsurance_bps,
        ),
        headers,
    )
    return get_success_data(resp)


def create_insured_patient(
    *,
    home_state_code: str = "CA",
    deductible_cents: int = 2000,
    copay_cents: int = 2000,
    coinsurance_bps: int = 2000,
    payer_id: Optional[str] = None,
    member_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience: create a patient with insurance fully populated so
    a Consult.billing_mode=INSURANCE will not trip
    ERR_INSURANCE_NOT_ENROLLED (PRD §3.3)."""
    return create_patient(
        home_state_code=home_state_code,
        insurance_payer_id=payer_id or random_payer_id(),
        insurance_member_id=member_id or random_member_id(),
        insurance_deductible_remaining_cents=deductible_cents,
        insurance_copay_cents=copay_cents,
        insurance_coinsurance_bps=coinsurance_bps,
    )


# ===========================================================================
# Re-read helpers.
# ===========================================================================
def re_get_physician(physician_id: str) -> Dict[str, Any]:
    resp = api_client.get_physician(
        physician_id, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def re_get_patient(patient_id: str) -> Dict[str, Any]:
    resp = api_client.get_patient(
        patient_id, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def re_get_consult(consult_id: str) -> Dict[str, Any]:
    resp = api_client.get_consult(
        consult_id, TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(resp)


def re_get_state_license(
    physician_id: str, license_id: str,
) -> Dict[str, Any]:
    """No singular GET on a license; list and find by id."""
    resp = api_client.list_state_licenses(
        physician_id, TEST_USERS["admin_headers"],
        params={"limit": 100, "offset": 0},
    )
    body = get_success_data(resp)
    items = body if isinstance(body, list) else body.get("items", body)
    if isinstance(items, dict):
        # Some implementations may wrap; fall through.
        items = items.get("items", [])
    for item in items:
        if item.get("id") == license_id:
            return item
    raise AssertionError(
        f"Setup failed: state license {license_id} not found under "
        f"physician {physician_id}"
    )


def re_get_claim(claim_id: str) -> Dict[str, Any]:
    resp = api_client.get_claim(
        claim_id, TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(resp)


def re_get_invoice(invoice_id: str) -> Dict[str, Any]:
    resp = api_client.get_invoice(
        invoice_id, TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(resp)


def re_get_followup(followup_id: str) -> Dict[str, Any]:
    resp = api_client.get_followup(
        followup_id, TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(resp)


def get_physician_compliance(physician_id: str) -> Dict[str, Any]:
    resp = api_client.get_physician_compliance(
        physician_id, TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: state progression helpers — Consult lifecycle steps.
# ===========================================================================
def create_consult(
    *,
    patient: Dict[str, Any],
    present_state_code: Optional[str] = None,
    billing_mode: str = "SELF_PAY",
    visit_tier: str = "STANDARD",
    requires_followup: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /telemed/consults — ComplianceOfficer only (PRD §3.3)."""
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.create_consult(
        create_consult_payload(
            patient_id=patient["id"],
            present_state_code=present_state_code,
            billing_mode=billing_mode,
            visit_tier=visit_tier,
            requires_followup=requires_followup,
        ),
        headers,
    )
    return get_success_data(resp)


def route_consult(
    *,
    consult: Dict[str, Any],
    physician: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /telemed/consults/{id}/route — ComplianceOfficer."""
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.route_consult(
        consult["id"],
        route_consult_payload(
            physician_id=physician["id"],
            version=consult.get("version"),
        ),
        headers,
    )
    return get_success_data(resp)


def decline_consult(
    *,
    consult: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.decline_consult(
        consult["id"], occ_payload(version=consult.get("version")), headers,
    )
    return get_success_data(resp)


def unroute_consult(
    *,
    consult: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.unroute_consult(
        consult["id"], occ_payload(version=consult.get("version")), headers,
    )
    return get_success_data(resp)


def start_consult(
    *,
    consult: Dict[str, Any],
    physician: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /telemed/consults/{id}/start — Physician role; ownership-
    gated. Must mint headers from the actual physician's id (PRD §2.1).
    """
    resp = api_client.start_consult(
        consult["id"], occ_payload(version=consult.get("version")),
        make_physician_headers(physician["id"]),
    )
    return get_success_data(resp)


def complete_consult(
    *,
    consult: Dict[str, Any],
    physician: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /telemed/consults/{id}/complete — Physician role;
    ownership-gated. Triggers the billing + follow-up cascade per
    PRD §3.7."""
    resp = api_client.complete_consult(
        consult["id"], occ_payload(version=consult.get("version")),
        make_physician_headers(physician["id"]),
    )
    return get_success_data(resp)


def close_consult(
    *,
    consult: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /telemed/consults/{id}/close — ComplianceOfficer."""
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.close_consult(
        consult["id"], occ_payload(version=consult.get("version")), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Prescription lifecycle helpers.
# ===========================================================================
def create_prescription(
    *,
    consult: Dict[str, Any],
    physician: Dict[str, Any],
    drug_name: Optional[str] = None,
    dea_schedule: str = "NONE",
    days_supply: int = 15,
    refills: Optional[int] = None,
    epcs_two_factor_token: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /telemed/consults/{cid}/prescriptions — Physician;
    ownership-gated on the owning consult's physician_id."""
    resp = api_client.create_prescription(
        consult["id"],
        create_prescription_payload(
            drug_name=drug_name,
            dea_schedule=dea_schedule,
            days_supply=days_supply,
            refills=refills,
            epcs_two_factor_token=epcs_two_factor_token,
        ),
        make_physician_headers(physician["id"]),
    )
    return get_success_data(resp)


def issue_prescription(
    *,
    prescription: Dict[str, Any],
    physician: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /telemed/prescriptions/{id}/issue — Physician;
    ownership-gated on prescribing_physician_id (PRD §2.1)."""
    resp = api_client.issue_prescription(
        prescription["id"],
        occ_payload(version=prescription.get("version")),
        make_physician_headers(physician["id"]),
    )
    return get_success_data(resp)


def transmit_prescription(
    *,
    prescription: Dict[str, Any],
    physician: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /telemed/prescriptions/{id}/transmit — Physician."""
    resp = api_client.transmit_prescription(
        prescription["id"],
        occ_payload(version=prescription.get("version")),
        make_physician_headers(physician["id"]),
    )
    return get_success_data(resp)


def mark_dispensed_prescription(
    *,
    prescription: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /telemed/prescriptions/{id}/mark-dispensed —
    ComplianceOfficer."""
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.mark_dispensed_prescription(
        prescription["id"],
        occ_payload(version=prescription.get("version")),
        headers,
    )
    return get_success_data(resp)


def void_prescription(
    *,
    prescription: Dict[str, Any],
    physician: Dict[str, Any],
    void_reason: str = "Voided in setup",
) -> Dict[str, Any]:
    """POST /telemed/prescriptions/{id}/void — Physician;
    ownership-gated."""
    resp = api_client.void_prescription(
        prescription["id"],
        void_prescription_payload(
            void_reason=void_reason,
            version=prescription.get("version"),
        ),
        make_physician_headers(physician["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: InsuranceClaim / SelfPayInvoice / FollowUp helpers.
# ===========================================================================
def approve_claim(*, claim: Dict[str, Any],
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["payer_headers"]
    resp = api_client.approve_claim(
        claim["id"], occ_payload(version=claim.get("version")), headers,
    )
    return get_success_data(resp)


def deny_claim(*, claim: Dict[str, Any],
               denial_reason: str = "missing pre-auth",
               headers: Optional[Dict[str, str]] = None,
               ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["payer_headers"]
    resp = api_client.deny_claim(
        claim["id"],
        deny_claim_payload(
            denial_reason=denial_reason,
            version=claim.get("version"),
        ),
        headers,
    )
    return get_success_data(resp)


def appeal_claim(*, claim: Dict[str, Any],
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.appeal_claim(
        claim["id"], occ_payload(version=claim.get("version")), headers,
    )
    return get_success_data(resp)


def mark_paid_claim(*, claim: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["payer_headers"]
    resp = api_client.mark_paid_claim(
        claim["id"], occ_payload(version=claim.get("version")), headers,
    )
    return get_success_data(resp)


def mark_paid_invoice(*, invoice: Dict[str, Any],
                      headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.mark_paid_invoice(
        invoice["id"], occ_payload(version=invoice.get("version")), headers,
    )
    return get_success_data(resp)


def complete_followup(*, followup: Dict[str, Any],
                      physician: Dict[str, Any],
                      ) -> Dict[str, Any]:
    """POST /telemed/followups/{id}/complete — Physician;
    ownership-gated."""
    resp = api_client.complete_followup(
        followup["id"], occ_payload(version=followup.get("version")),
        make_physician_headers(physician["id"]),
    )
    return get_success_data(resp)


def cancel_followup(*, followup: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.cancel_followup(
        followup["id"], occ_payload(version=followup.get("version")),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Hierarchy setup helpers.
# ===========================================================================
def setup_physician_with_license(
    *,
    state_code: str = "CA",
    license_type: str = "FULL",
    issued_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    with_dea: bool = False,
    imlc_compact_member: Optional[bool] = None,
    imlc_home_state: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Tier 2: physician + one StateLicense. Returns (physician, license).

    The most common building block: a physician who has a single
    ACTIVE FULL CA license. Set with_dea=True if the test issues
    controlled substances. Set license_type=IMLC_EXPEDITED + imlc_*
    fields for the IMLC path.
    """
    dea = random_dea_number() if with_dea else None
    physician = create_physician(
        dea_number=dea,
        imlc_compact_member=imlc_compact_member,
        imlc_home_state=imlc_home_state,
    )
    lic = create_state_license(
        physician,
        state_code=state_code,
        license_type=license_type,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return physician, lic


def setup_routed_consult(
    *,
    state_code: str = "CA",
    billing_mode: str = "SELF_PAY",
    visit_tier: str = "STANDARD",
    requires_followup: bool = False,
    with_dea: bool = False,
    license_type: str = "FULL",
    deductible_cents: int = 2000,
    copay_cents: int = 2000,
    coinsurance_bps: int = 2000,
    license_issued_at: Optional[str] = None,
    license_expires_at: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Tier 3: physician with license, patient (insured if INSURANCE),
    consult routed to that physician. Returns
    (physician, license, patient, consult)."""
    physician, lic = setup_physician_with_license(
        state_code=state_code,
        license_type=license_type,
        with_dea=with_dea,
        issued_at=license_issued_at,
        expires_at=license_expires_at,
    )
    if billing_mode == "INSURANCE":
        patient = create_insured_patient(
            home_state_code=state_code,
            deductible_cents=deductible_cents,
            copay_cents=copay_cents,
            coinsurance_bps=coinsurance_bps,
        )
    else:
        patient = create_patient(home_state_code=state_code)
    consult = create_consult(
        patient=patient,
        billing_mode=billing_mode,
        visit_tier=visit_tier,
        requires_followup=requires_followup,
        present_state_code=state_code,
    )
    consult = route_consult(consult=consult, physician=physician)
    return physician, lic, patient, consult


def setup_in_progress_consult(
    **kwargs: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Tier 3: routed consult, then started so it sits in IN_PROGRESS.
    Same return tuple as setup_routed_consult, with the consult in
    IN_PROGRESS."""
    physician, lic, patient, consult = setup_routed_consult(**kwargs)
    consult = start_consult(consult=consult, physician=physician)
    return physician, lic, patient, consult


def setup_completed_consult(
    *,
    state_code: str = "CA",
    billing_mode: str = "SELF_PAY",
    visit_tier: str = "STANDARD",
    requires_followup: bool = False,
    with_dea: bool = False,
    deductible_cents: int = 2000,
    copay_cents: int = 2000,
    coinsurance_bps: int = 2000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Tier 3: full lifecycle through COMPLETED. Returns
    (physician, license, patient, consult) where consult.status ==
    COMPLETED and the billing/follow-up side effects have already run.
    """
    physician, lic, patient, consult = setup_in_progress_consult(
        state_code=state_code,
        billing_mode=billing_mode,
        visit_tier=visit_tier,
        requires_followup=requires_followup,
        with_dea=with_dea,
        deductible_cents=deductible_cents,
        copay_cents=copay_cents,
        coinsurance_bps=coinsurance_bps,
    )
    consult = complete_consult(consult=consult, physician=physician)
    return physician, lic, patient, consult


def find_claim_for_consult(consult_id: str) -> Optional[Dict[str, Any]]:
    """Locate the InsuranceClaim auto-created for an INSURANCE consult
    completion. The API does not expose a list-by-consult endpoint, so
    the helper relies on the audit-events trail and follow-up reads."""
    # We can't list claims, so look through audit events for any
    # subject_entity matching InsuranceClaim under this consult. The
    # simpler path is: callers know the claim's id from the complete
    # response. So this helper does best-effort discovery via audit.
    resp = api_client.list_audit_events(
        TEST_USERS["compliance_officer_headers"],
        params={"subject_entity": "InsuranceClaim", "limit": 100},
    )
    body = get_success_data(resp)
    items = body if isinstance(body, list) else body.get("items", body)
    if isinstance(items, dict):
        items = items.get("items", [])
    for ev in items:
        payload = ev.get("payload_json") or {}
        if payload.get("consult_id") == consult_id:
            return re_get_claim(ev["subject_id"])
    return None


def find_invoice_for_consult(
    consult_id: str,
) -> Optional[Dict[str, Any]]:
    """Best-effort: locate the SelfPayInvoice auto-created on a
    SELF_PAY consult completion via the audit trail."""
    resp = api_client.list_audit_events(
        TEST_USERS["compliance_officer_headers"],
        params={"subject_entity": "SelfPayInvoice", "limit": 100},
    )
    body = get_success_data(resp)
    items = body if isinstance(body, list) else body.get("items", body)
    if isinstance(items, dict):
        items = items.get("items", [])
    for ev in items:
        payload = ev.get("payload_json") or {}
        if payload.get("consult_id") == consult_id:
            return re_get_invoice(ev["subject_id"])
    return None


# Note: PRD does not require a list-claims-by-consult endpoint, but
# implementations are at liberty to embed the auto-created child id
# in the complete_consult response. The two-reader rule blocks us from
# pinning a specific surface there; tests that need the claim/invoice
# id should accept any of:
#   (a) it is in consult.claim_id or consult.invoice_id after complete
#   (b) it is in the response body's `data` from the complete call
# We provide a helper that handles both.
def get_post_complete_claim_or_invoice(
    consult_after_complete: Dict[str, Any],
    billing_mode: str,
) -> Optional[Dict[str, Any]]:
    """Try common locations for the auto-created child entity id.

    The implementation may return it in the response body or it may
    only surface through audit events. Fall back to the audit trail.
    """
    candidate_keys = (
        ("claim", "claim_id", "insurance_claim", "insurance_claim_id")
        if billing_mode == "INSURANCE"
        else ("invoice", "invoice_id", "self_pay_invoice", "self_pay_invoice_id")
    )
    for key in candidate_keys:
        val = consult_after_complete.get(key)
        if isinstance(val, dict) and "id" in val:
            return (
                re_get_claim(val["id"])
                if billing_mode == "INSURANCE"
                else re_get_invoice(val["id"])
            )
        if isinstance(val, str):
            return (
                re_get_claim(val)
                if billing_mode == "INSURANCE"
                else re_get_invoice(val)
            )
    # Fallback: scan audit trail.
    cid = consult_after_complete["id"]
    return (
        find_claim_for_consult(cid)
        if billing_mode == "INSURANCE"
        else find_invoice_for_consult(cid)
    )


def find_followup_for_consult(
    consult_id: str,
) -> Optional[Dict[str, Any]]:
    """Best-effort FollowUp discovery via audit events. PRD does not
    pin a list endpoint."""
    # FollowUp creation is a side-effect of complete_consult, but no
    # AuditEvent type pins it. We discover by inspecting whether the
    # complete-consult response itself surfaced a followup id; if not,
    # we cannot pin it portably.
    return None


# ===========================================================================
# Tier 4: Threshold-targeting & calculation-pinning setups.
# ===========================================================================
def setup_two_consults_dual_billing_mode(
) -> Tuple[
    Dict[str, Any],  # physician (FULL CA license)
    Dict[str, Any],  # patient_insurance
    Dict[str, Any],  # patient_self_pay
    Dict[str, Any],  # consult_insurance (routed+started)
    Dict[str, Any],  # consult_self_pay (routed+started)
]:
    """Dual-variant_calc/consult_charge_self_pay_vs_insurance recipe.

    Two STANDARD-tier consults at the same physician/license, one
    INSURANCE (deductible=copay=2000, coinsurance_bps=2000) and one
    SELF_PAY. Both routed+started; ready for the test to call
    /complete on each and compare final_charge_cents.
    """
    physician, _ = setup_physician_with_license(state_code="CA")
    patient_ins = create_insured_patient(
        home_state_code="CA",
        deductible_cents=2000,
        copay_cents=2000,
        coinsurance_bps=2000,
    )
    patient_sp = create_patient(home_state_code="CA")
    consult_ins = create_consult(
        patient=patient_ins, billing_mode="INSURANCE",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult_ins = route_consult(consult=consult_ins, physician=physician)
    consult_ins = start_consult(consult=consult_ins, physician=physician)
    consult_sp = create_consult(
        patient=patient_sp, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult_sp = route_consult(consult=consult_sp, physician=physician)
    consult_sp = start_consult(consult=consult_sp, physician=physician)
    return physician, patient_ins, patient_sp, consult_ins, consult_sp


def setup_insurance_waterfall_pinning(
    *,
    deductible_cents: int = 333,
    copay_cents: int = 333,
    coinsurance_bps: int = 1250,
    visit_tier: str = "BRIEF",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Recipe for combinatorial_formula/insurance_waterfall_rounding_order_pin.

    Patient: deductible=333, copay=333, coinsurance_bps=1250. Consult:
    BRIEF (base=5000). Returns (physician, license, patient, consult)
    routed+started so the test can call /complete and read the claim's
    coinsurance_applied_cents to validate the per-step half-up rounding
    order.
    """
    physician, lic = setup_physician_with_license(state_code="CA")
    patient = create_insured_patient(
        home_state_code="CA",
        deductible_cents=deductible_cents,
        copay_cents=copay_cents,
        coinsurance_bps=coinsurance_bps,
    )
    consult = create_consult(
        patient=patient, billing_mode="INSURANCE",
        visit_tier=visit_tier, present_state_code="CA",
    )
    consult = route_consult(consult=consult, physician=physician)
    consult = start_consult(consult=consult, physician=physician)
    return physician, lic, patient, consult


def setup_score_at_exactly_80(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Recipe for boundary_precision_check/compliance_score_at_80.

    Physician with IMLC_EXPEDITED CA license + DEA registered. Routed
    consult in IN_PROGRESS. Returns (physician, license, patient,
    consult, draft_prescription) where the draft is:
       drug_name='AddIIp', dea_schedule=II, refills=0, days_supply=90,
       epcs_two_factor_token='T1'
    Score: routing_basis=IMLC_EXPEDITED → 30 + DEA OK → 30 + II/refill=0
    → 20 + days=90 → 0 = 80. Exactly at the >= 80 threshold.
    """
    physician = create_physician(
        dea_number=random_dea_number(),
        imlc_compact_member=True,
        imlc_home_state="CA",
    )
    lic = create_state_license(
        physician, state_code="CA",
        license_type="IMLC_EXPEDITED",
    )
    patient = create_patient(home_state_code="CA")
    consult = create_consult(
        patient=patient, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult = route_consult(consult=consult, physician=physician)
    consult = start_consult(consult=consult, physician=physician)
    rx = create_prescription(
        consult=consult, physician=physician,
        drug_name="AddIIp", dea_schedule="II", days_supply=90,
        refills=0, epcs_two_factor_token="T1",
    )
    return physician, lic, patient, consult, rx


def setup_score_just_below_80(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Recipe for boundary_precision_check/compliance_score_at_80 — the
    just-below counterpart.

    Same IMLC + DEA physician as setup_score_at_exactly_80. Draft Rx:
       drug_name='OxyIVf', dea_schedule=IV, refills=6, days_supply=45,
       epcs_two_factor_token='T2'
    Score: 30(IMLC) + 30(DEA OK) + 10(IV/refill>5) + 5(31<=days<=60)
    = 75. Below the 80 threshold — issuing should fail with
    ERR_COMPLIANCE_SCORE_TOO_LOW.
    """
    physician = create_physician(
        dea_number=random_dea_number(),
        imlc_compact_member=True,
        imlc_home_state="CA",
    )
    lic = create_state_license(
        physician, state_code="CA",
        license_type="IMLC_EXPEDITED",
    )
    patient = create_patient(home_state_code="CA")
    consult = create_consult(
        patient=patient, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult = route_consult(consult=consult, physician=physician)
    consult = start_consult(consult=consult, physician=physician)
    rx = create_prescription(
        consult=consult, physician=physician,
        drug_name="OxyIVf", dea_schedule="IV", days_supply=45,
        refills=6, epcs_two_factor_token="T2",
    )
    return physician, lic, patient, consult, rx


def setup_two_issued_prescriptions_for_compliance_avg(
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Recipe for dual_variant_calc/compliance_score_per_rx_vs_physician_aggregate.

    Physician with FULL CA license, no DEA. Two SEPARATE patients (PRD
    §3.3 forbids overlapping non-terminal consults per patient), each
    with one consult routed+started; one DRAFT non-controlled Rx per
    consult, both issued so they enter the issued-set used by the
    physician aggregate.
       Rx1: dea_schedule=NONE, days_supply=15, refills=0 →
            40+30+20+10 = 100
       Rx2: dea_schedule=NONE, days_supply=61, refills=0 →
            40+30+20+0 = 90
    Mean (HALF_UP, one decimal) = 95.0.
    Returns (physician, [rx1_issued, rx2_issued]).
    """
    physician, _ = setup_physician_with_license(state_code="CA")
    issued = []
    for spec in (
        {"drug_name": "AmoxNone", "days_supply": 15, "refills": 0},
        {"drug_name": "AmoxLow", "days_supply": 61, "refills": 0},
    ):
        patient = create_patient(home_state_code="CA")
        consult = create_consult(
            patient=patient, billing_mode="SELF_PAY",
            visit_tier="STANDARD", present_state_code="CA",
        )
        consult = route_consult(consult=consult, physician=physician)
        consult = start_consult(consult=consult, physician=physician)
        rx = create_prescription(
            consult=consult, physician=physician,
            dea_schedule="NONE", **spec,
        )
        rx_issued = issue_prescription(
            prescription=rx, physician=physician,
        )
        issued.append(rx_issued)
    return physician, issued


def setup_completed_insurance_consult_for_billing(
    *,
    visit_tier: str = "STANDARD",
    deductible_cents: int = 2000,
    copay_cents: int = 2000,
    coinsurance_bps: int = 2000,
    requires_followup: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Recipe for compensating_invariant/claim_money_conservation_billed_equals_allocation.

    Returns (physician, license, patient, completed_consult, claim).
    The claim is auto-created at completion in status=SUBMITTED.
    """
    physician, lic, patient, consult = setup_completed_consult(
        billing_mode="INSURANCE",
        visit_tier=visit_tier,
        deductible_cents=deductible_cents,
        copay_cents=copay_cents,
        coinsurance_bps=coinsurance_bps,
        requires_followup=requires_followup,
    )
    claim = get_post_complete_claim_or_invoice(consult, "INSURANCE")
    if claim is None:
        raise AssertionError(
            "Setup failed: could not locate auto-created InsuranceClaim "
            "for completed consult."
        )
    return physician, lic, patient, consult, claim


def setup_routed_consult_with_draft_rx(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Recipe for transitive_cascade/license_revoke_to_consult_to_rx_void_depth_3.

    Physician with single FULL CA license + DEA. Patient in CA, consult
    routed and STARTED (IN_PROGRESS — the only status under which a
    Prescription can be drafted per PRD §3.4). One DRAFT non-controlled
    Rx exists under the consult. Returns
    (physician, license, patient, consult, draft_rx).
    """
    physician, lic = setup_physician_with_license(
        state_code="CA", with_dea=True,
    )
    patient = create_patient(home_state_code="CA")
    consult = create_consult(
        patient=patient, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult = route_consult(consult=consult, physician=physician)
    consult = start_consult(consult=consult, physician=physician)
    rx = create_prescription(
        consult=consult, physician=physician,
        drug_name="Amox-cascade",
        dea_schedule="NONE", days_supply=15, refills=0,
    )
    return physician, lic, patient, consult, rx


def setup_two_consults_one_routed(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Recipe for priority_pair_validation_conflict/state_vs_business_safety_pair.

    physician_a: FULL CA license.
    physician_b: NO licenses anywhere.
    Patient in CA, consult routed to physician_a (status=ROUTED).
    Returns (physician_a, physician_b, patient, consult_routed_to_a).

    A subsequent /route call attempting to route the already-ROUTED
    consult to physician_b exercises BOTH ERR_INVALID_STATE (state
    precondition fails) AND ERR_NO_VALID_LICENSE (physician_b has no
    license for CA). Per PRD §2.6 priority order, ERR_INVALID_STATE
    must win.
    """
    physician_a, _ = setup_physician_with_license(state_code="CA")
    physician_b = create_physician()  # No licenses.
    patient = create_patient(home_state_code="CA")
    consult = create_consult(
        patient=patient, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult = route_consult(consult=consult, physician=physician_a)
    return physician_a, physician_b, patient, consult


def setup_two_physicians_one_consult(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Recipe for priority_pair_validation_conflict/business_referential_vs_business_safety_pair.

    physician_a: FULL CA license, NO DEA.
    physician_b: FULL CA license, NO DEA.
    Patient in CA; consult routed to physician_a and started so it is
    IN_PROGRESS.
    Returns (physician_a, physician_b, patient, consult_in_progress).
    """
    physician_a, _ = setup_physician_with_license(state_code="CA")
    physician_b, _ = setup_physician_with_license(state_code="CA")
    patient = create_patient(home_state_code="CA")
    consult = create_consult(
        patient=patient, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult = route_consult(consult=consult, physician=physician_a)
    consult = start_consult(consult=consult, physician=physician_a)
    return physician_a, physician_b, patient, consult


def setup_expiring_license_consult(
    *,
    clock_anchor: str = "2026-05-16T00:00:00.000Z",
    license_expires_at: str = "2026-06-01T00:00:00.000Z",
    advance_to_after_expiry: str = "2026-06-02T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Recipe for cross_entity_state_dependency/consult_start_depends_on_state_license_status.

    Returns (physician, license, patient, routed_consult). The clock is
    anchored, the consult is routed while license is ACTIVE, then the
    clock is advanced PAST the license's expires_at — but start has NOT
    been called yet. A subsequent /start call must fail because the
    license now projects to EXPIRED.
    """
    anchor_clock(clock_anchor)
    physician, lic = setup_physician_with_license(
        state_code="CA",
        issued_at="2026-01-01T00:00:00.000Z",
        expires_at=license_expires_at,
    )
    patient = create_patient(home_state_code="CA")
    consult = create_consult(
        patient=patient, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult = route_consult(consult=consult, physician=physician)
    advance_clock_to(advance_to_after_expiry)
    return physician, lic, patient, consult


def setup_completed_insurance_consult_with_followup(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Recipe for cross_entity_state_dependency/consult_close_depends_on_claim_followup_terminal.

    STANDARD insurance consult with requires_followup=true, completed
    so that both InsuranceClaim (SUBMITTED) and FollowUp (SCHEDULED)
    exist alongside it. Returns (physician, patient, completed_consult,
    claim).
    """
    physician, _, patient, consult = setup_completed_consult(
        billing_mode="INSURANCE",
        visit_tier="STANDARD",
        requires_followup=True,
        deductible_cents=2000,
        copay_cents=2000,
        coinsurance_bps=2000,
    )
    claim = get_post_complete_claim_or_invoice(consult, "INSURANCE")
    if claim is None:
        raise AssertionError(
            "Setup failed: could not locate auto-created InsuranceClaim."
        )
    return physician, patient, consult, claim


def setup_patient_with_routed_consult_for_overlap(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Recipe for resource_temporal_overlap/patient_active_consult_status_window_overlap.

    Patient with a ROUTED consult occupying them. Returns
    (physician, patient, consult_routed). A subsequent /consults POST
    for the same patient must trip ERR_PATIENT_HAS_ACTIVE_CONSULT.
    """
    physician, _, patient, consult = setup_routed_consult(
        billing_mode="SELF_PAY",
    )
    return physician, _, patient, consult


def setup_physician_with_one_license_for_overlap(
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Recipe for resource_temporal_overlap/state_license_period_half_open_interval_overlap.

    Physician with a single FULL CA license, [2026-01-01, 2026-12-31).
    Returns (physician, lic). The test then POSTs a second license
    overlapping or back-to-back to verify the half-open semantics.
    """
    physician, lic = setup_physician_with_license(
        state_code="CA",
        license_type="FULL",
        issued_at="2026-01-01T00:00:00.000Z",
        expires_at="2026-12-31T00:00:00.000Z",
    )
    return physician, lic


def setup_two_patients_two_insurance_consults_chain(
) -> Tuple[
    Dict[str, Any],  # physician
    Dict[str, Any],  # patient (shared)
    Dict[str, Any],  # consult_a (COMPLETED, INSURANCE)
    Dict[str, Any],  # claim_a (SUBMITTED)
]:
    """Recipe for compensating_invariant/patient_deductible_lifetime_conservation.

    Sets up a patient with deductible=3000 and one COMPLETED INSURANCE
    consult (consult_a / claim_a). Returns
    (physician, patient, completed_consult_a, claim_a). The test then
    pays claim_a (decrement by 3000), and afterwards creates a SECOND
    consult_b and verifies its claim_b has deductible_applied=0
    because the deductible was already exhausted.
    """
    anchor_clock()
    physician, _ = setup_physician_with_license(state_code="CA")
    patient = create_insured_patient(
        home_state_code="CA",
        deductible_cents=3000,
        copay_cents=1000,
        coinsurance_bps=2000,
    )
    consult_a = create_consult(
        patient=patient, billing_mode="INSURANCE",
        visit_tier="STANDARD", present_state_code="CA",
    )
    consult_a = route_consult(consult=consult_a, physician=physician)
    consult_a = start_consult(consult=consult_a, physician=physician)
    consult_a = complete_consult(consult=consult_a, physician=physician)
    claim_a = get_post_complete_claim_or_invoice(consult_a, "INSURANCE")
    if claim_a is None:
        raise AssertionError(
            "Setup failed: claim_a not found after completing consult_a."
        )
    return physician, patient, consult_a, claim_a


def setup_consult_with_no_rx_for_empty_followup(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Recipe for boundary_precision_check/followup_window_empty_prescription_set.

    Returns (physician, patient, consult_in_progress) where consult has
    requires_followup=true. No prescriptions are drafted/issued. The
    test then /completes the consult; the resulting FollowUp.due_by
    should be clock_before + 90 days (non-controlled-only variant).
    """
    physician, _, patient, consult = setup_in_progress_consult(
        billing_mode="SELF_PAY",
        visit_tier="STANDARD",
        requires_followup=True,
    )
    return physician, patient, consult


def setup_two_routes_for_concurrency(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """For concurrency_rules / non_linear_state_machine route races.

    Returns (physician, patient, consult_requested) so two parallel
    /route calls can race.
    """
    physician, _ = setup_physician_with_license(state_code="CA")
    patient = create_patient(home_state_code="CA")
    consult = create_consult(
        patient=patient, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    return physician, patient, consult


def setup_two_physicians_one_consult_route_cycle(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Recipe for non_linear_state_machine/consult_route_unroute_revert_cycle.

    physician_a: FULL CA license. physician_b: FULL NY license.
    Patient in CA; REQUESTED consult.
    Returns (physician_a, physician_b, patient, consult).
    """
    physician_a, _ = setup_physician_with_license(state_code="CA")
    physician_b, _ = setup_physician_with_license(state_code="NY")
    patient = create_patient(home_state_code="CA")
    consult = create_consult(
        patient=patient, billing_mode="SELF_PAY",
        visit_tier="STANDARD", present_state_code="CA",
    )
    return physician_a, physician_b, patient, consult


def setup_completed_insurance_consult_for_appeal_cycle(
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Recipe for non_linear_state_machine/claim_denial_appeal_cycle.

    Completed INSURANCE STANDARD consult, claim auto-created in
    SUBMITTED. Returns (physician, patient, completed_consult, claim).
    """
    return setup_completed_insurance_consult_for_billing(
        visit_tier="STANDARD",
        deductible_cents=2000,
        copay_cents=2000,
        coinsurance_bps=2000,
    )


__all__ = [
    # Clock helpers
    "advance_clock_to",
    "run_sweep",
    "anchor_clock",
    # Reference data
    "create_physician",
    "create_state_license",
    "revoke_state_license",
    "create_patient",
    "create_insured_patient",
    # Re-reads
    "re_get_physician",
    "re_get_patient",
    "re_get_consult",
    "re_get_state_license",
    "re_get_claim",
    "re_get_invoice",
    "re_get_followup",
    "get_physician_compliance",
    # Consult lifecycle
    "create_consult",
    "route_consult",
    "decline_consult",
    "unroute_consult",
    "start_consult",
    "complete_consult",
    "close_consult",
    # Prescription lifecycle
    "create_prescription",
    "issue_prescription",
    "transmit_prescription",
    "mark_dispensed_prescription",
    "void_prescription",
    # Billing
    "approve_claim",
    "deny_claim",
    "appeal_claim",
    "mark_paid_claim",
    "mark_paid_invoice",
    "complete_followup",
    "cancel_followup",
    # Hierarchies
    "setup_physician_with_license",
    "setup_routed_consult",
    "setup_in_progress_consult",
    "setup_completed_consult",
    "get_post_complete_claim_or_invoice",
    "find_claim_for_consult",
    "find_invoice_for_consult",
    "find_followup_for_consult",
    # Difficulty-design composites
    "setup_two_consults_dual_billing_mode",
    "setup_insurance_waterfall_pinning",
    "setup_score_at_exactly_80",
    "setup_score_just_below_80",
    "setup_two_issued_prescriptions_for_compliance_avg",
    "setup_completed_insurance_consult_for_billing",
    "setup_routed_consult_with_draft_rx",
    "setup_two_consults_one_routed",
    "setup_two_physicians_one_consult",
    "setup_expiring_license_consult",
    "setup_completed_insurance_consult_with_followup",
    "setup_patient_with_routed_consult_for_overlap",
    "setup_physician_with_one_license_for_overlap",
    "setup_two_patients_two_insurance_consults_chain",
    "setup_consult_with_no_rx_for_empty_followup",
    "setup_two_routes_for_concurrency",
    "setup_two_physicians_one_consult_route_cycle",
    "setup_completed_insurance_consult_for_appeal_cycle",
]
