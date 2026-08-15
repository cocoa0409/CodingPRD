"""Composite setup helpers.

Nearly every meaningful claim in this PRD requires the same multi-step chain:
carrier -> program -> guideline (OCC) -> capacity allocation (OCC) ->
rate filing -> submit -> approve -> mark-effective -> activate. The helpers
below package that chain and its common extensions (issued policy, TPA
appointment, claim in a given state) so tests can focus on assertions.

All helpers use get_success_data() so a setup failure surfaces as a clear
"Setup failed" rather than a confusing assertion error. Identity threading:
every ownership-gated carrier call uses make_carrier_underwriter_headers on
the real Carrier.id; every adjuster call uses make_tpa_adjuster_headers on
the real TPA.id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_allocation_payload,
    create_appointment_payload,
    create_audit_payload,
    create_bordereau_payload,
    create_carrier_payload,
    create_claim_payload,
    create_guideline_payload,
    create_policy_payload,
    create_program_payload,
    create_rate_filing_payload,
    create_tpa_payload,
)
from .test_users import (
    TEST_USERS,
    make_carrier_underwriter_headers,
    make_tpa_adjuster_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]
AUD = TEST_USERS["carrier_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: counterparties and program scaffolding
# ---------------------------------------------------------------------------

def create_carrier(**overrides):
    resp = api_client.create_carrier(create_carrier_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_tpa(**overrides):
    resp = api_client.create_tpa(create_tpa_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_program(carrier, **overrides):
    """Create a PROPOSED program under the given carrier entity."""
    payload = create_program_payload(carrier["id"], **overrides)
    resp = api_client.create_program(payload, UW)
    return get_success_data(resp)


def create_guideline(program, **overrides):
    """Create a guideline with a fresh expected_program_version (OCC)."""
    current = get_success_data(api_client.get_program(program["id"], UW))
    payload = create_guideline_payload(current["version"], **overrides)
    resp = api_client.create_guideline(program["id"], payload, UW)
    return get_success_data(resp)


def create_allocation(program, **overrides):
    """Create a capacity tranche with a fresh expected_program_version (OCC)."""
    cu = make_carrier_underwriter_headers(program["carrier_id"])
    current = get_success_data(api_client.get_program(program["id"], cu))
    payload = create_allocation_payload(current["version"], **overrides)
    resp = api_client.create_capacity_allocation(program["id"], payload, cu)
    return get_success_data(resp)


def create_filing(program, **overrides):
    resp = api_client.create_rate_filing(
        program["id"], create_rate_filing_payload(**overrides), UW)
    return get_success_data(resp)


def move_filing_to_effective(filing, program):
    """DRAFT -> SUBMITTED -> APPROVED -> EFFECTIVE (carrier = program's owner)."""
    cu = make_carrier_underwriter_headers(program["carrier_id"])
    get_success_data(api_client.submit_filing(filing["id"], UW))
    get_success_data(api_client.approve_filing(filing["id"], cu))
    return get_success_data(api_client.mark_effective_filing(filing["id"], cu))


# ---------------------------------------------------------------------------
# Tier 2: full program activation
# ---------------------------------------------------------------------------

def setup_active_program(program_overrides=None, guideline_overrides=None,
                         allocation_overrides=None, filing_overrides=None):
    """Carrier + PROPOSED program + ACTIVE guideline + ACTIVE tranche +
    EFFECTIVE filing + program ACTIVATED.

    Returns (carrier, program, guideline, allocation, filing) with the
    program dict refreshed post-activation.
    """
    carrier = create_carrier()
    program = create_program(carrier, **(program_overrides or {}))
    guideline = create_guideline(program, **(guideline_overrides or {}))
    allocation = create_allocation(program, **(allocation_overrides or {}))
    filing = create_filing(program, **(filing_overrides or {}))
    move_filing_to_effective(filing, program)
    cu = make_carrier_underwriter_headers(carrier["id"])
    get_success_data(api_client.activate_program(program["id"], cu))
    program = get_success_data(api_client.get_program(program["id"], UW))
    return carrier, program, guideline, allocation, filing


def setup_prepared_program(program_overrides=None, guideline_overrides=None,
                           allocation_overrides=None, filing_overrides=None):
    """Same chain as setup_active_program but the program is left PROPOSED
    (filing EFFECTIVE, guideline ACTIVE, tranche ACTIVE) — for tests that
    exercise activation itself."""
    carrier = create_carrier()
    program = create_program(carrier, **(program_overrides or {}))
    guideline = create_guideline(program, **(guideline_overrides or {}))
    allocation = create_allocation(program, **(allocation_overrides or {}))
    filing = create_filing(program, **(filing_overrides or {}))
    move_filing_to_effective(filing, program)
    program = get_success_data(api_client.get_program(program["id"], UW))
    return carrier, program, guideline, allocation, filing


# ---------------------------------------------------------------------------
# Tier 3: policies through the lifecycle
# ---------------------------------------------------------------------------

def quote_policy(program, **overrides):
    resp = api_client.create_policy(
        program["id"], create_policy_payload(**overrides), UW)
    return get_success_data(resp)


def bind_policy(policy):
    get_success_data(api_client.bind_policy(policy["id"], UW))
    return get_success_data(api_client.get_policy(policy["id"], UW))


def collect_premium(policy, amount_cents):
    return get_success_data(api_client.record_collection(
        policy["id"], {"amount_cents": amount_cents}, FIN))


def issue_policy(policy):
    get_success_data(api_client.issue_policy(policy["id"], UW))
    return get_success_data(api_client.get_policy(policy["id"], UW))


def create_bound_policy(program, collect=False, **overrides):
    """Quote + bind. Returns the bound policy dict."""
    policy = quote_policy(program, **overrides)
    policy = bind_policy(policy)
    if collect:
        collect_premium(policy, policy["gross_premium_cents"])
        policy = get_success_data(api_client.get_policy(policy["id"], UW))
    return policy


def create_issued_policy(program, **overrides):
    """Quote + bind + full collection + issue. Returns the issued policy."""
    policy = create_bound_policy(program, collect=True, **overrides)
    return issue_policy(policy)


def create_cancelled_policy(program, cancellation_date, reason, **overrides):
    """Issued policy -> PENDING_CANCELLATION -> run-daily -> CANCELLED."""
    policy = create_issued_policy(program, **overrides)
    get_success_data(api_client.cancel_policy(
        policy["id"], {"cancellation_date": cancellation_date, "reason": reason}, UW))
    get_success_data(api_client.run_daily(ADMIN))
    return get_success_data(api_client.get_policy(policy["id"], UW))


# ---------------------------------------------------------------------------
# Tier 4: appointments and claims
# ---------------------------------------------------------------------------

def create_active_appointment(program, tpa, **overrides):
    """Create + activate an appointment for the given TPA entity."""
    cu = make_carrier_underwriter_headers(program["carrier_id"])
    payload = create_appointment_payload(tpa["id"], **overrides)
    appt = get_success_data(api_client.create_appointment(program["id"], payload, cu))
    get_success_data(api_client.activate_appointment(appt["id"], cu))
    return get_success_data(api_client.get_appointment(appt["id"], cu))


def report_claim(policy, **overrides):
    resp = api_client.report_claim(
        policy["id"], create_claim_payload(**overrides), UW)
    return get_success_data(resp)


def create_claim_under_review(program, policy, tpa, **overrides):
    claim = report_claim(policy, **overrides)
    get_success_data(api_client.start_claim_review(
        claim["id"], make_tpa_adjuster_headers(tpa["id"])))
    return get_success_data(api_client.get_claim(claim["id"], UW))


def create_paid_claim(program, policy, tpa, approved_amount_cents, **overrides):
    """Claim walked REPORTED -> UNDER_REVIEW -> APPROVED -> PAID."""
    claim = create_claim_under_review(program, policy, tpa, **overrides)
    tpa_h = make_tpa_adjuster_headers(tpa["id"])
    get_success_data(api_client.approve_claim(
        claim["id"], {"approved_amount_cents": approved_amount_cents}, tpa_h))
    get_success_data(api_client.pay_claim(claim["id"], tpa_h))
    return get_success_data(api_client.get_claim(claim["id"], UW))


# ---------------------------------------------------------------------------
# Tier 5: standard active program with TPA + issued policy (claims-ready)
# ---------------------------------------------------------------------------

def setup_program_with_issued_policy_and_tpa(program_overrides=None,
                                             policy_overrides=None,
                                             appointment_overrides=None,
                                             guideline_overrides=None,
                                             allocation_overrides=None):
    """Active program + TPA + ACTIVE LIABILITY appointment + issued policy
    (gross fully collected). Returns (carrier, program, tpa, appt, policy).
    guideline/allocation overrides are threaded into the program setup so
    tests can size the premium cap and tranche for larger policies."""
    carrier, program, guideline, allocation, filing = setup_active_program(
        program_overrides=program_overrides,
        guideline_overrides=guideline_overrides,
        allocation_overrides=allocation_overrides)
    tpa = create_tpa()
    appt = create_active_appointment(program, tpa, **(appointment_overrides or {}))
    policy = create_issued_policy(program, **(policy_overrides or {}))
    return carrier, program, tpa, appt, policy


# ---------------------------------------------------------------------------
# Ops helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_daily():
    return get_success_data(api_client.run_daily(ADMIN))


def get_program_fresh(program_id, headers=None):
    return get_success_data(api_client.get_program(program_id, headers or UW))


def get_policy_fresh(policy_id, headers=None):
    return get_success_data(api_client.get_policy(policy_id, headers or UW))


def get_claim_fresh(claim_id, headers=None):
    return get_success_data(api_client.get_claim(claim_id, headers or UW))


def list_ledger(program_id):
    resp = api_client.list_program_ledger(program_id, FIN)
    entries, _meta = validate_paginated(resp)
    return entries
