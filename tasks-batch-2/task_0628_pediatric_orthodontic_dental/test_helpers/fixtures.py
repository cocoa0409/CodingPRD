"""Composite setup helpers.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints, since the server database is empty at the start of every test. All
calls use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors.

Identity threading: after creating a Provider we drive Orthodontist-scoped calls
with make_orthodontist_headers(provider_user_id); after creating a FamilyAccount
we drive Guardian-scoped calls (activate) with make_guardian_headers(guardian_user_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_orthodontist_headers, make_guardian_headers,
)
from . import factories as F


# Monotonic suffix so repeated fixture calls in one test never collide on
# provider_user_id / guardian_user_id / npi.
_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def set_clock(iso8601: str):
    """Advance the logical clock (ClinicAdmin)."""
    return get_success_data(
        api_client.set_clock(iso8601, TEST_USERS["admin_headers"])
    )


# -----------------------------------------------------------------------------
# Base actors
# -----------------------------------------------------------------------------

def create_family(guardian_user_id=None, **overrides):
    """Create a FamilyAccount. Returns the account dict."""
    n = _next()
    gid = guardian_user_id or f"guardian-{n}"
    payload = F.create_family_account_payload(
        family_name=overrides.pop("family_name", f"Fam{n}"),
        billing_email=overrides.pop("billing_email", f"fam{n}@x.com"),
        guardian_user_id=gid,
        **overrides,
    )
    return get_success_data(
        api_client.create_family_account(payload, TEST_USERS["frontdesk_headers"])
    )


def create_patient(family_account_id, **overrides):
    """Register a Patient under a family. Returns the patient dict."""
    n = _next()
    payload = F.create_patient_payload(
        family_account_id,
        full_name=overrides.pop("full_name", f"Patient{n}"),
        **overrides,
    )
    return get_success_data(
        api_client.create_patient(payload, TEST_USERS["frontdesk_headers"])
    )


def create_provider(**overrides):
    """Create a Provider (ClinicAdmin). Returns (provider_dict, provider_user_id)."""
    n = _next()
    puid = overrides.pop("provider_user_id", f"ortho-{n}")
    npi = overrides.pop("npi", f"10000000{n:02d}"[:10].ljust(10, "0"))
    payload = F.create_provider_payload(
        provider_user_id=puid, full_name=f"Dr {n}", npi=npi, **overrides,
    )
    prov = get_success_data(
        api_client.create_provider(payload, TEST_USERS["admin_headers"])
    )
    return prov, puid


def create_chair(turnover_buffer_minutes=10, **overrides):
    """Create a Chair (ClinicAdmin). Returns the chair dict."""
    n = _next()
    payload = F.create_chair_payload(
        label=overrides.pop("label", f"Chair{n}"),
        turnover_buffer_minutes=turnover_buffer_minutes,
        **overrides,
    )
    return get_success_data(
        api_client.create_chair(payload, TEST_USERS["admin_headers"])
    )


# -----------------------------------------------------------------------------
# Growth records / clinical gate
# -----------------------------------------------------------------------------

def finalize_records_complete(patient_id, provider_user_id, taken_at="2026-02-01T00:00:00Z"):
    """Create + finalize a PANO and a CEPH so the patient's records_complete
    becomes true. Returns (pano_id, ceph_id)."""
    ortho = make_orthodontist_headers(provider_user_id)
    pano = get_success_data(api_client.create_growth_record(
        F.create_growth_record_payload(patient_id, "PANO", taken_at=taken_at), ortho))
    get_success_data(api_client.finalize_growth_record(pano["id"], ortho))
    ceph = get_success_data(api_client.create_growth_record(
        F.create_growth_record_payload(patient_id, "CEPH", taken_at=taken_at), ortho))
    get_success_data(api_client.finalize_growth_record(ceph["id"], ortho))
    return pano["id"], ceph["id"]


# -----------------------------------------------------------------------------
# Plan lifecycle helpers
# -----------------------------------------------------------------------------

def create_plan_with_phases(patient_id, provider_user_id, phase_fees,
                            modality="BRACES", policy_id=None):
    """Create a DRAFT plan with the given list of phase fees. Returns the plan dict."""
    ortho = make_orthodontist_headers(provider_user_id)
    overrides = {}
    if policy_id is not None:
        overrides["policy_id"] = policy_id
    plan = get_success_data(api_client.create_treatment_plan(
        F.create_treatment_plan_payload(patient_id, modality=modality, **overrides), ortho))
    for i, fee in enumerate(phase_fees, start=1):
        get_success_data(api_client.create_treatment_phase(
            F.create_treatment_phase_payload(plan["id"], i, fee), ortho))
    return plan


def propose_plan(plan_id, provider_user_id):
    ortho = make_orthodontist_headers(provider_user_id)
    return get_success_data(api_client.propose_treatment_plan(plan_id, ortho))


def activate_plan(plan_id, guardian_user_id):
    guardian = make_guardian_headers(guardian_user_id)
    return get_success_data(api_client.activate_treatment_plan(plan_id, guardian))


def setup_active_plan(phase_fees, modality="BRACES", policy_id=None,
                      guardian_user_id=None, provider_user_id=None,
                      family=None, set_clock_to="2026-02-01T00:00:00Z"):
    """Full chain to an ACTIVE plan for a single fresh patient:
      clock -> family -> patient -> provider -> records complete ->
      plan + phases -> propose -> activate.

    Returns a dict with keys: family, patient, provider, provider_user_id,
    guardian_user_id, plan (the activated plan, with pinned fees).
    """
    if set_clock_to:
        set_clock(set_clock_to)
    if family is None:
        family = create_family(guardian_user_id=guardian_user_id)
    guardian_user_id = family["guardian_user_id"]
    patient = create_patient(family["id"])
    provider, provider_user_id = create_provider(
        **({"provider_user_id": provider_user_id} if provider_user_id else {}))
    finalize_records_complete(patient["id"], provider_user_id)
    plan = create_plan_with_phases(
        patient["id"], provider_user_id, phase_fees,
        modality=modality, policy_id=policy_id)
    propose_plan(plan["id"], provider_user_id)
    activated = activate_plan(plan["id"], guardian_user_id)
    return {
        "family": family,
        "patient": patient,
        "provider": provider,
        "provider_user_id": provider_user_id,
        "guardian_user_id": guardian_user_id,
        "plan": activated,
    }


def setup_proposed_plan(phase_fees, modality="BRACES", policy_id=None,
                        records_complete=True, guardian_user_id=None,
                        set_clock_to="2026-02-01T00:00:00Z"):
    """Chain to a PROPOSED plan. By default the patient's records are complete;
    set records_complete=False to leave the clinical gate unmet.

    Returns dict: family, patient, provider, provider_user_id,
    guardian_user_id, plan (PROPOSED).
    """
    if set_clock_to:
        set_clock(set_clock_to)
    family = create_family(guardian_user_id=guardian_user_id)
    guardian_user_id = family["guardian_user_id"]
    patient = create_patient(family["id"])
    provider, provider_user_id = create_provider()
    if records_complete:
        finalize_records_complete(patient["id"], provider_user_id)
    plan = create_plan_with_phases(
        patient["id"], provider_user_id, phase_fees,
        modality=modality, policy_id=policy_id)
    proposed = propose_plan(plan["id"], provider_user_id)
    return {
        "family": family,
        "patient": patient,
        "provider": provider,
        "provider_user_id": provider_user_id,
        "guardian_user_id": guardian_user_id,
        "plan": proposed,
    }


# -----------------------------------------------------------------------------
# Contract / installment helpers
# -----------------------------------------------------------------------------

def create_contract(plan_id, expected_plan_version, term_months=3,
                    down_payment_cents=0, **overrides):
    """Create a contract (BillingSpecialist). Returns the contract dict."""
    payload = F.create_contract_payload(
        plan_id, expected_plan_version, term_months=term_months,
        down_payment_cents=down_payment_cents, **overrides)
    return get_success_data(
        api_client.create_contract(payload, TEST_USERS["billing_headers"]))


def list_installments(contract_id):
    """Return the contract's installments sorted by created_at ascending
    (PRD 2.3 default sort)."""
    data, _meta = _paginated(api_client.list_installments(
        TEST_USERS["billing_headers"], params={"contract_id": contract_id}))
    return data


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


def setup_active_plan_with_contract(phase_fees=(90000,), term_months=3,
                                    down_payment_cents=0,
                                    set_clock_to="2026-02-01T00:00:00Z"):
    """ACTIVE self-pay plan + a contract financing it. Returns dict with keys
    from setup_active_plan plus: contract, installments (list)."""
    ctx = setup_active_plan(list(phase_fees), set_clock_to=set_clock_to)
    contract = create_contract(
        ctx["plan"]["id"], ctx["plan"]["version"],
        term_months=term_months, down_payment_cents=down_payment_cents)
    ctx["contract"] = contract
    ctx["installments"] = list_installments(contract["id"])
    return ctx


# -----------------------------------------------------------------------------
# Insurance helpers
# -----------------------------------------------------------------------------

def create_policy(patient_id, ortho_rider=True, ortho_coverage_pct=0.50,
                  lifetime_max_cents=200000, **overrides):
    """Create an InsurancePolicy (BillingSpecialist). Returns the policy dict."""
    payload = F.create_insurance_policy_payload(
        patient_id, ortho_rider=ortho_rider,
        ortho_coverage_pct=ortho_coverage_pct,
        lifetime_max_cents=lifetime_max_cents, **overrides)
    return get_success_data(
        api_client.create_insurance_policy(payload, TEST_USERS["billing_headers"]))


def submit_claim(policy_id, plan_id, billed_amount_cents):
    """Submit a claim (BillingSpecialist). Returns the claim dict."""
    payload = F.create_insurance_claim_payload(policy_id, plan_id, billed_amount_cents)
    return get_success_data(
        api_client.create_insurance_claim(payload, TEST_USERS["billing_headers"]))


def approve_claim(claim_id):
    return get_success_data(
        api_client.approve_insurance_claim(claim_id, TEST_USERS["billing_headers"]))


# -----------------------------------------------------------------------------
# Appointment helpers
# -----------------------------------------------------------------------------

def create_appointment(patient_id, provider_id, chair_id, visit_type,
                       starts_at, ends_at, plan_id=None):
    """Schedule an appointment (FrontDesk). Returns the appointment dict."""
    overrides = {}
    if plan_id is not None:
        overrides["plan_id"] = plan_id
    payload = F.create_appointment_payload(
        patient_id, provider_id, chair_id, visit_type, starts_at, ends_at, **overrides)
    return get_success_data(
        api_client.create_appointment(payload, TEST_USERS["frontdesk_headers"]))
