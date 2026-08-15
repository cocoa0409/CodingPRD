"""Cash movements: OCC, conservation, sufficiency, and restricted gating."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_approved_account,
    create_cash_movement_payload,
    deposit,
    get_account,
    get_account_version,
    make_customer_headers,
    setup_account_with_open_house_call,
    setup_funded_account,
    TEST_USERS,
    validate_error,
    validate_success,
)


def test_occ_stale_version_on_cash_movement(api):
    """PRD §2.8: "If `expected_account_version` does not match the account's
    current `version` — because another writer has since posted a movement,
    filled an order, or run a sweep cascade against the same account, advancing
    its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "A successful guarded write increments the account's `version` by
    exactly one."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_cash_movement
    """
    _customer, _app, account_id = create_approved_account()
    customer = _customer
    v0 = get_account_version(account_id)
    deposit(account_id, customer["id"], 100_000)
    # Replay the stale version.
    resp = api_client.create_cash_movement(
        account_id,
        create_cash_movement_payload(
            v0, movement_type="DEPOSIT", amount_cents=50_000
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # Fresh version succeeds.
    v1 = get_account_version(account_id)
    ok = validate_success(
        api_client.create_cash_movement(
            account_id,
            create_cash_movement_payload(
                v1, movement_type="DEPOSIT", amount_cents=50_000
            ),
            make_customer_headers(customer["id"]),
        ),
        expected_status=201,
    )
    assert ok["resulting_cash_balance_cents"] == 150_000


def test_version_increments_on_every_mutation(api):
    """PRD §2.7: "`version` — an integer, starting at its initial value on
    creation, that increments by one on every mutation; it backs the optimistic
    concurrency control of §2.8."
    PRD §2.8: "A successful guarded write increments the account's `version` by
    exactly one."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
    """
    customer, _app, account_id = create_approved_account()
    v0 = get_account_version(account_id)
    assert v0 == 1
    deposit(account_id, customer["id"], 100)
    v1 = get_account_version(account_id)
    assert v1 == 2
    deposit(account_id, customer["id"], 100)
    v2 = get_account_version(account_id)
    assert v2 == 3


def test_deposit_then_withdraw_conserves_cash_and_equity(api):
    """PRD §3.9: "Deposits and journal credits add to `cash_balance_cents`;
    withdrawals and journal debits subtract."
    PRD §3.9: "withdrawals and journal debits require `ACTIVE` posture ... may
    not exceed `cash_balance_cents` (`ERR_INSUFFICIENT_CASH`), and must leave
    the binding official maintenance excess at zero or above after the debit."

    Design: Difficulty/compensating_invariant/deposit_then_withdraw_conserves_cash_and_equity
    """
    customer, account_id = setup_funded_account(1_000_000)
    before = get_account(account_id)
    assert before["cash_balance_cents"] == 1_000_000
    assert before["equity_realtime_cents"] == 1_000_000
    assert before["equity_official_cents"] == 1_000_000

    deposit(account_id, customer["id"], 250_000)
    v = get_account_version(account_id)
    resp = api_client.create_cash_movement(
        account_id,
        create_cash_movement_payload(
            v, movement_type="WITHDRAWAL", amount_cents=250_000
        ),
        make_customer_headers(customer["id"]),
    )
    movement = validate_success(resp, expected_status=201)
    assert movement["resulting_cash_balance_cents"] == 1_000_000
    after = get_account(account_id)
    assert after["cash_balance_cents"] == 1_000_000
    assert after["equity_realtime_cents"] == 1_000_000
    assert after["equity_official_cents"] == 1_000_000


def test_withdrawal_exceeding_cash_returns_insufficient_cash(api):
    """PRD §3.9: "withdrawals and journal debits require `ACTIVE` posture
    (`ERR_ACCOUNT_RESTRICTED` while restricted), may not exceed
    `cash_balance_cents` (`ERR_INSUFFICIENT_CASH`), and must leave the binding
    official maintenance excess at zero or above after the debit
    (`ERR_MAINTENANCE_EXCESS_NEGATIVE`)."

    Design: Corner/validations/withdrawal_exceeding_cash_returns_insufficient_cash
    """
    customer, account_id = setup_funded_account(100_000)
    v = get_account_version(account_id)
    resp = api_client.create_cash_movement(
        account_id,
        create_cash_movement_payload(
            v, movement_type="WITHDRAWAL", amount_cents=100_001
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CASH)


def test_withdrawal_on_restricted_account_returns_restricted_not_fiscal(api):
    """PRD §2.10: "every request is validated against the following cascade in
    this fixed order — a failure at any step short-circuits all later steps:
    ... 5. **State preconditions** — ... opening orders and withdrawals
    additionally require `ACTIVE` posture (`ERR_ACCOUNT_RESTRICTED`); ... 10.
    **Fiscal checks** — post-trade buying power on opening orders
    (`ERR_INSUFFICIENT_BUYING_POWER`), withdrawal cash sufficiency
    (`ERR_INSUFFICIENT_CASH`), and the post-withdrawal maintenance-excess floor
    (`ERR_MAINTENANCE_EXCESS_NEGATIVE`)."

    Design: Difficulty/priority_pair_validation_conflict/withdrawal_state_beats_fiscal
    """
    ctx = setup_account_with_open_house_call()
    account = get_account(ctx["account_id"])
    assert account["account_status"] == "RESTRICTED"
    v = account["version"]
    # A withdrawal that would ALSO fail the cash check (cash is -1000000) still
    # surfaces the state error, never the fiscal error.
    resp = api_client.create_cash_movement(
        ctx["account_id"],
        create_cash_movement_payload(
            v, movement_type="WITHDRAWAL", amount_cents=500_000
        ),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESTRICTED)


def test_withdrawal_blocked_while_restricted_then_succeeds_after_waiver(api):
    """PRD §2.11: "The moment any margin call on the account transitions to
    `OPEN` — whether issued by the official-close mark cascade or by the daily
    sweep — the account flips from `ACTIVE` to `RESTRICTED`, and from that
    moment its opening orders and withdrawals are rejected with
    `ERR_ACCOUNT_RESTRICTED`. Conversely, whenever the account's last
    non-terminal call resolves ... the account automatically returns from
    `RESTRICTED` to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/withdrawal_requires_account_active_pair_cashmovement_account
    """
    from test_helpers import run_sweep, set_clock, setup_pdt_account, withdraw

    # Cash-only PDT account: withdraw 600000 -> equity 2400000 < 2500000 ->
    # next sweep issues DAY_TRADE_MIN_EQUITY and flips the account RESTRICTED.
    ctx = setup_pdt_account()
    account_id = ctx["account_id"]
    customer_id = ctx["customer"]["id"]
    resp = withdraw(account_id, customer_id, 600_000)
    validate_success(resp, expected_status=201)
    set_clock("2026-05-02T00:00:00Z")
    run_sweep()
    from test_helpers import validate_paginated

    calls_resp = api_client.list_account_margin_calls(
        account_id, TEST_USERS["supervisor_headers"]
    )
    rows, _meta = validate_paginated(calls_resp)
    assert rows, "Setup failed: expected a DAY_TRADE_MIN_EQUITY call"
    call = rows[0]
    assert call["call_type"] == "DAY_TRADE_MIN_EQUITY"

    account = get_account(account_id)
    assert account["account_status"] == "RESTRICTED"

    v = account["version"]
    blocked = api_client.create_cash_movement(
        account_id,
        create_cash_movement_payload(v, movement_type="WITHDRAWAL", amount_cents=100),
        make_customer_headers(customer_id),
    )
    validate_error(blocked, ApiErrorId.ERR_ACCOUNT_RESTRICTED)

    # Waive -> posture recheck flips the account back to ACTIVE.
    api_client.waive_margin_call(call["id"], TEST_USERS["supervisor_headers"])
    account_after = get_account(account_id)
    assert account_after["account_status"] == "ACTIVE"

    ok = api_client.create_cash_movement(
        account_id,
        create_cash_movement_payload(
            account_after["version"], movement_type="WITHDRAWAL", amount_cents=100
        ),
        make_customer_headers(customer_id),
    )
    movement = validate_success(ok, expected_status=201)
    assert movement["resulting_cash_balance_cents"] == 2_399_900
