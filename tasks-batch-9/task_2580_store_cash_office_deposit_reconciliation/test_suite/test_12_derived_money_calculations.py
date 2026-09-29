"""Derived money arithmetic: safe balances, till over/short, bank and card tie-outs."""

from test_helpers import (
    CLERK_1,
    CLERK_2,
    CLERK_3,
    append_attribution,
    arm_open_request,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    list_cases,
    make_cashier_headers,
    make_clerk_headers,
    open_safe,
    parse_instant,
    pickup_deposit,
    post_bank_credit_record,
    prepare_deposit,
    read_cashier,
    read_journal,
    read_safe,
    read_session,
    reconcile_bank,
    schedule_pickup,
    seal_deposit,
    set_clock,
    validate_paginated,
    validate_success,
)


def test_safe_balance_aggregates_signed_ledger_rows(api, clerk_headers):
    """PRD §2.6: "It is the sum of `effective_amount_cents` over every safe ledger row whose `safe_id` names that safe, recomputed in full every time a row is written and every time a drop is verified."

    PRD §2.6: "Nine transaction kinds exist, and their signs are fixed: `OPENING_BALANCE`, `MID_SHIFT_DROP`, `CLOSING_DROP`, `SMART_DEPOSIT`, `DEPOSIT_RETURN` and `CHANGE_ORDER_RECEIPT` add to the safe; `STARTING_BANK_ISSUE`, `DEPOSIT_REMOVAL` and `VARIANCE_ADJUSTMENT` subtract from it."

    PRD §2.6: "The row's basis is `verified_amount_cents` when that field is populated and `declared_amount_cents` otherwise."

    Design: Corner/calculations/safe_balance_aggregates_signed_ledger_rows
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1930", name="Store 1930", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    set_clock("2026-08-03T09:00:00Z")
    session = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    arm_open_request(safe["id"], CLERK_1, reason="Mid-shift drop")
    set_clock("2026-08-03T09:10:00Z")
    open_safe(safe["id"], CLERK_2)

    resp = api.create_drop(
        session["id"],
        {
            "txn_type": "MID_SHIFT_DROP",
            "declared_amount_cents": 25000,
            "memo": "Register 1 exceeded its till limit",
        },
        make_cashier_headers(cashier["id"]),
    )
    row = validate_success(resp, 201)

    assert row["txn_type"] == "MID_SHIFT_DROP", (
        f"expected MID_SHIFT_DROP, got {row['txn_type']}"
    )
    assert row["declared_amount_cents"] == 25000, (
        f"expected declared_amount_cents 25000, got {row['declared_amount_cents']}"
    )
    assert row["verified_amount_cents"] is None, (
        f"expected verified_amount_cents null, got {row['verified_amount_cents']}"
    )
    assert row["effective_amount_cents"] == 25000, (
        f"expected effective_amount_cents 25000, got {row['effective_amount_cents']}"
    )
    assert row["actor_user_id"] == cashier["id"], (
        f"expected actor_user_id {cashier['id']}, got {row['actor_user_id']}"
    )
    assert parse_instant(row["occurred_at"]) == parse_instant(
        "2026-08-03T09:10:00Z"
    ), (
        f"expected occurred_at 2026-08-03T09:10:00Z, got {row['occurred_at']}"
    )
    assert row["till_session_id"] == session["id"], (
        f"expected till_session_id {session['id']}, got {row['till_session_id']}"
    )

    refreshed_safe = read_safe(safe["id"])
    assert refreshed_safe["balance_cents"] == 505000, (
        f"expected balance_cents 505000 (500000 - 20000 + 25000), "
        f"got {refreshed_safe['balance_cents']}"
    )

    ledger, meta = validate_paginated(
        api.list_safe_transactions(clerk_headers, params={"safe_id": safe["id"], "limit": 100})
    )
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    effective = [entry["effective_amount_cents"] for entry in ledger]
    assert effective == [500000, -20000, 25000], (
        f"expected effective_amount_cents [500000, -20000, 25000], got {effective}"
    )

    refreshed_session = read_session(session["id"])
    assert refreshed_session["dropped_declared_cents"] == 25000, (
        f"expected dropped_declared_cents 25000, "
        f"got {refreshed_session['dropped_declared_cents']}"
    )
    assert refreshed_session["dropped_verified_cents"] is None, (
        f"expected dropped_verified_cents null, "
        f"got {refreshed_session['dropped_verified_cents']}"
    )


def test_till_over_short_selects_declared_drops_variant_when_unverified(api):
    """PRD §3.5: "If `dropped_verified_cents` is non-null at the moment reconciliation runs, `variance_basis` is recorded as `VERIFIED_DROPS` and the drop total used is `dropped_verified_cents`; otherwise `variance_basis` is recorded as `DECLARED_DROPS` and the drop total used is `dropped_declared_cents`."

    PRD §3.5: "The expected till contents are then the session's `starting_bank_cents`, plus its `pos_cash_sales_cents`, minus its `pos_paid_out_cents`, minus the chosen drop total; the result is stored as `expected_cash_cents`."

    Design: Corner/calculations/till_over_short_selects_declared_drops_variant_when_unverified
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1931", name="Store 1931", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    set_clock("2026-08-03T09:00:00Z")
    session = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )

    set_clock("2026-08-03T16:50:00Z")
    arm_open_request(safe["id"], CLERK_1, reason="Closing drop")
    set_clock("2026-08-03T16:55:00Z")
    open_safe(safe["id"], CLERK_2)
    validate_success(
        api.create_drop(
            session["id"],
            {
                "txn_type": "CLOSING_DROP",
                "declared_amount_cents": 30000,
                "memo": "Closing drop register 1",
            },
            make_cashier_headers(cashier["id"]),
        ),
        201,
    )

    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=2500,
    )
    blind_count(
        session["id"],
        [
            {"denomination_cents": 2000, "quantity": 43},
            {"denomination_cents": 500, "quantity": 3},
        ],
        CLERK_3,
    )

    reconciled = validate_success(
        api.reconcile_till_session(session["id"], make_clerk_headers(CLERK_1))
    )

    assert reconciled["status"] == "RECONCILED", (
        f"expected status RECONCILED, got {reconciled['status']}"
    )
    assert reconciled["variance_basis"] == "DECLARED_DROPS", (
        f"expected variance_basis DECLARED_DROPS, got {reconciled['variance_basis']}"
    )
    assert reconciled["counted_cash_cents"] == 87500, (
        f"expected counted_cash_cents 87500, got {reconciled['counted_cash_cents']}"
    )
    assert reconciled["expected_cash_cents"] == 87500, (
        f"expected expected_cash_cents 87500 (20000 + 100000 - 2500 - 30000), "
        f"got {reconciled['expected_cash_cents']}"
    )
    assert reconciled["variance_cents"] == 0, (
        f"expected variance_cents 0, got {reconciled['variance_cents']}"
    )
    assert reconciled["dropped_declared_cents"] == 30000, (
        f"expected dropped_declared_cents 30000, "
        f"got {reconciled['dropped_declared_cents']}"
    )
    assert reconciled["dropped_verified_cents"] is None, (
        "nothing re-counted the bag, so dropped_verified_cents must stay null, "
        f"got {reconciled['dropped_verified_cents']}"
    )

    refreshed_cashier = read_cashier(cashier["id"])
    assert refreshed_cashier["rolling_absolute_variance_cents"] == 0, (
        f"expected rolling_absolute_variance_cents 0, "
        f"got {refreshed_cashier['rolling_absolute_variance_cents']}"
    )
    assert refreshed_cashier["reconciled_session_count"] == 1, (
        f"expected reconciled_session_count 1, "
        f"got {refreshed_cashier['reconciled_session_count']}"
    )
    assert refreshed_cashier["coaching_state"] == "NONE", (
        f"expected coaching_state NONE, got {refreshed_cashier['coaching_state']}"
    )
    assert refreshed_cashier["till_eligibility"] == "ELIGIBLE", (
        f"expected till_eligibility ELIGIBLE, got {refreshed_cashier['till_eligibility']}"
    )

    refreshed_journal = read_journal(journal["id"])
    assert refreshed_journal["reconciled_session_count"] == 1, (
        f"expected reconciled_session_count 1, "
        f"got {refreshed_journal['reconciled_session_count']}"
    )
    assert refreshed_journal["open_case_count"] == 0, (
        f"expected open_case_count 0, got {refreshed_journal['open_case_count']}"
    )

    refreshed_safe = read_safe(safe["id"])
    assert refreshed_safe["balance_cents"] == 510000, (
        f"expected balance_cents 510000 (500000 - 20000 + 30000), "
        f"got {refreshed_safe['balance_cents']}"
    )


def test_rolling_variance_counts_only_reconciled_sessions(api):
    """PRD §3.5: "The window set is the cashier's sessions whose `status` is `RECONCILED` and whose `updated_at` lies inside it; sessions still `ACTIVE`, `PENDING_COUNT` or `COUNTED` are excluded even when a discarded count exists for them."

    PRD §3.5: "In the same link, if the absolute value of the session's own `variance_cents` is at or above the store's `single_event_variance_threshold_cents` — twenty-five dollars by default — the cashier's `coaching_state` is set to `COACHING_DUE`, `coaching_due_at` is set to the current clock plus 72 hours, and a variance case is opened with `case_type` `SESSION_VARIANCE` naming this cashier and this sales journal."

    Design: Corner/calculations/rolling_variance_counts_only_reconciled_sessions
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1932", name="Store 1932", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    session_a = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session_a["id"],
        pos_cash_sales_cents=50000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(
        session_a["id"],
        [
            {"denomination_cents": 2000, "quantity": 33},
            {"denomination_cents": 1000, "quantity": 1},
        ],
        CLERK_3,
    )

    session_b = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=2,
        shift_start_at="2026-08-03T17:00:00Z",
        shift_end_at="2026-08-03T21:00:00Z",
        starting_bank_cents=20000,
    )
    set_clock("2026-08-03T17:30:00Z")
    close_till(
        session_b["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(
        session_b["id"], [{"denomination_cents": 2000, "quantity": 40}], CLERK_3
    )

    reconciled = validate_success(
        api.reconcile_till_session(session_a["id"], make_clerk_headers(CLERK_1))
    )

    assert reconciled["expected_cash_cents"] == 70000, (
        f"expected expected_cash_cents 70000, got {reconciled['expected_cash_cents']}"
    )
    assert reconciled["counted_cash_cents"] == 67000, (
        f"expected counted_cash_cents 67000, got {reconciled['counted_cash_cents']}"
    )
    assert reconciled["variance_cents"] == -3000, (
        f"expected variance_cents -3000, got {reconciled['variance_cents']}"
    )

    refreshed_cashier = read_cashier(cashier["id"])
    assert refreshed_cashier["rolling_absolute_variance_cents"] == 3000, (
        "session B's 20000 short is excluded while COUNTED, so "
        "rolling_absolute_variance_cents must be 3000, got "
        f"{refreshed_cashier['rolling_absolute_variance_cents']}"
    )
    assert refreshed_cashier["rolling_net_variance_cents"] == -3000, (
        f"expected rolling_net_variance_cents -3000, "
        f"got {refreshed_cashier['rolling_net_variance_cents']}"
    )
    assert refreshed_cashier["reconciled_session_count"] == 1, (
        f"expected reconciled_session_count 1, "
        f"got {refreshed_cashier['reconciled_session_count']}"
    )
    assert refreshed_cashier["till_eligibility"] == "ELIGIBLE", (
        f"expected till_eligibility ELIGIBLE (3000 < 10000), "
        f"got {refreshed_cashier['till_eligibility']}"
    )
    assert refreshed_cashier["coaching_state"] == "COACHING_DUE", (
        f"expected coaching_state COACHING_DUE, "
        f"got {refreshed_cashier['coaching_state']}"
    )
    assert parse_instant(refreshed_cashier["coaching_due_at"]) == parse_instant(
        "2026-08-06T17:30:00Z"
    ), (
        f"expected coaching_due_at 2026-08-06T17:30:00Z (clock 17:30Z + 72h), "
        f"got {refreshed_cashier['coaching_due_at']}"
    )

    counted_b = read_session(session_b["id"])
    assert counted_b["status"] == "COUNTED", (
        f"expected session B status COUNTED, got {counted_b['status']}"
    )
    assert counted_b["variance_cents"] is None, (
        f"expected session B variance_cents null, got {counted_b['variance_cents']}"
    )
    assert counted_b["expected_cash_cents"] is None, (
        f"expected session B expected_cash_cents null, "
        f"got {counted_b['expected_cash_cents']}"
    )

    refreshed_journal = read_journal(journal["id"])
    assert refreshed_journal["session_count"] == 2, (
        f"expected session_count 2, got {refreshed_journal['session_count']}"
    )
    assert refreshed_journal["reconciled_session_count"] == 1, (
        f"expected reconciled_session_count 1, "
        f"got {refreshed_journal['reconciled_session_count']}"
    )
    assert refreshed_journal["open_case_count"] == 1, (
        "only the SESSION_VARIANCE 3000 case may exist, no ROLLING_PATTERN case, "
        f"got open_case_count {refreshed_journal['open_case_count']}"
    )
    cases = list_cases(sales_journal_id=journal["id"])
    case_types = sorted(case["case_type"] for case in cases)
    assert case_types == ["SESSION_VARIANCE"], (
        f"expected only a SESSION_VARIANCE case, got {case_types}"
    )


def test_change_order_baseline_plan_fills_every_denomination_bucket(api, clerk_headers):
    """PRD §3.9: "Five denomination rows are always planned, always in descending order of denomination, and each always produces one entry in `planned_lines` — even when its raw unit count rounds up from a fraction."

    PRD §3.9: "The row's `strap_count` is that raw count divided by the row's units-per-strap and rounded **up** to the next whole strap or roll."

    PRD §3.9: "Only after every line has been rounded up individually is `total_planned_cents` formed as the sum of the lines' `planned_cents`."

    PRD §3.9: "A new order sits at `status` `DRAFT` with `approved_by_user_id` and `received_amount_cents` null."

    Design: Corner/calculations/change_order_baseline_plan_fills_every_denomination_bucket
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1933", name="Store 1933", region_code="WEST")

    order = validate_success(
        api.create_change_order(
            {
                "store_id": store["id"],
                "target_week_start": "2026-08-10",
                "days_covered": 7,
                "baseline_daily_cash_demand_cents": 80000,
            },
            clerk_headers,
        ),
        201,
    )

    assert order["applied_seasonal_profile"] == "BASELINE", (
        f"expected applied_seasonal_profile BASELINE, "
        f"got {order['applied_seasonal_profile']}"
    )
    assert order["growth_pct"] == 0, (
        f"expected growth_pct 0, got {order['growth_pct']}"
    )
    assert order["status"] == "DRAFT", f"expected status DRAFT, got {order['status']}"
    assert order["forecast_demand_cents"] == 560000, (
        f"expected forecast_demand_cents 560000, got {order['forecast_demand_cents']}"
    )

    plan = order["planned_lines"]
    assert len(plan) == 5, f"expected exactly 5 planned_lines entries, got {len(plan)}"
    denominations = [line["denomination_cents"] for line in plan]
    assert denominations == [2000, 1000, 500, 100, 25], (
        f"expected descending denomination_cents [2000, 1000, 500, 100, 25], "
        f"got {denominations}"
    )

    expected_lines = {
        2000: {"strap_count": 6, "units": 150, "planned_cents": 300000},
        1000: {"strap_count": 5, "units": 125, "planned_cents": 125000},
        500: {"strap_count": 4, "units": 200, "planned_cents": 100000},
        100: {"strap_count": 12, "units": 600, "planned_cents": 60000},
        25: {"strap_count": 28, "units": 1120, "planned_cents": 28000},
    }
    for line in plan:
        wanted = expected_lines[line["denomination_cents"]]
        for field, value in wanted.items():
            assert line[field] == value, (
                f"line {line['denomination_cents']}: expected {field} {value}, "
                f"got {line[field]}"
            )

    assert order["total_planned_cents"] == 613000, (
        f"expected total_planned_cents 613000, got {order['total_planned_cents']}"
    )
    assert order["received_amount_cents"] is None, (
        f"expected received_amount_cents null, got {order['received_amount_cents']}"
    )


def test_bank_reconciliation_excludes_provisional_and_nets_adjustment(
    api, treasury_headers, clerk_headers
):
    """PRD §3.7: "`credited_total_cents` is the sum of `amount_cents` over the deposit's records whose `credit_type` is `FINAL` or `ADJUSTMENT`; `PROVISIONAL` rows are deliberately excluded, because provisional credit is a float the bank later reverses and counting it would double-count the deposit."

    PRD §3.7: "Negative `ADJUSTMENT` rows are included with their sign."

    PRD §3.6: "The difference is real whenever the fee straddles a thousand-dollar boundary: a bag of `declared_total_cents` 200500 is priced at a `carrier_fee_cents` of 1305 and an `expected_credit_cents` of 199195, whereas keying the increment count on the net figure would have given 1270 and 199230."

    Design: Corner/calculations/bank_reconciliation_excludes_provisional_and_nets_adjustment
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1934", name="Store 1934", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    arm_open_request(safe["id"], CLERK_1, reason="Deposit preparation")
    set_clock("2026-08-03T08:05:00Z")
    open_safe(safe["id"], CLERK_2)

    deposit = prepare_deposit(
        safe["id"],
        journal["id"],
        [
            {"denomination_cents": 2000, "quantity": 100},
            {"denomination_cents": 500, "quantity": 1},
        ],
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    seal_deposit(deposit["id"], "SEAL-1", CLERK_2)
    schedule_pickup(
        deposit["id"],
        "2026-08-03T10:00:00Z",
        "2026-08-03T10:30:00Z",
        carrier_reference="CAR-1934-A",
    )
    set_clock("2026-08-03T10:15:00Z")
    pickup_deposit(deposit["id"], "2026-08-03T10:15:00Z", carrier_signature="J.CARRIER")

    final_record = post_bank_credit_record(
        store["id"],
        200000,
        credit_type="FINAL",
        deposit_id=deposit["id"],
        value_date="2026-08-04",
        bank_reference="BR-1934-F",
    )
    reconcile_bank(deposit["id"], [final_record["id"]])

    cases = list_cases(deposit_id=deposit["id"])
    assert len(cases) == 1, f"expected one DEPOSIT_CREDIT case, got {len(cases)}"
    case = cases[0]
    append_attribution(
        case["id"],
        "BANK",
        805,
        case["version"],
        note="Bank withheld the strap fee on the coin bag",
    )

    adjustment = post_bank_credit_record(
        store["id"],
        -805,
        credit_type="ADJUSTMENT",
        deposit_id=deposit["id"],
        value_date="2026-08-05",
        bank_reference="BR-1934-ADJ",
    )

    reconciled = validate_success(
        api.reconcile_bank(
            deposit["id"], {"bank_credit_record_ids": [adjustment["id"]]}, treasury_headers
        )
    )

    assert reconciled["status"] == "RECONCILED", (
        f"expected status RECONCILED, got {reconciled['status']}"
    )
    assert reconciled["declared_total_cents"] == 200500, (
        f"expected declared_total_cents 200500, got {reconciled['declared_total_cents']}"
    )
    assert reconciled["carrier_fee_cents"] == 1305, (
        "expected carrier_fee_cents 1305 (1200 + 35 * ceil(200500/100000) = 1200 + 105), "
        f"got {reconciled['carrier_fee_cents']}"
    )
    assert reconciled["expected_credit_cents"] == 199195, (
        f"expected expected_credit_cents 199195, "
        f"got {reconciled['expected_credit_cents']}"
    )
    assert reconciled["credited_total_cents"] == 199195, (
        f"expected credited_total_cents 199195 (200000 + (-805)), "
        f"got {reconciled['credited_total_cents']}"
    )
    assert reconciled["credit_variance_cents"] == 0, (
        f"expected credit_variance_cents 0, got {reconciled['credit_variance_cents']}"
    )

    provisional, provisional_meta = validate_paginated(
        api.list_bank_credit_records(
            clerk_headers,
            params={
                "deposit_id": deposit["id"],
                "credit_type": "PROVISIONAL",
                "limit": 100,
            },
        )
    )
    assert provisional_meta["total_count"] == 1, (
        "the provisional row still exists and was still excluded, expected "
        f"total_count 1, got {provisional_meta['total_count']}"
    )
    assert provisional[0]["amount_cents"] == 200500, (
        f"expected the provisional amount_cents 200500, "
        f"got {provisional[0]['amount_cents']}"
    )

    refreshed_cases = list_cases(deposit_id=deposit["id"])
    refreshed_case = refreshed_cases[0]
    assert refreshed_case["status"] == "EXPLAINED", (
        f"expected case status EXPLAINED, got {refreshed_case['status']}"
    )
    assert refreshed_case["attributed_bank_cents"] == 805, (
        f"expected attributed_bank_cents 805, "
        f"got {refreshed_case['attributed_bank_cents']}"
    )
    assert refreshed_case["unexplained_cents"] == 0, (
        f"expected unexplained_cents 0, got {refreshed_case['unexplained_cents']}"
    )

    refreshed_journal = read_journal(journal["id"])
    assert refreshed_journal["open_case_count"] == 0, (
        f"expected open_case_count 0, got {refreshed_journal['open_case_count']}"
    )
    assert refreshed_journal["net_unexplained_cents"] == 0, (
        f"expected net_unexplained_cents 0, "
        f"got {refreshed_journal['net_unexplained_cents']}"
    )

    refreshed_safe = read_safe(safe["id"])
    assert refreshed_safe["provisional_credit_balance_cents"] == 0, (
        "a RECONCILED deposit leaves the provisional pool, so "
        "provisional_credit_balance_cents must be 0, got "
        f"{refreshed_safe['provisional_credit_balance_cents']}"
    )


def test_smart_deposit_provisional_credit_capped_by_store_policy(
    api, clerk_headers
):
    """PRD §3.6: "Only denominations the validator can read earn credit: the validated value is the sum, over every line whose `denomination_cents` is at least 500, of `denomination_cents` multiplied by `quantity`."

    PRD §3.6: "From that the deposit's `suspect_note_cents` is subtracted — the notes the validator rejected — and the result is capped, so `provisional_credit_cents` is the smaller of that net validated figure and the store's `provisional_credit_cap_cents`."

    PRD §3.6: "No safe opening is required or possible, because cash goes in through the validator and never comes out."

    Design: Corner/calculations/smart_deposit_provisional_credit_capped_by_store_policy
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(
        store_code="S-1935",
        name="Store 1935",
        region_code="WEST",
        provisional_credit_cap_cents=100000,
    )
    safe = create_safe(
        store["id"], safe_code="SAFE-B", safe_type="SMART", opening_balance_cents=500000
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    deposit = validate_success(
        api.create_smart_deposit(
            safe["id"],
            {
                "sales_journal_id": journal["id"],
                "business_date": "2026-08-03",
                "counted_lines": [{"denomination_cents": 2000, "quantity": 100}],
            },
            clerk_headers,
        ),
        201,
    )

    assert deposit["status"] == "SEALED", (
        f"expected status SEALED, got {deposit['status']}"
    )
    assert deposit["deposit_type"] == "SMART_SAFE", (
        f"expected deposit_type SMART_SAFE, got {deposit['deposit_type']}"
    )
    assert deposit["credit_basis"] == "SMART_PROVISIONAL", (
        f"expected credit_basis SMART_PROVISIONAL, got {deposit['credit_basis']}"
    )
    assert deposit["declared_total_cents"] == 200000, (
        f"expected declared_total_cents 200000, got {deposit['declared_total_cents']}"
    )
    assert deposit["provisional_credit_cents"] == 100000, (
        "expected provisional_credit_cents 100000 — min(validated 200000, cap 100000), "
        f"got {deposit['provisional_credit_cents']}"
    )
    assert deposit["suspect_note_cents"] == 0, (
        f"expected suspect_note_cents 0, got {deposit['suspect_note_cents']}"
    )
    assert deposit["seal_number"] == "SMART-SAFE-B", (
        f"expected seal_number SMART-SAFE-B, got {deposit['seal_number']}"
    )

    records, meta = validate_paginated(
        api.list_bank_credit_records(
            clerk_headers, params={"deposit_id": deposit["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert records[0]["credit_type"] == "PROVISIONAL", (
        f"expected credit_type PROVISIONAL, got {records[0]['credit_type']}"
    )
    assert records[0]["amount_cents"] == 100000, (
        f"expected amount_cents 100000, got {records[0]['amount_cents']}"
    )

    refreshed_safe = read_safe(safe["id"])
    assert refreshed_safe["balance_cents"] == 700000, (
        f"expected balance_cents 700000 (500000 + 200000), "
        f"got {refreshed_safe['balance_cents']}"
    )
    assert refreshed_safe["provisional_credit_balance_cents"] == 100000, (
        f"expected provisional_credit_balance_cents 100000, "
        f"got {refreshed_safe['provisional_credit_balance_cents']}"
    )
    assert refreshed_safe["open_state"] == "LOCKED", (
        f"expected open_state LOCKED, got {refreshed_safe['open_state']}"
    )
    assert refreshed_safe["unlocked_at"] is None, (
        f"expected unlocked_at null, got {refreshed_safe['unlocked_at']}"
    )


def test_empty_blind_count_yields_zero_counted_and_full_short(api, clerk_headers):
    """PRD §3.4: "Each blind count replaces `counted_lines` wholesale rather than appending to it, and `counted_cash_cents` is recomputed as the value of those lines, an empty list yielding zero."

    PRD §2.10: "An empty list is worth zero."

    PRD §3.5: "**Link three** fires because link two recomputed `rolling_absolute_variance_cents`: if that recomputed figure is at or above the store's `rolling_variance_threshold_cents` — one hundred dollars by default — the cashier's `till_eligibility` is set to `RESTRICTED` and a second variance case is opened with `case_type` `ROLLING_PATTERN`, again naming this cashier and this sales journal."

    Design: Corner/calculations/empty_blind_count_yields_zero_counted_and_full_short
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1936", name="Store 1936", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
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
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        pos_cash_sales_cents=0,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )

    counted = validate_success(
        api.blind_count(
            session["id"], {"counted_lines": []}, make_clerk_headers(CLERK_3)
        )
    )
    assert counted["counted_cash_cents"] == 0, (
        "an empty counted_lines list is a valid count of zero, expected "
        f"counted_cash_cents 0, got {counted['counted_cash_cents']}"
    )
    assert counted["status"] == "COUNTED", (
        f"expected status COUNTED, got {counted['status']}"
    )

    reconciled = validate_success(
        api.reconcile_till_session(session["id"], make_clerk_headers(CLERK_1))
    )
    assert reconciled["expected_cash_cents"] == 20000, (
        f"expected expected_cash_cents 20000, got {reconciled['expected_cash_cents']}"
    )
    assert reconciled["variance_cents"] == -20000, (
        f"expected variance_cents -20000, got {reconciled['variance_cents']}"
    )
    assert reconciled["variance_basis"] == "DECLARED_DROPS", (
        f"expected variance_basis DECLARED_DROPS, got {reconciled['variance_basis']}"
    )

    refreshed_cashier = read_cashier(cashier["id"])
    assert refreshed_cashier["rolling_absolute_variance_cents"] == 20000, (
        f"expected rolling_absolute_variance_cents 20000, "
        f"got {refreshed_cashier['rolling_absolute_variance_cents']}"
    )
    assert refreshed_cashier["till_eligibility"] == "RESTRICTED", (
        f"expected till_eligibility RESTRICTED, "
        f"got {refreshed_cashier['till_eligibility']}"
    )
    assert refreshed_cashier["coaching_state"] == "COACHING_DUE", (
        f"expected coaching_state COACHING_DUE, "
        f"got {refreshed_cashier['coaching_state']}"
    )
    assert parse_instant(refreshed_cashier["coaching_due_at"]) == parse_instant(
        "2026-08-06T17:00:00Z"
    ), (
        f"expected coaching_due_at 2026-08-06T17:00:00Z, "
        f"got {refreshed_cashier['coaching_due_at']}"
    )

    cases, meta = validate_paginated(
        api.list_variance_cases(
            clerk_headers, params={"sales_journal_id": journal["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    case_types = sorted(case["case_type"] for case in cases)
    assert case_types == ["ROLLING_PATTERN", "SESSION_VARIANCE"], (
        f"expected case_types ROLLING_PATTERN and SESSION_VARIANCE, got {case_types}"
    )
    for case in cases:
        assert case["total_variance_cents"] == 20000, (
            f"{case['case_type']}: expected total_variance_cents 20000, "
            f"got {case['total_variance_cents']}"
        )
        assert case["suspected_theft"] is False, (
            f"{case['case_type']}: expected suspected_theft false, "
            f"got {case['suspected_theft']}"
        )

    refreshed_journal = read_journal(journal["id"])
    assert refreshed_journal["open_case_count"] == 2, (
        f"expected open_case_count 2, got {refreshed_journal['open_case_count']}"
    )
    assert refreshed_journal["net_unexplained_cents"] == 40000, (
        f"expected net_unexplained_cents 40000, "
        f"got {refreshed_journal['net_unexplained_cents']}"
    )


def test_card_settlement_amex_adder_applied_on_top_tier(api, treasury_headers):
    """PRD §3.7: "The network then contributes an adder of 0.0035 for `AMEX` and nothing at all for `VISA_MC`."

    PRD §3.7: "`expected_fee_cents` is the product of `gross_card_sales_cents` and the sum of the tier rate and the network adder, rounded half up to whole cents, **plus** twelve cents for each transaction in `txn_count`."

    PRD §3.7: "`expected_funded_cents` is `gross_card_sales_cents` minus `expected_fee_cents` minus `chargeback_cents`, and `settlement_variance_cents` is `funded_amount_cents` minus `expected_funded_cents`."

    PRD §3.7: "The `settlement_status` is `MATCHED` when `settlement_variance_cents` is exactly zero and `VARIANCE` otherwise."

    Design: Corner/calculations/card_settlement_amex_adder_applied_on_top_tier
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1937", name="Store 1937", region_code="WEST")
    journal = create_sales_journal(store["id"], "2026-08-03")

    settlement = validate_success(
        api.create_card_settlement(
            {
                "sales_journal_id": journal["id"],
                "card_network": "AMEX",
                "gross_card_sales_cents": 412750,
                "txn_count": 143,
                "monthly_volume_cents": 21000000,
                "chargeback_cents": 1500,
                "funded_amount_cents": 400041,
            },
            treasury_headers,
        ),
        201,
    )

    assert settlement["expected_fee_cents"] == 11209, (
        "expected expected_fee_cents 11209 "
        "(round_half_up(412750 * 0.0230) == 9493, plus 1716), "
        f"got {settlement['expected_fee_cents']}"
    )
    assert settlement["expected_funded_cents"] == 400041, (
        "expected expected_funded_cents 400041 (412750 - 11209 - 1500), "
        f"got {settlement['expected_funded_cents']}"
    )
    assert settlement["settlement_variance_cents"] == 0, (
        f"expected settlement_variance_cents 0, "
        f"got {settlement['settlement_variance_cents']}"
    )
    assert settlement["settlement_status"] == "MATCHED", (
        f"expected settlement_status MATCHED, got {settlement['settlement_status']}"
    )

    refreshed_journal = read_journal(journal["id"])
    assert refreshed_journal["settlement_count"] == 1, (
        f"expected settlement_count 1, got {refreshed_journal['settlement_count']}"
    )
    assert refreshed_journal["settlement_variance_total_cents"] == 0, (
        f"expected settlement_variance_total_cents 0, "
        f"got {refreshed_journal['settlement_variance_total_cents']}"
    )
