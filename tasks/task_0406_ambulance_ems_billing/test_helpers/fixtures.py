"""Composite setup helpers for the Ambulance EMS Billing API.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Helpers use
the lenient get_success_data() so setup failures surface as clear "Setup failed".

Identity threading: every entity-backed role (Dispatcher, Coder, Biller,
ComplianceOfficer) acts under make_<role>_headers(staff_id) with the real
AgencyStaff id, never a shared constant — ownership/authority checks compare the
resource FK to X-User-ID.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_billing_admin_headers,
    make_dispatcher_headers,
    make_coder_headers,
    make_biller_headers,
    make_compliance_headers,
)
from . import factories as F


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: Agency org bootstrap (agency + full staff roster)
# ---------------------------------------------------------------------------

def setup_agency_org(*, with_compliance=True, pcs_authority=True, **agency_overrides) -> dict:
    """Create an ACTIVE agency plus a Dispatcher, Coder, Biller and (optionally) a
    ComplianceOfficer. Returns a dict of ids and ready-to-use header bundles.

    Keys: agency, dispatcher_id/coder_id/biller_id/compliance_id,
    admin_h, dispatcher_h, coder_h, biller_h, compliance_h.
    """
    admin_h = make_billing_admin_headers()
    agency = get_success_data(api_client.create_agency(F.create_agency_payload(**agency_overrides), admin_h))
    ag = agency["id"]

    disp = get_success_data(api_client.create_staff(
        F.create_staff_payload(ag, "Dispatcher", full_name="Dee Patcher"), admin_h))
    coder = get_success_data(api_client.create_staff(
        F.create_staff_payload(ag, "Coder", full_name="Cody Coder"), admin_h))
    biller = get_success_data(api_client.create_staff(
        F.create_staff_payload(ag, "Biller", full_name="Bill Biller"), admin_h))

    out = {
        "agency": agency,
        "dispatcher_id": disp["id"],
        "coder_id": coder["id"],
        "biller_id": biller["id"],
        "admin_h": admin_h,
        "dispatcher_h": make_dispatcher_headers(disp["id"]),
        "coder_h": make_coder_headers(coder["id"]),
        "biller_h": make_biller_headers(biller["id"]),
    }
    if with_compliance:
        comp = get_success_data(api_client.create_staff(
            F.create_staff_payload(ag, "ComplianceOfficer", full_name="Cara Compliance",
                                   pcs_signature_authority=pcs_authority), admin_h))
        out["compliance_id"] = comp["id"]
        out["compliance_h"] = make_compliance_headers(comp["id"])
    return out


def create_medicare_plan(org: dict, **overrides) -> dict:
    """Create an ACTIVE Medicare plan (bootstrap-open). allows_balance_billing default false."""
    plan_kwargs = {"name": "Medicare Part B", "allows_balance_billing": False}
    plan_kwargs.update(overrides)
    payload = F.create_payer_plan_payload("MEDICARE", **plan_kwargs)
    return get_success_data(api_client.create_payer_plan(payload, org["admin_h"]))


def create_plan(org: dict, payer_type: str, **overrides) -> dict:
    """Create an ACTIVE payer plan of the given type (bootstrap-open)."""
    payload = F.create_payer_plan_payload(payer_type, **overrides)
    return get_success_data(api_client.create_payer_plan(payload, org["admin_h"]))


def create_patient_with_coverages(org: dict, coverages, **overrides) -> dict:
    """Create a patient holding the given coverage list [{payer_plan_id, policy_rank}, ...]."""
    payload = F.create_patient_payload(coverages=coverages, **overrides)
    return get_success_data(api_client.create_patient(payload, org["admin_h"]))


# ---------------------------------------------------------------------------
# Tier 1: Transport state-progression helpers
# ---------------------------------------------------------------------------

def import_transport(org: dict, patient_id: str, run_number: str, **overrides) -> dict:
    """Import a NEMSIS run (documentation IMPORTED, billing UNBILLED)."""
    payload = F.create_transport_payload(org["agency"]["id"], patient_id, run_number, **overrides)
    return get_success_data(api_client.create_transport(payload, org["dispatcher_h"]))


def code_transport(org: dict, transport_id: str, level_of_service: str) -> dict:
    """Code a transport (IMPORTED -> CODED); synthesizes charges."""
    return get_success_data(api_client.code_transport(
        transport_id, F.code_transport_payload(level_of_service), org["coder_h"]))


def import_and_code(org: dict, patient_id: str, run_number: str, level_of_service: str, **overrides) -> dict:
    """Import + code; returns the coded transport."""
    t = import_transport(org, patient_id, run_number, **overrides)
    code_transport(org, t["id"], level_of_service)
    return get_success_data(api_client.get_transport(t["id"], org["biller_h"]))


def setup_documentation_complete(org: dict, patient_id: str, run_number: str,
                                 level_of_service: str = "ALS1", **overrides) -> dict:
    """Walk a transport all the way to documentation_status DOCUMENTATION_COMPLETE
    (import -> code -> attest-necessity -> sign-pcs). Returns the transport dict.

    Requires org to include a compliance officer with pcs_signature_authority.
    """
    t = import_transport(org, patient_id, run_number, **overrides)
    tid = t["id"]
    code_transport(org, tid, level_of_service)
    get_success_data(api_client.attest_necessity(tid, org["coder_h"]))
    get_success_data(api_client.sign_pcs(tid, org["compliance_h"]))
    return get_success_data(api_client.get_transport(tid, org["biller_h"]))


def transport_version(org: dict, transport_id: str) -> int:
    """Read the current transport version (for the OCC expected_transport_version field)."""
    t = get_success_data(api_client.get_transport(transport_id, org["biller_h"]))
    return t["version"]


# ---------------------------------------------------------------------------
# Tier 3: Claim lifecycle shortcuts
# ---------------------------------------------------------------------------

def submit_primary_claim(org: dict, transport_id: str, payer_plan_id: str) -> dict:
    """Submit the primary claim against a DOCUMENTATION_COMPLETE transport.
    Reads the live version first so expected_transport_version matches."""
    v = transport_version(org, transport_id)
    payload = F.create_claim_payload(payer_plan_id, v)
    return get_success_data(api_client.create_claim(transport_id, payload, org["biller_h"]))


def submit_secondary_claim(org: dict, transport_id: str, payer_plan_id: str, prior_claim_id: str) -> dict:
    """Submit a secondary/tertiary claim naming prior_claim_id."""
    v = transport_version(org, transport_id)
    payload = F.create_claim_payload(payer_plan_id, v, prior_claim_id=prior_claim_id)
    return get_success_data(api_client.create_claim(transport_id, payload, org["biller_h"]))


def post_remittance(org: dict, claim_id: str, outcome: str, paid_cents: int, **overrides) -> dict:
    """Post a remittance line adjudicating a claim."""
    payload = F.create_remittance_payload(outcome, paid_cents, **overrides)
    return get_success_data(api_client.create_remittance(claim_id, payload, org["biller_h"]))


def setup_submitted_primary_claim(org: dict, patient_id: str, run_number: str, payer_plan_id: str,
                                  level_of_service: str = "ALS1", **transport_overrides) -> dict:
    """Full chain to a SUBMITTED primary claim. Returns {"transport", "claim"}."""
    t = setup_documentation_complete(org, patient_id, run_number, level_of_service, **transport_overrides)
    claim = submit_primary_claim(org, t["id"], payer_plan_id)
    return {"transport": t, "claim": claim}


def setup_paid_primary_claim(org: dict, patient_id: str, run_number: str, payer_plan_id: str,
                             paid_cents: int, level_of_service: str = "ALS1",
                             remittance_overrides=None, **transport_overrides) -> dict:
    """Full chain to a PAID primary claim (Medicare default). After the remittance the
    billing dimension auto-advances. Returns {"transport", "claim", "remittance"}.

    remittance_overrides may carry e.g. reported_allowed_cents.
    """
    sub = setup_submitted_primary_claim(org, patient_id, run_number, payer_plan_id,
                                        level_of_service, **transport_overrides)
    rem = post_remittance(org, sub["claim"]["id"], "PAID", paid_cents, **(remittance_overrides or {}))
    transport = get_success_data(api_client.get_transport(sub["transport"]["id"], org["biller_h"]))
    claim = get_success_data(api_client.get_claim(sub["claim"]["id"], org["biller_h"]))
    return {"transport": transport, "claim": claim, "remittance": rem}


# ---------------------------------------------------------------------------
# Tier 4: PATIENT_BALANCE targeting (Medicare cost-share = 10120 for ALS1-emerg 12mi PAID 40480)
# ---------------------------------------------------------------------------

def setup_medicare_patient_balance(org: dict, patient_id: str, run_number: str, medicare_plan_id: str) -> dict:
    """Bill a standard Medicare ALS1-emergency 12mi transport through to PATIENT_BALANCE
    with patient_responsibility_cents == 10120 (billed 101000, allowed 50600,
    paid 40480, contractual 50400). Returns {"transport", "claim"}."""
    res = setup_paid_primary_claim(org, patient_id, run_number, medicare_plan_id, paid_cents=40480,
                                   level_of_service="ALS1", loaded_miles=12.0, emergency_indicator=True)
    return {"transport": res["transport"], "claim": res["claim"]}


# ---------------------------------------------------------------------------
# Fleet helpers (UnitAssignment scheduling)
# ---------------------------------------------------------------------------

def create_vehicle(org: dict, **overrides) -> dict:
    return get_success_data(api_client.create_vehicle(
        F.create_vehicle_payload(org["agency"]["id"], **overrides), org["admin_h"]))


def create_crew(org: dict, certification: str = "PARAMEDIC", **overrides) -> dict:
    return get_success_data(api_client.create_crew_member(
        F.create_crew_member_payload(org["agency"]["id"], certification, **overrides), org["admin_h"]))


def create_assignment(org: dict, transport_id, vehicle_id, crew_member_id, start_iso, end_iso) -> dict:
    payload = F.create_unit_assignment_payload(transport_id, vehicle_id, crew_member_id, start_iso, end_iso)
    return get_success_data(api_client.create_unit_assignment(payload, org["dispatcher_h"]))
