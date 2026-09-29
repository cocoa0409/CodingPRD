"""Cash-office state cycles that revisit an earlier state: the till recount loop
and the safe time-delay device returning to LOCKED three different ways."""

from test_helpers import (
    CLERK_1,
    CLERK_2,
    CLERK_3,
    CLERK_4,
    ApiErrorId,
    arm_open_request,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    lines,
    list_cases,
    open_safe,
    parse_instant,
    prepare_deposit,
    read_cashier,
    read_safe,
    read_session,
    record_drop,
    seal_deposit,
    set_clock,
    validate_error,
    validate_success,
)

#: Store S-1005 runs a 5-minute delay, a 10-minute window and dual control.
_STORE_1005 = {
    "store_code": "S-1005",
    "name": "Store 1005",
    "region_code": "WEST",
    "safe_time_delay_minutes": 5,
    "safe_open_window_minutes": 10,
    "dual_control_required": True,
    "single_event_variance_threshold_cents": 2500,
}

#: Store S-1006 shares the timing policy; it never runs a till.
_STORE_1006 = {
    "store_code": "S-1006",
    "name": "Store 1006",
    "region_code": "WEST",
    "safe_time_delay_minutes": 5,
    "safe_open_window_minutes": 10,
    "dual_control_required": True,
}


def _setup_recount_ready_session():
    """Drive one till session to COUNTED with a first blind count of 18000.

    Register 1 of the 2026-08-03 journal takes a 20000 starting bank, drops a
    declared 147500 into the open safe, closes on POS cash 150000 with 2500
    paid out, and is blind-counted at 18000 by U-CLERK-3.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(**_STORE_1005)
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], "2026-08-03")
    session = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    arm_open_request(safe["id"], CLERK_1, reason="Closing drop")
    set_clock("2026-08-03T09:05:00Z")
    open_safe(safe["id"], CLERK_2)
    record_drop(session["id"], cashier["id"], 147500, txn_type="CLOSING_DROP")
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        cashier_id=cashier["id"],
        pos_cash_sales_cents=150000,
        pos_card_sales_cents=80000,
        pos_paid_out_cents=2500,
    )
    blind_count(session["id"], lines((2000, 9)), CLERK_3)
    return {
        "store": store,
        "safe": safe,
        "cashier": cashier,
        "journal": journal,
        "session": read_session(session["id"]),
    }


def test_recount_returns_the_counted_session_to_pending_count_and_discards_the_count(
    api, clerk_3_headers
):
    """PRD §3.4: "The recount increments `recount_count` by 1, clears `counted_lines` to an empty list, sets `counted_cash_cents` back to null, clears `counted_by_user_id`, and increments `version`."

    PRD §3.4: "It deliberately leaves `dropped_declared_cents`, `dropped_verified_cents`, the cashier's rolling variance figures and the safe's `balance_cents` exactly as they were — a discarded count moved no money."

    Design: Difficulty/non_linear_state_machine/till_session_recount_cycle_returns_to_pending_count
    """
    ctx = _setup_recount_ready_session()
    before = ctx["session"]
    assert before["status"] == "COUNTED", f"expected COUNTED, got {before['status']}"
    assert (
        before["counted_cash_cents"] == 18000
    ), f"first blind count is worth 18000, got {before['counted_cash_cents']}"
    assert (
        before["recount_count"] == 0
    ), f"recount_count starts at zero, got {before['recount_count']}"
    assert (
        before["counted_by_user_id"] == CLERK_3
    ), f"expected {CLERK_3}, got {before['counted_by_user_id']}"
    safe_before = read_safe(ctx["safe"]["id"])

    recounted = validate_success(
        api.recount(
            before["id"],
            {"recount_reason": "Strap suspected miscounted"},
            clerk_3_headers,
        )
    )
    assert (
        recounted["status"] == "PENDING_COUNT"
    ), f"expected PENDING_COUNT, got {recounted['status']}"
    assert (
        recounted["recount_count"] == 1
    ), f"expected recount_count 1, got {recounted['recount_count']}"
    assert recounted["version"] == before["version"] + 1, (
        f"the recount increments version: expected {before['version'] + 1}, "
        f"got {recounted['version']}"
    )

    after = read_session(before["id"])
    assert (
        after["status"] == "PENDING_COUNT"
    ), f"expected PENDING_COUNT, got {after['status']}"
    assert (
        after["recount_count"] == 1
    ), f"expected recount_count 1, got {after['recount_count']}"
    assert (
        after["counted_cash_cents"] is None
    ), f"counted_cash_cents goes back to null, got {after['counted_cash_cents']}"
    assert (
        after["counted_by_user_id"] is None
    ), f"counted_by_user_id is cleared, got {after['counted_by_user_id']}"
    assert (
        after["counted_lines"] == []
    ), f"counted_lines is cleared to an empty list, got {after['counted_lines']}"
    assert after["dropped_declared_cents"] == 147500, (
        "a discarded count moved no money: expected 147500, "
        f"got {after['dropped_declared_cents']}"
    )
    assert (
        after["dropped_verified_cents"] is None
    ), f"no deposit was prepared, got {after['dropped_verified_cents']}"

    safe_after = read_safe(ctx["safe"]["id"])
    assert safe_after["balance_cents"] == safe_before["balance_cents"], (
        f"the safe's balance_cents is untouched: expected "
        f"{safe_before['balance_cents']}, got {safe_after['balance_cents']}"
    )
    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["rolling_absolute_variance_cents"] == 0, (
        "the cashier's rolling variance figures are untouched: expected 0, "
        f"got {cashier['rolling_absolute_variance_cents']}"
    )


def test_reconcile_is_refused_while_the_recounted_session_sits_in_pending_count(
    api, clerk_3_headers
):
    """PRD §3.5: "A session may be reconciled only from `COUNTED`; any other `status` answers `ERR_TILL_SESSION_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/till_session_recount_cycle_returns_to_pending_count
    """
    ctx = _setup_recount_ready_session()
    session_id = ctx["session"]["id"]
    validate_success(
        api.recount(
            session_id,
            {"recount_reason": "Strap suspected miscounted"},
            clerk_3_headers,
        )
    )

    refused = api.reconcile_till_session(session_id, clerk_3_headers)
    validate_error(refused, ApiErrorId.ERR_TILL_SESSION_INVALID_STATE.value)

    after = read_session(session_id)
    assert (
        after["status"] == "PENDING_COUNT"
    ), f"the refusal leaves the session PENDING_COUNT, got {after['status']}"
    assert (
        after["recount_count"] == 1
    ), f"the refusal leaves recount_count at 1, got {after['recount_count']}"
    assert (
        after["counted_cash_cents"] is None
    ), f"counted_cash_cents stays null, got {after['counted_cash_cents']}"


def test_second_blind_count_supersedes_the_discarded_one_and_reconciles_flat(
    api, clerk_3_headers, clerk_4_headers
):
    """PRD §3.4: "The `COUNTED` → `PENDING_COUNT` → `COUNTED` cycle may repeat without bound, and the next blind count fully supersedes the discarded one; only the most recent count ever feeds the reconciliation."

    PRD §3.5: "The expected till contents are then the session's `starting_bank_cents`, plus its `pos_cash_sales_cents`, minus its `pos_paid_out_cents`, minus the chosen drop total; the result is stored as `expected_cash_cents`."

    Design: Difficulty/non_linear_state_machine/till_session_recount_cycle_returns_to_pending_count
    """
    ctx = _setup_recount_ready_session()
    session_id = ctx["session"]["id"]
    validate_success(
        api.recount(
            session_id,
            {"recount_reason": "Strap suspected miscounted"},
            clerk_3_headers,
        )
    )

    second = validate_success(
        api.blind_count(
            session_id, {"counted_lines": lines((2000, 10))}, clerk_4_headers
        )
    )
    assert second["status"] == "COUNTED", f"expected COUNTED, got {second['status']}"
    assert (
        second["counted_cash_cents"] == 20000
    ), f"the second count is worth 20000, got {second['counted_cash_cents']}"
    assert (
        second["recount_count"] == 1
    ), f"recount_count stays at 1, got {second['recount_count']}"

    counted = read_session(session_id)
    assert (
        counted["counted_by_user_id"] == CLERK_4
    ), f"expected {CLERK_4}, got {counted['counted_by_user_id']}"

    reconciled = validate_success(
        api.reconcile_till_session(session_id, clerk_3_headers)
    )
    assert (
        reconciled["status"] == "RECONCILED"
    ), f"expected RECONCILED, got {reconciled['status']}"
    assert (
        reconciled["variance_basis"] == "DECLARED_DROPS"
    ), f"expected DECLARED_DROPS, got {reconciled['variance_basis']}"
    assert (
        reconciled["expected_cash_cents"] == 20000
    ), f"expected 20000, got {reconciled['expected_cash_cents']}"
    assert (
        reconciled["variance_cents"] == 0
    ), f"the second count ties out exactly, got {reconciled['variance_cents']}"

    cashier = read_cashier(ctx["cashier"]["id"])
    assert (
        cashier["coaching_state"] == "NONE"
    ), f"a zero variance breaches nothing, got {cashier['coaching_state']}"
    assert (
        cashier["rolling_absolute_variance_cents"] == 0
    ), f"expected 0, got {cashier['rolling_absolute_variance_cents']}"

    cases = list_cases(sales_journal_id=ctx["journal"]["id"])
    assert len(cases) == 0, f"no variance case is opened, got {len(cases)}"


def _setup_expired_open_request():
    """Arm SAFE-A at 18:00:00Z, then stand the clock at the window's exclusive end.

    With a 5-minute delay and a 10-minute window, 18:15:00Z is exactly the upper
    bound at which the request is no longer executable.
    """
    set_clock("2026-08-03T18:00:00Z")
    store = create_store(**_STORE_1006)
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    journal = create_sales_journal(store["id"], "2026-08-03")
    arm_open_request(safe["id"], CLERK_1, reason="First attempt")
    armed = read_safe(safe["id"])
    assert (
        armed["open_state"] == "OPEN_REQUESTED"
    ), f"arming moves the safe to OPEN_REQUESTED, got {armed['open_state']}"
    set_clock("2026-08-03T18:15:00Z")
    return {"store": store, "safe": armed, "journal": journal}


def test_lapsed_open_window_reverts_the_safe_to_locked_and_then_refuses_the_open(
    api, clerk_2_headers
):
    """PRD §2.8: "When the window has lapsed, the server clears `open_requested_at` and `open_requested_by_user_id`, moves `open_state` from `OPEN_REQUESTED` back to `LOCKED`, increments the safe's `version` by 1, and *then* returns `ERR_SAFE_OPEN_REQUEST_EXPIRED`."

    Design: Difficulty/non_linear_state_machine/safe_open_state_reverts_to_locked_on_window_expiry_then_cycles_again
    """
    ctx = _setup_expired_open_request()
    armed = ctx["safe"]

    refused = api.open_safe(armed["id"], clerk_2_headers)
    validate_error(refused, ApiErrorId.ERR_SAFE_OPEN_REQUEST_EXPIRED.value)

    safe = read_safe(armed["id"])
    assert (
        safe["open_state"] == "LOCKED"
    ), f"the lapsed request reverts the safe to LOCKED, got {safe['open_state']}"
    assert (
        safe["open_requested_at"] is None
    ), f"open_requested_at is cleared, got {safe['open_requested_at']}"
    assert (
        safe["open_requested_by_user_id"] is None
    ), f"open_requested_by_user_id is cleared, got {safe['open_requested_by_user_id']}"
    assert safe["version"] == armed["version"] + 1, (
        f"the rejected open still increments version: expected "
        f"{armed['version'] + 1}, got {safe['version']}"
    )


def test_safe_rearms_from_locked_and_the_next_seal_returns_it_to_locked_again(
    api, clerk_2_headers
):
    """PRD §2.8: "A lapsed request must not be left pending, so the next arming starts cleanly from `LOCKED`."

    PRD §3.6: "Sealing records `seal_number` and `sealed_by_user_id`, moves the deposit from `PREPARING` to `SEALED`, and ends the cash-office opening: the parent safe's `open_state` returns from `UNLOCKED` to `LOCKED` with `open_requested_at`, `open_requested_by_user_id` and `unlocked_at` all cleared, and the safe's `version` increments by 1 alongside the deposit's."

    Design: Difficulty/non_linear_state_machine/safe_open_state_reverts_to_locked_on_window_expiry_then_cycles_again
    """
    ctx = _setup_expired_open_request()
    safe_id = ctx["safe"]["id"]
    validate_error(
        api.open_safe(safe_id, clerk_2_headers),
        ApiErrorId.ERR_SAFE_OPEN_REQUEST_EXPIRED.value,
    )

    arm_open_request(safe_id, CLERK_1, reason="Second attempt after lapse")
    rearmed = read_safe(safe_id)
    assert (
        rearmed["open_state"] == "OPEN_REQUESTED"
    ), f"the second arming starts cleanly, got {rearmed['open_state']}"
    assert parse_instant(rearmed["open_requested_at"]) == parse_instant(
        "2026-08-03T18:15:00Z"
    ), (
        "open_requested_at takes the current logical clock: expected "
        f"2026-08-03T18:15:00Z, got {rearmed['open_requested_at']}"
    )
    assert (
        rearmed["open_requested_by_user_id"] == CLERK_1
    ), f"expected {CLERK_1}, got {rearmed['open_requested_by_user_id']}"

    set_clock("2026-08-03T18:20:00Z")
    opened = open_safe(safe_id, CLERK_2)
    assert (
        opened["open_state"] == "UNLOCKED"
    ), f"expected UNLOCKED, got {opened['open_state']}"
    assert parse_instant(opened["unlocked_at"]) == parse_instant(
        "2026-08-03T18:20:00Z"
    ), f"expected 2026-08-03T18:20:00Z, got {opened['unlocked_at']}"

    deposit = prepare_deposit(
        safe_id,
        ctx["journal"]["id"],
        lines((2000, 2), (1000, 1)),
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    assert (
        deposit["declared_total_cents"] == 5000
    ), f"expected 5000, got {deposit['declared_total_cents']}"

    sealed = seal_deposit(deposit["id"], "SEAL-A-001", CLERK_2)
    assert sealed["status"] == "SEALED", f"expected SEALED, got {sealed['status']}"

    safe = read_safe(safe_id)
    assert (
        safe["open_state"] == "LOCKED"
    ), f"the seal ends the opening, got {safe['open_state']}"
    assert (
        safe["open_requested_at"] is None
    ), f"open_requested_at is cleared, got {safe['open_requested_at']}"
    assert (
        safe["open_requested_by_user_id"] is None
    ), f"open_requested_by_user_id is cleared, got {safe['open_requested_by_user_id']}"
    assert (
        safe["unlocked_at"] is None
    ), f"unlocked_at is cleared, got {safe['unlocked_at']}"
    assert (
        safe["balance_cents"] == 495000
    ), f"expected 495000, got {safe['balance_cents']}"
