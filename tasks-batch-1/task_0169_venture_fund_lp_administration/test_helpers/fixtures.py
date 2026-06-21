"""Composite setup helpers.

Each test runs against a freshly restarted, empty database, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. All
setup calls use get_success_data() (lenient 2xx validator) so a broken setup
surfaces a clear "Setup step failed" message rather than a confusing assertion.

Identity threading: LimitedPartnerUser is entity-backed, so any ownership-gated
call uses make_limited_partner_headers(lp_id) with the real LP id; opaque-role
calls use the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_limited_partner_headers
from . import factories as f

FM = TEST_USERS["fund_manager_headers"]
FA = TEST_USERS["fund_administrator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# --------------------------------------------------------------------------
# Tier 1 — Atomic creators
# --------------------------------------------------------------------------

def create_fund(**overrides) -> dict:
    """Create a fund in FORMING status (version 1)."""
    resp = api_client.create_fund(f.create_fund_payload(**overrides), FM)
    return get_success_data(resp)


def create_lp(**overrides) -> dict:
    """Create a LimitedPartner record."""
    resp = api_client.create_limited_partner(f.create_limited_partner_payload(**overrides), FA)
    return get_success_data(resp)


def create_portfolio_company(**overrides) -> dict:
    resp = api_client.create_portfolio_company(f.create_portfolio_company_payload(**overrides), FM)
    return get_success_data(resp)


def fund_version(fund_id: str) -> int:
    """Read the fund's current version (the OCC anchor)."""
    return get_success_data(api_client.get_fund(fund_id, FM))["version"]


# --------------------------------------------------------------------------
# Tier 2 — Commitment progression
# --------------------------------------------------------------------------

def create_pending_commitment(fund_id, lp_id, committed_cents=5_000_000) -> dict:
    """Create a commitment in PENDING status."""
    resp = api_client.create_commitment(
        f.create_commitment_payload(fund_id, lp_id, committed_cents=committed_cents), FM)
    return get_success_data(resp)


def create_accepted_commitment(fund_id, lp_id, committed_cents=5_000_000) -> dict:
    """Create a commitment and accept it (PENDING -> ACTIVE)."""
    commitment = create_pending_commitment(fund_id, lp_id, committed_cents)
    return get_success_data(api_client.accept_commitment(commitment["id"], FM))


def setup_fund_with_active_commitments(committed_amounts, **fund_overrides):
    """Create a fund and one ACTIVE commitment per amount in `committed_amounts`,
    each with its own freshly created LP (created in list order so created_at
    ascending matches the list order, which the largest-remainder tie-break
    depends on).

    Returns (fund, [commitments], [lps]).
    """
    fund = create_fund(**fund_overrides)
    commitments = []
    lps = []
    for i, amount in enumerate(committed_amounts):
        lp = create_lp(legal_name=f"LP {i}", tax_id_last4=f"{1000 + i}")
        commitment = create_accepted_commitment(fund["id"], lp["id"], amount)
        lps.append(lp)
        commitments.append(commitment)
    return fund, commitments, lps


# --------------------------------------------------------------------------
# Tier 3 — Capital-call lifecycle
# --------------------------------------------------------------------------

def issue_capital_call(fund_id, called_amount_cents, purpose="INVESTMENT",
                       due_date="2030-02-01T00:00:00Z", expected_fund_version=None):
    """Issue a capital call against a fund (OCC-anchored). Returns the call."""
    if expected_fund_version is None:
        expected_fund_version = fund_version(fund_id)
    payload = f.create_capital_call_payload(
        fund_id, expected_fund_version,
        purpose=purpose, called_amount_cents=called_amount_cents, due_date=due_date)
    return get_success_data(api_client.create_capital_call(payload, FM))


def list_call_allocations(call_id) -> list:
    """Return the allocations of a call, ordered as the server returns them."""
    return get_success_data(api_client.list_call_allocations(call_id, FA))


def fund_all_allocations(call_id):
    """Fund every PENDING allocation of a call in full (drives the call toward
    SETTLED and bumps each commitment's drawn_cents)."""
    for alloc in list_call_allocations(call_id):
        if alloc["status"] == "PENDING":
            get_success_data(api_client.fund_allocation(
                alloc["id"], f.fund_allocation_payload(alloc["allocated_amount_cents"]), FA))


def issue_and_fund_call(fund_id, called_amount_cents, purpose="INVESTMENT"):
    """Issue a call and fund every allocation in full. Returns the call id."""
    call = issue_capital_call(fund_id, called_amount_cents, purpose=purpose)
    fund_all_allocations(call["id"])
    return call


def allocation_for_commitment(call_id, commitment_id) -> dict:
    """Return the allocation of `call_id` belonging to `commitment_id`."""
    data = get_success_data(api_client.list_allocations(
        FA, params={"commitment_id": commitment_id, "capital_call_id": call_id}))
    assert data, f"No allocation for commitment {commitment_id} on call {call_id}"
    return data[0]


# --------------------------------------------------------------------------
# Tier 4 — Investment / valuation / realization
# --------------------------------------------------------------------------

def create_investment(fund_id, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
                      company_name="Test Co", sector="SaaS"):
    """Create a portfolio company and an ACTIVE investment in it.
    Returns (investment, portfolio_company)."""
    pc = create_portfolio_company(name=company_name, sector=sector)
    inv = get_success_data(api_client.create_investment(
        f.create_investment_payload(
            fund_id, pc["id"], cost_basis_cents=cost_basis_cents,
            ownership_pct_bps=ownership_pct_bps), FM))
    return inv, pc


def create_realized_investment(fund_id, realized_proceeds_cents,
                               cost_basis_cents=5_000_000, ownership_pct_bps=1000,
                               company_name="Test Co", sector="SaaS"):
    """Create an investment and realize it. Returns (investment, portfolio_company)."""
    inv, pc = create_investment(
        fund_id, cost_basis_cents=cost_basis_cents, ownership_pct_bps=ownership_pct_bps,
        company_name=company_name, sector=sector)
    inv = get_success_data(api_client.realize_investment(
        inv["id"], f.realize_investment_payload(realized_proceeds_cents), FM))
    return inv, pc


def create_final_mark(investment_id, as_of_date, fair_value_cents, methodology="DCF"):
    """Create a DRAFT mark and finalize it. Returns the finalized mark."""
    draft = get_success_data(api_client.create_valuation_mark(
        f.create_valuation_mark_payload(
            investment_id, as_of_date=as_of_date,
            fair_value_cents=fair_value_cents, methodology=methodology), FA))
    return get_success_data(api_client.finalize_valuation_mark(draft["id"], FA))


# --------------------------------------------------------------------------
# Tier 5 — Distribution lifecycle
# --------------------------------------------------------------------------

def declare_distribution(fund_id, source_investment_id, gross_amount_cents,
                         distribution_type="CAPITAL_GAIN", recyclable=False,
                         expected_fund_version=None):
    """Declare a distribution event (OCC-anchored). Returns the event."""
    if expected_fund_version is None:
        expected_fund_version = fund_version(fund_id)
    payload = f.create_distribution_event_payload(
        fund_id, source_investment_id, expected_fund_version,
        gross_amount_cents=gross_amount_cents, distribution_type=distribution_type,
        recyclable=recyclable)
    return get_success_data(api_client.create_distribution_event(payload, FM))


def declare_and_pay_distribution(fund_id, source_investment_id, gross_amount_cents,
                                 distribution_type="CAPITAL_GAIN", recyclable=False):
    """Declare a distribution and pay it (DECLARED -> PAID). Returns the event."""
    event = declare_distribution(
        fund_id, source_investment_id, gross_amount_cents,
        distribution_type=distribution_type, recyclable=recyclable)
    return get_success_data(api_client.pay_distribution_event(event["id"], FA))


# --------------------------------------------------------------------------
# Composite scenarios reused across difficulty + corner instances
# --------------------------------------------------------------------------

def setup_two_commitment_fund_funded(c1_amount, c2_amount, called_amount_cents,
                                     **fund_overrides):
    """Fund with two ACTIVE commitments (c1 created first), an issued+fully-funded
    capital call drawing `called_amount_cents`. Returns (fund, c1, c2).
    After this both commitments carry drawn_cents per the allocation split.
    """
    fund, commitments, _ = setup_fund_with_active_commitments(
        [c1_amount, c2_amount], **fund_overrides)
    issue_and_fund_call(fund["id"], called_amount_cents)
    # Re-read commitments so callers see refreshed drawn/unfunded.
    c1 = get_success_data(api_client.get_commitment(commitments[0]["id"], FM))
    c2 = get_success_data(api_client.get_commitment(commitments[1]["id"], FM))
    return fund, c1, c2


def setup_single_commitment_funded(committed_cents, called_amount_cents=None,
                                   **fund_overrides):
    """Fund with one ACTIVE commitment fully funded by a single call.
    Returns (fund, commitment, lp)."""
    if called_amount_cents is None:
        called_amount_cents = committed_cents
    fund = create_fund(**fund_overrides)
    lp = create_lp(legal_name="Solo LP", tax_id_last4="5000")
    commitment = create_accepted_commitment(fund["id"], lp["id"], committed_cents)
    issue_and_fund_call(fund["id"], called_amount_cents)
    commitment = get_success_data(api_client.get_commitment(commitment["id"], FM))
    return fund, commitment, lp
