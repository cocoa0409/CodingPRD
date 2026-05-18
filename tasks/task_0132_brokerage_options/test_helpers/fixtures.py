"""Composite setup helpers — multi-step preambles tests can reuse.

The brokerage pipeline is long: customer create -> KYC submit -> KYC
verify -> account create -> (optional) INBOUND ACAT funding cycle ->
(optional) options-approval lifecycle -> (optional) DayTrade
accumulation -> (optional) order/transfer state setup.

IDENTITY THREADING — PRD §2.1:

- ComplianceOfficer / PlatformAdmin are OPAQUE. Shared TEST_USERS
  constants are canonical for every operator-only call.

- Customer is ENTITY-BACKED. Every Customer-driven call whose success
  depends on owning the targeted resource MUST mint headers via
  make_customer_headers(customer["id"]) — never via the shared
  CUSTOMER_FALLBACK_ID. The fixtures here return the actual Customer
  row so consumer tests / consumer fixtures can route customer-acting
  calls through this header builder.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test assertion
failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ACAT_BUSINESS_DAYS,
    PDT_EQUITY_FLOOR_CENTS,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_account_payload,
    create_acat_transfer_payload,
    create_customer_payload,
    create_options_approval_payload,
    create_order_payload,
    decide_options_approval_payload,
    fill_order_payload,
    kyc_decision_payload,
    pdt_reset_payload,
    submit_kyc_payload,
    years_ago_dob,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)


# Roughly one business week. Used by INBOUND ACAT settlement.
# PRD §3.5: 6 business days + buffer to land past expected_completion_at.
_ACAT_SETTLE_SECONDS = 9 * 24 * 60 * 60  # 9 calendar days covers 6BD


# ===========================================================================
# Stage 0: low-level wrappers
# ===========================================================================
def advance_clock(
    seconds: int,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    """POST /brokerage/_clock/advance seconds=N. PRD §3.8: drives
    time-gated transitions on ACATTransfer."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(seconds=seconds), headers,
    )
    # PRD §4 declares /_clock/advance returns no data body; tolerate
    # any 2xx response shape so consumer fixtures aren't forced to
    # interpret an empty envelope.
    if 200 <= resp.status_code < 300:
        return resp
    raise AssertionError(
        f"Setup advance_clock failed with HTTP {resp.status_code}: "
        f"{resp.text}"
    )


def run_sweep(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    """POST /brokerage/_sweep/run. PRD §3.8."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.sweep_run(headers)
    if 200 <= resp.status_code < 300:
        return resp
    raise AssertionError(
        f"Setup run_sweep failed with HTTP {resp.status_code}: "
        f"{resp.text}"
    )


# ===========================================================================
# Tier 1: Customer + Account creation (PENDING_KYC posture)
# ===========================================================================
def create_customer(
    *,
    legal_name: Optional[str] = None,
    years_options_experience: int = 5,
    liquid_net_worth_cents: int = 100_000_000,
    total_net_worth_cents: int = 200_000_000,
    annual_income_cents: int = 30_000_000,
    date_of_birth: Optional[str] = None,
    ssn_last4: str = "1234",
) -> Dict[str, Any]:
    """POST /brokerage/customers. PRD §3.1.

    Authorized: Customer, PlatformAdmin. We submit as PlatformAdmin
    because at this moment no real Customer.id exists yet to use as
    X-User-ID; PlatformAdmin is opaque (PRD §2.1) so the shared header
    constant is canonical.
    """
    payload = create_customer_payload(
        legal_name=legal_name,
        date_of_birth=(
            date_of_birth
            if date_of_birth is not None
            else years_ago_dob(30)
        ),
        ssn_last4=ssn_last4,
        annual_income_cents=annual_income_cents,
        liquid_net_worth_cents=liquid_net_worth_cents,
        total_net_worth_cents=total_net_worth_cents,
        years_options_experience=years_options_experience,
    )
    resp = api_client.create_customer(
        payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def create_account(
    *,
    customer: Dict[str, Any],
    account_type: str = "CASH",
) -> Dict[str, Any]:
    """POST /brokerage/accounts as the owning Customer. PRD §3.1.

    Customer is ENTITY-BACKED (PRD §2.1): X-User-ID must equal the
    acting Customer.id, so we mint per-customer headers via
    make_customer_headers(customer["id"]).
    """
    headers = make_customer_headers(customer["id"])
    resp = api_client.create_account(
        create_account_payload(
            customer_id=customer["id"],
            account_type=account_type,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: KYC submission + verification (Account -> APPROVED, posture OPEN)
# ===========================================================================
def submit_kyc(
    customer: Dict[str, Any],
    *,
    address_country: str = "US",
    w9_signed_name: Optional[str] = None,
    government_id_type: str = "PASSPORT",
) -> Dict[str, Any]:
    """POST /brokerage/customers/{id}/kyc as the Customer. PRD §3.1.

    Defaults to legally-passing W-9 name (matches Customer.legal_name).
    """
    headers = make_customer_headers(customer["id"])
    resp = api_client.submit_kyc(
        customer["id"],
        submit_kyc_payload(
            legal_name_for_w9=customer["legal_name"],
            address_country=address_country,
            w9_signed_name=w9_signed_name,
            government_id_type=government_id_type,
        ),
        headers,
    )
    return get_success_data(resp)


def verify_kyc(customer_id: str) -> Dict[str, Any]:
    """POST /brokerage/customers/{id}/kyc/decision body={decision:'VERIFY'}.
    PRD §3.1: ComplianceOfficer-only."""
    resp = api_client.kyc_decision(
        customer_id,
        kyc_decision_payload(decision="VERIFY"),
        TEST_USERS["compliance_headers"],
    )
    return get_success_data(resp)


def reject_kyc(customer_id: str) -> Dict[str, Any]:
    """POST /brokerage/customers/{id}/kyc/decision body={decision:'REJECT'}.
    PRD §3.1."""
    resp = api_client.kyc_decision(
        customer_id,
        kyc_decision_payload(decision="REJECT"),
        TEST_USERS["compliance_headers"],
    )
    return get_success_data(resp)


def setup_approved_customer_and_account(
    *,
    account_type: str = "CASH",
    years_options_experience: int = 5,
    liquid_net_worth_cents: int = 100_000_000,
    total_net_worth_cents: int = 200_000_000,
    legal_name: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Convenience: customer + account + KYC submit + VERIFY.

    Returns (customer, account). After this:
      - Customer.kyc_status == VERIFIED
      - Account.status == APPROVED
      - Account.trading_posture == OPEN

    (PRD §3.1 verification side-effects.)
    """
    customer = create_customer(
        legal_name=legal_name,
        years_options_experience=years_options_experience,
        liquid_net_worth_cents=liquid_net_worth_cents,
        total_net_worth_cents=total_net_worth_cents,
    )
    account = create_account(
        customer=customer, account_type=account_type,
    )
    submit_kyc(customer)
    verify_kyc(customer["id"])
    # Re-fetch the up-to-date account.
    fresh = get_success_data(
        api_client.get_account(
            account["id"], make_customer_headers(customer["id"]),
        )
    )
    return customer, fresh


# ===========================================================================
# Tier 3: Funding the account via INBOUND ACAT (cash_balance_cents > 0)
# ===========================================================================
def fund_account_inbound_acat(
    customer: Dict[str, Any],
    account: Dict[str, Any],
    *,
    amount_cents: int,
) -> Dict[str, Any]:
    """Inject cash into the account by running a full INBOUND ACAT
    pipeline (initiate -> validate -> advance clock -> COMPLETED).

    PRD §3.5: "An INBOUND completion adds requested_value_cents to both
    Account.cash_balance_cents and Account.equity_value_cents."

    Returns the up-to-date Account after funding.
    """
    cust_headers = make_customer_headers(customer["id"])

    # Initiate INBOUND.
    resp = api_client.create_acat_transfer(
        create_acat_transfer_payload(
            account_id=account["id"],
            direction="INBOUND",
            requested_value_cents=amount_cents,
        ),
        cust_headers,
    )
    transfer = get_success_data(resp)

    # Validate as ComplianceOfficer.
    resp = api_client.validate_acat_transfer(
        transfer["id"], TEST_USERS["compliance_headers"],
    )
    get_success_data(resp)

    # Advance clock past expected_completion_at (6 business days at
    # 17:00 UTC + buffer). PRD §3.5 says transfer auto-advances to
    # COMPLETED when now() >= expected_completion_at.
    advance_clock(_ACAT_SETTLE_SECONDS)

    fresh = get_success_data(
        api_client.get_account(account["id"], cust_headers)
    )
    return fresh


def setup_funded_account(
    *,
    account_type: str = "MARGIN_REG_T",
    cash_amount_cents: int = 10_000_000,  # $100k
    years_options_experience: int = 5,
    liquid_net_worth_cents: int = 100_000_000,
    total_net_worth_cents: int = 200_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Approved + funded account ready to submit orders.

    Returns (customer, account) where account.cash_balance_cents ==
    cash_amount_cents and trading_posture == OPEN.
    """
    customer, account = setup_approved_customer_and_account(
        account_type=account_type,
        years_options_experience=years_options_experience,
        liquid_net_worth_cents=liquid_net_worth_cents,
        total_net_worth_cents=total_net_worth_cents,
    )
    if cash_amount_cents > 0:
        account = fund_account_inbound_acat(
            customer, account, amount_cents=cash_amount_cents,
        )
    return customer, account


# ===========================================================================
# Tier 4: OptionsApproval lifecycle helpers
# ===========================================================================
def create_options_approval(
    customer: Dict[str, Any],
    account: Dict[str, Any],
    *,
    requested_level: int,
) -> Dict[str, Any]:
    """POST /brokerage/options-approvals as the owning Customer."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.create_options_approval(
        create_options_approval_payload(
            account_id=account["id"],
            requested_level=requested_level,
        ),
        headers,
    )
    return get_success_data(resp)


def start_options_review(approval_id: str) -> Dict[str, Any]:
    """POST .../start-review as ComplianceOfficer."""
    resp = api_client.start_options_review(
        approval_id, TEST_USERS["compliance_headers"],
    )
    return get_success_data(resp)


def decide_options_approval(
    approval_id: str,
    *,
    decision: str,
    approved_level: Optional[int] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """POST .../decide as ComplianceOfficer."""
    resp = api_client.decide_options_approval(
        approval_id,
        decide_options_approval_payload(
            decision=decision,
            approved_level=approved_level,
            notes=notes,
        ),
        TEST_USERS["compliance_headers"],
    )
    return get_success_data(resp)


def setup_options_approval_under_review(
    customer: Dict[str, Any],
    account: Dict[str, Any],
    *,
    requested_level: int = 4,
) -> Dict[str, Any]:
    """Approval submitted + start-review -> UNDER_REVIEW. Returns approval."""
    approval = create_options_approval(
        customer, account, requested_level=requested_level,
    )
    return start_options_review(approval["id"])


def setup_account_with_options_level(
    *,
    level: int,
    account_type: str = "MARGIN_REG_T",
    cash_amount_cents: int = 10_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Funded approved account whose options_level == `level`.

    Walks the full options-approval lifecycle:
      submit -> start-review -> decide APPROVE(approved_level=level)
    """
    # Need customer with sufficient eligibility for the requested level.
    # Use ultra-rich defaults so all four tier criteria are met.
    customer, account = setup_funded_account(
        account_type=account_type,
        cash_amount_cents=cash_amount_cents,
        years_options_experience=10,
        liquid_net_worth_cents=50_000_000_00,   # 5 billion cents, >>$25M
        total_net_worth_cents=100_000_000_00,
    )
    if level <= 0:
        return customer, account
    approval = create_options_approval(
        customer, account, requested_level=level,
    )
    start_options_review(approval["id"])
    decide_options_approval(
        approval["id"], decision="APPROVE", approved_level=level,
    )
    fresh = get_success_data(
        api_client.get_account(
            account["id"], make_customer_headers(customer["id"]),
        )
    )
    return customer, fresh


# ===========================================================================
# Tier 5: Order helpers
# ===========================================================================
def submit_order(
    customer: Dict[str, Any],
    account: Dict[str, Any],
    *,
    symbol: str = "AAPL",
    instrument_type: str = "EQUITY",
    option_strategy: Optional[str] = None,
    side: str = "BUY",
    order_type: str = "LIMIT",
    quantity: int = 1,
    limit_price_cents: Optional[int] = None,
    stop_price_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /brokerage/orders as the owning Customer."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.create_order(
        create_order_payload(
            account_id=account["id"],
            symbol=symbol,
            instrument_type=instrument_type,
            option_strategy=option_strategy,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price_cents=limit_price_cents,
            stop_price_cents=stop_price_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def fill_order(order_id: str, *, execution_price_cents: int) -> Dict[str, Any]:
    """POST /brokerage/orders/{id}/fill as PlatformAdmin."""
    resp = api_client.fill_order(
        order_id,
        fill_order_payload(execution_price_cents=execution_price_cents),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def cancel_order(
    customer: Dict[str, Any],
    order_id: str,
) -> Dict[str, Any]:
    """DELETE /brokerage/orders/{id} as the owning Customer."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.cancel_order(order_id, headers)
    return get_success_data(resp)


def submit_working_limit_buy(
    customer: Dict[str, Any],
    account: Dict[str, Any],
    *,
    symbol: str = "AAPL",
    quantity: int = 1,
    limit_price_cents: int = 100,
) -> Dict[str, Any]:
    """Submit a LIMIT BUY order that lands in WORKING. Non-MARKET orders
    auto-advance ACCEPTED -> WORKING (PRD §3.3).
    """
    return submit_order(
        customer, account,
        symbol=symbol,
        instrument_type="EQUITY",
        side="BUY",
        order_type="LIMIT",
        quantity=quantity,
        limit_price_cents=limit_price_cents,
    )


# ===========================================================================
# Tier 6: DayTrade accumulation (round-trip MARKET BUY+SELL same day)
# ===========================================================================
def execute_one_day_trade(
    customer: Dict[str, Any],
    account: Dict[str, Any],
    *,
    symbol: str,
    market_price_cents: int = 100,
    quantity: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Round-trip MARKET BUY then MARKET SELL on `symbol` at
    market_price_cents to produce ONE DayTrade pairing.

    PRD §3.3: 'A MARKET order auto-fills immediately at the submitted
    market-reference price.' MARKET orders need limit_price_cents as the
    submitted reference (the implementation must accept some price input
    for MARKET — based on PRD §3.3: 'the submitted market-reference
    price for a MARKET order'). We pass limit_price_cents as that
    reference.

    PRD §3.4 day_trade_pairing: matching BUY+SELL fills same symbol same
    UTC trading day pairs into one DayTrade.
    """
    buy = submit_order(
        customer, account,
        symbol=symbol,
        instrument_type="EQUITY",
        side="BUY",
        order_type="MARKET",
        quantity=quantity,
        limit_price_cents=market_price_cents,
    )
    sell = submit_order(
        customer, account,
        symbol=symbol,
        instrument_type="EQUITY",
        side="SELL",
        order_type="MARKET",
        quantity=quantity,
        limit_price_cents=market_price_cents,
    )
    return buy, sell


def accumulate_n_day_trades(
    customer: Dict[str, Any],
    account: Dict[str, Any],
    *,
    n: int,
    market_price_cents: int = 100,
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Round-trip MARKET BUY+SELL n times in the same UTC trading day to
    produce n distinct DayTrade rows (one per BUY+SELL pair, distinct
    symbols to avoid FIFO pairing collisions).

    PRD §3.4 day_trade_pairing uses (account, symbol, trade_date, side)
    matching; using distinct symbols per round guarantees one DayTrade
    per pair.
    """
    pairs = []
    # Distinct two-letter symbols to keep pairings clean.
    pool = [
        "AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH",
        "III", "JJJ", "KKK", "LLL", "MMM",
    ]
    for i in range(n):
        sym = pool[i % len(pool)] + chr(ord("A") + (i // len(pool)))
        # Ensure symbol stays within 1..5 uppercase A-Z.
        sym = sym[:5]
        b, s = execute_one_day_trade(
            customer, account,
            symbol=sym, market_price_cents=market_price_cents,
        )
        pairs.append((b, s))
    return pairs


# ===========================================================================
# Tier 7: PDT-targeting compound fixtures (difficulty-design driven)
# ===========================================================================
def setup_account_below_pdt_floor_with_n_day_trades(
    *,
    n_prior_day_trades: int,
    cash_amount_cents: int = 2_499_900,  # < $25,000 floor (PRD §3.4)
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Tuple[Dict, Dict]]]:
    """Funded REG_T account with cash_balance_cents < PDT floor and
    `n_prior_day_trades` DayTrade rows in today's window.

    PRD §3.4 PDT trips when count of DayTrade rows in the rolling 5BD
    window is at least 4 AND equity_value_cents is strictly less than
    2,500,000. This fixture pins equity below the floor and pre-stages
    `n_prior_day_trades` day trades so a test can trigger the 4th day
    trade and observe the cascade.

    Cash math: each round-trip nets to zero (BUY at P then SELL at P
    leaves cash_balance_cents unchanged; PRD §3.3 'BUY debits ... SELL
    credits'). So cash_amount_cents stays at the seeded value across
    rounds.

    Equity math: after all positions are closed, equity_value_cents ==
    cash_balance_cents (PRD §3.7: 'If there is no last price for the
    symbol or if the net signed quantity is less than or equal to 0,
    the contribution of that symbol is exactly 0.').
    """
    assert cash_amount_cents < PDT_EQUITY_FLOOR_CENTS, (
        "fixture by contract pins cash below PDT floor"
    )
    customer, account = setup_funded_account(
        account_type="MARGIN_REG_T",
        cash_amount_cents=cash_amount_cents,
    )
    pairs = accumulate_n_day_trades(
        customer, account,
        n=n_prior_day_trades, market_price_cents=100,
    )
    fresh = get_success_data(
        api_client.get_account(
            account["id"], make_customer_headers(customer["id"]),
        )
    )
    return customer, fresh, pairs


def trigger_fourth_day_trade(
    customer: Dict[str, Any],
    account: Dict[str, Any],
    *,
    symbol: str = "ZZZ",
    market_price_cents: int = 100,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Execute the 4th round-trip MARKET BUY+SELL. When invoked on an
    account already at the PDT threshold (3 prior DayTrades, equity <
    floor), this triggers the PDT cascade per PRD §3.4.
    """
    return execute_one_day_trade(
        customer, account,
        symbol=symbol,
        market_price_cents=market_price_cents,
    )


# ===========================================================================
# Tier 8: Account close / dependency / posture compound fixtures
# ===========================================================================
def setup_account_with_working_limit_order(
    *,
    account_type: str = "MARGIN_REG_T",
    cash_amount_cents: int = 10_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Approved + funded account + one WORKING LIMIT BUY order.

    Returns (customer, account, order). Used by tests that require an
    open order to:
    - block ACAT outbound validate (PRD §3.5 / validation P=27)
    - block account close (PRD §3.6)
    - exercise WORKING -> CANCELLED transition (PRD §3.3)
    """
    customer, account = setup_funded_account(
        account_type=account_type,
        cash_amount_cents=cash_amount_cents,
    )
    order = submit_working_limit_buy(
        customer, account,
        symbol="AAPL", quantity=1, limit_price_cents=100,
    )
    return customer, account, order


def setup_account_with_outbound_acat_initiated(
    *,
    cash_amount_cents: int = 10_000_000,
    transfer_value_cents: int = 500_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Approved + funded account + one OUTBOUND ACAT in INITIATED state.

    Returns (customer, account, transfer). Used by ACAT no-overlap and
    cancel-preserves-equity tests.
    """
    customer, account = setup_funded_account(
        account_type="CASH",
        cash_amount_cents=cash_amount_cents,
    )
    headers = make_customer_headers(customer["id"])
    resp = api_client.create_acat_transfer(
        create_acat_transfer_payload(
            account_id=account["id"],
            direction="OUTBOUND",
            requested_value_cents=transfer_value_cents,
        ),
        headers,
    )
    transfer = get_success_data(resp)
    return customer, account, transfer


def setup_account_with_outbound_acat_validated(
    *,
    cash_amount_cents: int = 10_000_000,
    transfer_value_cents: int = 500_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """OUTBOUND ACAT after validate -> VALIDATED, posture is
    TRANSFER_LOCKED.

    PRD §3.5: 'When direction is OUTBOUND, validation also flips
    Account.trading_posture from OPEN to TRANSFER_LOCKED as a cascade'.
    Used by transfer-lock posture tests and cancel-preserves-equity
    tests.
    """
    customer, account, transfer = (
        setup_account_with_outbound_acat_initiated(
            cash_amount_cents=cash_amount_cents,
            transfer_value_cents=transfer_value_cents,
        )
    )
    resp = api_client.validate_acat_transfer(
        transfer["id"], TEST_USERS["compliance_headers"],
    )
    transfer = get_success_data(resp)
    fresh_acct = get_success_data(
        api_client.get_account(
            account["id"], make_customer_headers(customer["id"]),
        )
    )
    return customer, fresh_acct, transfer


# ===========================================================================
# Tier 9: Composite for the 3-hop PDT cascade (difficulty-design)
# ===========================================================================
def setup_for_pdt_three_hop_cascade(
    *,
    cash_amount_cents: int = 2_499_900,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]
]:
    """Pre-stage everything the PDT 3-hop cascade test needs:
      - approved REG_T account with cash < PDT floor
      - 3 prior DayTrade rows in today's window
      - one WORKING LIMIT Order O1 on the same account
      - one OptionsApproval OA1 in UNDER_REVIEW (after start-review)

    Returns (customer, account, working_order, under_review_approval).

    PRD §3.4 cascade chain: DayTrade insert (4th) -> Account.pdt_flag :=
    true, posture := PDT_FROZEN -> all non-terminal Orders -> CANCELLED
    AND all non-terminal OptionsApprovals -> REJECTED with reason
    'PDT_FREEZE'.
    """
    # Build with ultra-rich customer so options eligibility is high
    # enough to submit any level (we use level 1 to minimize tier risk).
    customer, account = setup_funded_account(
        account_type="MARGIN_REG_T",
        cash_amount_cents=cash_amount_cents,
        years_options_experience=10,
        liquid_net_worth_cents=50_000_000_00,
        total_net_worth_cents=100_000_000_00,
    )
    # 3 prior DayTrade rows.
    accumulate_n_day_trades(
        customer, account, n=3, market_price_cents=100,
    )
    # One WORKING LIMIT BUY.
    working = submit_working_limit_buy(
        customer, account, symbol="AAPL",
        quantity=1, limit_price_cents=100,
    )
    # OptionsApproval in UNDER_REVIEW.
    approval = setup_options_approval_under_review(
        customer, account, requested_level=1,
    )
    fresh_acct = get_success_data(
        api_client.get_account(
            account["id"], make_customer_headers(customer["id"]),
        )
    )
    return customer, fresh_acct, working, approval


# ===========================================================================
# Tier 10: Composite for the ACAT completion 2-hop cascade
# ===========================================================================
def setup_for_acat_completion_two_hop_cascade(
    *,
    cash_amount_cents: int = 10_000_000,
    transfer_value_cents: int = 500_000,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any]
]:
    """Approved + funded account with OUTBOUND ACAT in VALIDATED state.

    Returns (customer, account, transfer).

    Used by the 2-hop cascade test where a subsequent
    /_clock/advance crosses expected_completion_at, triggering:
      Hop 1: ACATTransfer -> COMPLETED, cash decremented by
             requested_value_cents
      Hop 2: Account.trading_posture reverts to OPEN
    (PRD §3.5.)
    """
    return setup_account_with_outbound_acat_validated(
        cash_amount_cents=cash_amount_cents,
        transfer_value_cents=transfer_value_cents,
    )


__all__ = [
    "advance_clock",
    "run_sweep",
    "create_customer",
    "create_account",
    "submit_kyc",
    "verify_kyc",
    "reject_kyc",
    "setup_approved_customer_and_account",
    "fund_account_inbound_acat",
    "setup_funded_account",
    "create_options_approval",
    "start_options_review",
    "decide_options_approval",
    "setup_options_approval_under_review",
    "setup_account_with_options_level",
    "submit_order",
    "fill_order",
    "cancel_order",
    "submit_working_limit_buy",
    "execute_one_day_trade",
    "accumulate_n_day_trades",
    "setup_account_below_pdt_floor_with_n_day_trades",
    "trigger_fourth_day_trade",
    "setup_account_with_working_limit_order",
    "setup_account_with_outbound_acat_initiated",
    "setup_account_with_outbound_acat_validated",
    "setup_for_pdt_three_hop_cascade",
    "setup_for_acat_completion_two_hop_cascade",
]
