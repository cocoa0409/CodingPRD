"""Endpoint behaviours: coaching acknowledgement, bank credit links, journal reads,
deposit listings and the smart-safe gate."""

from test_helpers import (
    ApiErrorId,
    CLERK_1,
    CLERK_2,
    CLERK_3,
    ApiClient,
    arm_open_request,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    make_cashier_headers,
    open_safe,
    parse_instant,
    prepare_deposit,
    read_deposit,
    read_journal,
    read_safe,
    reconcile_till,
    seal_deposit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_acknowledged_coaching_reopens_till_assignment_after_the_deadline(
    api: ApiClient, manager_headers
):
    """PRD §3.2: "The acknowledgement moves `coaching_state` from `COACHING_DUE` to `COACHING_ACKNOWLEDGED` and increments the cashier's `version`; it leaves `till_eligibility` exactly as it was."

    PRD §3.2: "A cashier who is still `ELIGIBLE` but whose `coaching_state` is `COACHING_DUE` may be assigned only while the logical clock is at or before `coaching_due_at` — the boundary instant itself is permitted — and once that deadline has passed the assignment is refused with `ERR_COACHING_NOT_ACKNOWLEDGED`."

    PRD §3.2: "`coaching_due_at` is the instant of the single-event breach plus a grace period of three days, that is 72 hours."

    Design: Corner/endpoints/acknowledged_coaching_reopens_till_assignment_after_the_deadline
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1960", name="Store 1960", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal_1 = create_sales_journal(store["id"], "2026-08-03")

    session_1 = assign_till(
        journal_1["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    set_clock("2026-08-03T18:00:00Z")
    close_till(
        session_1["id"],
        pos_cash_sales_cents=50000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(
        session_1["id"],
        [
            {"denomination_cents": 2000, "quantity": 33},
            {"denomination_cents": 1000, "quantity": 1},
        ],
        CLERK_3,
    )
    reconcile_till(session_1["id"], CLERK_1)

    set_clock("2026-08-06T18:01:00Z")
    journal_2 = create_sales_journal(store["id"], "2026-08-06")

    acknowledged = validate_success(
        api.acknowledge_coaching(
            cashier["id"],
            {"acknowledgement_note": "Reviewed drawer procedure with the manager"},
            make_cashier_headers(cashier["id"]),
        )
    )

    assert acknowledged["coaching_state"] == "COACHING_ACKNOWLEDGED", (
        f"expected coaching_state COACHING_ACKNOWLEDGED, "
        f"got {acknowledged['coaching_state']}"
    )
    assert acknowledged["till_eligibility"] == "ELIGIBLE", (
        f"expected till_eligibility ELIGIBLE (untouched by the acknowledgement), "
        f"got {acknowledged['till_eligibility']}"
    )
    assert parse_instant(acknowledged["coaching_due_at"]) == parse_instant(
        "2026-08-06T18:00:00Z"
    ), (
        "acknowledging satisfies the deadline rather than moving it, so "
        f"coaching_due_at must stay 2026-08-06T18:00:00Z, "
        f"got {acknowledged['coaching_due_at']}"
    )

    session_2 = validate_success(
        api.create_till_session(
            {
                "sales_journal_id": journal_2["id"],
                "cashier_id": cashier["id"],
                "safe_id": safe["id"],
                "register_number": 1,
                "shift_start_at": "2026-08-06T18:30:00Z",
                "shift_end_at": "2026-08-06T22:00:00Z",
                "starting_bank_cents": 20000,
            },
            manager_headers,
        ),
        201,
    )

    assert session_2["status"] == "ACTIVE", (
        "the assignment is accepted 61 seconds past the lapsed deadline, so "
        f"expected status ACTIVE, got {session_2['status']}"
    )
    assert session_2["starting_bank_cents"] == 20000, (
        f"expected starting_bank_cents 20000, got {session_2['starting_bank_cents']}"
    )

    refreshed_safe = read_safe(safe["id"])
    assert refreshed_safe["balance_cents"] == 460000, (
        f"expected balance_cents 460000 (500000 - 20000 - 20000), "
        f"got {refreshed_safe['balance_cents']}"
    )

    refreshed_journal_2 = read_journal(journal_2["id"])
    assert refreshed_journal_2["session_count"] == 1, (
        f"expected session_count 1 on the 2026-08-06 journal, "
        f"got {refreshed_journal_2['session_count']}"
    )


def test_bank_credit_record_links_a_deposit_and_starts_unmatched(
    api: ApiClient, treasury_headers
):
    """PRD §3.7: "A record's `match_state` is `UNMATCHED` at creation **even when `deposit_id` is supplied at creation** — supplying the link is a hint, not a match, and the record only becomes `MATCHED` when a bank reconciliation consumes it."

    PRD §3.6: "`provisional_credit_cents` starts at 0, `credited_total_cents` at 0, `credit_variance_cents` null, and `pickup_window_start`, `pickup_window_end`, `seal_number`, `sealed_by_user_id` and `carrier_reference` all null."

    PRD §3.7: "Records may be listed with `store_id`, `deposit_id`, `credit_type` and `match_state` filters."

    Design: Corner/endpoints/bank_credit_record_links_a_deposit_and_starts_unmatched
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1961", name="Store 1961", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    arm_open_request(safe["id"], CLERK_1, reason="Deposit preparation")
    set_clock("2026-08-03T08:05:00Z")
    open_safe(safe["id"], CLERK_2)

    safe_version = read_safe(safe["id"])["version"]
    deposit = prepare_deposit(
        safe["id"],
        journal["id"],
        [{"denomination_cents": 2000, "quantity": 50}],
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
        expected_safe_version=safe_version,
    )

    record = validate_success(
        api.create_bank_credit_record(
            {
                "store_id": store["id"],
                "deposit_id": deposit["id"],
                "credit_type": "FINAL",
                "amount_cents": 98765,
                "value_date": "2026-08-04",
                "bank_reference": "BR-1961-F",
            },
            treasury_headers,
        ),
        201,
    )

    assert record["deposit_id"] == deposit["id"], (
        f"expected deposit_id {deposit['id']}, got {record['deposit_id']}"
    )
    assert record["store_id"] == store["id"], (
        f"expected store_id {store['id']}, got {record['store_id']}"
    )
    assert record["credit_type"] == "FINAL", (
        f"expected credit_type FINAL, got {record['credit_type']}"
    )
    assert record["amount_cents"] == 98765, (
        f"expected amount_cents 98765, got {record['amount_cents']}"
    )
    assert record["match_state"] == "UNMATCHED", (
        "supplying the link is a hint, not a match, so match_state must be "
        f"UNMATCHED, got {record['match_state']}"
    )

    refreshed_deposit = read_deposit(deposit["id"])
    assert refreshed_deposit["credited_total_cents"] == 0, (
        f"expected credited_total_cents 0 until reconcile-bank runs, "
        f"got {refreshed_deposit['credited_total_cents']}"
    )
    assert refreshed_deposit["credit_variance_cents"] is None, (
        f"expected credit_variance_cents null, "
        f"got {refreshed_deposit['credit_variance_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_bank_credit_records(
            treasury_headers,
            params={"deposit_id": deposit["id"], "match_state": "UNMATCHED"},
        )
    )
    assert meta["total_count"] == 1, (
        f"expected total_count 1, got {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [record["id"]], (
        f"expected the single row {record['id']}, got {[row['id'] for row in rows]}"
    )


def test_journal_read_returns_derived_case_counters(api: ApiClient, manager_headers):
    """PRD §3.1: "`open_case_count` is the number of variance cases on the journal whose `status` is `OPEN`, `RESEARCHING` or `ESCALATED`."

    PRD §3.1: "`net_unexplained_cents` is the sum of `unexplained_cents` over that same set of cases."

    PRD §3.1: "The journal is **structurally complete** when its `status` is `TENDERS_POSTED` or `OUT_OF_BALANCE`, its `session_count` is at least 1, its `reconciled_session_count` equals its `session_count`, its `settlement_count` is at least 1, and at least one deposit attached to the journal has reached `SEALED`, `SCHEDULED`, `IN_TRANSIT` or `RECONCILED`."

    PRD §3.1: "A freshly opened journal has `status` `OPEN`, both of its posted tender figures null, and all of its derived counters at zero."

    Design: Corner/endpoints/journal_read_returns_derived_case_counters
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1962", name="Store 1962", region_code="WEST")
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
        pos_cash_sales_cents=50000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(
        session["id"],
        [
            {"denomination_cents": 2000, "quantity": 33},
            {"denomination_cents": 1000, "quantity": 1},
        ],
        CLERK_3,
    )
    reconcile_till(session["id"], CLERK_1)

    read = validate_success(api.get_sales_journal(journal["id"], manager_headers))

    assert read["status"] == "OPEN", (
        "structural completeness needs TENDERS_POSTED first, so the journal must "
        f"still read OPEN, got {read['status']}"
    )
    assert read["session_count"] == 1, (
        f"expected session_count 1, got {read['session_count']}"
    )
    assert read["reconciled_session_count"] == 1, (
        f"expected reconciled_session_count 1, got {read['reconciled_session_count']}"
    )
    assert read["settlement_count"] == 0, (
        f"expected settlement_count 0, got {read['settlement_count']}"
    )
    assert read["open_case_count"] == 1, (
        "the 3000 short breached the single-event threshold and opened one case, so "
        f"expected open_case_count 1, got {read['open_case_count']}"
    )
    assert read["net_unexplained_cents"] == 3000, (
        f"expected net_unexplained_cents 3000, got {read['net_unexplained_cents']}"
    )
    assert read["journal_cash_sales_cents"] is None, (
        f"expected journal_cash_sales_cents null, "
        f"got {read['journal_cash_sales_cents']}"
    )
    assert read["journal_card_sales_cents"] is None, (
        f"expected journal_card_sales_cents null, "
        f"got {read['journal_card_sales_cents']}"
    )


def test_deposit_listing_filters_by_status(api: ApiClient, treasury_headers):
    """PRD §3.6: "Deposits may be listed with `safe_id`, `sales_journal_id`, `status` and `business_date` filters."

    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` — the number of records matching the filters before pagination is applied — and `has_more`, which is true exactly when records matching the filters remain beyond the current page."

    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    PRD §2.11: "A single safe opening legitimately supports several bags, so a second preparation is not blocked by any state rule — the safe is still `UNLOCKED` and the action is valid product behaviour."

    Design: Corner/endpoints/deposit_listing_filters_by_status
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1963", name="Store 1963", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    arm_open_request(safe["id"], CLERK_1, reason="Two bags")
    set_clock("2026-08-03T08:05:00Z")
    open_safe(safe["id"], CLERK_2)

    deposit_a = prepare_deposit(
        safe["id"],
        journal["id"],
        [{"denomination_cents": 2000, "quantity": 50}],
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
        expected_safe_version=read_safe(safe["id"])["version"],
    )
    deposit_b = prepare_deposit(
        safe["id"],
        journal["id"],
        [{"denomination_cents": 2000, "quantity": 50}],
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
        expected_safe_version=read_safe(safe["id"])["version"],
    )
    seal_deposit(deposit_a["id"], "SEAL-A", CLERK_2)

    response = api.list_deposits(
        treasury_headers,
        params={"sales_journal_id": journal["id"], "status": "SEALED"},
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array", (
        f"expected response_type array for a list read, "
        f"got {response.json()['response_type']}"
    )
    assert meta["total_count"] == 1, (
        "only bag A is SEALED, so the status filter must report total_count 1, "
        f"got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"expected has_more false, got {meta['has_more']}"
    )
    assert len(rows) == 1, f"expected exactly 1 row, got {len(rows)}"
    assert rows[0]["id"] == deposit_a["id"], (
        f"expected the single row {deposit_a['id']}, got {rows[0]['id']}"
    )
    assert rows[0]["seal_number"] == "SEAL-A", (
        f"expected seal_number SEAL-A, got {rows[0]['seal_number']}"
    )
    assert rows[0]["declared_total_cents"] == 100000, (
        f"expected declared_total_cents 100000, got {rows[0]['declared_total_cents']}"
    )

    _all_rows, all_meta = validate_paginated(
        api.list_deposits(
            treasury_headers, params={"sales_journal_id": journal["id"]}
        )
    )
    assert all_meta["total_count"] == 2, (
        f"the unfiltered listing for the journal must report total_count 2, "
        f"got {all_meta['total_count']}"
    )

    refreshed_b = read_deposit(deposit_b["id"])
    assert refreshed_b["status"] == "PREPARING", (
        f"expected bag B status PREPARING, got {refreshed_b['status']}"
    )

    refreshed_safe = read_safe(safe["id"])
    assert refreshed_safe["balance_cents"] == 300000, (
        f"expected balance_cents 300000 (500000 - 100000 - 100000), "
        f"got {refreshed_safe['balance_cents']}"
    )


def test_smart_deposit_on_a_manual_safe_returns_smart_safe_required(
    api: ApiClient, clerk_headers, treasury_headers
):
    """PRD §3.6: "The target safe's `safe_type` must be `SMART`, failing which the answer is `ERR_SMART_SAFE_REQUIRED`; its `posture` must be `OPEN`; the journal must belong to the safe's store; and `suspect_note_cents` may not exceed the value of `counted_lines`, otherwise the insertion is rejected with `ERR_INVALID_REQUEST`."

    PRD §3.6: "It writes a safe ledger row of kind `SMART_DEPOSIT` linked to the deposit with `declared_amount_cents` equal to `declared_total_cents`, recomputes the safe's `balance_cents`, prices `carrier_fee_cents` and `expected_credit_cents` by the same pinned fee rule as an armored bag, and increments the safe's `version` by 1."

    Design: Corner/endpoints/smart_deposit_on_a_manual_safe_returns_smart_safe_required
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1964", name="Store 1964", region_code="WEST")
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    response = api.create_smart_deposit(
        safe["id"],
        {
            "sales_journal_id": journal["id"],
            "business_date": "2026-08-03",
            "counted_lines": [{"denomination_cents": 2000, "quantity": 50}],
        },
        clerk_headers,
    )
    validate_error(response, ApiErrorId.ERR_SMART_SAFE_REQUIRED.value)

    refreshed_safe = read_safe(safe["id"])
    assert refreshed_safe["balance_cents"] == 500000, (
        "the rejected insertion writes no SMART_DEPOSIT row, so balance_cents must "
        f"stay 500000, got {refreshed_safe['balance_cents']}"
    )
    assert refreshed_safe["provisional_credit_balance_cents"] == 0, (
        "no provisional credit is granted, so provisional_credit_balance_cents must "
        f"be 0, got {refreshed_safe['provisional_credit_balance_cents']}"
    )

    _deposits, deposit_meta = validate_paginated(
        api.list_deposits(treasury_headers, params={"safe_id": safe["id"]})
    )
    assert deposit_meta["total_count"] == 0, (
        f"expected no deposit for the safe, got total_count {deposit_meta['total_count']}"
    )

    _records, record_meta = validate_paginated(
        api.list_bank_credit_records(treasury_headers, params={"store_id": store["id"]})
    )
    assert record_meta["total_count"] == 0, (
        f"expected no bank credit record for the store, "
        f"got total_count {record_meta['total_count']}"
    )
