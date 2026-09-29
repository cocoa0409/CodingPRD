"""The logical clock, the coaching deadline, dual control and the barred cashier."""

from test_helpers import (
    CLERK_1,
    CLERK_3,
    MANAGER_1,
    ApiErrorId,
    append_attribution,
    arm_open_request,
    assign_till,
    blind_count,
    close_case,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    escalate_case,
    headers_for_role,
    list_cases,
    parse_instant,
    prepare_deposit,
    read_case,
    read_cashier,
    read_journal,
    read_safe,
    reconcile_till,
    set_clock,
    store_payload,
    till_session_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A syntactically valid identifier that names no store in an empty database.
ABSENT_STORE_ID = "00000000-0000-4000-8000-000000000001"

BAG_100000 = [{"denomination_cents": 2000, "quantity": 50}]
COUNT_67000 = [
    {"denomination_cents": 2000, "quantity": 33},
    {"denomination_cents": 1000, "quantity": 1},
]
COUNT_60000 = [{"denomination_cents": 2000, "quantity": 30}]


def test_clock_cannot_move_backwards(api, treasury_headers):
    """PRD §2.4: "The clock may only move forward: a `current_utc` earlier than the clock's present value is rejected with `ERR_CLOCK_MONOTONIC` (HTTP 422)." And: "Setting the clock to its present value is permitted."

    Design: Corner/validations/clock_cannot_move_backwards
    """
    set_clock("2026-08-03T12:00:00Z")

    rewind = api.set_clock("2026-08-03T11:00:00Z", treasury_headers)
    validate_error(rewind, ApiErrorId.ERR_CLOCK_MONOTONIC.value)

    store = validate_success(
        api.create_store(
            store_payload(store_code="S-1949", region_code="WEST"), treasury_headers
        ),
        201,
    )
    assert parse_instant(store["created_at"]) == parse_instant(
        "2026-08-03T12:00:00Z"
    ), (
        f"the clock never moved: expected created_at 2026-08-03T12:00:00Z, "
        f"got {store['created_at']}"
    )

    identical = validate_success(
        api.set_clock("2026-08-03T12:00:00Z", treasury_headers)
    )
    assert identical is not None, "setting the clock to its present value is permitted"


def test_coaching_deadline_lapse_blocks_till_assignment(api, manager_headers):
    """PRD §3.2: "A cashier who is still `ELIGIBLE` but whose `coaching_state` is `COACHING_DUE` may be assigned only while the logical clock is at or before `coaching_due_at` — the boundary instant itself is permitted — and once that deadline has passed the assignment is refused with `ERR_COACHING_NOT_ACKNOWLEDGED`." The deadline itself: "`coaching_due_at` is the instant of the single-event breach plus a grace period of three days, that is 72 hours."

    Design: Corner/validations/coaching_deadline_lapse_blocks_till_assignment
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1950", region_code="WEST")
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal_1 = create_sales_journal(store["id"], "2026-08-03")
    session = assign_till(
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
        session["id"],
        pos_cash_sales_cents=50000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(session["id"], COUNT_67000, CLERK_3)
    reconcile_till(session["id"], CLERK_1)

    set_clock("2026-08-06T18:01:00Z")
    journal_2 = create_sales_journal(store["id"], "2026-08-06")

    resp = api.create_till_session(
        till_session_payload(
            journal_2["id"],
            cashier["id"],
            safe["id"],
            register_number=1,
            shift_start_at="2026-08-06T18:30:00Z",
            shift_end_at="2026-08-06T22:00:00Z",
            starting_bank_cents=20000,
        ),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_COACHING_NOT_ACKNOWLEDGED.value)

    cashier_after = read_cashier(cashier["id"])
    assert cashier_after["till_eligibility"] == "ELIGIBLE", (
        f"a rolling 3000 stays under 10000, so the cashier is not restricted: "
        f"expected ELIGIBLE, got {cashier_after['till_eligibility']}"
    )
    assert cashier_after["coaching_state"] == "COACHING_DUE", (
        f"expected COACHING_DUE, got {cashier_after['coaching_state']}"
    )
    assert parse_instant(cashier_after["coaching_due_at"]) == parse_instant(
        "2026-08-06T18:00:00Z"
    ), (
        f"expected coaching_due_at 2026-08-06T18:00:00Z, "
        f"got {cashier_after['coaching_due_at']}"
    )

    journal_2_after = read_journal(journal_2["id"])
    assert journal_2_after["session_count"] == 0, (
        f"expected session_count 0, got {journal_2_after['session_count']}"
    )
    safe_after = read_safe(safe["id"])
    assert safe_after["balance_cents"] == 480000, (
        f"no second starting bank left the safe: expected 480000, "
        f"got {safe_after['balance_cents']}"
    )


def test_safe_open_at_the_exact_time_delay_boundary_succeeds(api, clerk_2_headers):
    """PRD §2.8: "The open is permitted only once the clock has reached `open_requested_at` plus the store's `safe_time_delay_minutes` — the boundary instant itself is permitted — and only while the clock is strictly before `open_requested_at` plus `safe_time_delay_minutes` plus `safe_open_window_minutes`."

    Design: Corner/validations/safe_open_at_the_exact_time_delay_boundary_succeeds
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1951", region_code="WEST")
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    set_clock("2026-08-03T09:00:00Z")
    arm_open_request(safe["id"], CLERK_1, reason="Scheduled cash office count")
    set_clock("2026-08-03T09:05:00Z")

    opened = validate_success(api.open_safe(safe["id"], clerk_2_headers))

    assert opened["open_state"] == "UNLOCKED", (
        f"expected UNLOCKED, got {opened['open_state']}"
    )
    assert parse_instant(opened["unlocked_at"]) == parse_instant(
        "2026-08-03T09:05:00Z"
    ), f"expected unlocked_at 2026-08-03T09:05:00Z, got {opened['unlocked_at']}"
    assert parse_instant(opened["open_requested_at"]) == parse_instant(
        "2026-08-03T09:00:00Z"
    ), (
        f"expected open_requested_at 2026-08-03T09:00:00Z, "
        f"got {opened['open_requested_at']}"
    )
    assert opened["open_requested_by_user_id"] == "U-CLERK-1", (
        f"expected open_requested_by_user_id U-CLERK-1, "
        f"got {opened['open_requested_by_user_id']}"
    )
    assert opened["version"] == 3, (
        f"create, arm and open are three accepted writes: expected version 3, "
        f"got {opened['version']}"
    )
    assert opened["posture"] == "OPEN", f"expected OPEN, got {opened['posture']}"
    assert opened["balance_cents"] == 500000, (
        f"opening the safe moves no cash: expected 500000, "
        f"got {opened['balance_cents']}"
    )


def test_store_read_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/store_read_missing_auth_headers_returns_unauthenticated
    """
    set_clock("2026-08-03T08:00:00Z")

    anonymous = api.get_store(ABSENT_STORE_ID, {})
    # Authentication is checked before path resolution, so an anonymous caller
    # cannot probe which ids exist.
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert anonymous.status_code == 401, (
        f"expected HTTP 401, got {anonymous.status_code}"
    )

    unknown_role = api.get_store(
        ABSENT_STORE_ID, headers_for_role("Auditor", "U-AUDIT-1")
    )
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert unknown_role.status_code == 401, (
        f"a role outside the six declared is unauthenticated: expected HTTP 401, "
        f"got {unknown_role.status_code}"
    )


def test_dual_control_disabled_allows_one_user_to_prepare_and_seal(api, clerk_headers):
    """PRD §2.7: "When a store sets `dual_control_required` to false, all three comparisons are skipped and a single operator may complete the pair."

    Design: Corner/validations/dual_control_disabled_allows_one_user_to_prepare_and_seal
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(
        store_code="S-1952", region_code="WEST", dual_control_required=False
    )
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    arm_open_request(safe["id"], CLERK_1, reason="Solo cash office")
    set_clock("2026-08-03T08:05:00Z")
    opened = validate_success(api.open_safe(safe["id"], clerk_headers))
    assert opened["open_state"] == "UNLOCKED", (
        f"the arming user may also open the safe here: expected UNLOCKED, "
        f"got {opened['open_state']}"
    )

    deposit = prepare_deposit(
        safe["id"],
        journal["id"],
        BAG_100000,
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
    )
    sealed = validate_success(
        api.seal_deposit(deposit["id"], {"seal_number": "SEAL-SOLO"}, clerk_headers)
    )

    assert sealed["status"] == "SEALED", f"expected SEALED, got {sealed['status']}"
    assert sealed["seal_number"] == "SEAL-SOLO", (
        f"expected seal_number SEAL-SOLO, got {sealed['seal_number']}"
    )
    assert sealed["prepared_by_user_id"] == "U-CLERK-1", (
        f"expected prepared_by_user_id U-CLERK-1, "
        f"got {sealed['prepared_by_user_id']}"
    )
    assert sealed["sealed_by_user_id"] == "U-CLERK-1", (
        f"the same user on both steps: expected sealed_by_user_id U-CLERK-1, "
        f"got {sealed['sealed_by_user_id']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["open_state"] == "LOCKED", (
        f"sealing ends the cash-office opening: expected LOCKED, "
        f"got {safe_after['open_state']}"
    )
    assert safe_after["balance_cents"] == 400000, (
        f"expected 500000 - 100000 == 400000, got {safe_after['balance_cents']}"
    )


def test_barred_cashier_cannot_be_assigned_after_substantiated_close(
    api, manager_headers, treasury_headers
):
    """PRD §3.8: "A `SUBSTANTIATED` finding moves the case to `CLOSED_SUBSTANTIATED`, writes the confirmed loss off the ledger with one safe transaction of kind `VARIANCE_ADJUSTMENT` against the store's earliest-created safe — the one with the lowest `created_at` — carrying `declared_amount_cents` equal to the case's `unexplained_cents`, recomputes that safe's `balance_cents`, and leaves the cashier's `till_eligibility` at `BARRED`." PRD §3.2: "A cashier whose `till_eligibility` is `BARRED` may never be assigned a till: the answer is `ERR_CASHIER_BARRED`."

    Design: Corner/validations/barred_cashier_cannot_be_assigned_after_substantiated_close
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1953", region_code="WEST")
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
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(session["id"], COUNT_60000, CLERK_3)
    reconcile_till(session["id"], CLERK_1)

    cases = list_cases(sales_journal_id=journal["id"], case_type="SESSION_VARIANCE")
    assert len(cases) == 1, f"expected one SESSION_VARIANCE case, got {len(cases)}"
    case = cases[0]
    append_attribution(
        case["id"],
        "REGISTER",
        1000,
        case["version"],
        note="Void keyed as cash",
        headers=manager_headers,
    )
    escalate_case(
        case["id"],
        reason="60000 short with no plausible explanation",
        user_id=MANAGER_1,
        as_manager=True,
    )
    close_case(
        case["id"],
        "SUBSTANTIATED",
        closing_note="Video shows cash removed from the till drawer",
    )

    resp = api.create_till_session(
        till_session_payload(
            journal["id"],
            cashier["id"],
            safe["id"],
            register_number=2,
            shift_start_at="2026-08-03T18:00:00Z",
            shift_end_at="2026-08-03T22:00:00Z",
            starting_bank_cents=20000,
        ),
        manager_headers,
    )
    # The close restored posture, so the barred-cashier gate is the answer here.
    validate_error(resp, ApiErrorId.ERR_CASHIER_BARRED.value)

    case_after = read_case(case["id"])
    assert case_after["status"] == "CLOSED_SUBSTANTIATED", (
        f"expected CLOSED_SUBSTANTIATED, got {case_after['status']}"
    )
    assert case_after["disposition"] == "SUBSTANTIATED", (
        f"expected disposition SUBSTANTIATED, got {case_after['disposition']}"
    )
    assert case_after["unexplained_cents"] == 59000, (
        f"expected unexplained_cents 59000, got {case_after['unexplained_cents']}"
    )

    cashier_after = read_cashier(cashier["id"])
    assert cashier_after["till_eligibility"] == "BARRED", (
        f"a substantiated finding does not reinstate the cashier: expected BARRED, "
        f"got {cashier_after['till_eligibility']}"
    )

    safe_after = read_safe(safe["id"])
    assert safe_after["posture"] == "OPEN", (
        f"expected posture OPEN, got {safe_after['posture']}"
    )
    assert safe_after["balance_cents"] == 421000, (
        f"expected 480000 - 59000 written off == 421000, "
        f"got {safe_after['balance_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_safe_transactions(
            treasury_headers,
            params={"safe_id": safe["id"], "txn_type": "VARIANCE_ADJUSTMENT"},
        )
    )
    assert meta["total_count"] == 1, (
        f"expected one VARIANCE_ADJUSTMENT row, got {meta['total_count']}"
    )
    assert rows[0]["declared_amount_cents"] == 59000, (
        f"expected declared_amount_cents 59000, "
        f"got {rows[0]['declared_amount_cents']}"
    )
    assert rows[0]["effective_amount_cents"] == -59000, (
        f"expected effective_amount_cents -59000, "
        f"got {rows[0]['effective_amount_cents']}"
    )

    journal_after = read_journal(journal["id"])
    assert journal_after["open_case_count"] == 1, (
        f"the ROLLING_PATTERN case survives: expected open_case_count 1, "
        f"got {journal_after['open_case_count']}"
    )
    assert journal_after["session_count"] == 1, (
        f"expected session_count 1, got {journal_after['session_count']}"
    )
