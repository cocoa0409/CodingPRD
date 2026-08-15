"""Second-coverage tests for difficulty-design instances."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_cash_movement_payload,
    create_liquidation_order_payload,
    deposit,
    get_account,
    get_account_version,
    make_customer_headers,
    make_desk_headers,
    run_sweep,
    set_clock,
    setup_debit_account_with_tiers,
    setup_expired_house_call,
    setup_funded_account,
    setup_liquidation_order,
    setup_pdt_account,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw,
)


def test_per_day_rounding_visible_on_each_daily_entry(api):
    """PRD §3.9: "the day's `amount_cents` is the debit times the tier's
    `annual_rate_bps` divided by ten thousand and by 360, rounded half up to
    whole cents."
    PRD §2.4: "each daily interest accrual is rounded before the month's
    accruals are summed into a monthly posting."

    Design: Difficulty/combinatorial_formula/interest_accrual_mode_b_per_day_rounding_pinned
    """
    # Debit 12000001 at 950bps: each individual daily entry is exactly 3167 —
    # the fractional residue (.668...) never carries into the next day.
    # Deposit 13999999 clears the §3.4 opening-order gate (equity' 13999999 >=
    # Reg T initial' 13000000 and >= house' 13000000).
    ctx = setup_debit_account_with_tiers(
        13_999_999, 2_600, tiers=((3, 10_000_000, 950),)
    )
    account_id = ctx["account_id"]
    run_sweep()
    set_clock("2026-05-02T00:00:00Z")
    run_sweep()
    set_clock("2026-05-03T00:00:00Z")
    run_sweep()
    entries_resp = api_client.list_interest_entries(
        account_id, TEST_USERS["supervisor_headers"]
    )
    entries, _meta = validate_paginated(entries_resp)
    assert len(entries) == 3
    for entry in entries:
        assert entry["entry_type"] == "DAILY_ACCRUAL"
        assert entry["amount_cents"] == 3_167
        assert entry["rate_bps_applied"] == 950


def test_provisional_estimate_assumes_constant_debit(api):
    """PRD §3.9: "a `provisional_month_estimate_cents` equal to the
    month-to-date accrual plus the remaining days of the month times the
    current daily accrual (an estimate that assumes the debit stays constant
    and therefore diverges from posted actuals when the debit changes
    mid-month) ..."

    Design: Difficulty/dual_variant_calc/interest_provisional_vs_posted_diverge_on_midmonth_balance_change
    """
    # Constant debit of 3000000 at tier2 1100bps -> daily 917. After the first
    # sweep (May 1) mtd == 917 and the provisional estimate projects the
    # remaining 30 days at the current daily rate: 917 + 30*917 = 28397.
    # Deposit 3500000 clears the §3.4 opening-order gate (equity' 3500000 >=
    # Reg T initial' 3250000 and >= house' 3250000).
    ctx = setup_debit_account_with_tiers(3_500_000, 650)
    account_id = ctx["account_id"]
    run_sweep()
    summary = validate_success(
        api_client.get_interest_summary(account_id, TEST_USERS["supervisor_headers"])
    )
    assert summary["month_to_date_accrued_cents"] == 917
    assert summary["current_daily_accrual_cents"] == 917
    assert summary["provisional_month_estimate_cents"] == 917 + 30 * 917


def test_journal_credit_and_debit_move_cash_symmetrically(api):
    """PRD §3.9: "Deposits and journal credits add to `cash_balance_cents`;
    withdrawals and journal debits subtract."

    Design: Difficulty/compensating_invariant/deposit_then_withdraw_conserves_cash_and_equity
    """
    customer, account_id = setup_funded_account(1_000_000)
    v = get_account_version(account_id)
    resp = api_client.create_cash_movement(
        account_id,
        create_cash_movement_payload(
            v, movement_type="JOURNAL_CREDIT", amount_cents=40_000
        ),
        make_customer_headers(customer["id"]),
    )
    credited = validate_success(resp, expected_status=201)
    assert credited["resulting_cash_balance_cents"] == 1_040_000
    v = get_account_version(account_id)
    resp = api_client.create_cash_movement(
        account_id,
        create_cash_movement_payload(
            v, movement_type="JOURNAL_DEBIT", amount_cents=40_000
        ),
        make_customer_headers(customer["id"]),
    )
    debited = validate_success(resp, expected_status=201)
    assert debited["resulting_cash_balance_cents"] == 1_000_000
    account = get_account(account_id)
    assert account["cash_balance_cents"] == 1_000_000
    assert account["equity_realtime_cents"] == 1_000_000
    assert account["equity_official_cents"] == 1_000_000


def test_cancel_partially_filled_order_compensates_only_unfilled_remainder(api):
    """PRD §3.9: "Cancelling is allowed from `PENDING` or `PARTIALLY_FILLED`
    (else `ERR_LIQUIDATION_INVALID_STATE`) and lands the order in its other
    terminal state, `CANCELLED`; the unfilled remainder is subtracted from the
    position's `reserved_qty`, while fills already applied are not reversed."

    Design: Difficulty/compensating_invariant/liquidation_create_then_cancel_conserves_position_shares
    """
    ctx = setup_liquidation_order()
    position_id = ctx["position"]["id"]
    api_client.fill_liquidation_order(
        ctx["order"]["id"],
        {"filled_quantity": 50, "fill_price_cents": 7_000},
        make_desk_headers("desk-2"),
    )
    mid = validate_success(
        api_client.get_position(position_id, TEST_USERS["supervisor_headers"])
    )
    assert mid["quantity"] == 150
    assert mid["reserved_qty"] == 150
    cancelled = validate_success(
        api_client.cancel_liquidation_order(ctx["order"]["id"], make_desk_headers("desk-1"))
    )
    assert cancelled["order_status"] == "CANCELLED"
    assert cancelled["filled_quantity"] == 50
    end = validate_success(
        api_client.get_position(position_id, TEST_USERS["supervisor_headers"])
    )
    # Applied fills are not reversed; only the 150-share remainder is released.
    assert end["quantity"] == 150
    assert end["reserved_qty"] == 0


def test_deposit_allowed_on_restricted_account_and_cures_open_call(api):
    """PRD §3.9: "Deposits and journal credits are permitted on any
    non-`CLOSED` account; withdrawals and journal debits require `ACTIVE`
    posture (`ERR_ACCOUNT_RESTRICTED` while restricted) ..."
    PRD §3.9: "A deposit or credit that satisfies an `OPEN` call's cure test
    resolves it with `cure_method` `DEPOSIT`, followed by the posture recheck."

    Design: Difficulty/priority_pair_validation_conflict/withdrawal_state_beats_fiscal
    """
    from test_helpers import setup_account_with_open_house_call

    ctx = setup_account_with_open_house_call()
    account = get_account(ctx["account_id"])
    assert account["account_status"] == "RESTRICTED"
    # Deposit is a different movement family: allowed while RESTRICTED, and a
    # sufficient deposit cures the OPEN call and restores ACTIVE posture.
    deposit(ctx["account_id"], ctx["customer"]["id"], 300_000)
    call = validate_success(
        api_client.get_margin_call(ctx["call"]["id"], TEST_USERS["supervisor_headers"])
    )
    assert call["call_status"] == "CURED"
    assert call["cure_method"] == "DEPOSIT"
    account = get_account(ctx["account_id"])
    assert account["account_status"] == "ACTIVE"


def test_restricted_blocks_withdrawal_but_not_deposit(api):
    """PRD §3.9: "Deposits and journal credits are permitted on any
    non-`CLOSED` account; withdrawals and journal debits require `ACTIVE`
    posture (`ERR_ACCOUNT_RESTRICTED` while restricted) ..."

    Design: Difficulty/cross_entity_state_dependency/withdrawal_requires_account_active_pair_cashmovement_account
    """
    from test_helpers import setup_account_with_open_house_call

    ctx = setup_account_with_open_house_call()
    account = get_account(ctx["account_id"])
    assert account["account_status"] == "RESTRICTED"
    # Withdrawal blocked...
    resp = api_client.create_cash_movement(
        ctx["account_id"],
        create_cash_movement_payload(
            account["version"], movement_type="WITHDRAWAL", amount_cents=100
        ),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESTRICTED)
    # ...but a deposit on the same restricted account succeeds.
    deposited = deposit(ctx["account_id"], ctx["customer"]["id"], 50_000)
    assert deposited["movement_type"] == "DEPOSIT"
    account_after = get_account(ctx["account_id"])
    assert account_after["cash_balance_cents"] == -950_000


def test_liquidation_lock_releases_after_terminal_fill(api):
    """PRD §3.9: "the account must not already carry a non-terminal liquidation
    order: while any earlier order on the account remains `PENDING` or
    `PARTIALLY_FILLED`, a fresh creation is rejected with
    `ERR_LIQUIDATION_IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/liquidation_lock_half_open_lifetime_on_account
    """
    ctx = setup_liquidation_order()
    # Drive the first order to a terminal state via a full fill.
    filled = validate_success(
        api_client.fill_liquidation_order(
            ctx["order"]["id"],
            {"filled_quantity": 200, "fill_price_cents": 7_000},
            make_desk_headers("desk-2"),
        )
    )
    assert filled["order_status"] == "EXECUTED"
    # The call is now CURED (terminal), so a second liquidation create against
    # it must fail — but with the call-state error, proving the account lock
    # itself has released.
    version = get_account_version(ctx["account_id"])
    resp = api_client.create_liquidation_order(
        ctx["account_id"],
        create_liquidation_order_payload(ctx["call"]["id"], version),
        make_desk_headers("desk-1"),
    )
    validate_error(resp, ApiErrorId.ERR_CALL_NOT_EXPIRED)
