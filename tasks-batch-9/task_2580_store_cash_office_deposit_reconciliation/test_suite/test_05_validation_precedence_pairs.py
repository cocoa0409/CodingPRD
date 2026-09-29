"""Cash-office precedence pairs: physical control outranks arithmetic, and segregation of duties outranks the time-delay clock."""

from test_helpers import (
    ApiErrorId,
    CLERK_1,
    CLERK_2,
    arm_open_request,
    create_safe,
    create_sales_journal,
    create_store,
    make_clerk_headers,
    parse_instant,
    read_safe,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

BUSINESS_DATE = "2026-08-03"


def _same_instant(actual, expected) -> bool:
    """Compare two ISO 8601 UTC instants, tolerating the fractional-digit form."""
    return actual is not None and parse_instant(actual) == parse_instant(expected)


# ------------------------------------------------------------------ recipe A


def _setup_locked_safe_over_balance():
    """Store S-1009 with a MANUAL safe holding only 5000 cents, still LOCKED.

    Returns (store, safe, journal). The safe is never armed, so its open_state
    is LOCKED while a 200000-cent bag is far beyond its balance_cents.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = create_store(
        store_code="S-1009",
        name="Store 1009",
        region_code="EAST",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
    )
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=5000,
    )
    journal = create_sales_journal(store["id"], BUSINESS_DATE)
    return store, safe, journal


def _oversized_deposit_payload(safe_id, journal_id, expected_safe_version):
    """A bag worth 200000 cents — a removal the 5000-cent safe cannot fund."""
    return {
        "safe_id": safe_id,
        "sales_journal_id": journal_id,
        "business_date": BUSINESS_DATE,
        "counted_lines": [{"denomination_cents": 2000, "quantity": 100}],
        "expected_safe_version": expected_safe_version,
    }


def test_locked_safe_outranks_insufficient_balance_on_deposit_prepare(api):
    """PRD §2.12: "This step sits deliberately *after* the state check, so preparing a deposit that exceeds the safe balance while the safe is still `LOCKED` returns `ERR_SAFE_NOT_UNLOCKED`, not `ERR_INSUFFICIENT_SAFE_BALANCE`: the physical-control failure outranks the arithmetic one."

    Design: Difficulty/priority_pair_validation_conflict/deposit_prepare_on_locked_safe_rejects_before_balance_floor
    """
    store, safe, journal = _setup_locked_safe_over_balance()
    assert safe["open_state"] == "LOCKED", (
        f"a newly commissioned safe starts LOCKED, got {safe['open_state']}"
    )
    assert safe["balance_cents"] == 5000, (
        f"expected balance_cents 5000, got {safe['balance_cents']}"
    )

    resp = api.create_deposit(
        _oversized_deposit_payload(safe["id"], journal["id"], safe["version"]),
        make_clerk_headers(CLERK_1),
    )

    error = validate_error(resp, ApiErrorId.ERR_SAFE_NOT_UNLOCKED.value)
    assert resp.status_code == 409, (
        f"the state failure carries HTTP 409, got {resp.status_code}"
    )
    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_SAFE_BALANCE.value, (
        "the arithmetic failure must not be reported ahead of the state failure"
    )
    assert resp.status_code != 422, (
        f"the fiscal-capacity status must not be used here, got {resp.status_code}"
    )

    after = read_safe(safe["id"])
    assert after["balance_cents"] == 5000, (
        f"a rejected preparation moves no cash: expected 5000, got {after['balance_cents']}"
    )
    deposits, meta = validate_paginated(
        api.list_deposits(make_clerk_headers(CLERK_1), params={"safe_id": safe["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a rejected preparation creates no deposit, got {meta['total_count']}"
    )
    assert deposits == [], f"expected no deposits, got {deposits}"


def test_insufficient_balance_fires_once_the_safe_is_unlocked(api):
    """PRD §3.6: "The journal must belong to the safe's store, and the safe's `balance_cents` must be at least the value of the submitted `counted_lines`, failing which the answer is `ERR_INSUFFICIENT_SAFE_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/deposit_prepare_on_locked_safe_rejects_before_balance_floor
    """
    store, safe, journal = _setup_locked_safe_over_balance()

    # The same body is refused on the state rule while the safe is LOCKED.
    locked_resp = api.create_deposit(
        _oversized_deposit_payload(safe["id"], journal["id"], safe["version"]),
        make_clerk_headers(CLERK_1),
    )
    validate_error(locked_resp, ApiErrorId.ERR_SAFE_NOT_UNLOCKED.value)

    arm_open_request(safe["id"], CLERK_1, reason="Prepare deposit")
    set_clock("2026-08-03T09:05:00Z")
    validate_success(api.open_safe(safe["id"], make_clerk_headers(CLERK_2)))
    unlocked = read_safe(safe["id"])
    assert unlocked["open_state"] == "UNLOCKED", (
        f"expected UNLOCKED before the second preparation, got {unlocked['open_state']}"
    )

    resp = api.create_deposit(
        _oversized_deposit_payload(safe["id"], journal["id"], unlocked["version"]),
        make_clerk_headers(CLERK_1),
    )

    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SAFE_BALANCE.value)
    assert resp.status_code == 422, (
        f"the fiscal-capacity failure carries HTTP 422, got {resp.status_code}"
    )

    after = read_safe(safe["id"])
    assert after["balance_cents"] == 5000, (
        f"neither rejection moves cash: expected 5000, got {after['balance_cents']}"
    )
    deposits, meta = validate_paginated(
        api.list_deposits(make_clerk_headers(CLERK_1), params={"safe_id": safe["id"]})
    )
    assert meta["total_count"] == 0, (
        f"neither rejection creates a deposit, got {meta['total_count']}"
    )
    assert deposits == [], f"expected no deposits, got {deposits}"


# ------------------------------------------------------------------ recipe B


def _setup_armed_safe_inside_delay():
    """Store S-1010 with a MANUAL safe armed by U-CLERK-1 at 18:00Z.

    Returns (store, safe). The clock is left at 18:02:00Z, two minutes into the
    five-minute delay, so both the dual-control rule and the delay rule fail.
    """
    set_clock("2026-08-03T18:00:00Z")
    store = create_store(
        store_code="S-1010",
        name="Store 1010",
        region_code="EAST",
        safe_time_delay_minutes=5,
        safe_open_window_minutes=10,
        dual_control_required=True,
    )
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    arm_open_request(safe["id"], CLERK_1, reason="Cash pull")
    set_clock("2026-08-03T18:02:00Z")
    return store, read_safe(safe["id"])


def test_dual_control_outranks_time_delay_on_safe_open(api):
    """PRD §2.12: "Ninth, dual control (`ERR_DUAL_CONTROL_VIOLATION`, HTTP 403) on safe opening and deposit sealing — deliberately ahead of the time-delay check, so that a lone operator is turned away on segregation-of-duties grounds even when the delay has not yet elapsed and the response never reveals whether the delay was satisfied."

    Design: Difficulty/priority_pair_validation_conflict/safe_open_dual_control_rejects_before_time_delay_elapsed
    """
    store, safe = _setup_armed_safe_inside_delay()
    assert safe["open_state"] == "OPEN_REQUESTED", (
        f"arming moves the safe to OPEN_REQUESTED, got {safe['open_state']}"
    )
    assert safe["open_requested_by_user_id"] == CLERK_1, (
        f"expected requester {CLERK_1}, got {safe['open_requested_by_user_id']}"
    )

    resp = api.open_safe(safe["id"], make_clerk_headers(CLERK_1))

    error = validate_error(resp, ApiErrorId.ERR_DUAL_CONTROL_VIOLATION.value)
    assert resp.status_code == 403, (
        f"the segregation-of-duties failure carries HTTP 403, got {resp.status_code}"
    )
    assert error["error_id"] != ApiErrorId.ERR_TIME_DELAY_NOT_ELAPSED.value, (
        "the response must not reveal whether the delay was satisfied"
    )

    after = read_safe(safe["id"])
    assert after["open_state"] == "OPEN_REQUESTED", (
        f"a refused open leaves the request pending, got {after['open_state']}"
    )
    assert _same_instant(after["open_requested_at"], "2026-08-03T18:00:00Z"), (
        f"expected open_requested_at 2026-08-03T18:00:00Z, got {after['open_requested_at']}"
    )
    assert after["unlocked_at"] is None, (
        f"a refused open never stamps unlocked_at, got {after['unlocked_at']}"
    )


def test_time_delay_fires_for_a_second_operator_still_inside_the_delay(api):
    """PRD §2.8: "An open before the lower bound is refused with `ERR_TIME_DELAY_NOT_ELAPSED`; an open at or after the upper bound is refused with `ERR_SAFE_OPEN_REQUEST_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safe_open_dual_control_rejects_before_time_delay_elapsed
    """
    store, safe = _setup_armed_safe_inside_delay()

    # The requester is turned away on dual control, learning nothing about timing.
    lone_resp = api.open_safe(safe["id"], make_clerk_headers(CLERK_1))
    validate_error(lone_resp, ApiErrorId.ERR_DUAL_CONTROL_VIOLATION.value)

    # A second, different operator satisfies dual control, so the delay is reached.
    resp = api.open_safe(safe["id"], make_clerk_headers(CLERK_2))

    validate_error(resp, ApiErrorId.ERR_TIME_DELAY_NOT_ELAPSED.value)
    assert resp.status_code == 409, (
        f"the time-delay failure carries HTTP 409, got {resp.status_code}"
    )

    after = read_safe(safe["id"])
    assert after["open_state"] == "OPEN_REQUESTED", (
        f"after both failures the safe is still OPEN_REQUESTED, got {after['open_state']}"
    )
    assert _same_instant(after["open_requested_at"], "2026-08-03T18:00:00Z"), (
        f"expected open_requested_at 2026-08-03T18:00:00Z, got {after['open_requested_at']}"
    )
    assert after["open_requested_by_user_id"] == CLERK_1, (
        f"the pending request still names {CLERK_1}, got {after['open_requested_by_user_id']}"
    )


def test_second_operator_opens_the_safe_at_the_delay_boundary_instant(api):
    """PRD §2.8: "The open is permitted only once the clock has reached `open_requested_at` plus the store's `safe_time_delay_minutes` — the boundary instant itself is permitted — and only while the clock is strictly before `open_requested_at` plus `safe_time_delay_minutes` plus `safe_open_window_minutes`."

    Design: Difficulty/priority_pair_validation_conflict/safe_open_dual_control_rejects_before_time_delay_elapsed
    """
    store, safe = _setup_armed_safe_inside_delay()
    validate_error(
        api.open_safe(safe["id"], make_clerk_headers(CLERK_1)),
        ApiErrorId.ERR_DUAL_CONTROL_VIOLATION.value,
    )
    validate_error(
        api.open_safe(safe["id"], make_clerk_headers(CLERK_2)),
        ApiErrorId.ERR_TIME_DELAY_NOT_ELAPSED.value,
    )

    set_clock("2026-08-03T18:05:00Z")
    opened = validate_success(api.open_safe(safe["id"], make_clerk_headers(CLERK_2)))

    assert opened["open_state"] == "UNLOCKED", (
        f"the boundary instant is permitted: expected UNLOCKED, got {opened['open_state']}"
    )
    assert _same_instant(opened["unlocked_at"], "2026-08-03T18:05:00Z"), (
        f"expected unlocked_at 2026-08-03T18:05:00Z, got {opened['unlocked_at']}"
    )
    assert _same_instant(opened["open_requested_at"], "2026-08-03T18:00:00Z"), (
        "open_requested_at remains populated for audit, got "
        f"{opened['open_requested_at']}"
    )
