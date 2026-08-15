"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: the Client role is entity-backed by Client, so every
client-sign / client-decline / withdrawal-cancel call uses
make_client_headers(client["id"]) — never the shared fallback constant.
Opaque-role calls that SoD rules compare (amendment proposer vs voter, minute
recorder vs ratifier) take explicit user ids.
"""
from prd_bench_local_runner.testing import (
    build_user_headers,
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO
from .factories import (
    DEFAULTS,
    allocation_targets_payload,
    cash_movement_payload,
    create_benchmark_payload,
    create_client_payload,
    create_committee_minute_payload,
    create_ips_amendment_payload,
    create_ips_payload,
    create_portfolio_payload,
    create_position_payload,
    create_rebalance_proposal_payload,
    create_restricted_list_entry_payload,
    create_security_payload,
    create_withdrawal_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_committee_chair_headers,
    make_committee_member_headers,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation / state progression
# ---------------------------------------------------------------------------

def create_active_client(full_name="Test Client", risk_tolerance_score=50):
    """Create a client and activate PROSPECT -> ACTIVE. Returns the client."""
    client = get_success_data(api_client.create_client(
        create_client_payload(full_name=full_name,
                              risk_tolerance_score=risk_tolerance_score), ADVISOR))
    return get_success_data(api_client.activate_client(client["id"], ADVISOR))


def create_benchmark(name="Test Bench", description="blend"):
    """Create a benchmark (born ACTIVE). Returns the benchmark."""
    return get_success_data(api_client.create_benchmark(
        create_benchmark_payload(name=name, description=description), COMPLIANCE))


def create_active_ips(client, benchmark, targets=None, risk=50, cadence=12,
                      objective_text="Growth"):
    """Drive an IPS DRAFT -> PENDING_COMPLIANCE -> PENDING_CLIENT -> ACTIVE.

    The client-sign step uses make_client_headers(client["id"]) because it is
    ownership-gated. Returns the ACTIVE IPS.
    """
    payload = create_ips_payload(client["id"], benchmark["id"],
                                 objective_text=objective_text,
                                 risk_tolerance_score=risk,
                                 review_cadence_months=cadence)
    ips = get_success_data(api_client.create_ips(payload, ADVISOR))
    get_success_data(api_client.replace_allocation_targets(
        ips["id"], allocation_targets_payload(targets or DEFAULTS["TARGETS_60_40"]),
        ADVISOR))
    get_success_data(api_client.submit_ips(ips["id"], ADVISOR))
    get_success_data(api_client.compliance_approve_ips(ips["id"], COMPLIANCE))
    return get_success_data(
        api_client.client_sign_ips(ips["id"], make_client_headers(client["id"])))


def create_security(ticker, asset_class, price_cents):
    """Register a security (born LISTED, price seeded). Returns the security."""
    return get_success_data(api_client.create_security(
        create_security_payload(ticker=ticker, asset_class=asset_class,
                                initial_price_cents=price_cents), COMPLIANCE))


def deposit(portfolio_id, amount_cents, occurred_at=CLOCK_DEFAULT_ISO):
    """Append a MANUAL_DEPOSIT event. Returns the CashFlowEvent."""
    return get_success_data(api_client.create_cash_movement(
        portfolio_id, cash_movement_payload("DEPOSIT", amount_cents, occurred_at),
        ADVISOR))


def withdraw_cash(portfolio_id, amount_cents, occurred_at=CLOCK_DEFAULT_ISO):
    """Append a MANUAL_WITHDRAWAL event. Returns the CashFlowEvent."""
    return get_success_data(api_client.create_cash_movement(
        portfolio_id, cash_movement_payload("WITHDRAWAL", amount_cents, occurred_at),
        ADVISOR))


def add_position(portfolio_id, security_id, quantity, opening_cost_basis_cents):
    """Transfer in an opening position. Returns the Position."""
    return get_success_data(api_client.create_position(
        create_position_payload(portfolio_id, security_id, quantity=quantity,
                                opening_cost_basis_cents=opening_cost_basis_cents),
        ADVISOR))


def reprice(security_id, new_price_cents):
    return get_success_data(api_client.reprice_security(
        security_id, new_price_cents, COMPLIANCE))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy (client + IPS + portfolio)
# ---------------------------------------------------------------------------

def setup_active_portfolio(targets=None, tax_status="TAXABLE", risk=50, cadence=12,
                           client_name="Test Client", benchmark_name="Test Bench"):
    """ACTIVE client + ACTIVE IPS + ACTIVE portfolio (zero cash, no positions).

    Returns dict(client, benchmark, ips, portfolio).
    """
    client = create_active_client(full_name=client_name, risk_tolerance_score=risk)
    benchmark = create_benchmark(name=benchmark_name)
    ips = create_active_ips(client, benchmark, targets=targets, risk=risk,
                            cadence=cadence)
    portfolio = get_success_data(api_client.create_portfolio(
        create_portfolio_payload(client["id"], tax_status=tax_status), ADVISOR))
    portfolio = get_success_data(api_client.activate_portfolio(portfolio["id"], ADVISOR))
    return {"client": client, "benchmark": benchmark, "ips": ips,
            "portfolio": portfolio}


# ---------------------------------------------------------------------------
# Tier 3: canonical market fixtures
# ---------------------------------------------------------------------------

def setup_three_lot_portfolio(tax_status="TAXABLE", targets=None):
    """ACTIVE TAXABLE (by default) portfolio with cash 100000 and three lots:

    LOT1 EQA 100 @ 1000 basis 90000 (US_EQUITY, gain/unit +100)
    LOT2 EQB 100 @ 1000 basis 40000 (US_EQUITY, gain/unit +600)
    LOT3 EIB 200 @  500 basis 110000 (INTL_EQUITY, gain/unit -50)

    Total value 400000; default targets 60/20/20 with 5.00 bands. At prices
    as registered the book is US 50% vs 60% target -> BREACHED.

    Returns dict(client, benchmark, ips, portfolio, securities, positions).
    """
    fx = setup_active_portfolio(targets=targets or DEFAULTS["TARGETS_60_20_20"],
                                tax_status=tax_status)
    p = fx["portfolio"]["id"]
    deposit(p, 100000)
    s_eqa = create_security("EQA", "US_EQUITY", 1000)
    s_eqb = create_security("EQB", "US_EQUITY", 1000)
    s_eib = create_security("EIB", "INTL_EQUITY", 500)
    lot1 = add_position(p, s_eqa["id"], 100, 90000)
    lot2 = add_position(p, s_eqb["id"], 100, 40000)
    lot3 = add_position(p, s_eib["id"], 200, 110000)
    fx.update({
        "securities": {"EQA": s_eqa, "EQB": s_eqb, "EIB": s_eib},
        "positions": {"LOT1": lot1, "LOT2": lot2, "LOT3": lot3},
    })
    return fx


def setup_breached_60_40(reprice_to=1500, tax_status="TAXABLE", client_name="Breach"):
    """60/40 portfolio pushed into drift breach by a reprice.

    Cash 400000 + EQA 600 @ 1000 basis 480000 (total 1000000, on target);
    repricing EQA to `reprice_to` (default 1500) lifts US to ~69.2% ->
    BREACHED. Returns dict(client, benchmark, ips, portfolio, security,
    position). With reprice_to=None the book stays exactly on target
    (WITHIN_BANDS) and no reprice is issued.
    """
    fx = setup_active_portfolio(targets=DEFAULTS["TARGETS_60_40"],
                                tax_status=tax_status, client_name=client_name)
    p = fx["portfolio"]["id"]
    deposit(p, 400000)
    security = create_security("EQA", "US_EQUITY", 1000)
    position = add_position(p, security["id"], 600, 480000)
    if reprice_to is not None:
        reprice(security["id"], reprice_to)
    fx.update({"security": security, "position": position})
    return fx


# ---------------------------------------------------------------------------
# Tier 4: proposals and trades
# ---------------------------------------------------------------------------

def portfolio_version(portfolio_id):
    """Read the current Portfolio.version (for the OCC field)."""
    return get_success_data(api_client.get_portfolio(portfolio_id, ADVISOR))["version"]


def generate_proposal(portfolio_id, trigger_type="DRIFT_BREACH"):
    """Generate a proposal with a freshly read expected_portfolio_version.

    Returns the created RebalanceProposal (status PROPOSED).
    """
    payload = create_rebalance_proposal_payload(
        portfolio_id, portfolio_version(portfolio_id), trigger_type=trigger_type)
    return get_success_data(api_client.create_rebalance_proposal(payload, ADVISOR))


def proposal_trades(proposal_id, status=None):
    """List trade instructions of a proposal, optionally filtered by status."""
    params = {"proposal_id": proposal_id}
    if status is not None:
        params["status"] = status
    rows, _meta = validate_paginated(api_client.list_trade_instructions(ADVISOR, params))
    return rows


def approve_and_execute_proposal(proposal_id):
    """APPROVED -> EXECUTED shortcut. Returns the executed proposal."""
    get_success_data(api_client.approve_proposal(proposal_id, COMPLIANCE))
    return get_success_data(api_client.execute_proposal(proposal_id, ADVISOR))


# ---------------------------------------------------------------------------
# Tier 4b: withdrawals
# ---------------------------------------------------------------------------

def create_withdrawal(portfolio_id, amount_cents, funding_mode="TAX_AWARE"):
    """Create a withdrawal request (born SUBMITTED) as the Advisor."""
    return get_success_data(api_client.create_withdrawal_request(
        create_withdrawal_request_payload(portfolio_id, amount_cents=amount_cents,
                                          funding_mode=funding_mode), ADVISOR))


def model_withdrawal(withdrawal_id):
    return get_success_data(api_client.model_withdrawal(withdrawal_id, ADVISOR))


def settle_modeled_withdrawal(withdrawal_id):
    """MODELED -> APPROVED -> SETTLED. Returns the settled request."""
    get_success_data(api_client.approve_withdrawal(withdrawal_id, ADVISOR))
    return get_success_data(api_client.settle_withdrawal(withdrawal_id, ADVISOR))


def settle_full_withdrawal(portfolio_id, amount_cents, funding_mode="TAX_AWARE"):
    """Create -> model -> approve -> settle in one call. Returns the request."""
    w = create_withdrawal(portfolio_id, amount_cents, funding_mode)
    model_withdrawal(w["id"])
    return settle_modeled_withdrawal(w["id"])


# ---------------------------------------------------------------------------
# Tier 4c: amendments, votes, minutes
# ---------------------------------------------------------------------------

def _advisor_headers_as(user_id):
    return build_user_headers(user_id, "Advisor")


def create_draft_amendment(ips_id, proposer="adv-1", **levers):
    """Draft an amendment; proposed_by_user_id is the proposer's X-User-ID."""
    return get_success_data(api_client.create_ips_amendment(
        create_ips_amendment_payload(ips_id, **levers), _advisor_headers_as(proposer)))


def submit_amendment(amendment_id, proposer="adv-1"):
    return get_success_data(api_client.submit_ips_amendment(
        amendment_id, _advisor_headers_as(proposer)))


def vote_to_quorum(amendment_id, decision="APPROVE", voters=("cm-1", "cm-2", "cm-3")):
    """Cast `decision` votes from distinct committee members until quorum.

    Returns the amendment after the final vote (QUORUM_REACHED or REJECTED).
    """
    result = None
    for voter in voters:
        result = get_success_data(api_client.vote_ips_amendment(
            amendment_id, decision, make_committee_member_headers(voter)))
    return result


def setup_quorum_amendment(ips_id, proposer="adv-1", **levers):
    """Draft -> submit -> 3 APPROVE votes. Returns the QUORUM_REACHED amendment."""
    amendment = create_draft_amendment(ips_id, proposer=proposer, **levers)
    submit_amendment(amendment["id"], proposer=proposer)
    vote_to_quorum(amendment["id"], "APPROVE")
    return get_success_data(api_client.get_ips_amendment(
        amendment["id"], TEST_USERS["advisor_headers"]))


def create_ratified_minute(amendment_refs=(), recorder="cm-1", chair="chair-1",
                           meeting_date="2026-08-01", decisions_text="Approved"):
    """Record a minute as `recorder` and ratify it as a different chair.

    Returns the RATIFIED minute.
    """
    minute = get_success_data(api_client.create_committee_minute(
        create_committee_minute_payload(meeting_date=meeting_date,
                                        amendment_refs=list(amendment_refs),
                                        decisions_text=decisions_text),
        make_committee_member_headers(recorder)))
    return get_success_data(api_client.ratify_committee_minute(
        minute["id"], make_committee_chair_headers(chair)))


def ips_version(ips_id):
    """Read the current InvestmentPolicyStatement.version (for OCC)."""
    return get_success_data(api_client.get_ips(ips_id, ADVISOR))["version"]


def finalize_amendment(amendment_id, minute_id, chair="chair-1"):
    """Finalize with a freshly read expected_ips_version. Returns the amendment."""
    amendment = get_success_data(api_client.get_ips_amendment(
        amendment_id, TEST_USERS["advisor_headers"]))
    return get_success_data(api_client.finalize_ips_amendment(
        amendment_id, minute_id, ips_version(amendment["ips_id"]),
        make_committee_chair_headers(chair)))


# ---------------------------------------------------------------------------
# Tier 5: restriction windows
# ---------------------------------------------------------------------------

def create_restriction(security_id, level="NO_TRADE",
                       effective_from="2026-08-01T00:00:00Z",
                       effective_to="2026-09-01T00:00:00Z", reason="probe"):
    """Create a restricted-list entry. Returns the entry."""
    return get_success_data(api_client.create_restricted_list_entry(
        create_restricted_list_entry_payload(
            security_id, restriction_level=level, effective_from=effective_from,
            effective_to=effective_to, reason=reason), COMPLIANCE))
