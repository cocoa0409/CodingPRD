"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked into a specific state
across several API calls (schedule -> check-in -> start -> code -> finalize, or
draft -> submit -> sign -> transmit -> dispense). These helpers encapsulate
those preambles so each test focuses on its own assertion.

Fixtures use get_success_data() (lenient) internally so a setup failure surfaces
as a clear "Setup failed" error rather than a confusing assertion failure.

Identity threading: after creating a Provider, every ownership-gated call (start,
code, reopen, charge-line, sign, prescription create, referral create/cancel) is
issued with make_provider_headers(provider["id"]); after creating a Patient,
portal activation uses make_patient_headers(patient["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_provider_payload,
    create_patient_payload,
    create_cpt_code_payload,
    create_visit_payload,
    create_charge_line_payload,
    create_prescription_payload,
    create_referral_payload,
    create_portal_account_payload,
    create_hedis_measure_payload,
)
from .test_users import TEST_USERS, make_provider_headers, make_patient_headers

FD = TEST_USERS["frontdesk_headers"]
BILLER = TEST_USERS["biller_headers"]
QA = TEST_USERS["quality_headers"]


# ─── Clock ────────────────────────────────────────────────────────────

def set_clock(iso8601: str, headers=FD):
    """Set the server logical clock. Returns the response data."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, headers))


# ─── Tier 1: Primitive creates ────────────────────────────────────────

def create_provider(**overrides):
    """Create an ACTIVE provider. Returns provider data."""
    return get_success_data(api_client.create_provider(create_provider_payload(**overrides), FD))


def create_patient(**overrides):
    """Create an ACTIVE patient. Returns patient data."""
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), FD))


def create_cpt_code(**overrides):
    """Create a CPT code. Returns cpt code data."""
    return get_success_data(api_client.create_cpt_code(create_cpt_code_payload(**overrides), BILLER))


def create_hedis_measure(patient_id, **overrides):
    """Create a HEDIS measure. Returns measure data."""
    return get_success_data(
        api_client.create_hedis_measure(create_hedis_measure_payload(patient_id, **overrides), QA)
    )


def create_provider_and_patient(provider_overrides=None, patient_overrides=None):
    """The most common preamble: one ACTIVE provider + one ACTIVE patient."""
    provider = create_provider(**(provider_overrides or {}))
    patient = create_patient(**(patient_overrides or {}))
    return provider, patient


# ─── Tier 2: Visit lifecycle walks ────────────────────────────────────

def create_visit(patient_id, provider_id, **overrides):
    """Create a SCHEDULED visit. Returns visit data."""
    return get_success_data(
        api_client.create_visit(create_visit_payload(patient_id, provider_id, **overrides), FD)
    )


def create_visit_in_progress(provider=None, patient=None, visit_overrides=None):
    """Provider + patient + visit, walked SCHEDULED -> CHECKED_IN -> IN_PROGRESS.

    Returns (provider, patient, visit). The visit is owned by `provider`, so
    start uses that provider's entity-backed headers.
    """
    if provider is None:
        provider = create_provider()
    if patient is None:
        patient = create_patient()
    prov_hdr = make_provider_headers(provider["id"])
    visit = create_visit(patient["id"], provider["id"], **(visit_overrides or {}))
    get_success_data(api_client.check_in_visit(visit["id"], FD))
    visit = get_success_data(api_client.start_visit(visit["id"], prov_hdr))
    return provider, patient, visit


def add_charge_line(visit_id, provider_id, cpt_code, **overrides):
    """Add a charge line to an IN_PROGRESS visit (provider-owned). Returns line data."""
    prov_hdr = make_provider_headers(provider_id)
    return get_success_data(
        api_client.create_charge_line(visit_id, create_charge_line_payload(cpt_code, **overrides), prov_hdr)
    )


def create_coded_visit(provider=None, patient=None, cpt_overrides=None,
                       charge_overrides=None, visit_overrides=None):
    """Walk a visit to CODED with one charge line.

    Defaults to an EM code requiring em_level so a tiered charge is produced.
    Returns (provider, patient, cpt, visit) with visit in CODED.
    """
    provider, patient, visit = create_visit_in_progress(
        provider=provider, patient=patient, visit_overrides=visit_overrides
    )
    cpt = create_cpt_code(**(cpt_overrides or {"category": "EM", "base_fee_cents": 8000,
                                               "requires_em_level": True}))
    charge = dict(charge_overrides or {})
    if cpt.get("requires_em_level") and "em_level" not in charge:
        charge["em_level"] = 3
    add_charge_line(visit["id"], provider["id"], cpt["code"], **charge)
    prov_hdr = make_provider_headers(provider["id"])
    visit = get_success_data(api_client.code_visit(visit["id"], prov_hdr))
    return provider, patient, cpt, visit


def create_finalized_visit(provider=None, patient=None, cpt_overrides=None,
                           charge_overrides=None, visit_overrides=None):
    """Walk a visit all the way to FINALIZED. Returns (provider, patient, cpt, visit)."""
    provider, patient, cpt, visit = create_coded_visit(
        provider=provider, patient=patient, cpt_overrides=cpt_overrides,
        charge_overrides=charge_overrides, visit_overrides=visit_overrides
    )
    visit = get_success_data(api_client.finalize_visit(visit["id"], BILLER))
    return provider, patient, cpt, visit


# ─── Tier 3: Prescription lifecycle walks ─────────────────────────────

def create_prescription(patient_id, provider_id, visit_id, **overrides):
    """Create a DRAFT prescription (provider-owned). Returns prescription data."""
    prov_hdr = make_provider_headers(provider_id)
    return get_success_data(
        api_client.create_prescription(
            create_prescription_payload(patient_id, provider_id, visit_id, **overrides), prov_hdr
        )
    )


def create_prescription_pending(provider=None, patient=None, schedule="NON_CONTROLLED",
                                rx_overrides=None):
    """Create a prescription on an IN_PROGRESS visit and submit it.

    Returns (provider, patient, visit, rx) with rx in PENDING_SIGNATURE.
    """
    provider, patient, visit = create_visit_in_progress(provider=provider, patient=patient)
    prov_hdr = make_provider_headers(provider["id"])
    rx = create_prescription(patient["id"], provider["id"], visit["id"],
                             schedule=schedule, **(rx_overrides or {}))
    rx = get_success_data(api_client.submit_prescription(rx["id"], prov_hdr))
    return provider, patient, visit, rx


def create_prescription_transmitted(provider=None, patient=None, rx_overrides=None):
    """Walk a NON_CONTROLLED prescription DRAFT -> ... -> TRANSMITTED.

    Returns (provider, patient, visit, rx) with rx in TRANSMITTED.
    """
    provider, patient, visit, rx = create_prescription_pending(
        provider=provider, patient=patient, schedule="NON_CONTROLLED", rx_overrides=rx_overrides
    )
    prov_hdr = make_provider_headers(provider["id"])
    rx = get_success_data(api_client.sign_prescription(rx["id"], {}, prov_hdr))
    rx = get_success_data(api_client.transmit_prescription(rx["id"], prov_hdr))
    return provider, patient, visit, rx


# ─── Tier 4: Panel binding ────────────────────────────────────────────

def create_provider_with_panel_capacity(capacity):
    """Create a provider with a specific panel_capacity. Returns provider data."""
    return create_provider(panel_capacity=capacity)


def bind_patient(provider_id, patient_id, expected_provider_version):
    """Bind a patient to a provider as PCP. Returns the updated provider data."""
    return get_success_data(
        api_client.bind_panel(
            provider_id,
            {"patient_id": patient_id, "expected_provider_version": expected_provider_version},
            FD,
        )
    )


def create_pcp_bound_patient(provider_overrides=None, patient_overrides=None):
    """Create a provider + patient and bind the patient to the provider as PCP.

    Returns (provider_after_bind, patient).
    """
    provider = create_provider(**(provider_overrides or {}))
    patient = create_patient(**(patient_overrides or {}))
    provider_after = bind_patient(provider["id"], patient["id"], provider["version"])
    return provider_after, patient


# ─── Tier 5: Referral lifecycle ───────────────────────────────────────

def create_referral(patient_id, referring_provider_id, **overrides):
    """Create a REQUESTED referral (provider-owned). Returns referral data."""
    prov_hdr = make_provider_headers(referring_provider_id)
    return get_success_data(
        api_client.create_referral(
            create_referral_payload(patient_id, referring_provider_id, **overrides), prov_hdr
        )
    )


def create_authorized_referral(priority="ROUTINE", referral_overrides=None):
    """PCP-bound patient + a referral authorized by FrontDesk.

    Returns (provider, patient, referral) with referral in AUTHORIZED.
    """
    provider, patient = create_pcp_bound_patient()
    referral = create_referral(patient["id"], provider["id"],
                               priority=priority, **(referral_overrides or {}))
    referral = get_success_data(api_client.authorize_referral(referral["id"], FD))
    return provider, patient, referral


# ─── Tier 6: Portal accounts ──────────────────────────────────────────

def create_portal_account(patient_id, **overrides):
    """Invite a patient to the portal (INVITED). Returns (account, activation_token)."""
    data = get_success_data(
        api_client.create_portal_account(create_portal_account_payload(patient_id, **overrides), FD)
    )
    return data, data.get("activation_token")


def create_active_portal_account(patient=None):
    """Create a patient + INVITED portal account, then activate it.

    Returns (patient, account) with account in ACTIVE.
    """
    if patient is None:
        patient = create_patient()
    account, token = create_portal_account(patient["id"])
    pat_hdr = make_patient_headers(patient["id"])
    account = get_success_data(
        api_client.activate_portal_account(account["id"], {"activation_token": token}, pat_hdr)
    )
    return patient, account
