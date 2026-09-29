"""Half-open cashier shifts versus buffer-expanded, closed carrier pickup windows."""

from test_helpers import (
    ApiErrorId,
    CLERK_1,
    CLERK_2,
    assign_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    lines,
    parse_instant,
    prepare_and_seal_deposit,
    read_deposit,
    read_journal,
    read_safe,
    schedule_pickup,
    set_clock,
    till_session_payload,
    unlock_safe,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_cashier_with_morning_shift():
    """Cashier E-100 holding one 09:00-17:00 session on register 1.

    The safe stays LOCKED: issuing a starting bank needs no physical open.
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1015", name="Store 1015", region_code="SOUTH")
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
    return {
        "store": store,
        "safe": safe,
        "cashier": cashier,
        "journal": journal,
        "session_a": session_a,
    }


def _book_adjacent_evening_shift(api, headers, ctx):
    """Book the back-to-back 17:00-21:00 shift on register 2."""
    return api.create_till_session(
        till_session_payload(
            ctx["journal"]["id"],
            ctx["cashier"]["id"],
            ctx["safe"]["id"],
            register_number=2,
            shift_start_at="2026-08-03T17:00:00Z",
            shift_end_at="2026-08-03T21:00:00Z",
            starting_bank_cents=20000,
        ),
        headers,
    )


def test_back_to_back_shift_touching_at_one_instant_is_accepted(api, manager_headers):
    """PRD §3.2: "A cashier's shift window is treated as half-open, running from `shift_start_at` inclusive to `shift_end_at` exclusive, and the new window must not overlap the window of any other non-terminal session of the same cashier; because the interval is half-open, back-to-back shifts that touch at a single instant are allowed."

    Design: Difficulty/resource_temporal_overlap/cashier_shift_half_open_allows_adjacency_rejects_one_minute_overlap
    """
    ctx = _setup_cashier_with_morning_shift()
    session_b = validate_success(
        _book_adjacent_evening_shift(api, manager_headers, ctx), 201
    )
    assert session_b["status"] == "ACTIVE", (
        f"expected ACTIVE, got {session_b['status']}"
    )
    assert session_b["register_number"] == 2, (
        f"expected 2, got {session_b['register_number']}"
    )

    journal = read_journal(ctx["journal"]["id"])
    assert journal["session_count"] == 2, (
        f"expected 2, got {journal['session_count']}"
    )
    safe = read_safe(ctx["safe"]["id"])
    assert safe["balance_cents"] == 460000, (
        f"expected 460000, got {safe['balance_cents']}"
    )


def test_shift_overlapping_by_one_minute_is_refused(api, manager_headers):
    """PRD §3.2: "An overlap is refused with `ERR_CASHIER_SHIFT_OVERLAP`."

    PRD §3.2: "A cashier's shift window is treated as half-open, running from `shift_start_at` inclusive to `shift_end_at` exclusive, and the new window must not overlap the window of any other non-terminal session of the same cashier; because the interval is half-open, back-to-back shifts that touch at a single instant are allowed."

    Design: Difficulty/resource_temporal_overlap/cashier_shift_half_open_allows_adjacency_rejects_one_minute_overlap
    """
    ctx = _setup_cashier_with_morning_shift()
    validate_success(_book_adjacent_evening_shift(api, manager_headers, ctx), 201)

    overlapping = api.create_till_session(
        till_session_payload(
            ctx["journal"]["id"],
            ctx["cashier"]["id"],
            ctx["safe"]["id"],
            register_number=3,
            shift_start_at="2026-08-03T16:59:00Z",
            shift_end_at="2026-08-03T21:00:00Z",
            starting_bank_cents=20000,
        ),
        manager_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_CASHIER_SHIFT_OVERLAP.value)

    sessions, _meta = validate_paginated(
        api.list_till_sessions(
            manager_headers, params={"cashier_id": ctx["cashier"]["id"], "limit": 100}
        )
    )
    assert len(sessions) == 2, f"expected exactly 2 sessions, got {len(sessions)}"

    journal = read_journal(ctx["journal"]["id"])
    assert journal["session_count"] == 2, (
        f"expected 2, got {journal['session_count']}"
    )
    safe = read_safe(ctx["safe"]["id"])
    assert safe["balance_cents"] == 460000, (
        f"expected 460000, got {safe['balance_cents']}"
    )


def _setup_scheduled_and_sealed_deposits():
    """Deposit D1 SCHEDULED for 10:00Z-10:30Z and deposit D2 SEALED but unbooked.

    The store's pickup_buffer_minutes is 30, so D1 occupies 09:30Z-11:00Z once
    both sides of its window are expanded.
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(
        store_code="S-1016",
        name="Store 1016",
        region_code="SOUTH",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
        pickup_buffer_minutes=30,
        max_daily_pickups=5,
    )
    safe = create_safe(
        store["id"], safe_code="SAFE-A", safe_type="MANUAL", opening_balance_cents=500000
    )
    journal = create_sales_journal(store["id"], "2026-08-03")

    unlock_safe(
        safe["id"],
        "2026-08-03T08:00:00Z",
        delay_minutes=5,
        requester_user_id=CLERK_1,
        opener_user_id=CLERK_2,
    )
    deposit_1 = prepare_and_seal_deposit(
        safe["id"],
        journal["id"],
        lines((2000, 5)),
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
        sealer_user_id=CLERK_2,
        seal_number="SEAL-D1",
    )
    schedule_pickup(
        deposit_1["id"],
        "2026-08-03T10:00:00Z",
        "2026-08-03T10:30:00Z",
        carrier_reference="CR-D1",
        user_id=CLERK_1,
    )

    unlock_safe(
        safe["id"],
        "2026-08-03T08:05:00Z",
        delay_minutes=5,
        requester_user_id=CLERK_1,
        opener_user_id=CLERK_2,
    )
    deposit_2 = prepare_and_seal_deposit(
        safe["id"],
        journal["id"],
        lines((2000, 7)),
        business_date="2026-08-03",
        preparer_user_id=CLERK_1,
        sealer_user_id=CLERK_2,
        seal_number="SEAL-D2",
    )
    return {
        "store": store,
        "safe": safe,
        "journal": journal,
        "deposit_1": deposit_1,
        "deposit_2": deposit_2,
    }


def test_touching_pickup_window_conflicts_after_buffer_expansion(api, clerk_headers):
    """PRD §3.6: "First, the requested window, expanded by the store's `pickup_buffer_minutes` on **both** sides, must not intersect the identically expanded window of any other deposit of the same store that is `SCHEDULED` or `IN_TRANSIT`; these intervals are treated as closed, so two windows that merely touch after expansion **do** conflict, and the answer is `ERR_PICKUP_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pickup_window_buffer_expansion_makes_touching_windows_conflict
    """
    ctx = _setup_scheduled_and_sealed_deposits()
    conflicting = api.schedule_pickup(
        ctx["deposit_2"]["id"],
        {
            "pickup_window_start": "2026-08-03T11:00:00Z",
            "pickup_window_end": "2026-08-03T11:30:00Z",
            "carrier_reference": "CR-D2",
        },
        clerk_headers,
    )
    validate_error(conflicting, ApiErrorId.ERR_PICKUP_WINDOW_CONFLICT.value)

    deposit_2 = read_deposit(ctx["deposit_2"]["id"])
    assert deposit_2["status"] == "SEALED", (
        f"expected SEALED, got {deposit_2['status']}"
    )
    assert deposit_2["pickup_window_start"] is None, (
        f"expected null pickup_window_start, got {deposit_2['pickup_window_start']}"
    )


def test_pickup_window_one_minute_clear_of_the_buffer_is_accepted(api, clerk_headers):
    """PRD §3.6: "A successful booking stores the two window fields and moves the deposit from `SEALED` to `SCHEDULED`."

    PRD §3.6: "First, the requested window, expanded by the store's `pickup_buffer_minutes` on **both** sides, must not intersect the identically expanded window of any other deposit of the same store that is `SCHEDULED` or `IN_TRANSIT`; these intervals are treated as closed, so two windows that merely touch after expansion **do** conflict, and the answer is `ERR_PICKUP_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pickup_window_buffer_expansion_makes_touching_windows_conflict
    """
    ctx = _setup_scheduled_and_sealed_deposits()
    validate_error(
        api.schedule_pickup(
            ctx["deposit_2"]["id"],
            {
                "pickup_window_start": "2026-08-03T11:00:00Z",
                "pickup_window_end": "2026-08-03T11:30:00Z",
                "carrier_reference": "CR-D2",
            },
            clerk_headers,
        ),
        ApiErrorId.ERR_PICKUP_WINDOW_CONFLICT.value,
    )

    # D1 expands to 09:30Z-11:00Z. A request starting at 11:31Z expands to
    # 11:01Z-12:31Z, which clears D1's expanded end by exactly one minute, so
    # the closed intervals do not intersect and the booking is accepted.
    booked = validate_success(
        api.schedule_pickup(
            ctx["deposit_2"]["id"],
            {
                "pickup_window_start": "2026-08-03T11:31:00Z",
                "pickup_window_end": "2026-08-03T12:01:00Z",
                "carrier_reference": "CR-D2",
            },
            clerk_headers,
        )
    )
    assert booked["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {booked['status']}"
    )
    assert parse_instant(booked["pickup_window_start"]) == parse_instant(
        "2026-08-03T11:31:00Z"
    ), f"expected 2026-08-03T11:31:00Z, got {booked['pickup_window_start']}"
    assert parse_instant(booked["pickup_window_end"]) == parse_instant(
        "2026-08-03T12:01:00Z"
    ), f"expected 2026-08-03T12:01:00Z, got {booked['pickup_window_end']}"

    deposit_1 = read_deposit(ctx["deposit_1"]["id"])
    assert deposit_1["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {deposit_1['status']}"
    )
    assert parse_instant(deposit_1["pickup_window_start"]) == parse_instant(
        "2026-08-03T10:00:00Z"
    ), f"expected 2026-08-03T10:00:00Z, got {deposit_1['pickup_window_start']}"

    safe = read_safe(ctx["safe"]["id"])
    assert safe["balance_cents"] == 476000, (
        f"expected 476000, got {safe['balance_cents']}"
    )
