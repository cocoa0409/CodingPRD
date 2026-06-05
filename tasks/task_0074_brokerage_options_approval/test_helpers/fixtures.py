"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server before each test, so the DB is
always empty at fixture entry). Setup calls use the lenient get_success_data()
so a broken precondition surfaces as a clear "Setup step failed".
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_account_holder_headers,
    make_compliance_officer_headers,
    make_custodian_headers,
)
from .factories import (
    create_account_payload,
    create_options_approval_payload,
    create_margin_upgrade_payload,
    create_position_payload,
    create_order_payload,
    create_acat_transfer_payload,
)

# Canonical opaque ids used throughout setup.
HOLDER_ID = "h_a"
CO_SUBMITTER_ID = "co_1"
CO_DECIDER_ID = "co_2"
CUST_ID = "cust_1"

HOLDER = make_account_holder_headers(HOLDER_ID)
CO_SUBMITTER = make_compliance_officer_headers(CO_SUBMITTER_ID)
CO_DECIDER = make_compliance_officer_headers(CO_DECIDER_ID)
CUST = make_custodian_headers(CUST_ID)


def _data(resp):
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: Account state progression
# ---------------------------------------------------------------------------

def open_account(holder_id=HOLDER_ID, **overrides) -> dict:
    """Open a PENDING_KYC account owned by holder_id. Returns the account dict."""
    payload = create_account_payload(account_holder_user_id=holder_id, **overrides)
    return _data(api_client.create_account(payload, make_account_holder_headers(holder_id)))


def open_and_activate_account(holder_id=HOLDER_ID, **overrides) -> dict:
    """Open + activate an account; returns the ACTIVE account dict (re-read)."""
    acct = open_account(holder_id=holder_id, **overrides)
    _data(api_client.activate_account(acct["id"], CO_SUBMITTER))
    return _data(api_client.get_account(acct["id"], CO_SUBMITTER))


def get_account(account_id) -> dict:
    return _data(api_client.get_account(account_id, CO_SUBMITTER))


# ---------------------------------------------------------------------------
# Tier 2 / 3: Options approval lifecycle
# ---------------------------------------------------------------------------

def grant_options_level(account_id, target_level: int):
    """Walk options approvals from the account's current level up to target_level,
    one rung at a time, each approved by a different officer than the submitter.
    Assumes the account's suitability fields already satisfy target_level."""
    current = get_account(account_id)["options_level"]
    for lvl in range(current + 1, target_level + 1):
        oa = _data(api_client.create_options_approval(
            create_options_approval_payload(account_id, lvl), CO_SUBMITTER))
        _data(api_client.submit_options_approval(oa["id"], CO_SUBMITTER))
        _data(api_client.approve_options_approval(oa["id"], CO_DECIDER))


def submit_options_approval(account_id, requested_level: int) -> dict:
    """Create + submit an options approval at requested_level. Returns it (SUBMITTED)."""
    oa = _data(api_client.create_options_approval(
        create_options_approval_payload(account_id, requested_level), CO_SUBMITTER))
    return _data(api_client.submit_options_approval(oa["id"], CO_SUBMITTER))


def draft_options_approval(account_id, requested_level: int) -> dict:
    """Create a DRAFT options approval. Returns it."""
    return _data(api_client.create_options_approval(
        create_options_approval_payload(account_id, requested_level), CO_SUBMITTER))


# ---------------------------------------------------------------------------
# Margin upgrade lifecycle
# ---------------------------------------------------------------------------

def submit_margin_upgrade(account_id, requested_margin_type) -> dict:
    """Create + submit a margin upgrade. Returns it (SUBMITTED)."""
    mu = _data(api_client.create_margin_upgrade(
        create_margin_upgrade_payload(account_id, requested_margin_type), CO_SUBMITTER))
    return _data(api_client.submit_margin_upgrade(mu["id"], CO_SUBMITTER))


def upgrade_margin(account_id, requested_margin_type) -> dict:
    """Create + submit + approve a margin upgrade with the correct expected_account_version.
    Returns the re-read account."""
    submit_margin_upgrade(account_id, requested_margin_type)
    # Re-read to find the margin upgrade id we just created (most recent for account).
    mus, _ = _list(api_client.list_margin_upgrades(CO_DECIDER, {"account_id": account_id}))
    mu_id = mus[-1]["id"]
    ver = get_account(account_id)["version"]
    _data(api_client.approve_margin_upgrade(mu_id, {"expected_account_version": ver}, CO_DECIDER))
    return get_account(account_id)


def _list(resp):
    body = get_success_data(resp)
    # get_success_data returns body["data"]; for list endpoints that is the array.
    return body, None


# ---------------------------------------------------------------------------
# Tier 2: Positions
# ---------------------------------------------------------------------------

def open_position(account_id, symbol="ACME", instrument_type="EQUITY",
                  quantity=10, market_value_cents=1_000_000) -> dict:
    """Record an OPEN position. Returns the position dict."""
    return _data(api_client.create_position(
        create_position_payload(account_id, symbol=symbol, instrument_type=instrument_type,
                                quantity=quantity, market_value_cents=market_value_cents),
        HOLDER))


# ---------------------------------------------------------------------------
# Tier 3: Orders
# ---------------------------------------------------------------------------

def draft_order(account_id, holder_id=HOLDER_ID, **order_overrides) -> dict:
    """Create a DRAFT order. Returns it."""
    payload = create_order_payload(account_id, **order_overrides)
    return _data(api_client.create_order(payload, make_account_holder_headers(holder_id)))


def accept_order(account_id, holder_id=HOLDER_ID, **order_overrides) -> dict:
    """Create + accept an order. Returns the ACCEPTED order (re-read)."""
    ord_ = draft_order(account_id, holder_id=holder_id, **order_overrides)
    _data(api_client.accept_order(ord_["id"], make_account_holder_headers(holder_id)))
    return _data(api_client.get_order(ord_["id"], make_account_holder_headers(holder_id)))


# ---------------------------------------------------------------------------
# Tier 4: Day-trade accumulation
# ---------------------------------------------------------------------------

def fill_same_day_round_trip(account_id, symbol, trade_date, holder_id=HOLDER_ID):
    """Create -> accept -> full-fill a SELL LIMIT same-day-closing order, producing
    one DayTrade row. quantity 1, limit 100. Returns the FILLED order."""
    holder = make_account_holder_headers(holder_id)
    ord_ = draft_order(account_id, holder_id=holder_id, symbol=symbol,
                       side="SELL", order_type="LIMIT", quantity=1,
                       limit_price_cents=100, opened_position_same_day=True,
                       trade_date=trade_date)
    _data(api_client.accept_order(ord_["id"], holder))
    _data(api_client.fill_order(ord_["id"], {"fill_quantity": 1}, CO_SUBMITTER))
    return _data(api_client.get_order(ord_["id"], holder))


def setup_three_same_day_day_trades(cash_balance_cents=100_000, trade_date="2026-06-01"):
    """Active under-capitalized account (equity < $25k) with exactly THREE FILLED
    same-day round trips on trade_date. Returns (account_id, holder_id).
    Used to set up the PDT 4th-trade boundary tests."""
    acct = open_and_activate_account(cash_balance_cents=cash_balance_cents)
    for sym in ("DT1", "DT2", "DT3"):
        fill_same_day_round_trip(acct["id"], sym, trade_date)
    return acct["id"], HOLDER_ID


def seed_day_trades_and_flag(account_id, trade_date, count):
    """Inject `count` synthetic DayTrade rows via the admin seed endpoint and
    recompute PDT status. Returns the re-read account."""
    _data(api_client.seed_day_trades(
        {"account_id": account_id, "trade_date": trade_date, "count": count}, CO_SUBMITTER))
    return get_account(account_id)


# ---------------------------------------------------------------------------
# ACAT transfers
# ---------------------------------------------------------------------------

def request_acat(account_id, direction="IN", transfer_value_cents=500_000) -> dict:
    """Request an ACAT transfer (REQUESTED). Returns it."""
    return _data(api_client.create_acat_transfer(
        create_acat_transfer_payload(account_id, direction=direction,
                                     transfer_value_cents=transfer_value_cents), HOLDER))


def validate_acat(account_id, direction="IN", transfer_value_cents=500_000) -> dict:
    """Request + validate an ACAT transfer (VALIDATED). Returns it."""
    t = request_acat(account_id, direction=direction, transfer_value_cents=transfer_value_cents)
    return _data(api_client.validate_acat_transfer(t["id"], CUST))


def settle_acat(account_id, direction="IN", transfer_value_cents=500_000) -> dict:
    """Request + validate + settle an ACAT transfer (SETTLED). Returns it."""
    t = validate_acat(account_id, direction=direction, transfer_value_cents=transfer_value_cents)
    return _data(api_client.settle_acat_transfer(t["id"], CUST))
