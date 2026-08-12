"""Order gating: buying power, marks, PDT flag evaluation and gate."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_approved_account,
    create_customer,
    create_order_payload,
    create_security_profile,
    deposit,
    get_account,
    make_customer_headers,
    place_order,
    post_mark,
    post_marks_both,
    run_sweep,
    setup_funded_account,
    setup_pdt_account,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw,
)


def test_insufficient_buying_power_on_overleveraged_opening_order(api):
    """PRD §3.4: "The fill is allowed only if post-trade equity is greater
    than or equal to the Reg T initial requirement and greater than or equal to
    the house requirement; otherwise the order is rejected with
    `ERR_INSUFFICIENT_BUYING_POWER` and nothing is recorded."

    Design: Corner/validations/insufficient_buying_power_on_overleveraged_opening_order
    """
    security = create_security_profile(symbol="ABC")
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    # Buying 201 shares: cash' = -1010000, mv' = 2010000, equity' = 1000000;
    # Reg T initial req = 2010000*0.5 = 1005000 > equity' -> rejected.
    resp = api_client.place_order(
        account_id,
        create_order_payload(security["id"], side="BUY", quantity=201),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BUYING_POWER)


def test_order_on_unmarked_security_returns_no_market_mark(api):
    """PRD §3.4: "Instrument checks follow — the security must be `marginable`
    (`ERR_SECURITY_NOT_MARGINABLE`) and must have at least one `REALTIME` mark
    on record (`ERR_NO_MARKET_MARK`)."

    Design: Corner/validations/order_on_unmarked_security_returns_no_market_mark
    """
    security = create_security_profile(symbol="NOMARK")
    customer, account_id = setup_funded_account(1_000_000)
    resp = api_client.place_order(
        account_id,
        create_order_payload(security["id"], side="BUY", quantity=1),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_MARKET_MARK)


def test_immediate_visibility_of_order_effects(api):
    """PRD §3.4: "Orders fill immediately, in full, at the security's latest
    `REALTIME` mark."
    PRD §3.4: "A successful fill does several things atomically. A `TradeFill`
    is recorded ... Cash moves with the fill: `BUY` and `BUY_TO_COVER` debit
    `cash_balance_cents` by the filled value ..."

    Design: Corner/consistency_model/immediate_visibility_of_order_effects
    """
    security = create_security_profile(symbol="ABC")
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    position = place_order(account_id, customer["id"], security["id"], "BUY", 10)
    assert position["quantity"] == 10
    assert position["mv_realtime_cents"] == 100_000
    account = get_account(account_id)
    assert account["cash_balance_cents"] == 900_000


def test_day_trade_detection_one_event_per_security_day(api):
    """PRD §3.4: "When a `SELL` closes long shares that were bought the same
    day, the day-trade share count is the smaller of `today_bought_qty` as it
    stood before the fill and the sold quantity; when that count is positive,
    the fill is marked `is_day_trade` and, unless a `DayTradeEvent` already
    exists for that account, security, and `event_date`, one is created — at
    most one event ever exists per account, security, and calendar date."

    Design: Corner/calculations/day_trade_detection_creates_one_event_per_account_security_day
    """
    security = create_security_profile(symbol="ABC", concentration_threshold_bps=9000)
    post_marks_both(security["id"], 1_000)
    customer, account_id = setup_funded_account(
        3_000_000,
        annual_income_cents=50_000_000,
        liquid_net_worth_cents=90_000_000,
        investment_experience_years=7,
    )
    cust = make_customer_headers(customer["id"])
    for _ in range(2):
        place_order(account_id, customer["id"], security["id"], "BUY", 5)
        place_order(account_id, customer["id"], security["id"], "SELL", 5)

    events_resp = api_client.list_account_day_trade_events(
        account_id, TEST_USERS["supervisor_headers"]
    )
    events, events_meta = validate_paginated(events_resp)
    assert events_meta["total_count"] == 1
    assert len(events) == 1

    fills_resp = api_client.list_account_fills(
        account_id, TEST_USERS["supervisor_headers"], params={"limit": 100}
    )
    fills, _ = validate_paginated(fills_resp)
    assert len(fills) == 4
    sells = [f for f in fills if f["side"] == "SELL"]
    assert len(sells) == 2
    assert all(f["is_day_trade"] is True for f in sells)


def test_pdt_count_boundary_three_round_trips_no_flag(api):
    """PRD §3.6: "The account is flagged — `pdt_flag` set true — when both
    conditions hold: the day-trade count is at least 4, and the day-trade count
    strictly exceeds six percent of the fill count, evaluated as integer
    cross-multiplication (day trades times one hundred strictly greater than
    six times fills)."

    Design: Corner/calculations/pdt_count_boundary_three_round_trips_no_flag
    """
    security = create_security_profile(symbol="ABC", concentration_threshold_bps=9000)
    post_marks_both(security["id"], 1_000)

    # Account A: exactly 3 round trips -> 3 events / 6 fills -> below threshold.
    cust_a, _app_a, acct_a = create_approved_account(
        annual_income_cents=50_000_000,
        liquid_net_worth_cents=90_000_000,
        investment_experience_years=7,
    )
    deposit(acct_a, cust_a["id"], 5_000_000)
    from test_helpers import run_round_trips

    run_round_trips(acct_a, cust_a["id"], security["id"], 3, quantity=1)

    # Account B: 4 round trips -> 4 events / 8 fills -> 400 > 48 -> flagged.
    cust_b, _app_b, acct_b = create_approved_account(
        annual_income_cents=50_000_000,
        liquid_net_worth_cents=90_000_000,
        investment_experience_years=7,
    )
    deposit(acct_b, cust_b["id"], 5_000_000)
    run_round_trips(acct_b, cust_b["id"], security["id"], 4, quantity=1)

    run_sweep()
    assert get_account(acct_a)["pdt_flag"] is False
    assert get_account(acct_b)["pdt_flag"] is True


def test_pdt_equity_boundary_exact_2500000_opens_allowed(api):
    """PRD §3.4: "when the account's `pdt_flag` is set and
    `equity_realtime_cents` is below 2,500,000 cents (twenty-five thousand
    dollars), the order is rejected with `ERR_PDT_MIN_EQUITY`."

    Design: Difficulty/boundary_precision_check/pdt_equity_boundary_exact_2500000_opens_allowed
    """
    # Account at exactly 2500000 realtime equity: gate is "below" -> allowed.
    ctx = setup_pdt_account()
    account_id = ctx["account_id"]
    customer_id = ctx["customer"]["id"]
    security_id = ctx["security"]["id"]
    resp = withdraw(account_id, customer_id, 500_000)
    validate_success(resp, expected_status=201)
    account = get_account(account_id)
    assert account["pdt_flag"] is True
    assert account["equity_realtime_cents"] == 2_500_000
    ok = api_client.place_order(
        account_id,
        create_order_payload(security_id, side="BUY", quantity=1),
        make_customer_headers(customer_id),
    )
    validate_success(ok, expected_status=201)


def test_pdt_equity_one_cent_below_boundary_rejected(api):
    """PRD §3.4: "when the account's `pdt_flag` is set and
    `equity_realtime_cents` is below 2,500,000 cents (twenty-five thousand
    dollars), the order is rejected with `ERR_PDT_MIN_EQUITY`."

    Design: Difficulty/boundary_precision_check/pdt_equity_boundary_exact_2500000_opens_allowed
    """
    ctx = setup_pdt_account()
    account_id = ctx["account_id"]
    customer_id = ctx["customer"]["id"]
    security_id = ctx["security"]["id"]
    resp = withdraw(account_id, customer_id, 500_001)
    validate_success(resp, expected_status=201)
    account = get_account(account_id)
    assert account["pdt_flag"] is True
    assert account["equity_realtime_cents"] == 2_499_999
    blocked = api_client.place_order(
        account_id,
        create_order_payload(security_id, side="BUY", quantity=1),
        make_customer_headers(customer_id),
    )
    validate_error(blocked, ApiErrorId.ERR_PDT_MIN_EQUITY)


def test_order_pdt_safety_beats_marginable_constraint(api):
    """PRD §2.10: "every request is validated against the following cascade in
    this fixed order — a failure at any step short-circuits all later steps:
    ... 6. **Regulatory and compliance gates** — segregation of duties on
    application approve/reject, liquidation fills, and dispute decisions
    (`ERR_SEGREGATION_OF_DUTIES`); and the pattern-day-trader minimum-equity
    gate on opening orders (`ERR_PDT_MIN_EQUITY`). ... 8. **Instrument and
    structural rules** — the security must be marginable for opening orders
    (`ERR_SECURITY_NOT_MARGINABLE`); a realtime mark must exist
    (`ERR_NO_MARKET_MARK`); ..."

    Design: Difficulty/priority_pair_validation_conflict/order_pdt_safety_beats_marginable_constraint
    """
    ctx = setup_pdt_account()
    account_id = ctx["account_id"]
    customer_id = ctx["customer"]["id"]
    resp = withdraw(account_id, customer_id, 500_001)
    validate_success(resp, expected_status=201)
    account = get_account(account_id)
    assert account["pdt_flag"] is True
    assert account["equity_realtime_cents"] == 2_499_999

    nm = create_security_profile(
        symbol="NM",
        marginable=False,
        house_maint_long_bps=10_000,
        house_maint_short_bps=10_000,
        liquidity_tier=9,
        concentration_threshold_bps=9000,
    )
    post_marks_both(nm["id"], 500)
    blocked = api_client.place_order(
        account_id,
        create_order_payload(nm["id"], side="BUY", quantity=1),
        make_customer_headers(customer_id),
    )
    # Priority 6 (PDT gate) short-circuits priority 8 (marginable check).
    validate_error(blocked, ApiErrorId.ERR_PDT_MIN_EQUITY)


def test_opening_order_on_restricted_account_rejected(api):
    """PRD §3.4: "Orders that would establish a new position or increase the
    size of an existing one are "opening orders": they require `ACTIVE`
    posture, and on a `RESTRICTED` account they fail with
    `ERR_ACCOUNT_RESTRICTED`, while orders that reduce or close out a position
    remain permitted."

    Design: Difficulty/priority_pair_validation_conflict/order_pdt_safety_beats_marginable_constraint
    """
    # Independent confirmation that a RESTRICTED account rejects opening
    # orders at the state step of the same cascade.
    from test_helpers import setup_account_with_open_house_call

    ctx = setup_account_with_open_house_call()
    account = get_account(ctx["account_id"])
    assert account["account_status"] == "RESTRICTED"
    resp = api_client.place_order(
        ctx["account_id"],
        create_order_payload(ctx["security"]["id"], side="BUY", quantity=1),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESTRICTED)
