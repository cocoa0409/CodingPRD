"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

The test harness resets the database before every test, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. All callers
use the opaque Advisor / Compliance headers from test_users (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_security_payload,
    create_model_portfolio_payload,
    create_account_payload,
    create_questionnaire_payload,
    create_tax_lot_payload,
    create_harvest_event_payload,
    create_rebalance_event_payload,
    create_tax_form_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ─── Tier 0: Primitives ─────────────────────────────────────────────
def set_clock(iso: str):
    """Pin the server clock to an ISO 8601 instant (PRD §3.10). Returns data dict."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso), ADVISOR))


def create_security(ticker, asset_class="US_EQUITY", price_cents=10000, correlated_with=None):
    """Create one security (PRD §3.1). Returns the security dict."""
    res = api_client.create_security(
        create_security_payload(
            ticker=ticker,
            asset_class=asset_class,
            price_cents=price_cents,
            correlated_with=correlated_with,
        ),
        ADVISOR,
    )
    return get_success_data(res)


def create_model(
    name="Test Model",
    min_risk_score=70,
    max_risk_score=100,
    targets=None,
    drift_threshold_pct=90,
    lot_selection=None,
):
    """Create one model portfolio (PRD §3.1). Returns the model dict."""
    res = api_client.create_model_portfolio(
        create_model_portfolio_payload(
            name=name,
            min_risk_score=min_risk_score,
            max_risk_score=max_risk_score,
            targets=targets,
            drift_threshold_pct=drift_threshold_pct,
            lot_selection=lot_selection,
        ),
        ADVISOR,
    )
    return get_success_data(res)


def create_account(client_email):
    """Open an account (PRD §3.2). Returns the account dict (PENDING_PROFILE)."""
    res = api_client.create_account(create_account_payload(client_email=client_email), ADVISOR)
    return get_success_data(res)


def open_tax_lot(account_id, security_id, quantity, cost_basis_cents):
    """Open one tax lot (PRD §3.3). Returns the lot dict."""
    res = api_client.create_tax_lot(
        create_tax_lot_payload(
            account_id=account_id,
            security_id=security_id,
            quantity=quantity,
            cost_basis_cents=cost_basis_cents,
        ),
        ADVISOR,
    )
    return get_success_data(res)


# ─── Tier 1: Account state progression ──────────────────────────────
def create_active_account(
    client_email,
    model_id=None,
    questionnaire_inputs=None,
):
    """Open an account, score a questionnaire, accept it -> ACTIVE (PRD §3.2).

    If model_id is None, an active [70,100] single-asset model is created first
    so a default high-risk questionnaire (score 82) resolves to it.
    Returns the account dict after acceptance, when the account is ACTIVE.
    """
    if model_id is None:
        create_model(name=f"M-{client_email}")
    acct = create_account(client_email)
    inputs = questionnaire_inputs or {}
    q = get_success_data(
        api_client.create_questionnaire(
            create_questionnaire_payload(account_id=acct["id"], **inputs), ADVISOR
        )
    )
    accepted = get_success_data(api_client.accept_questionnaire(q["id"], ADVISOR))
    # Re-read the account to get the post-accept ACTIVE state + version.
    acct_active = get_success_data(api_client.get_account(acct["id"], ADVISOR))
    return acct_active


def get_account(account_id):
    """Fetch the current account state (PRD §2.7, §2.8)."""
    return get_success_data(api_client.get_account(account_id, ADVISOR))


def get_tax_lot(lot_id):
    return get_success_data(api_client.get_tax_lot(lot_id, ADVISOR))


def get_harvest(harvest_id):
    return get_success_data(api_client.get_harvest_event(harvest_id, ADVISOR))


def get_rebalance(rebalance_id):
    return get_success_data(api_client.get_rebalance_event(rebalance_id, ADVISOR))


def get_tax_form(form_id):
    return get_success_data(api_client.get_tax_form(form_id, ADVISOR))


# ─── Tier 2: Harvest scenarios ──────────────────────────────────────
def setup_active_account_with_loss_lot(
    clock_iso,
    email,
    source_qty=5,
    source_basis=60000,
    source_price=10000,
    repl_price=4000,
    correlation=0.05,
    drift_threshold_pct=90,
    src_ticker="SRC",
    repl_ticker="REPL",
):
    """ACTIVE single-asset (US_EQUITY 100%) account holding one loss lot in SRC,
    plus an uncorrelated active replacement security REPL (PRD §3.1–§3.4).

    With source_price 10000 and basis 60000 on 5 shares, market value is 50000
    and unrealized_gain_cents is -10000 (a loss lot, PRD §3.3). Returns a dict:
    {account, model, src_sec, repl_sec, source_lot, acct_version}.
    """
    set_clock(clock_iso)
    model = create_model(
        name=f"M-{email}",
        targets=[{"asset_class": "US_EQUITY", "target_pct": 100}],
        drift_threshold_pct=drift_threshold_pct,
    )
    src = create_security(
        src_ticker,
        "US_EQUITY",
        source_price,
        correlated_with=[{"ticker": repl_ticker, "correlation": correlation}],
    )
    repl = create_security(
        repl_ticker,
        "US_EQUITY",
        repl_price,
        correlated_with=[{"ticker": src_ticker, "correlation": correlation}],
    )
    acct = create_active_account(email, model_id=model["id"])
    lot = open_tax_lot(acct["id"], src["id"], source_qty, source_basis)
    acct_after = get_account(acct["id"])
    return {
        "account": acct_after,
        "model": model,
        "src_sec": src,
        "repl_sec": repl,
        "source_lot": lot,
        "acct_version": acct_after["version"],
    }


def propose_harvest(account_id, source_lot_id, replacement_security_id, expected_version):
    """Propose a harvest event (PRD §3.4). Returns the PROPOSED event dict."""
    res = api_client.create_harvest_event(
        create_harvest_event_payload(
            account_id=account_id,
            source_lot_id=source_lot_id,
            replacement_security_id=replacement_security_id,
            expected_account_version=expected_version,
        ),
        ADVISOR,
    )
    return get_success_data(res)


def setup_proposed_harvest(
    clock_iso,
    email,
    **scenario_overrides,
):
    """Full chain to a PROPOSED harvest on a clean loss lot (PRD §3.4).

    Returns the scenario dict from setup_active_account_with_loss_lot plus
    {"harvest": <proposed event>}.
    """
    scenario = setup_active_account_with_loss_lot(clock_iso, email, **scenario_overrides)
    harvest = propose_harvest(
        scenario["account"]["id"],
        scenario["source_lot"]["id"],
        scenario["repl_sec"]["id"],
        scenario["acct_version"],
    )
    scenario["harvest"] = harvest
    return scenario


def setup_executed_harvest(clock_iso, email, **scenario_overrides):
    """Full chain to an EXECUTED harvest on a clean loss lot (PRD §3.4).

    Returns the scenario dict plus {"harvest": <executed event>}.
    """
    scenario = setup_proposed_harvest(clock_iso, email, **scenario_overrides)
    executed = get_success_data(
        api_client.execute_harvest_event(scenario["harvest"]["id"], ADVISOR)
    )
    scenario["harvest"] = executed
    return scenario


def setup_active_account_with_washsale_loss_lot(
    clock_iso,
    email,
    in_window_qty=2,
    in_window_basis=24000,
    source_qty=5,
    source_basis=60000,
    src_ticker="WS_A",
    repl_ticker="WS_B",
    correlation=0.10,
):
    """ACTIVE account holding TWO OPEN lots in the same US_EQUITY security SRC:
    an in-window lot (acquired now, before the source) plus the 5sh/60000 source
    loss lot. A replacement security REPL (uncorrelated) is also created.

    With SRC price 10000, the 5-share source lot has market value 50000 and
    realized loss 10000; the 2-share in-window lot triggers a wash-sale
    disallowance on close (PRD §3.5). Returns
    {account, model, src_sec, repl_sec, in_window_lot, source_lot, acct_version}.
    """
    set_clock(clock_iso)
    model = create_model(
        name=f"WS-{email}",
        targets=[{"asset_class": "US_EQUITY", "target_pct": 100}],
        drift_threshold_pct=90,
    )
    src = create_security(
        src_ticker,
        "US_EQUITY",
        10000,
        correlated_with=[{"ticker": repl_ticker, "correlation": correlation}],
    )
    repl = create_security(
        repl_ticker,
        "US_EQUITY",
        4000,
        correlated_with=[{"ticker": src_ticker, "correlation": correlation}],
    )
    acct = create_active_account(email, model_id=model["id"])
    in_window = open_tax_lot(acct["id"], src["id"], in_window_qty, in_window_basis)
    source = open_tax_lot(acct["id"], src["id"], source_qty, source_basis)
    acct_after = get_account(acct["id"])
    return {
        "account": acct_after,
        "model": model,
        "src_sec": src,
        "repl_sec": repl,
        "in_window_lot": in_window,
        "source_lot": source,
        "acct_version": acct_after["version"],
    }


# ─── Tier 3: Drift / rebalance scenarios ────────────────────────────
def setup_account_two_asset_model(
    clock_iso,
    email,
    us_target=60,
    bond_target=40,
    drift_threshold_pct=5,
    lot_selection=None,
):
    """ACTIVE account on a US_EQUITY/BOND two-asset model (PRD §3.1–§3.3).

    Both securities priced at 10000. Returns
    {account, model, us_sec, bond_sec}.
    """
    set_clock(clock_iso)
    model = create_model(
        name=f"TA-{email}",
        targets=[
            {"asset_class": "US_EQUITY", "target_pct": us_target},
            {"asset_class": "BOND", "target_pct": bond_target},
        ],
        drift_threshold_pct=drift_threshold_pct,
        lot_selection=lot_selection,
    )
    us = create_security(f"USE{abs(hash(email)) % 9999}", "US_EQUITY", 10000)
    bond = create_security(f"BND{abs(hash(email)) % 9999}", "BOND", 10000)
    acct = create_active_account(email, model_id=model["id"])
    return {"account": acct, "model": model, "us_sec": us, "bond_sec": bond}


def setup_rebalance_due_account(
    clock_iso,
    email,
    us_target=60,
    bond_target=40,
    drift_threshold_pct=5,
    us_qty=7,
    us_basis=70000,
    bond_qty=3,
    bond_basis=30000,
):
    """ACTIVE -> REBALANCE_DUE account: open US and BOND lots that drive drift
    at or above threshold so the account auto-flips to REBALANCE_DUE (PRD §2.7).

    With us_qty 7 @ 10000 (mkt 70000) and bond_qty 3 @ 10000 (mkt 30000),
    invested is 100000, US is 70% (target 60, drift 10 >= 5). Returns
    {account, model, us_sec, bond_sec, us_lot, bond_lot, acct_version}.
    """
    base = setup_account_two_asset_model(
        clock_iso,
        email,
        us_target=us_target,
        bond_target=bond_target,
        drift_threshold_pct=drift_threshold_pct,
    )
    us_lot = open_tax_lot(base["account"]["id"], base["us_sec"]["id"], us_qty, us_basis)
    bond_lot = open_tax_lot(
        base["account"]["id"], base["bond_sec"]["id"], bond_qty, bond_basis
    )
    acct_after = get_account(base["account"]["id"])
    base.update(
        {
            "us_lot": us_lot,
            "bond_lot": bond_lot,
            "account": acct_after,
            "acct_version": acct_after["version"],
        }
    )
    return base
