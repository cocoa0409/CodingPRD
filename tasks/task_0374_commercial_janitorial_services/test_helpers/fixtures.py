"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints,
using get_success_data() (lenient) so setup failures surface as clear errors.
The harness restarts the server with an empty DB before every test, so nothing
is carried over.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F
from .constants import DEFAULT_CONTACT_USER_ID

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
CC = TEST_USERS["client_contact_headers"]


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: basic entity creation
# ---------------------------------------------------------------------------
def create_account(**overrides) -> dict:
    resp = api_client.create_account(F.create_account_payload(**overrides), AM)
    return get_success_data(resp)


def create_site(account_id=None, **overrides) -> dict:
    if account_id is None:
        account_id = create_account()["id"]
    resp = api_client.create_site(F.create_site_payload(account_id, **overrides), AM)
    return get_success_data(resp)


def create_crew(**overrides) -> dict:
    resp = api_client.create_crew(F.create_crew_payload(**overrides), FS)
    return get_success_data(resp)


def create_active_contract(site_id, **overrides) -> dict:
    """Create a DRAFT contract for the site then activate it."""
    resp = api_client.create_contract(F.create_contract_payload(site_id, **overrides), AM)
    contract = get_success_data(resp)
    get_success_data(api_client.activate_contract(contract["id"], AM))
    return get_success_data(api_client.get_contract(contract["id"], AM))


def create_draft_contract(site_id, **overrides) -> dict:
    resp = api_client.create_contract(F.create_contract_payload(site_id, **overrides), AM)
    return get_success_data(resp)


def open_billing_period(contract_id, **overrides) -> dict:
    resp = api_client.create_billing_period(F.create_billing_period_payload(contract_id, **overrides), AM)
    return get_success_data(resp)


def get_account_version(account_id) -> int:
    return get_success_data(api_client.get_account(account_id, AM))["version"]


# ---------------------------------------------------------------------------
# Tier 2: common scenario bundles
# ---------------------------------------------------------------------------
def setup_account_site_crew(site_overrides=None, crew_overrides=None):
    """Active account + active site + available crew. Returns (account, site, crew)."""
    account = create_account()
    site = create_site(account["id"], **(site_overrides or {}))
    crew = create_crew(**(crew_overrides or {}))
    return account, site, crew


def setup_billing_scenario(site_overrides=None, contract_overrides=None, crew=True):
    """Active account + site + (optional) crew + active contract + OPEN period.
    Returns dict with account, site, crew, contract, period."""
    account = create_account()
    site = create_site(account["id"], **(site_overrides or {}))
    crew_obj = create_crew() if crew else None
    contract = create_active_contract(site["id"], **(contract_overrides or {}))
    period = open_billing_period(contract["id"])
    return {
        "account": account,
        "site": site,
        "crew": crew_obj,
        "contract": contract,
        "period": period,
    }


# ---------------------------------------------------------------------------
# Tier 3: visit lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_visit(site_id, crew_id, **overrides) -> dict:
    resp = api_client.create_visit(F.create_visit_payload(site_id, crew_id, **overrides), FS)
    return get_success_data(resp)


def start_visit(visit_id) -> dict:
    return get_success_data(api_client.start_visit(visit_id, FS))


def clock_full_entry(visit_id, crew_id, clock_in_min, clock_out_min) -> dict:
    """Create a time entry and clock it out (OPEN -> COMPLETED). Returns the entry."""
    te = get_success_data(api_client.create_time_entry(
        F.create_time_entry_payload(visit_id, crew_id, clock_in_min), FS))
    get_success_data(api_client.clock_out_time_entry(te["id"], {"clock_out_min": clock_out_min}, FS))
    return get_success_data(api_client.get_time_entry(te["id"], FS))


def create_started_visit(site_id, crew_id, **overrides) -> dict:
    """Create a ROUTINE visit and start it (SCHEDULED -> IN_PROGRESS)."""
    visit = create_visit(site_id, crew_id, **overrides)
    start_visit(visit["id"])
    return get_success_data(api_client.get_visit(visit["id"], FS))


def create_completed_routine_visit(site_id, crew_id, clock_in_min=480, clock_out_min=540, **overrides) -> dict:
    """Create a ROUTINE visit, start it, clock one full entry, complete it.
    Returns the COMPLETED visit."""
    visit = create_visit(site_id, crew_id, **overrides)
    start_visit(visit["id"])
    clock_full_entry(visit["id"], crew_id, clock_in_min, clock_out_min)
    return get_success_data(api_client.complete_visit(visit["id"], FS))


# ---------------------------------------------------------------------------
# Tier 3: periodic job lifecycle
# ---------------------------------------------------------------------------
def create_periodic_job(site_id, **overrides) -> dict:
    resp = api_client.create_periodic_job(F.create_periodic_job_payload(site_id, **overrides), AM)
    return get_success_data(resp)


def dispatch_periodic_job(job_id, crew_id, **overrides) -> dict:
    """Dispatch a REQUESTED periodic job; returns (job, visit_id)."""
    resp = api_client.dispatch_periodic_job(
        job_id, F.dispatch_periodic_job_payload(crew_id, **overrides), FS)
    job = get_success_data(resp)
    return job


def setup_dispatched_periodic_visit(site_id, crew_id, job_overrides=None, dispatch_overrides=None):
    """Request a periodic job + dispatch it (creates PERIODIC SCHEDULED visit).
    Returns (job, periodic_visit_id)."""
    job = create_periodic_job(site_id, **(job_overrides or {}))
    job = dispatch_periodic_job(job["id"], crew_id, **(dispatch_overrides or {}))
    return job, job["visit_id"]


def setup_completed_periodic_visit(site_id, crew_id, clock_in_min, clock_out_min,
                                   job_overrides=None, dispatch_overrides=None):
    """Dispatch a periodic job, clock its visit, complete it. Returns (job, visit)."""
    job, pvisit_id = setup_dispatched_periodic_visit(
        site_id, crew_id, job_overrides=job_overrides, dispatch_overrides=dispatch_overrides)
    start_visit(pvisit_id)
    clock_full_entry(pvisit_id, crew_id, clock_in_min, clock_out_min)
    visit = get_success_data(api_client.complete_visit(pvisit_id, FS))
    job = get_success_data(api_client.get_periodic_job(job["id"], AM))
    return job, visit


# ---------------------------------------------------------------------------
# Tier 3: complaint lifecycle
# ---------------------------------------------------------------------------
def raise_complaint(site_id, severity="MINOR", contact_headers=None, **overrides) -> dict:
    """Raise a complaint as the site's ClientContact (default CC headers)."""
    headers = contact_headers if contact_headers is not None else CC
    resp = api_client.create_complaint(
        F.create_complaint_payload(site_id, severity=severity, **overrides), headers)
    return get_success_data(resp)


def setup_callback_scheduled_complaint(site_id, crew_id, severity="MAJOR", contact_headers=None):
    """Raise a complaint, acknowledge, schedule callback. Returns (complaint, callback_visit_id)."""
    complaint = raise_complaint(site_id, severity=severity, contact_headers=contact_headers)
    get_success_data(api_client.acknowledge_complaint(complaint["id"], FS))
    cresp = api_client.schedule_callback(
        complaint["id"], F.schedule_callback_payload(crew_id), FS)
    complaint = get_success_data(cresp)
    return complaint, complaint["callback_visit_id"]


def setup_resolved_complaint(site_id, crew_id, severity="MAJOR", contact_headers=None):
    """Full path: raise -> acknowledge -> schedule-callback -> complete callback -> resolve.
    Returns the RESOLVED complaint."""
    complaint, cb_visit_id = setup_callback_scheduled_complaint(
        site_id, crew_id, severity=severity, contact_headers=contact_headers)
    start_visit(cb_visit_id)
    clock_full_entry(cb_visit_id, crew_id, 600, 660)
    get_success_data(api_client.complete_visit(cb_visit_id, FS))
    return get_success_data(api_client.resolve_complaint(complaint["id"], FS))


# ---------------------------------------------------------------------------
# Tier 5: billing-period finalization helpers
# ---------------------------------------------------------------------------
def close_period(period_id, account_id):
    """Close a period using the current account version. Returns the closed period."""
    ver = get_account_version(account_id)
    return get_success_data(api_client.close_billing_period(period_id, {"expected_account_version": ver}, AM))


def reopen_period(period_id, account_id):
    ver = get_account_version(account_id)
    return get_success_data(api_client.reopen_billing_period(period_id, {"expected_account_version": ver}, AM))


def setup_closed_period(site_overrides=None, contract_overrides=None):
    """Active account + site + active contract + OPEN period closed once.
    Returns dict with account, site, contract, period (CLOSED)."""
    bundle = setup_billing_scenario(site_overrides=site_overrides,
                                    contract_overrides=contract_overrides, crew=False)
    closed = close_period(bundle["period"]["id"], bundle["account"]["id"])
    bundle["period"] = closed
    return bundle
