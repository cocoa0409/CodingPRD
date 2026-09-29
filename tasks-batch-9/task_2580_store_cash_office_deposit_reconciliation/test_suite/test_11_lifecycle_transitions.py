"""Lifecycle transitions of tills, deposits, change orders, safes and cases."""

from test_helpers import (
    ApiErrorId,
    CLERK_1,
    CLERK_2,
    CLERK_3,
    LP_1,
    MANAGER_1,
    MANAGER_2,
    append_attribution,
    arm_open_request,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_change_order,
    create_safe,
    create_sales_journal,
    create_store,
    list_cases,
    make_clerk_headers,
    make_investigator_headers,
    make_manager_headers,
    open_safe,
    parse_instant,
    pickup_deposit,
    post_bank_credit_record,
    post_card_settlement,
    prepare_deposit,
    read_cashier,
    read_change_order,
    read_deposit,
    read_journal,
    read_safe,
    read_session,
    reconcile_till,
    reject_change_order,
    schedule_pickup,
    seal_deposit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------- setup helpers


def _store(store_code, name, region_code="WEST", **overrides):
    """Register one store with the chain-default cash-office policy envelope."""
    return create_store(
        store_code=store_code, name=name, region_code=region_code, **overrides
    )


def _manual_safe(store_id, opening_balance_cents=500000):
    return create_safe(
        store_id,
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=opening_balance_cents,
    )


def _cashier(store_id, employee_code, display_name):
    return create_cashier(
        store_id, employee_code=employee_code, display_name=display_name
    )


def _till_payload(journal_id, cashier_id, safe_id, register_number=1,
                  shift_start_at="2026-08-03T09:00:00Z",
                  shift_end_at="2026-08-03T17:00:00Z",
                  starting_bank_cents=20000):
    return {
        "sales_journal_id": journal_id,
        "cashier_id": cashier_id,
        "safe_id": safe_id,
        "register_number": register_number,
        "shift_start_at": shift_start_at,
        "shift_end_at": shift_end_at,
        "starting_bank_cents": starting_bank_cents,
    }


def _unlock_manual_safe(safe_id, armed_at, opened_at):
    """Arm the time-delay device at `armed_at` and open the safe at `opened_at`."""
    set_clock(armed_at)
    arm_open_request(safe_id, CLERK_1, reason="Deposit preparation")
    set_clock(opened_at)
    return open_safe(safe_id, CLERK_2)


def _total_count(resp):
    _, meta = validate_paginated(resp)
    return meta["total_count"]


# ------------------------------------------------------------ initial state


def test_till_session_initial_state_is_active(api, manager_headers):
    """PRD §3.2: "A successful assignment produces a session with `status` `ACTIVE`, an empty `counted_lines` list, and `counted_cash_cents`, `expected_cash_cents`, `variance_cents` and `variance_basis` all null, with `recount_count` at zero and `forced_close` false."

    PRD §3.2: "The journal's `session_count` increments by 1."

    PRD §3.6: "Once every drop row of a session carries a `verified_amount_cents`, that session's `dropped_verified_cents` becomes non-null, which is precisely what flips a later reconciliation of that session onto the verified branch of §3.5."

    Design: Corner/state_machines/till_session_initial_state_is_active
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1912", "Store 1912")
    safe = _manual_safe(store["id"])
    cashier = _cashier(store["id"], "E-100", "Cashier 100")
    journal = create_sales_journal(store["id"], "2026-08-03")

    resp = api.create_till_session(
        _till_payload(journal["id"], cashier["id"], safe["id"]), manager_headers
    )
    session = validate_success(resp, 201)

    assert session["status"] == "ACTIVE", f"expected ACTIVE, got {session['status']}"
    assert session["counted_lines"] == [], (
        f"a freshly assigned till has an empty counted_lines list, "
        f"got {session['counted_lines']}"
    )
    for field in (
        "counted_cash_cents",
        "expected_cash_cents",
        "variance_cents",
        "variance_basis",
    ):
        assert session[field] is None, f"expected {field} null, got {session[field]}"
    assert session["recount_count"] == 0, (
        f"expected recount_count 0, got {session['recount_count']}"
    )
    assert session["dropped_declared_cents"] == 0, (
        f"expected dropped_declared_cents 0, got {session['dropped_declared_cents']}"
    )
    assert session["dropped_verified_cents"] is None, (
        f"expected dropped_verified_cents null, got {session['dropped_verified_cents']}"
    )
    assert session["counted_by_user_id"] is None, (
        f"expected counted_by_user_id null, got {session['counted_by_user_id']}"
    )
    assert session["forced_close"] is False, (
        f"expected forced_close false, got {session['forced_close']}"
    )
    assert session["pos_cash_sales_cents"] is None, (
        f"expected pos_cash_sales_cents null, got {session['pos_cash_sales_cents']}"
    )
    assert session["pos_card_sales_cents"] is None, (
        f"expected pos_card_sales_cents null, got {session['pos_card_sales_cents']}"
    )
    assert session["version"] == 1, f"expected version 1, got {session['version']}"

    journal_after = read_journal(journal["id"])
    assert journal_after["session_count"] == 1, (
        f"expected session_count 1, got {journal_after['session_count']}"
    )
    assert journal_after["reconciled_session_count"] == 0, (
        f"expected reconciled_session_count 0, "
        f"got {journal_after['reconciled_session_count']}"
    )


# --------------------------------------------------- precondition enforcement


def test_blind_count_on_active_session_returns_till_session_invalid_state(api):
    """PRD §3.4: "A `CashOfficeClerk` submits `counted_lines`, the denomination breakdown of the cash actually found in the drawer, and the session moves from `PENDING_COUNT` to `COUNTED`."

    PRD §2.12: "The failures are `ERR_TILL_SESSION_INVALID_STATE`, `ERR_DEPOSIT_INVALID_STATE`, `ERR_VARIANCE_CASE_INVALID_STATE`, `ERR_CHANGE_ORDER_INVALID_STATE`, `ERR_TENDERS_ALREADY_POSTED`, `ERR_SAFE_NOT_UNLOCKED`, `ERR_SAFE_OPEN_REQUEST_ACTIVE` and `ERR_SMART_SAFE_REQUIRED`, all HTTP 409."

    Design: Corner/state_machines/blind_count_on_active_session_returns_till_session_invalid_state
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1913", "Store 1913")
    safe = _manual_safe(store["id"])
    cashier = _cashier(store["id"], "E-100", "Cashier 100")
    journal = create_sales_journal(store["id"], "2026-08-03")
    session = assign_till(journal["id"], cashier["id"], safe["id"])
    session_v = session["version"]
    assert session["status"] == "ACTIVE", "the session must still be ACTIVE"

    resp = api.blind_count(
        session["id"],
        {"counted_lines": [{"denomination_cents": 2000, "quantity": 6}]},
        make_clerk_headers(CLERK_3),
    )
    validate_error(resp, ApiErrorId.ERR_TILL_SESSION_INVALID_STATE.value)

    after = read_session(session["id"])
    assert after["status"] == "ACTIVE", (
        f"the rejected count must leave the session ACTIVE, got {after['status']}"
    )
    assert after["counted_cash_cents"] is None, (
        f"expected counted_cash_cents null, got {after['counted_cash_cents']}"
    )
    assert after["counted_by_user_id"] is None, (
        f"expected counted_by_user_id null, got {after['counted_by_user_id']}"
    )
    assert after["counted_lines"] == [], (
        f"expected counted_lines [], got {after['counted_lines']}"
    )
    assert after["version"] == session_v, (
        f"a rejected count must not increment version: expected {session_v}, "
        f"got {after['version']}"
    )


def test_deposit_seal_twice_returns_deposit_invalid_state(api):
    """PRD §3.6: "A `CashOfficeClerk` or `StoreManager` supplies a tamper-evident `seal_number`; the deposit must be `PREPARING` (any other `status` answers `ERR_DEPOSIT_INVALID_STATE`) and, while the store requires dual control, the sealing `X-User-ID` must differ from `prepared_by_user_id`."

    PRD §3.6: "Sealing records `seal_number` and `sealed_by_user_id`, moves the deposit from `PREPARING` to `SEALED`, and ends the cash-office opening: the parent safe's `open_state` returns from `UNLOCKED` to `LOCKED` with `open_requested_at`, `open_requested_by_user_id` and `unlocked_at` all cleared, and the safe's `version` increments by 1 alongside the deposit's."

    Design: Corner/state_machines/deposit_seal_twice_returns_deposit_invalid_state
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1914", "Store 1914")
    safe = _manual_safe(store["id"])
    journal = create_sales_journal(store["id"], "2026-08-03")
    _unlock_manual_safe(safe["id"], "2026-08-03T08:00:00Z", "2026-08-03T08:10:00Z")

    deposit = prepare_deposit(
        safe["id"],
        journal["id"],
        [{"denomination_cents": 2000, "quantity": 50}],
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    seal_deposit(deposit["id"], "SEAL-1", CLERK_2)

    resp = api.seal_deposit(
        deposit["id"], {"seal_number": "SEAL-2"}, make_clerk_headers(CLERK_2)
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INVALID_STATE.value)

    after = read_deposit(deposit["id"])
    assert after["status"] == "SEALED", f"expected SEALED, got {after['status']}"
    assert after["seal_number"] == "SEAL-1", (
        f"the second seal must not overwrite the first: expected SEAL-1, "
        f"got {after['seal_number']}"
    )
    assert after["sealed_by_user_id"] == CLERK_2, (
        f"expected sealed_by_user_id {CLERK_2}, got {after['sealed_by_user_id']}"
    )
    assert after["prepared_by_user_id"] == CLERK_1, (
        f"expected prepared_by_user_id {CLERK_1}, got {after['prepared_by_user_id']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["open_state"] == "LOCKED", (
        f"the first seal relocked the safe once: expected LOCKED, "
        f"got {safe_after['open_state']}"
    )

    rows, meta = validate_paginated(
        api.list_safe_transactions(
            make_clerk_headers(CLERK_1), params={"deposit_id": deposit["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one ledger row for the deposit, got {meta['total_count']}"
    )
    assert rows[0]["txn_type"] == "DEPOSIT_REMOVAL", (
        f"expected DEPOSIT_REMOVAL, got {rows[0]['txn_type']}"
    )


# ------------------------------------------------------ invalid transitions


def test_change_order_receive_from_draft_returns_change_order_invalid_state(api):
    """PRD §3.9: "A `CashOfficeClerk` records the `received_amount_cents` actually delivered by the bank; the order must be `APPROVED`, failing which the answer is again `ERR_CHANGE_ORDER_INVALID_STATE`."

    PRD §3.9: "A new order sits at `status` `DRAFT` with `approved_by_user_id` and `received_amount_cents` null."

    Design: Corner/state_machines/change_order_receive_from_draft_returns_change_order_invalid_state
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1915", "Store 1915")
    safe = _manual_safe(store["id"])
    order = create_change_order(
        store["id"],
        target_week_start="2026-08-10",
        days_covered=7,
        baseline_daily_cash_demand_cents=80000,
    )
    assert order["status"] == "DRAFT", f"expected DRAFT, got {order['status']}"

    resp = api.receive_change_order(
        order["id"], {"received_amount_cents": 613000}, make_clerk_headers(CLERK_1)
    )
    validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_INVALID_STATE.value)

    after = read_change_order(order["id"])
    assert after["status"] == "DRAFT", (
        f"the rejected receipt must leave the order DRAFT, got {after['status']}"
    )
    assert after["received_amount_cents"] is None, (
        f"expected received_amount_cents null, got {after['received_amount_cents']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["balance_cents"] == 500000, (
        f"no cash was booked in: expected 500000, got {safe_after['balance_cents']}"
    )
    receipt_rows = _total_count(
        api.list_safe_transactions(
            make_clerk_headers(CLERK_1), params={"change_order_id": order["id"]}
        )
    )
    assert receipt_rows == 0, (
        f"no CHANGE_ORDER_RECEIPT row may be written, got {receipt_rows} rows"
    )


def test_change_order_rejected_is_terminal_and_blocks_approval(api):
    """PRD §3.9: "Rejection, which requires a `rejection_reason`, moves the order from `DRAFT` to `REJECTED` and likewise records the deciding manager; a rejected order is terminal and can never be received."

    PRD §3.9: "Deciding an order that is not `DRAFT` answers `ERR_CHANGE_ORDER_INVALID_STATE`."

    Design: Corner/state_machines/change_order_rejected_is_terminal_and_blocks_approval
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1916", "Store 1916")
    order = create_change_order(
        store["id"],
        target_week_start="2026-08-10",
        days_covered=7,
        baseline_daily_cash_demand_cents=80000,
    )

    rejected = reject_change_order(
        order["id"], "Vault cannot source $20 straps this week", MANAGER_1
    )
    assert rejected["status"] == "REJECTED", (
        f"expected REJECTED, got {rejected['status']}"
    )

    resp = api.approve_change_order(
        order["id"], {"approval_note": "Reconsidered"}, make_manager_headers(MANAGER_2)
    )
    validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_INVALID_STATE.value)

    after = read_change_order(order["id"])
    assert after["status"] == "REJECTED", (
        f"REJECTED is terminal: expected REJECTED, got {after['status']}"
    )
    assert after["approved_by_user_id"] == MANAGER_1, (
        f"the deciding manager on the rejection stays recorded: expected {MANAGER_1}, "
        f"got {after['approved_by_user_id']}"
    )


# --------------------------------------------------------- valid transitions


def test_manager_forced_close_leaves_pos_totals_null_and_blocks_reconcile(
    api, manager_headers, clerk_headers
):
    """PRD §3.4: "Either the session's own `Cashier` or a `StoreManager` may close a session, but `forced_close` is reserved to `StoreManager`: a forced close leaves all three point-of-sale figures null, ignores any figures supplied, and sets `forced_close` to true."

    PRD §3.4: "Because a forced-closed session has no cash-sales figure, it can never be reconciled — every later reconciliation attempt on a session whose `pos_cash_sales_cents` is null answers `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/manager_forced_close_leaves_pos_totals_null_and_blocks_reconcile
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1917", "Store 1917")
    safe = _manual_safe(store["id"])
    cashier = _cashier(store["id"], "E-100", "Cashier 100")
    journal = create_sales_journal(store["id"], "2026-08-03")
    session = assign_till(journal["id"], cashier["id"], safe["id"])
    set_clock("2026-08-03T12:00:00Z")

    closed = validate_success(
        api.close_till_session(session["id"], {"forced_close": True}, manager_headers)
    )
    assert closed["status"] == "PENDING_COUNT", (
        f"a forced close moves the session to PENDING_COUNT, got {closed['status']}"
    )

    after_close = read_session(session["id"])
    assert after_close["forced_close"] is True, (
        f"expected forced_close true, got {after_close['forced_close']}"
    )
    for field in (
        "pos_cash_sales_cents",
        "pos_card_sales_cents",
        "pos_paid_out_cents",
    ):
        assert after_close[field] is None, (
            f"a forced close leaves {field} null, got {after_close[field]}"
        )

    counted = validate_success(
        api.blind_count(
            session["id"],
            {"counted_lines": [{"denomination_cents": 2000, "quantity": 10}]},
            make_clerk_headers(CLERK_3),
        )
    )
    assert counted["counted_cash_cents"] == 20000, (
        f"expected counted_cash_cents 20000, got {counted['counted_cash_cents']}"
    )
    assert counted["status"] == "COUNTED", f"expected COUNTED, got {counted['status']}"

    resp = api.reconcile_till_session(session["id"], clerk_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    after = read_session(session["id"])
    assert after["status"] == "COUNTED", (
        f"the refused reconciliation leaves the session COUNTED, got {after['status']}"
    )
    assert after["expected_cash_cents"] is None, (
        f"expected expected_cash_cents null, got {after['expected_cash_cents']}"
    )
    assert after["variance_cents"] is None, (
        f"expected variance_cents null, got {after['variance_cents']}"
    )

    cashier_after = read_cashier(cashier["id"])
    assert cashier_after["coaching_state"] == "NONE", (
        f"no variance was written: expected NONE, got {cashier_after['coaching_state']}"
    )
    assert cashier_after["rolling_absolute_variance_cents"] == 0, (
        f"expected rolling_absolute_variance_cents 0, "
        f"got {cashier_after['rolling_absolute_variance_cents']}"
    )


# -------------------------------------------------------- guarded transitions


def test_cross_store_cashier_assignment_returns_cashier_not_found(
    api, manager_headers
):
    """PRD §2.12: "Store scoping is part of resolution rather than a separate rule: when a till session is assigned, an armored deposit prepared, or a smart-safe deposit inserted, a `Cashier` or `Safe` whose `store_id` differs from the sales journal's `store_id` is treated as non-existent for that request and reported as `ERR_CASHIER_NOT_FOUND` or `ERR_SAFE_NOT_FOUND`, so no caller can enumerate another store's records."

    Design: Corner/state_machines/cross_store_cashier_assignment_returns_cashier_not_found
    """
    set_clock("2026-08-03T08:00:00Z")
    store_a = _store("S-1918", "Store 1918", region_code="WEST")
    store_b = _store("S-1919", "Store 1919", region_code="EAST")
    safe_a = _manual_safe(store_a["id"])
    cashier_b = _cashier(store_b["id"], "E-300", "Cashier 300")
    journal_a = create_sales_journal(store_a["id"], "2026-08-03")

    resp = api.create_till_session(
        _till_payload(journal_a["id"], cashier_b["id"], safe_a["id"]), manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_CASHIER_NOT_FOUND.value)

    safe_after = read_safe(safe_a["id"])
    assert safe_after["balance_cents"] == 500000, (
        f"no starting bank was issued: expected 500000, "
        f"got {safe_after['balance_cents']}"
    )
    rows = _total_count(
        api.list_safe_transactions(
            make_clerk_headers(CLERK_1), params={"safe_id": safe_a["id"]}
        )
    )
    assert rows == 1, (
        f"only the OPENING_BALANCE row may exist, got {rows} rows"
    )

    journal_after = read_journal(journal_a["id"])
    assert journal_after["session_count"] == 0, (
        f"no session row was created: expected session_count 0, "
        f"got {journal_after['session_count']}"
    )


# ----------------------------------------------------- compound derivation


def test_sales_journal_derives_balanced_from_children(api, clerk_headers):
    """PRD §3.1: "The journal is **structurally complete** when its `status` is `TENDERS_POSTED` or `OUT_OF_BALANCE`, its `session_count` is at least 1, its `reconciled_session_count` equals its `session_count`, its `settlement_count` is at least 1, and at least one deposit attached to the journal has reached `SEALED`, `SCHEDULED`, `IN_TRANSIT` or `RECONCILED`."

    PRD §3.1: "The journal is **balanced** when `register_cash_tieout_cents` is zero, `settlement_variance_total_cents` is zero, and `open_case_count` is zero."

    PRD §3.1: "When the journal is structurally complete and balanced, its `status` becomes `BALANCED`, which is terminal."

    PRD §3.5: "If `dropped_verified_cents` is non-null at the moment reconciliation runs, `variance_basis` is recorded as `VERIFIED_DROPS` and the drop total used is `dropped_verified_cents`; otherwise `variance_basis` is recorded as `DECLARED_DROPS` and the drop total used is `dropped_declared_cents`."

    Design: Corner/state_machines/sales_journal_derives_balanced_from_children
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1920", "Store 1920")
    safe = _manual_safe(store["id"])
    cashier = _cashier(store["id"], "E-100", "Cashier 100")
    journal = create_sales_journal(store["id"], "2026-08-03")
    session = assign_till(journal["id"], cashier["id"], safe["id"])

    # One session reconciled with variance 0.
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=50000,
        pos_paid_out_cents=0,
    )
    blind_count(
        session["id"], [{"denomination_cents": 2000, "quantity": 60}], CLERK_3
    )
    reconcile_till(session["id"], CLERK_1)

    # One VISA_MC settlement funded exactly.
    post_card_settlement(
        journal["id"],
        gross_card_sales_cents=50000,
        txn_count=20,
        monthly_volume_cents=1000000,
        funded_amount_cents=48510,
        card_network="VISA_MC",
    )

    # One deposit of 100000 sealed.
    _unlock_manual_safe(safe["id"], "2026-08-03T17:05:00Z", "2026-08-03T17:10:00Z")
    deposit = prepare_deposit(
        safe["id"],
        journal["id"],
        [{"denomination_cents": 2000, "quantity": 50}],
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    seal_deposit(deposit["id"], "SEAL-1", CLERK_2)

    resp = api.post_tenders(
        journal["id"],
        {"journal_cash_sales_cents": 100000, "journal_card_sales_cents": 50000},
        clerk_headers,
    )
    derived = validate_success(resp)

    assert derived["status"] == "BALANCED", (
        f"the compound derivation runs inside the post-tenders request: "
        f"expected BALANCED, got {derived['status']}"
    )
    assert derived["session_count"] == 1, (
        f"expected session_count 1, got {derived['session_count']}"
    )
    assert derived["reconciled_session_count"] == 1, (
        f"expected reconciled_session_count 1, "
        f"got {derived['reconciled_session_count']}"
    )
    assert derived["settlement_count"] == 1, (
        f"expected settlement_count 1, got {derived['settlement_count']}"
    )
    assert derived["register_cash_tieout_cents"] == 0, (
        f"100000 pos cash minus 100000 journal cash: expected 0, "
        f"got {derived['register_cash_tieout_cents']}"
    )
    assert derived["settlement_variance_total_cents"] == 0, (
        f"expected settlement_variance_total_cents 0, "
        f"got {derived['settlement_variance_total_cents']}"
    )
    assert derived["open_case_count"] == 0, (
        f"expected open_case_count 0, got {derived['open_case_count']}"
    )
    assert derived["net_unexplained_cents"] == 0, (
        f"expected net_unexplained_cents 0, got {derived['net_unexplained_cents']}"
    )

    session_after = read_session(session["id"])
    assert session_after["expected_cash_cents"] == 120000, (
        f"expected expected_cash_cents 120000, "
        f"got {session_after['expected_cash_cents']}"
    )
    assert session_after["counted_cash_cents"] == 120000, (
        f"expected counted_cash_cents 120000, "
        f"got {session_after['counted_cash_cents']}"
    )
    assert session_after["variance_cents"] == 0, (
        f"expected variance_cents 0, got {session_after['variance_cents']}"
    )
    assert session_after["variance_basis"] == "DECLARED_DROPS", (
        f"expected variance_basis DECLARED_DROPS, "
        f"got {session_after['variance_basis']}"
    )

    cashier_after = read_cashier(cashier["id"])
    assert cashier_after["coaching_state"] == "NONE", (
        f"a zero variance trips no threshold: expected NONE, "
        f"got {cashier_after['coaching_state']}"
    )
    assert cashier_after["till_eligibility"] == "ELIGIBLE", (
        f"expected till_eligibility ELIGIBLE, "
        f"got {cashier_after['till_eligibility']}"
    )

    deposit_after = read_deposit(deposit["id"])
    assert deposit_after["status"] == "SEALED", (
        f"expected SEALED, got {deposit_after['status']}"
    )
    assert deposit_after["carrier_fee_cents"] == 1235, (
        f"expected carrier_fee_cents 1235, got {deposit_after['carrier_fee_cents']}"
    )
    assert deposit_after["expected_credit_cents"] == 98765, (
        f"expected expected_credit_cents 98765, "
        f"got {deposit_after['expected_credit_cents']}"
    )


# ---------------------------------------------------------------- branching


def test_deposit_bank_reconcile_short_credit_branches_to_discrepant(
    api, treasury_headers
):
    """PRD §3.7: "When `credit_variance_cents` computes to a non-zero value, the deposit moves from `IN_TRANSIT` to `DISCREPANT` instead: `credited_total_cents` and the non-zero `credit_variance_cents` are stored, a variance case is opened with `case_type` `DEPOSIT_CREDIT` naming this deposit and this sales journal with a null cashier reference and a `total_variance_cents` equal to the absolute value of `credit_variance_cents`, the journal's `open_case_count` and `net_unexplained_cents` are recomputed and its compound derivation re-evaluated, and the provisional credit stays outstanding."

    PRD §3.7: "`credit_variance_cents` is then `credited_total_cents` minus `expected_credit_cents`."

    Design: Corner/state_machines/deposit_bank_reconcile_short_credit_branches_to_discrepant
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1921", "Store 1921")
    safe = _manual_safe(store["id"])
    journal = create_sales_journal(store["id"], "2026-08-03")
    _unlock_manual_safe(safe["id"], "2026-08-03T08:00:00Z", "2026-08-03T08:05:00Z")

    deposit = prepare_deposit(
        safe["id"],
        journal["id"],
        [{"denomination_cents": 2000, "quantity": 100}],
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    seal_deposit(deposit["id"], "SEAL-1", CLERK_2)
    schedule_pickup(
        deposit["id"],
        "2026-08-03T10:00:00Z",
        "2026-08-03T10:30:00Z",
        carrier_reference="CAR-1921-A",
    )
    set_clock("2026-08-03T10:15:00Z")
    pickup_deposit(deposit["id"], "2026-08-03T10:15:00Z", "J.CARRIER")

    final_record = post_bank_credit_record(
        store["id"],
        198000,
        credit_type="FINAL",
        deposit_id=deposit["id"],
        value_date="2026-08-04",
        bank_reference="BR-1921-F",
    )

    resp = api.reconcile_bank(
        deposit["id"],
        {"bank_credit_record_ids": [final_record["id"]]},
        treasury_headers,
    )
    reconciled = validate_success(resp)

    assert reconciled["status"] == "DISCREPANT", (
        f"a non-zero credit variance takes the DISCREPANT branch, not RECONCILED: "
        f"got {reconciled['status']}"
    )
    assert reconciled["declared_total_cents"] == 200000, (
        f"expected declared_total_cents 200000, "
        f"got {reconciled['declared_total_cents']}"
    )
    assert reconciled["carrier_fee_cents"] == 1270, (
        f"expected carrier_fee_cents 1270, got {reconciled['carrier_fee_cents']}"
    )
    assert reconciled["expected_credit_cents"] == 198730, (
        f"expected expected_credit_cents 198730, "
        f"got {reconciled['expected_credit_cents']}"
    )
    assert reconciled["credited_total_cents"] == 198000, (
        f"expected credited_total_cents 198000, "
        f"got {reconciled['credited_total_cents']}"
    )
    assert reconciled["credit_variance_cents"] == -730, (
        f"expected credit_variance_cents -730, "
        f"got {reconciled['credit_variance_cents']}"
    )

    cases, meta = validate_paginated(
        api.list_variance_cases(treasury_headers, params={"deposit_id": deposit["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the DISCREPANT branch opens exactly one case, got {meta['total_count']}"
    )
    case = cases[0]
    assert case["case_type"] == "DEPOSIT_CREDIT", (
        f"expected case_type DEPOSIT_CREDIT, got {case['case_type']}"
    )
    assert case["status"] == "OPEN", f"expected status OPEN, got {case['status']}"
    assert case["total_variance_cents"] == 730, (
        f"expected total_variance_cents 730, got {case['total_variance_cents']}"
    )
    assert case["unexplained_cents"] == 730, (
        f"expected unexplained_cents 730, got {case['unexplained_cents']}"
    )
    assert case["suspected_theft"] is False, (
        f"730 is below the theft threshold: expected false, "
        f"got {case['suspected_theft']}"
    )
    assert case["cashier_id"] is None, (
        f"a DEPOSIT_CREDIT case names no cashier, got {case['cashier_id']}"
    )

    record_after = validate_success(
        api.get_bank_credit_record(final_record["id"], treasury_headers)
    )
    assert record_after["match_state"] == "MATCHED", (
        f"expected match_state MATCHED, got {record_after['match_state']}"
    )

    journal_after = read_journal(journal["id"])
    assert journal_after["open_case_count"] == 1, (
        f"expected open_case_count 1, got {journal_after['open_case_count']}"
    )
    assert journal_after["net_unexplained_cents"] == 730, (
        f"expected net_unexplained_cents 730, "
        f"got {journal_after['net_unexplained_cents']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["provisional_credit_balance_cents"] == 200000, (
        f"the DISCREPANT branch keeps the provisional credit outstanding: "
        f"expected 200000, got {safe_after['provisional_credit_balance_cents']}"
    )


# ------------------------------------------------------- parallel dimensions


def test_safe_posture_freeze_is_independent_of_open_state_dimension(
    api, manager_headers
):
    """PRD §2.9: "Posture and `open_state` never constrain each other: a safe can be `UNLOCKED` and `FROZEN` at the same time, and freezing does not relock anything."

    PRD §2.9: "Five operations are refused with `ERR_SAFE_FROZEN` (HTTP 409) on a frozen safe: assigning a till session (which issues a starting bank), recording a till drop, inserting a smart-safe deposit, preparing an armored deposit, and receiving a change order into the safe."

    Design: Corner/state_machines/safe_posture_freeze_is_independent_of_open_state_dimension
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1922", "Store 1922")
    safe = _manual_safe(store["id"])
    cashier_a = _cashier(store["id"], "E-100", "Cashier 100")
    cashier_b = _cashier(store["id"], "E-200", "Cashier 200")
    journal = create_sales_journal(store["id"], "2026-08-03")
    session = assign_till(journal["id"], cashier_a["id"], safe["id"])

    # E-100's session reconciles 60000 short: expected 120000 against 60000 counted.
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(
        session["id"], [{"denomination_cents": 2000, "quantity": 30}], CLERK_3
    )
    reconcile_till(session["id"], CLERK_1)

    # The safe is left UNLOCKED at 17:10Z.
    _unlock_manual_safe(safe["id"], "2026-08-03T17:05:00Z", "2026-08-03T17:10:00Z")

    cases = list_cases(
        headers=make_manager_headers(MANAGER_1),
        sales_journal_id=journal["id"],
        case_type="SESSION_VARIANCE",
    )
    assert len(cases) == 1, f"expected one SESSION_VARIANCE case, got {len(cases)}"
    case = cases[0]
    append_attribution(
        case["id"],
        "REGISTER",
        1000,
        case["version"],
        note="Keying error on a refund",
        headers=make_manager_headers(MANAGER_1),
    )

    escalated = validate_success(
        api.escalate_variance_case(
            case["id"],
            {
                "escalation_reason": (
                    "60000 short on a single till with no explanation"
                )
            },
            make_manager_headers(MANAGER_1),
        )
    )
    assert escalated["status"] == "ESCALATED", (
        f"expected ESCALATED, got {escalated['status']}"
    )
    assert escalated["suspected_theft"] is True, (
        f"escalation forces suspected_theft true, got {escalated['suspected_theft']}"
    )

    safe_frozen = read_safe(safe["id"])
    assert safe_frozen["posture"] == "FROZEN", (
        f"expected posture FROZEN, got {safe_frozen['posture']}"
    )
    assert safe_frozen["open_state"] == "UNLOCKED", (
        f"freezing does not relock anything: expected UNLOCKED, "
        f"got {safe_frozen['open_state']}"
    )
    assert safe_frozen["unlocked_at"] is not None, "unlocked_at must stay intact"
    assert parse_instant(safe_frozen["unlocked_at"]) == parse_instant(
        "2026-08-03T17:10:00Z"
    ), (
        f"expected unlocked_at 2026-08-03T17:10:00Z, got {safe_frozen['unlocked_at']}"
    )
    assert safe_frozen["open_requested_by_user_id"] == CLERK_1, (
        f"expected open_requested_by_user_id {CLERK_1}, "
        f"got {safe_frozen['open_requested_by_user_id']}"
    )

    assert read_cashier(cashier_a["id"])["till_eligibility"] == "BARRED", (
        "the escalated case bars its cashier"
    )

    resp = api.create_till_session(
        _till_payload(
            journal["id"],
            cashier_b["id"],
            safe["id"],
            register_number=2,
            shift_start_at="2026-08-03T18:00:00Z",
            shift_end_at="2026-08-03T22:00:00Z",
        ),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SAFE_FROZEN.value)

    cashier_b_after = read_cashier(cashier_b["id"])
    assert cashier_b_after["till_eligibility"] == "ELIGIBLE", (
        f"E-200 is not barred: expected ELIGIBLE, "
        f"got {cashier_b_after['till_eligibility']}"
    )

    journal_after = read_journal(journal["id"])
    assert journal_after["session_count"] == 1, (
        f"no session row was created: expected session_count 1, "
        f"got {journal_after['session_count']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["balance_cents"] == 480000, (
        f"no STARTING_BANK_ISSUE row for E-200: expected 480000, "
        f"got {safe_after['balance_cents']}"
    )


# ------------------------------------------------------------- compensation


def test_unsubstantiated_close_compensates_the_escalation_cascade(api):
    """PRD §3.8: "An `UNSUBSTANTIATED` finding moves the case to `CLOSED_UNSUBSTANTIATED`, writes **no** safe transaction at all — an unsubstantiated case moves no cash — and reinstates the cashier: provided no other case naming that cashier is still `ESCALATED`, `till_eligibility` is restored to `RESTRICTED` when the cashier's `rolling_absolute_variance_cents` is at or above the store's `rolling_variance_threshold_cents`, and to `ELIGIBLE` otherwise, with `coaching_state` untouched in either outcome."

    PRD §3.8: "Both closures share the same housekeeping. The sales journal's `open_case_count` and the cashier's `open_case_count` are decremented, the journal's `net_unexplained_cents` is recomputed, every safe of the store has its `posture` restored to `OPEN` once no escalated case remains for that store, the journal's compound derivation is re-evaluated — which is what lets an `OUT_OF_BALANCE` day finally reach `BALANCED` — and the case's `version` increments by 1."

    Design: Corner/state_machines/unsubstantiated_close_compensates_the_escalation_cascade
    """
    set_clock("2026-08-03T08:00:00Z")
    store = _store("S-1923", "Store 1923")
    safe = _manual_safe(store["id"])
    cashier = _cashier(store["id"], "E-100", "Cashier 100")
    journal = create_sales_journal(store["id"], "2026-08-03")
    session = assign_till(journal["id"], cashier["id"], safe["id"])

    # The session reconciles 60000 short: expected 120000 against 60000 counted.
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(
        session["id"], [{"denomination_cents": 2000, "quantity": 30}], CLERK_3
    )
    reconcile_till(session["id"], CLERK_1)

    cases = list_cases(
        headers=make_manager_headers(MANAGER_1),
        sales_journal_id=journal["id"],
        case_type="SESSION_VARIANCE",
    )
    assert len(cases) == 1, f"expected one SESSION_VARIANCE case, got {len(cases)}"
    case = cases[0]
    append_attribution(
        case["id"],
        "REGISTER",
        1000,
        case["version"],
        note="Keying error on a refund",
        headers=make_manager_headers(MANAGER_1),
    )
    validate_success(
        api.escalate_variance_case(
            case["id"],
            {"escalation_reason": "60000 short on a single till"},
            make_manager_headers(MANAGER_1),
        )
    )

    resp = api.close_variance_case(
        case["id"],
        {
            "disposition": "UNSUBSTANTIATED",
            "closing_note": (
                "Camera review shows a miscount at handover, no theft"
            ),
        },
        make_investigator_headers(LP_1),
    )
    closed = validate_success(resp)

    assert closed["status"] == "CLOSED_UNSUBSTANTIATED", (
        f"expected CLOSED_UNSUBSTANTIATED, got {closed['status']}"
    )
    assert closed["disposition"] == "UNSUBSTANTIATED", (
        f"expected disposition UNSUBSTANTIATED, got {closed['disposition']}"
    )
    assert closed["unexplained_cents"] == 59000, (
        f"the close does not move the unexplained remainder: expected 59000, "
        f"got {closed['unexplained_cents']}"
    )

    cashier_after = read_cashier(cashier["id"])
    assert cashier_after["rolling_absolute_variance_cents"] == 60000, (
        f"expected rolling_absolute_variance_cents 60000, "
        f"got {cashier_after['rolling_absolute_variance_cents']}"
    )
    assert cashier_after["till_eligibility"] == "RESTRICTED", (
        f"60000 is at or above the rolling threshold, so the cashier is restored to "
        f"RESTRICTED rather than ELIGIBLE: got {cashier_after['till_eligibility']}"
    )
    assert cashier_after["coaching_state"] == "COACHING_DUE", (
        f"coaching_state is untouched by the close: expected COACHING_DUE, "
        f"got {cashier_after['coaching_state']}"
    )
    assert cashier_after["open_case_count"] == 1, (
        f"the ROLLING_PATTERN case remains: expected open_case_count 1, "
        f"got {cashier_after['open_case_count']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["posture"] == "OPEN", (
        f"no ESCALATED case remains for the store: expected OPEN, "
        f"got {safe_after['posture']}"
    )
    assert safe_after["balance_cents"] == 480000, (
        f"an unsubstantiated case moves no cash: expected 480000, "
        f"got {safe_after['balance_cents']}"
    )
    adjustment_rows = _total_count(
        api.list_safe_transactions(
            make_clerk_headers(CLERK_1),
            params={"safe_id": safe["id"], "txn_type": "VARIANCE_ADJUSTMENT"},
        )
    )
    assert adjustment_rows == 0, (
        f"no VARIANCE_ADJUSTMENT row may be written, got {adjustment_rows} rows"
    )

    journal_after = read_journal(journal["id"])
    assert journal_after["open_case_count"] == 1, (
        f"the rolling case only: expected open_case_count 1, "
        f"got {journal_after['open_case_count']}"
    )
    assert journal_after["net_unexplained_cents"] == 60000, (
        f"the rolling case only: expected net_unexplained_cents 60000, "
        f"got {journal_after['net_unexplained_cents']}"
    )
