"""Composite setup helpers.

These helpers encapsulate the multi-step chains shared across the test suite:
customer onboarding -> application -> review -> approve -> deposit -> order ->
mark cascade -> sweep -> dispute -> liquidation. All helpers use lenient
success validation so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_application_payload,
    create_cash_movement_payload,
    create_customer_payload,
    create_liquidation_fill_payload,
    create_liquidation_order_payload,
    create_market_mark_payload,
    create_order_payload,
    create_rate_tier_payload,
    create_security_profile_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_desk_headers,
)

_counter = {"n": 0}


def _next():
    _counter["n"] += 1
    return _counter["n"]


# ---------------------------------------------------------------------------
# Tier 1: atomic creators
# ---------------------------------------------------------------------------


def create_customer(legal_name=None, email=None):
    """Onboard one customer. Returns the Customer dict."""
    n = _next()
    payload = create_customer_payload(
        legal_name=legal_name or f"Customer {n}",
        email=email or f"customer{n}@example.com",
    )
    resp = api_client.create_customer(payload, TEST_USERS["analyst_headers"])
    return get_success_data(resp)


def create_security_profile(**overrides):
    """Register one security profile. Returns the SecurityProfile dict."""
    n = _next()
    overrides.setdefault("symbol", f"SEC{n}")
    payload = create_security_profile_payload(**overrides)
    resp = api_client.create_security_profile(payload, TEST_USERS["supervisor_headers"])
    return get_success_data(resp)


def post_mark(security_id, mark_type, price_cents):
    """Post one price mark. Returns the PriceMark dict."""
    payload = create_market_mark_payload(
        security_id, mark_type=mark_type, price_cents=price_cents
    )
    resp = api_client.post_market_mark(payload, TEST_USERS["market_ops_headers"])
    return get_success_data(resp)


def post_marks_both(security_id, price_cents):
    """Post both a REALTIME and an OFFICIAL_CLOSE mark at the same price."""
    post_mark(security_id, "REALTIME", price_cents)
    post_mark(security_id, "OFFICIAL_CLOSE", price_cents)


def create_rate_tier(**overrides):
    payload = create_rate_tier_payload(**overrides)
    resp = api_client.create_rate_tier(payload, TEST_USERS["supervisor_headers"])
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(
        {"to_iso8601": to_iso8601}, TEST_USERS["market_ops_headers"]
    )
    return get_success_data(resp)


def run_sweep():
    resp = api_client.run_daily_sweep(TEST_USERS["market_ops_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: application pipeline
# ---------------------------------------------------------------------------


def create_approved_account(
    annual_income_cents=15_000_000,
    liquid_net_worth_cents=50_000_000,
    investment_experience_years=5,
    reviewer="analyst-1",
    approver="sup-1",
):
    """Customer -> application -> review -> approve.

    Returns (customer, application, account_id). The approver is a different
    user id than the reviewer to clear the segregation-of-duties gate.
    """
    customer = create_customer()
    cust_headers = make_customer_headers(customer["id"])
    payload = create_application_payload(
        customer["id"],
        annual_income_cents=annual_income_cents,
        liquid_net_worth_cents=liquid_net_worth_cents,
        investment_experience_years=investment_experience_years,
    )
    app = get_success_data(api_client.create_account_application(payload, cust_headers))
    app = get_success_data(
        api_client.review_application(app["id"], {"X-User-ID": reviewer, "X-User-Role": "MarginAnalyst", "Content-Type": "application/json"})
    )
    app = get_success_data(
        api_client.approve_application(app["id"], {"X-User-ID": approver, "X-User-Role": "MarginSupervisor", "Content-Type": "application/json"})
    )
    return customer, app, app["account_id"]


def get_account(account_id):
    return get_success_data(
        api_client.get_account(account_id, TEST_USERS["supervisor_headers"])
    )


def get_account_version(account_id):
    return get_account(account_id)["version"]


def deposit(account_id, customer_id, amount_cents):
    """DEPOSIT cash movement with fresh OCC version. Returns CashMovement."""
    version = get_account_version(account_id)
    payload = create_cash_movement_payload(
        version, movement_type="DEPOSIT", amount_cents=amount_cents
    )
    resp = api_client.create_cash_movement(
        account_id, payload, make_customer_headers(customer_id)
    )
    return get_success_data(resp)


def place_order(account_id, customer_id, security_id, side, quantity):
    """Place a market order. Returns the Position dict."""
    payload = create_order_payload(security_id, side=side, quantity=quantity)
    resp = api_client.place_order(
        account_id, payload, make_customer_headers(customer_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: funded / positioned accounts
# ---------------------------------------------------------------------------


def setup_funded_account(deposit_cents, **app_kwargs):
    """Approved account with one DEPOSIT applied.

    Returns (customer, account_id).
    """
    customer, _app, account_id = create_approved_account(**app_kwargs)
    deposit(account_id, customer["id"], deposit_cents)
    return customer, account_id


def setup_account_with_long_position(
    deposit_cents,
    quantity,
    mark_price_cents=10_000,
    security_overrides=None,
):
    """Approved account, one security marked on both bases, one long position.

    Returns dict with keys: customer, account_id, security, position.
    """
    security = create_security_profile(**(security_overrides or {}))
    post_marks_both(security["id"], mark_price_cents)
    customer, account_id = setup_funded_account(deposit_cents)
    position = place_order(account_id, customer["id"], security["id"], "BUY", quantity)
    return {
        "customer": customer,
        "account_id": account_id,
        "security": security,
        "position": position,
    }


# ---------------------------------------------------------------------------
# Tier 3: margin-call scenarios
# ---------------------------------------------------------------------------


def setup_account_with_open_house_call(
    deposit_cents=1_000_000,
    quantity=200,
    initial_mark=10_000,
    dropped_mark=7_000,
    security_overrides=None,
):
    """Long position whose OFFICIAL_CLOSE mark then drops, issuing a call.

    Default numbers: 200 shares bought at 10000 with a 1000000 deposit; the
    official mark drops to 7000 -> equity 400000, HOUSE call of 300000 and the
    account flips RESTRICTED.

    Returns dict with keys: customer, account_id, security, position, call.
    """
    ctx = setup_account_with_long_position(
        deposit_cents, quantity, initial_mark, security_overrides
    )
    post_mark(ctx["security"]["id"], "OFFICIAL_CLOSE", dropped_mark)
    # The list endpoint returns a paginated envelope; read its data list.
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_account_margin_calls(
        ctx["account_id"], TEST_USERS["supervisor_headers"]
    )
    rows, _meta = validate_paginated(resp)
    assert rows, "Setup failed: expected a margin call after the mark drop"
    ctx["call"] = rows[0]
    return ctx


def expire_call(account_id, to_iso8601="2026-05-03T00:00:01Z"):
    """Advance the clock past the call deadline and sweep -> call EXPIRED.

    Returns (call, account_version) with the refreshed state.
    """
    set_clock(to_iso8601)
    run_sweep()
    return get_account_version(account_id)


def setup_expired_house_call(**kwargs):
    """OPEN HOUSE call swept past its 48h deadline -> EXPIRED.

    Returns ctx dict with: customer, account_id, security, position, call (now
    EXPIRED), account_version (post-sweep).
    """
    ctx = setup_account_with_open_house_call(**kwargs)
    version = expire_call(ctx["account_id"])
    call = get_success_data(
        api_client.get_margin_call(ctx["call"]["id"], TEST_USERS["supervisor_headers"])
    )
    ctx["call"] = call
    ctx["account_version"] = version
    return ctx


def setup_liquidation_order(desk_user="desk-1", **kwargs):
    """EXPIRED HOUSE call + one liquidation order created by the desk.

    Returns ctx dict with everything from setup_expired_house_call plus
    `order` (the first-ranked LiquidationOrder).
    """
    ctx = setup_expired_house_call(**kwargs)
    version = get_account_version(ctx["account_id"])
    payload = create_liquidation_order_payload(ctx["call"]["id"], version)
    order = get_success_data(
        api_client.create_liquidation_order(
            ctx["account_id"], payload, make_desk_headers(desk_user)
        )
    )
    ctx["order"] = order
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: pattern-day-trader scenarios
# ---------------------------------------------------------------------------


def run_round_trips(account_id, customer_id, security_id, trips, quantity=10):
    """Execute `trips` same-day BUY/SELL round trips."""
    for _ in range(trips):
        place_order(account_id, customer_id, security_id, "BUY", quantity)
        place_order(account_id, customer_id, security_id, "SELL", quantity)


def setup_pdt_account(
    deposit_cents=3_000_000,
    round_trips=4,
    mark_price_cents=1_000,
    sweep=True,
):
    """PDT-flagged account: funded, N same-day round trips on a cheap security,
    then swept so the flag evaluation runs.

    Returns dict with: customer, account_id, security.
    """
    security = create_security_profile(concentration_threshold_bps=9000)
    post_marks_both(security["id"], mark_price_cents)
    customer, _app, account_id = create_approved_account(
        annual_income_cents=50_000_000,
        liquid_net_worth_cents=90_000_000,
        investment_experience_years=7,
    )
    deposit(account_id, customer["id"], deposit_cents)
    run_round_trips(account_id, customer["id"], security["id"], round_trips)
    if sweep:
        run_sweep()
    return {"customer": customer, "account_id": account_id, "security": security}


def withdraw(account_id, customer_id, amount_cents):
    version = get_account_version(account_id)
    payload = create_cash_movement_payload(
        version, movement_type="WITHDRAWAL", amount_cents=amount_cents
    )
    return api_client.create_cash_movement(
        account_id, payload, make_customer_headers(customer_id)
    )


# ---------------------------------------------------------------------------
# Tier 5: interest accrual scenarios
# ---------------------------------------------------------------------------


def setup_debit_account_with_tiers(
    deposit_cents,
    buy_quantity,
    mark_price_cents=10_000,
    tiers=((1, 0, 1200), (2, 2_500_000, 1100), (3, 10_000_000, 950)),
    security_overrides=None,
):
    """Approved account with rate tiers installed and a debit balance created
    by buying a position larger than the deposit.

    Returns dict with: customer, account_id, security.
    """
    security = create_security_profile(
        **(security_overrides or {"concentration_threshold_bps": 9500})
    )
    post_marks_both(security["id"], mark_price_cents)
    for level, min_balance, rate in tiers:
        create_rate_tier(
            tier_level=level,
            min_balance_cents=min_balance,
            annual_rate_bps=rate,
            effective_from="2026-01-01",
            effective_to=None,
        )
    customer, _app, account_id = create_approved_account(
        annual_income_cents=90_000_000,
        liquid_net_worth_cents=90_000_000,
        investment_experience_years=9,
    )
    deposit(account_id, customer["id"], deposit_cents)
    place_order(account_id, customer["id"], security["id"], "BUY", buy_quantity)
    return {"customer": customer, "account_id": account_id, "security": security}


def advance_one_day_and_sweep(current_iso):
    """Move the clock to the given ISO instant (next day) and run the sweep."""
    set_clock(current_iso)
    return run_sweep()
