"""Multi-entity cascades: the till reconciliation chain and the escalation chain
that bars a cashier and freezes every safe at the store."""

from test_helpers import (
    CLERK_1,
    CLERK_2,
    CLERK_3,
    LP_1,
    MANAGER_1,
    ApiErrorId,
    approve_change_order,
    arm_open_request,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_change_order,
    create_safe,
    create_sales_journal,
    create_store,
    escalate_case,
    lines,
    list_cases,
    list_ledger,
    open_safe,
    parse_instant,
    read_cashier,
    read_change_order,
    read_journal,
    read_safe,
    read_session,
    reconcile_till,
    record_drop,
    set_clock,
    validate_error,
    validate_paginated,
)

#: Store S-1007 breaches its rolling threshold at exactly 10000 cents.
_STORE_1007 = {
    "store_code": "S-1007",
    "name": "Store 1007",
    "region_code": "WEST",
    "safe_time_delay_minutes": 5,
    "safe_open_window_minutes": 10,
    "dual_control_required": True,
    "single_event_variance_threshold_cents": 2500,
    "rolling_variance_threshold_cents": 10000,
    "rolling_window_days": 30,
    "theft_escalation_threshold_cents": 50000,
}

#: Store S-1008 treats a 50000-cent case as suspected theft.
_STORE_1008 = {
    "store_code": "S-1008",
    "name": "Store 1008",
    "region_code": "SOUTH",
    "safe_time_delay_minutes": 5,
    "safe_open_window_minutes": 10,
    "dual_control_required": True,
    "single_event_variance_threshold_cents": 2500,
    "theft_escalation_threshold_cents": 50000,
}


def _setup_rolling_window_at_3000():
    """Reconcile session A at -3000, then leave session B COUNTED at 17:00:00Z.

    Session A (register 1, 09:00-13:00) is short 3000, which breaches the store's
    single-event threshold and leaves the cashier's rolling absolute variance at
    3000. Session B (register 2, 13:00-17:00) is counted at 13000 against an
    expected 20000 and is left waiting for its reconciliation.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(**_STORE_1007)
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
    arm_open_request(safe["id"], CLERK_1, reason="Cash room open for the day")
    set_clock("2026-08-03T09:05:00Z")
    open_safe(safe["id"], CLERK_2)

    session_a = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T13:00:00Z",
        starting_bank_cents=20000,
    )
    record_drop(session_a["id"], cashier["id"], 100000, txn_type="CLOSING_DROP")
    set_clock("2026-08-03T13:00:00Z")
    close_till(
        session_a["id"],
        cashier_id=cashier["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=40000,
        pos_paid_out_cents=0,
    )
    blind_count(session_a["id"], lines((2000, 8), (1000, 1)), CLERK_3)
    reconciled_a = reconcile_till(session_a["id"], CLERK_2)
    assert (
        reconciled_a["variance_cents"] == -3000
    ), f"session A must be short 3000, got {reconciled_a['variance_cents']}"
    primed = read_cashier(cashier["id"])
    assert primed["rolling_absolute_variance_cents"] == 3000, (
        "the rolling window must start at 3000, got "
        f"{primed['rolling_absolute_variance_cents']}"
    )
    assert (
        primed["coaching_state"] == "COACHING_DUE"
    ), f"the 3000 breach must be coachable, got {primed['coaching_state']}"

    session_b = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=2,
        shift_start_at="2026-08-03T13:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    record_drop(session_b["id"], cashier["id"], 150000, txn_type="CLOSING_DROP")
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session_b["id"],
        cashier_id=cashier["id"],
        pos_cash_sales_cents=150000,
        pos_card_sales_cents=60000,
        pos_paid_out_cents=0,
    )
    blind_count(session_b["id"], lines((2000, 6), (1000, 1)), CLERK_3)
    return {
        "store": store,
        "safe": safe,
        "cashier": cashier,
        "journal": journal,
        "session_a": read_session(session_a["id"]),
        "session_b": read_session(session_b["id"]),
    }


def test_reconcile_writes_the_session_over_short_off_the_declared_drop_total():
    """PRD §3.5: "The over/short is `counted_cash_cents` — taken from the most recent blind count only, since a recount discards the previous lines entirely — minus `expected_cash_cents`, and is stored as `variance_cents`."

    PRD §3.5: "If `dropped_verified_cents` is non-null at the moment reconciliation runs, `variance_basis` is recorded as `VERIFIED_DROPS` and the drop total used is `dropped_verified_cents`; otherwise `variance_basis` is recorded as `DECLARED_DROPS` and the drop total used is `dropped_declared_cents`."

    Design: Difficulty/transitive_cascade/reconcile_cascade_session_to_cashier_to_case_to_journal
    """
    ctx = _setup_rolling_window_at_3000()

    reconciled = reconcile_till(ctx["session_b"]["id"], CLERK_2)
    assert (
        reconciled["status"] == "RECONCILED"
    ), f"expected RECONCILED, got {reconciled['status']}"
    assert (
        reconciled["expected_cash_cents"] == 20000
    ), f"expected 20000, got {reconciled['expected_cash_cents']}"
    assert (
        reconciled["variance_cents"] == -7000
    ), f"expected -7000, got {reconciled['variance_cents']}"
    assert (
        reconciled["variance_basis"] == "DECLARED_DROPS"
    ), f"no bag was ever re-counted, got {reconciled['variance_basis']}"

    safe = read_safe(ctx["safe"]["id"])
    assert (
        safe["balance_cents"] == 710000
    ), f"expected 710000, got {safe['balance_cents']}"


def test_reconcile_rolls_the_cashier_window_to_the_threshold_and_restricts_the_cashier():
    """PRD §3.5: "From that set, `reconciled_session_count` becomes the number of sessions, `rolling_absolute_variance_cents` becomes the sum of the absolute values of their variances, and `rolling_net_variance_cents` becomes the signed sum of the same variances."

    PRD §3.5: "**Link three** fires because link two recomputed `rolling_absolute_variance_cents`: if that recomputed figure is at or above the store's `rolling_variance_threshold_cents` — one hundred dollars by default — the cashier's `till_eligibility` is set to `RESTRICTED` and a second variance case is opened with `case_type` `ROLLING_PATTERN`, again naming this cashier and this sales journal."

    Design: Difficulty/transitive_cascade/reconcile_cascade_session_to_cashier_to_case_to_journal
    """
    ctx = _setup_rolling_window_at_3000()

    reconcile_till(ctx["session_b"]["id"], CLERK_2)

    cashier = read_cashier(ctx["cashier"]["id"])
    assert cashier["rolling_absolute_variance_cents"] == 10000, (
        "expected 10000, got "
        f"{cashier['rolling_absolute_variance_cents']}"
    )
    assert (
        cashier["rolling_net_variance_cents"] == -10000
    ), f"expected -10000, got {cashier['rolling_net_variance_cents']}"
    assert (
        cashier["reconciled_session_count"] == 2
    ), f"expected 2, got {cashier['reconciled_session_count']}"
    assert (
        cashier["till_eligibility"] == "RESTRICTED"
    ), f"the rolling breach restricts the cashier, got {cashier['till_eligibility']}"
    assert (
        cashier["coaching_state"] == "COACHING_DUE"
    ), f"expected COACHING_DUE, got {cashier['coaching_state']}"
    assert parse_instant(cashier["coaching_due_at"]) == parse_instant(
        "2026-08-06T17:00:00Z"
    ), (
        "the deadline is the breach instant plus 72 hours: expected "
        f"2026-08-06T17:00:00Z, got {cashier['coaching_due_at']}"
    )
    assert (
        cashier["open_case_count"] == 3
    ), f"expected 3, got {cashier['open_case_count']}"

    cases = list_cases(sales_journal_id=ctx["journal"]["id"])
    assert len(cases) == 3, f"expected exactly 3 cases, got {len(cases)}"
    session_cases = [c for c in cases if c["case_type"] == "SESSION_VARIANCE"]
    rolling_cases = [c for c in cases if c["case_type"] == "ROLLING_PATTERN"]
    assert (
        len(session_cases) == 2
    ), f"expected 2 SESSION_VARIANCE cases, got {len(session_cases)}"
    assert sorted(c["total_variance_cents"] for c in session_cases) == [3000, 7000], (
        "expected SESSION_VARIANCE magnitudes 3000 and 7000, got "
        f"{sorted(c['total_variance_cents'] for c in session_cases)}"
    )
    assert (
        len(rolling_cases) == 1
    ), f"expected 1 ROLLING_PATTERN case, got {len(rolling_cases)}"
    assert (
        rolling_cases[0]["total_variance_cents"] == 10000
    ), f"expected 10000, got {rolling_cases[0]['total_variance_cents']}"
    assert (
        rolling_cases[0]["status"] == "OPEN"
    ), f"expected OPEN, got {rolling_cases[0]['status']}"


def test_reconcile_cascade_recomputes_the_journals_case_counters():
    """PRD §3.5: "**Link four** fires because links two and three may have created variance cases: the journal's `open_case_count` and `net_unexplained_cents` are recomputed and the journal's compound derivation of §3.1 is re-evaluated."

    PRD §3.1: "`open_case_count` is the number of variance cases on the journal whose `status` is `OPEN`, `RESEARCHING` or `ESCALATED`."

    PRD §3.1: "The journal is **structurally complete** when its `status` is `TENDERS_POSTED` or `OUT_OF_BALANCE`, its `session_count` is at least 1, its `reconciled_session_count` equals its `session_count`, its `settlement_count` is at least 1, and at least one deposit attached to the journal has reached `SEALED`, `SCHEDULED`, `IN_TRANSIT` or `RECONCILED`."

    Design: Difficulty/transitive_cascade/reconcile_cascade_session_to_cashier_to_case_to_journal
    """
    ctx = _setup_rolling_window_at_3000()

    reconcile_till(ctx["session_b"]["id"], CLERK_2)

    journal = read_journal(ctx["journal"]["id"])
    assert (
        journal["session_count"] == 2
    ), f"expected 2, got {journal['session_count']}"
    assert (
        journal["reconciled_session_count"] == 2
    ), f"expected 2, got {journal['reconciled_session_count']}"
    assert (
        journal["open_case_count"] == 3
    ), f"expected 3, got {journal['open_case_count']}"

    cases = list_cases(sales_journal_id=ctx["journal"]["id"])
    unexplained = sum(case["unexplained_cents"] for case in cases)
    assert journal["net_unexplained_cents"] == unexplained, (
        f"net_unexplained_cents must sum the open cases: expected {unexplained}, "
        f"got {journal['net_unexplained_cents']}"
    )
    assert journal["status"] == "OPEN", (
        "the day is not structurally complete while its tenders are unposted: "
        f"expected OPEN, got {journal['status']}"
    )


def _setup_escalation_ready_case(with_active_session=False):
    """Open a suspected-theft SESSION_VARIANCE case of 60000 at store S-1008.

    Register 1 takes an 80000 starting bank, declares a 200000 closing drop,
    closes on POS cash 200000 and is blind-counted at 20000, so the reconcile is
    short 60000 — at or above the store's 50000 theft threshold. An APPROVED
    change order for the coming week is waiting to be received into the safe.
    When `with_active_session` is set, the same cashier also holds a second,
    still-ACTIVE till on register 2 with a zero starting bank.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(**_STORE_1008)
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
    order = create_change_order(
        store["id"],
        target_week_start="2026-08-10",
        days_covered=7,
        baseline_daily_cash_demand_cents=80000,
        growth_pct=0,
    )
    order = approve_change_order(
        order["id"], "Approved for week of Aug 10", MANAGER_1
    )
    assert order["status"] == "APPROVED", f"expected APPROVED, got {order['status']}"

    arm_open_request(safe["id"], CLERK_1, reason="Cash room open for the day")
    set_clock("2026-08-03T09:05:00Z")
    open_safe(safe["id"], CLERK_2)

    session = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=80000,
    )
    active_session = None
    if with_active_session:
        active_session = assign_till(
            journal["id"],
            cashier["id"],
            safe["id"],
            register_number=2,
            shift_start_at="2026-08-03T17:00:00Z",
            shift_end_at="2026-08-03T21:00:00Z",
            starting_bank_cents=0,
        )
    record_drop(session["id"], cashier["id"], 200000, txn_type="CLOSING_DROP")
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        cashier_id=cashier["id"],
        pos_cash_sales_cents=200000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(session["id"], lines((2000, 10)), CLERK_3)
    reconciled = reconcile_till(session["id"], CLERK_2)
    assert (
        reconciled["variance_cents"] == -60000
    ), f"the till must be short 60000, got {reconciled['variance_cents']}"

    cases = list_cases(
        sales_journal_id=journal["id"], case_type="SESSION_VARIANCE"
    )
    assert len(cases) == 1, f"expected one SESSION_VARIANCE case, got {len(cases)}"
    case = cases[0]
    assert (
        case["total_variance_cents"] == 60000
    ), f"expected 60000, got {case['total_variance_cents']}"
    assert (
        case["status"] == "OPEN"
    ), f"the case must still be OPEN, got {case['status']}"
    return {
        "store": store,
        "safe": safe,
        "cashier": cashier,
        "journal": journal,
        "order": order,
        "session": read_session(session["id"]),
        "active_session": active_session,
        "case": case,
    }


def test_escalation_marks_the_case_escalated_and_forces_suspected_theft():
    """PRD §3.8: "The first link sets the case's `status` to `ESCALATED`, records `escalated_by_user_id` from the acting `X-User-ID`, and forces `suspected_theft` to true even if the magnitude alone would not have warranted it."

    Design: Difficulty/transitive_cascade/escalation_cascade_case_to_cashier_to_safe_freeze
    """
    ctx = _setup_escalation_ready_case()

    escalated = escalate_case(
        ctx["case"]["id"],
        "Register 1 short 60000 with no explanation at count",
        LP_1,
    )
    assert (
        escalated["status"] == "ESCALATED"
    ), f"expected ESCALATED, got {escalated['status']}"
    assert (
        escalated["suspected_theft"] is True
    ), f"expected suspected_theft true, got {escalated['suspected_theft']}"
    assert (
        escalated["escalated_by_user_id"] == LP_1
    ), f"expected {LP_1}, got {escalated['escalated_by_user_id']}"
    assert (
        escalated["total_variance_cents"] == 60000
    ), f"expected 60000, got {escalated['total_variance_cents']}"
    assert escalated["version"] == ctx["case"]["version"] + 1, (
        f"the case's version increments: expected {ctx['case']['version'] + 1}, "
        f"got {escalated['version']}"
    )


def test_escalation_bars_the_cashier_and_force_closes_the_still_active_till():
    """PRD §3.8: "The second link fires *because* the case became escalated: when the case names a cashier, that cashier's `till_eligibility` becomes `BARRED`, with `coaching_state` left untouched."

    PRD §3.8: "The third link fires *because* that cashier became barred: every till session of that cashier whose `status` is still `ACTIVE` is force-closed, moving from `ACTIVE` to `PENDING_COUNT` with `forced_close` set to true, leaving all three point-of-sale figures null, and writing **no** safe ledger row — no cash moves during a forced close, and those sessions can consequently never be reconciled."

    Design: Difficulty/transitive_cascade/escalation_cascade_case_to_cashier_to_safe_freeze
    """
    ctx = _setup_escalation_ready_case(with_active_session=True)
    before = read_cashier(ctx["cashier"]["id"])
    still_active = read_session(ctx["active_session"]["id"])
    assert (
        still_active["status"] == "ACTIVE"
    ), f"the second till must still be ACTIVE, got {still_active['status']}"
    rows_before = list_ledger(
        ctx["safe"]["id"], till_session_id=still_active["id"]
    )

    escalate_case(
        ctx["case"]["id"],
        "Register 1 short 60000 with no explanation at count",
        LP_1,
    )

    cashier = read_cashier(ctx["cashier"]["id"])
    assert (
        cashier["till_eligibility"] == "BARRED"
    ), f"expected BARRED, got {cashier['till_eligibility']}"
    assert cashier["coaching_state"] == before["coaching_state"], (
        f"coaching_state is left untouched: expected {before['coaching_state']}, "
        f"got {cashier['coaching_state']}"
    )

    forced = read_session(still_active["id"])
    assert (
        forced["status"] == "PENDING_COUNT"
    ), f"expected PENDING_COUNT, got {forced['status']}"
    assert (
        forced["forced_close"] is True
    ), f"expected forced_close true, got {forced['forced_close']}"
    assert (
        forced["pos_cash_sales_cents"] is None
    ), f"pos_cash_sales_cents stays null, got {forced['pos_cash_sales_cents']}"
    assert (
        forced["pos_card_sales_cents"] is None
    ), f"pos_card_sales_cents stays null, got {forced['pos_card_sales_cents']}"
    assert (
        forced["pos_paid_out_cents"] is None
    ), f"pos_paid_out_cents stays null, got {forced['pos_paid_out_cents']}"

    rows_after = list_ledger(ctx["safe"]["id"], till_session_id=still_active["id"])
    assert len(rows_after) == len(rows_before), (
        "a forced close writes no safe ledger row: expected "
        f"{len(rows_before)} rows, got {len(rows_after)}"
    )


def test_escalation_freezes_every_store_safe_and_blocks_the_change_order_receipt(
    api, clerk_headers
):
    """PRD §3.8: "Separately from that chain, and as a direct fan-out of the first link, every safe belonging to the case's store has its `posture` set to `FROZEN`, which blocks all cash movement at that store as described in §2.9."

    PRD §2.9: "Five operations are refused with `ERR_SAFE_FROZEN` (HTTP 409) on a frozen safe: assigning a till session (which issues a starting bank), recording a till drop, inserting a smart-safe deposit, preparing an armored deposit, and receiving a change order into the safe."

    Design: Difficulty/transitive_cascade/escalation_cascade_case_to_cashier_to_safe_freeze
    """
    ctx = _setup_escalation_ready_case()

    escalate_case(
        ctx["case"]["id"],
        "Register 1 short 60000 with no explanation at count",
        LP_1,
    )

    safe = read_safe(ctx["safe"]["id"])
    assert (
        safe["posture"] == "FROZEN"
    ), f"every safe of the store is frozen, got {safe['posture']}"

    refused = api.receive_change_order(
        ctx["order"]["id"], {"received_amount_cents": 613000}, clerk_headers
    )
    validate_error(refused, ApiErrorId.ERR_SAFE_FROZEN.value)

    order = read_change_order(ctx["order"]["id"])
    assert (
        order["status"] == "APPROVED"
    ), f"the blocked receipt leaves the order APPROVED, got {order['status']}"
    assert (
        order["received_amount_cents"] is None
    ), f"received_amount_cents stays null, got {order['received_amount_cents']}"

    after = read_safe(ctx["safe"]["id"])
    assert (
        after["balance_cents"] == 620000
    ), f"the blocked receipt moves no cash: expected 620000, got {after['balance_cents']}"

    rows, meta = validate_paginated(
        api.list_safe_transactions(
            clerk_headers, params={"change_order_id": ctx["order"]["id"]}
        )
    )
    assert len(rows) == 0, f"no CHANGE_ORDER_RECEIPT row is written, got {len(rows)}"
    assert (
        meta["total_count"] == 0
    ), f"no CHANGE_ORDER_RECEIPT row is written, got {meta['total_count']}"
