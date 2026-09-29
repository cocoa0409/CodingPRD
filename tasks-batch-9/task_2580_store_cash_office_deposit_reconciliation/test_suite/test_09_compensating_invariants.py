"""Compensating rows and negative attributions: two conserved cash-office quantities."""

from test_helpers import (
    CLERK_1,
    CLERK_2,
    api_client,
    append_attribution,
    create_safe,
    create_sales_journal,
    create_store,
    lines,
    list_ledger,
    make_clerk_headers,
    prepare_and_seal_deposit,
    read_case,
    read_deposit,
    read_safe,
    set_clock,
    setup_session_variance_case,
    unlock_safe,
    validate_paginated,
    void_deposit,
)

#: A deposit still in flight is one the store is accountable for outside the safe.
IN_FLIGHT_STATUSES = ("PREPARING", "SEALED", "SCHEDULED", "IN_TRANSIT")


def _accountability_total_cents(safe_id):
    """Store cash accountability: the safe balance plus every in-flight bag.

    Defined as Safe.balance_cents plus the sum of declared_total_cents over the
    safe's deposits that are still PREPARING, SEALED, SCHEDULED or IN_TRANSIT.
    """
    safe = read_safe(safe_id)
    deposits, _meta = validate_paginated(
        api_client.list_deposits(
            make_clerk_headers(CLERK_1), params={"safe_id": safe_id, "limit": 100}
        )
    )
    in_flight = sum(
        deposit["declared_total_cents"]
        for deposit in deposits
        if deposit["status"] in IN_FLIGHT_STATUSES
    )
    return safe["balance_cents"] + in_flight


def _setup_sealed_armored_deposit():
    """A 200500 armored bag SEALED out of a safe commissioned with 500000."""
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(
        store_code="S-1017",
        name="Store 1017",
        region_code="NORTH",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
    )
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    journal = create_sales_journal(store["id"], "2026-08-03")
    unlock_safe(
        safe["id"],
        "2026-08-03T09:00:00Z",
        delay_minutes=5,
        requester_user_id=CLERK_1,
        opener_user_id=CLERK_2,
    )
    deposit = prepare_and_seal_deposit(
        safe["id"],
        journal["id"],
        lines((2000, 100), (100, 5)),
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
        sealer_user_id=CLERK_2,
        seal_number="SEAL-A-017",
    )
    return {"store": store, "safe": safe, "journal": journal, "deposit": deposit}


def test_void_appends_a_deposit_return_row_and_restores_the_balance():
    """PRD §3.6: "Voiding writes a compensating safe ledger row of kind `DEPOSIT_RETURN` linked to the deposit with `declared_amount_cents` equal to `declared_total_cents`, so that the recomputed `balance_cents` returns to its pre-preparation value — the removal row is never deleted, because the ledger is append-only."

    PRD §2.6: "No status filter is applied, because the ledger is append-only and has no void rows: a voided deposit is represented by a compensating return row, never by deleting the removal row that preceded it."

    Design: Difficulty/compensating_invariant/deposit_void_restores_store_cash_accountability_total
    """
    ctx = _setup_sealed_armored_deposit()
    assert ctx["deposit"]["declared_total_cents"] == 200500, (
        f"expected 200500, got {ctx['deposit']['declared_total_cents']}"
    )
    sealed_safe = read_safe(ctx["safe"]["id"])
    assert sealed_safe["balance_cents"] == 299500, (
        f"expected 299500, got {sealed_safe['balance_cents']}"
    )

    voided = void_deposit(
        ctx["deposit"]["id"],
        reason="Carrier route cancelled, cash returned to safe",
    )
    assert voided["status"] == "VOIDED", f"expected VOIDED, got {voided['status']}"

    safe = read_safe(ctx["safe"]["id"])
    assert safe["balance_cents"] == 500000, (
        f"expected 500000, got {safe['balance_cents']}"
    )

    rows = list_ledger(ctx["safe"]["id"])
    assert len(rows) == 3, f"expected exactly 3 ledger rows, got {len(rows)}"
    assert [row["txn_type"] for row in rows] == [
        "OPENING_BALANCE",
        "DEPOSIT_REMOVAL",
        "DEPOSIT_RETURN",
    ], f"unexpected ledger kinds: {[row['txn_type'] for row in rows]}"

    removal = rows[1]
    assert removal["effective_amount_cents"] == -200500, (
        f"expected -200500, got {removal['effective_amount_cents']}"
    )
    ret = rows[2]
    assert ret["effective_amount_cents"] == 200500, (
        f"expected 200500, got {ret['effective_amount_cents']}"
    )
    assert ret["declared_amount_cents"] == 200500, (
        f"expected 200500, got {ret['declared_amount_cents']}"
    )
    assert ret["deposit_id"] == ctx["deposit"]["id"], (
        f"expected {ctx['deposit']['id']}, got {ret['deposit_id']}"
    )


def test_void_conserves_accountability_and_leaves_the_safe_locked():
    """PRD §3.6: "Sealing records `seal_number` and `sealed_by_user_id`, moves the deposit from `PREPARING` to `SEALED`, and ends the cash-office opening: the parent safe's `open_state` returns from `UNLOCKED` to `LOCKED` with `open_requested_at`, `open_requested_by_user_id` and `unlocked_at` all cleared, and the safe's `version` increments by 1 alongside the deposit's."

    PRD §3.6: "Voiding writes a compensating safe ledger row of kind `DEPOSIT_RETURN` linked to the deposit with `declared_amount_cents` equal to `declared_total_cents`, so that the recomputed `balance_cents` returns to its pre-preparation value — the removal row is never deleted, because the ledger is append-only."

    Design: Difficulty/compensating_invariant/deposit_void_restores_store_cash_accountability_total
    """
    ctx = _setup_sealed_armored_deposit()
    sealed_total = _accountability_total_cents(ctx["safe"]["id"])
    assert sealed_total == 500000, (
        f"accountability during the sealed state must be 500000, got {sealed_total}"
    )
    sealed_safe = read_safe(ctx["safe"]["id"])
    assert sealed_safe["open_state"] == "LOCKED", (
        f"the seal relocked the safe: expected LOCKED, got {sealed_safe['open_state']}"
    )

    void_deposit(
        ctx["deposit"]["id"],
        reason="Carrier route cancelled, cash returned to safe",
    )

    voided_total = _accountability_total_cents(ctx["safe"]["id"])
    assert voided_total == 500000, (
        f"accountability after the void must be 500000, got {voided_total}"
    )
    deposit = read_deposit(ctx["deposit"]["id"])
    assert deposit["status"] == "VOIDED", (
        f"expected VOIDED, got {deposit['status']}"
    )
    assert deposit["declared_total_cents"] == 200500, (
        "declared_total_cents is left untouched for audit: expected 200500, got "
        f"{deposit['declared_total_cents']}"
    )

    safe = read_safe(ctx["safe"]["id"])
    assert safe["balance_cents"] == 500000, (
        f"expected 500000, got {safe['balance_cents']}"
    )
    assert safe["open_state"] == "LOCKED", (
        f"the void did not reopen the safe: expected LOCKED, got {safe['open_state']}"
    )
    assert safe["provisional_credit_balance_cents"] == 0, (
        f"expected 0, got {safe['provisional_credit_balance_cents']}"
    )


def _setup_session_variance_case_of_3000():
    """One RECONCILED session short by 3000, opening a SESSION_VARIANCE case.

    The count of 17000 against an expected 20000 breaches the store's
    single_event_variance_threshold_cents of 2500, so the case's
    total_variance_cents is the absolute value 3000 and unexplained_cents 3000.
    """
    ctx = setup_session_variance_case(
        -3000,
        clock="2026-08-03T09:00:00Z",
        store_overrides={
            "safe_time_delay_minutes": 5,
            "safe_open_window_minutes": 10,
            "dual_control_required": True,
            "single_event_variance_threshold_cents": 2500,
            "theft_escalation_threshold_cents": 50000,
        },
        starting_bank_cents=20000,
        drop_amount_cents=100000,
        pos_cash_sales_cents=100000,
        close_at="2026-08-03T13:00:00Z",
        opening_balance_cents=500000,
    )
    session_cases = [
        case for case in ctx["cases"] if case["case_type"] == "SESSION_VARIANCE"
    ]
    assert len(session_cases) == 1, (
        f"expected exactly one SESSION_VARIANCE case, got {len(session_cases)}"
    )
    ctx["case"] = session_cases[0]
    return ctx


def _walk_four_attributions(case_id, clerk_headers, manager_headers):
    """Append REGISTER 1000, SAFE 1200, the SAFE -400 correction and BANK 1200.

    Returns the case as read back after each of the four entries.
    """
    snapshots = []
    case = read_case(case_id)
    append_attribution(
        case_id,
        "REGISTER",
        1000,
        case["version"],
        note="Two twenties handed back in error",
        headers=clerk_headers,
    )
    snapshots.append(read_case(case_id))

    append_attribution(
        case_id,
        "SAFE",
        1200,
        snapshots[-1]["version"],
        note="Strap miscount in safe",
        headers=clerk_headers,
    )
    snapshots.append(read_case(case_id))

    append_attribution(
        case_id,
        "SAFE",
        -400,
        snapshots[-1]["version"],
        note="Correction: safe slice was over-attributed by 400",
        headers=clerk_headers,
    )
    snapshots.append(read_case(case_id))

    append_attribution(
        case_id,
        "BANK",
        1200,
        snapshots[-1]["version"],
        note="Bank short-credited the deposit",
        headers=manager_headers,
    )
    snapshots.append(read_case(case_id))
    return snapshots


def test_negative_attribution_walks_the_safe_bucket_back(
    clerk_3_headers, manager_headers
):
    """PRD §3.8: "An `amount_cents` may itself be negative, which is how a researcher reverses an earlier over-attribution."

    PRD §3.8: "The very first attribution also moves the case from `OPEN` to `RESEARCHING`; every subsequent one, including a correcting entry, leaves it in `RESEARCHING`."

    PRD §3.8: "When an attribution brings `unexplained_cents` to exactly zero and the case's `suspected_theft` is false, the case moves from `RESEARCHING` to `EXPLAINED`, which is terminal; the sales journal's `open_case_count` and the cashier's `open_case_count` are each decremented, the journal's `net_unexplained_cents` is recomputed, and the journal's compound derivation is re-evaluated."

    Design: Difficulty/compensating_invariant/variance_case_negative_attribution_preserves_decomposition_invariant
    """
    ctx = _setup_session_variance_case_of_3000()
    case_id = ctx["case"]["id"]
    assert ctx["case"]["status"] == "OPEN", (
        f"expected OPEN, got {ctx['case']['status']}"
    )
    assert ctx["case"]["unexplained_cents"] == 3000, (
        f"expected 3000, got {ctx['case']['unexplained_cents']}"
    )

    first, second, third, fourth = _walk_four_attributions(
        case_id, clerk_3_headers, manager_headers
    )

    assert first["status"] == "RESEARCHING", (
        f"expected RESEARCHING, got {first['status']}"
    )
    assert first["attributed_register_cents"] == 1000, (
        f"expected 1000, got {first['attributed_register_cents']}"
    )
    assert first["attributed_safe_cents"] == 0, (
        f"expected 0, got {first['attributed_safe_cents']}"
    )
    assert first["attributed_bank_cents"] == 0, (
        f"expected 0, got {first['attributed_bank_cents']}"
    )
    assert first["unexplained_cents"] == 2000, (
        f"expected 2000, got {first['unexplained_cents']}"
    )

    assert second["attributed_safe_cents"] == 1200, (
        f"expected 1200, got {second['attributed_safe_cents']}"
    )
    assert second["unexplained_cents"] == 800, (
        f"expected 800, got {second['unexplained_cents']}"
    )

    assert third["attributed_safe_cents"] == 800, (
        f"the -400 correction walks the safe bucket back: expected 800, got "
        f"{third['attributed_safe_cents']}"
    )
    assert third["unexplained_cents"] == 1200, (
        f"expected 1200, got {third['unexplained_cents']}"
    )
    assert third["status"] == "RESEARCHING", (
        f"expected RESEARCHING, got {third['status']}"
    )

    assert fourth["attributed_register_cents"] == 1000, (
        f"expected 1000, got {fourth['attributed_register_cents']}"
    )
    assert fourth["attributed_safe_cents"] == 800, (
        f"expected 800, got {fourth['attributed_safe_cents']}"
    )
    assert fourth["attributed_bank_cents"] == 1200, (
        f"expected 1200, got {fourth['attributed_bank_cents']}"
    )
    assert fourth["unexplained_cents"] == 0, (
        f"expected 0, got {fourth['unexplained_cents']}"
    )
    assert fourth["status"] == "EXPLAINED", (
        f"expected EXPLAINED, got {fourth['status']}"
    )


def test_decomposition_identity_holds_across_every_attribution(
    clerk_3_headers, manager_headers
):
    """PRD §3.8: "The conservation identity therefore holds after every single entry: `total_variance_cents` always equals `attributed_register_cents` plus `attributed_safe_cents` plus `attributed_bank_cents` plus `unexplained_cents`."

    PRD §3.8: "The figure is an unsigned magnitude frozen at creation, so later attributions and later sessions cannot move the denominator of the research."

    PRD §3.8: "In the same instant, `suspected_theft` is set to true when `total_variance_cents` is at or above the store's `theft_escalation_threshold_cents` and to false otherwise — again evaluated once, at creation."

    Design: Difficulty/compensating_invariant/variance_case_negative_attribution_preserves_decomposition_invariant
    """
    ctx = _setup_session_variance_case_of_3000()
    case_id = ctx["case"]["id"]
    snapshots = _walk_four_attributions(case_id, clerk_3_headers, manager_headers)

    for index, case in enumerate(snapshots, start=1):
        decomposed = (
            case["attributed_register_cents"]
            + case["attributed_safe_cents"]
            + case["attributed_bank_cents"]
            + case["unexplained_cents"]
        )
        assert case["total_variance_cents"] == 3000, (
            f"total_variance_cents is frozen at 3000, got "
            f"{case['total_variance_cents']} after attribution {index}"
        )
        assert decomposed == case["total_variance_cents"], (
            f"decomposition broke after attribution {index}: {decomposed} != "
            f"{case['total_variance_cents']}"
        )
        assert case["suspected_theft"] is False, (
            f"expected suspected_theft False, got {case['suspected_theft']} after "
            f"attribution {index}"
        )

    final = snapshots[-1]
    amounts = [entry["amount_cents"] for entry in final["attributions"]]
    assert amounts == [1000, 1200, -400, 1200], (
        f"expected [1000, 1200, -400, 1200] in call order, got {amounts}"
    )
    buckets = [entry["bucket"] for entry in final["attributions"]]
    assert buckets == ["REGISTER", "SAFE", "SAFE", "BANK"], (
        f"expected [REGISTER, SAFE, SAFE, BANK] in call order, got {buckets}"
    )
