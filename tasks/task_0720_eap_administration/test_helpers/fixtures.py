"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty DB before every test).
Setup calls use get_success_data() so setup failures surface clearly.

Identity threading: after creating a Provider (entity-backed role), any
ownership-gated call uses make_provider_headers(provider["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_provider_headers
from . import factories as F

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]
CRISIS = TEST_USERS["crisis_counselor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock control + atomic creators
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_contract(**overrides) -> dict:
    return get_success_data(
        api_client.create_contract(F.create_contract_payload(**overrides), ADMIN))


def create_published_plan(contract_id, **overrides) -> dict:
    plan = get_success_data(
        api_client.create_plan(F.create_plan_payload(contract_id, **overrides), ADMIN))
    return get_success_data(api_client.publish_plan(plan["id"], ADMIN))


def create_draft_plan(contract_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_plan(F.create_plan_payload(contract_id, **overrides), ADMIN))


def create_employee(contract_id, plan_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee(
            F.create_employee_payload(contract_id, plan_id, **overrides), ADMIN))


def create_provider(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider(F.create_provider_payload(**overrides), ADMIN))


def create_case(contract_id, employee_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_case(
            F.create_case_payload(contract_id, employee_id, **overrides), COORD))


# ---------------------------------------------------------------------------
# Tier 1: contract + published plan + employee bundle
# ---------------------------------------------------------------------------
def setup_contract_plan_employee(contract_overrides=None, plan_overrides=None,
                                 employee_overrides=None):
    """Active contract + published plan + one ELIGIBLE employee.
    Returns (contract, plan, employee). The contract dict carries version."""
    contract = create_contract(**(contract_overrides or {}))
    plan = create_published_plan(contract["id"], **(plan_overrides or {}))
    employee = create_employee(contract["id"], plan["id"], **(employee_overrides or {}))
    return contract, plan, employee


# ---------------------------------------------------------------------------
# Tier 2: authorized case (with provider) ready for scheduling
# ---------------------------------------------------------------------------
def setup_authorized_case(contract_overrides=None, plan_overrides=None,
                          employee_overrides=None, provider_overrides=None,
                          case_overrides=None, clock=None):
    """Active contract + published plan + employee + provider + AUTHORIZED case.
    Optionally advances the clock after authorize so sessions can be scheduled.
    Returns (contract, plan, employee, provider, case)."""
    contract, plan, employee = setup_contract_plan_employee(
        contract_overrides, plan_overrides, employee_overrides)
    provider = create_provider(**(provider_overrides or {}))
    case = create_case(contract["id"], employee["id"], **(case_overrides or {}))
    case = get_success_data(api_client.authorize_case(
        case["id"], {"expected_contract_version": contract["version"]}, COORD))
    if clock is not None:
        set_clock(clock)
    return contract, plan, employee, provider, case


def schedule_session(case_id, provider_id, scheduled_for, **overrides) -> dict:
    return get_success_data(api_client.create_session(
        case_id, F.create_session_payload(provider_id, scheduled_for, **overrides), COORD))


def complete_session(session_id, provider) -> dict:
    """Advance a session to COMPLETED via the acting provider (entity-backed)."""
    return get_success_data(api_client.set_session_status(
        session_id, {"to_status": "COMPLETED"}, make_provider_headers(provider["id"])))


# ---------------------------------------------------------------------------
# Tier 3: claim lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_completed_session(contract_overrides=None, plan_overrides=None,
                            provider_overrides=None, scheduled_for="2026-03-02T10:00:00Z",
                            clock="2026-03-02T09:00:00Z"):
    """Active contract/plan/employee/provider + AUTHORIZED case + one COMPLETED
    session. Returns (contract, plan, employee, provider, case, session)."""
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides=contract_overrides, plan_overrides=plan_overrides,
        provider_overrides=provider_overrides, clock=clock)
    session = schedule_session(case["id"], provider["id"], scheduled_for)
    session = complete_session(session["id"], provider)
    return contract, plan, employee, provider, case, session


def submit_claim(contract_id, session_id, billed_cents=12000, provider=None) -> dict:
    headers = make_provider_headers(provider["id"]) if provider else TEST_USERS["provider_headers"]
    return get_success_data(api_client.create_claim(
        F.create_claim_payload(contract_id, session_id, billed_cents), headers))


def drive_claim_to_approved(contract_id, session_id, billed_cents, provider) -> dict:
    """submit -> review -> approve. Returns the APPROVED claim (final_cents set)."""
    claim = submit_claim(contract_id, session_id, billed_cents, provider)
    get_success_data(api_client.review_claim(claim["id"], ADMIN))
    return get_success_data(api_client.approve_claim(claim["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: crisis-line shortcuts
# ---------------------------------------------------------------------------
def setup_triaged_crisis_contact(disposition, severity="MODERATE",
                                 crisis_sla_minutes=15, opened_clock="2026-03-02T08:00:00Z",
                                 triage_clock=None):
    """Contract + crisis contact opened at opened_clock + triaged with the given
    disposition (optionally after advancing the clock to triage_clock).
    Returns (contract, crisis_contact)."""
    contract = create_contract(crisis_sla_minutes=crisis_sla_minutes)
    set_clock(opened_clock)
    cc = get_success_data(api_client.create_crisis_contact(
        F.create_crisis_contact_payload(contract["id"], severity=severity), CRISIS))
    if triage_clock is not None:
        set_clock(triage_clock)
    cc = get_success_data(api_client.triage_crisis_contact(
        cc["id"], {"disposition": disposition}, CRISIS))
    return contract, cc


# ---------------------------------------------------------------------------
# Tier 5: referral shortcuts
# ---------------------------------------------------------------------------
def setup_referral(required_specialty="STRESS", referral_type="WORKLIFE",
                   provider_specs=None, worklife_referrals_per_year=5):
    """Active contract + published plan + employee + N providers + one auto-assigned
    referral. provider_specs is a list of provider payload override dicts (one per
    provider to create, in creation order). Returns (contract, employee, providers, referral)."""
    contract, plan, employee = setup_contract_plan_employee(
        plan_overrides={"worklife_referrals_per_year": worklife_referrals_per_year})
    specs = provider_specs if provider_specs is not None else [{}]
    providers = [create_provider(**spec) for spec in specs]
    referral = get_success_data(api_client.create_referral(
        F.create_referral_payload(employee["id"], required_specialty,
                                  referral_type=referral_type), COORD))
    return contract, employee, providers, referral
