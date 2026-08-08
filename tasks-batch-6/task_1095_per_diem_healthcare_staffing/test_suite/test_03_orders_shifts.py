"""Staffing orders and shift posting: initial state, rate-card selection, and the
duration / window / headcount / unit-capacity guards on shift creation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_scheduler_headers,
    fixtures as fx,
)


def test_new_order_starts_open_with_zeroed_counters(api):
    """PRD 3.3: "A new order is created in `status` `OPEN` with all five of its
    counters — `shift_count`, `open_count`, `filled_count`, `completed_count`, and
    `cancelled_count` — at 0."

    Design: Corner/state_machines/new_staffing_order_starts_in_open_with_zeroed_counters
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Initial State Health")
    resp = api.create_order(
        {"facility_id": fac["id"], "specialty": "RN", "headcount": 2, "urgency": "STANDARD",
         "window_start": "2026-06-08T00:00:00Z", "window_end": "2026-06-15T00:00:00Z"},
        make_scheduler_headers(fac["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"
    assert data["shift_count"] == 0 and data["open_count"] == 0
    assert data["filled_count"] == 0 and data["completed_count"] == 0 and data["cancelled_count"] == 0
    assert data["version"] == 1


def test_rate_card_selection_picks_greatest_effective_from(api):
    """PRD 3.1: "When a shift is later posted, the system chooses among the facility's
    cards for that specialty whose `effective_from` is at or before the shift's start
    and whose `effective_to` is either absent or strictly after the shift's start; of
    those, it takes the card with the greatest `effective_from`, breaking a tie by the
    greatest `created_at`."

    Design: Corner/calculations/rate_card_selection_picks_greatest_effective_from
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Kestrel")
    fx.add_rate_card(fac["id"], base_pay_rate_cents_per_hour=7500, effective_from="2026-01-01T00:00:00Z")
    fx.add_rate_card(fac["id"], base_pay_rate_cents_per_hour=9000, effective_from="2026-06-01T00:00:00Z")
    order = fx.new_order(fac["id"])
    resp = api.create_shift(
        order["id"],
        {"scheduled_start": "2026-06-08T07:00:00Z", "scheduled_end": "2026-06-08T19:00:00Z"},
        make_scheduler_headers(fac["id"]),
    )
    data = validate_success(resp, 201)
    assert data["base_pay_rate_cents_per_hour"] == 9000
    assert data["effective_rate_cents_per_hour"] == 9000
    assert data["estimated_pay_cents"] == 103500
    cards, meta = validate_paginated(api.list_rate_cards(fac["id"], make_scheduler_headers(fac["id"])))
    assert meta["total_count"] == 2


def test_shift_without_matching_rate_card_returns_rate_card_not_found(api):
    """PRD 3.1: "If no card qualifies, shift posting fails with
    `ERR_RATE_CARD_NOT_FOUND`."

    Design: Corner/calculations/shift_creation_without_matching_rate_card_returns_rate_card_not_found
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Larkspur")
    fx.add_rate_card(fac["id"], specialty="LPN", base_pay_rate_cents_per_hour=5000)
    order = fx.new_order(fac["id"], specialty="RN")
    resp = api.create_shift(
        order["id"],
        {"scheduled_start": "2026-06-08T07:00:00Z", "scheduled_end": "2026-06-08T19:00:00Z"},
        make_scheduler_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RATE_CARD_NOT_FOUND.value, 422)
    order_after = validate_success(api.get_order(order["id"], make_scheduler_headers(fac["id"])), 200)
    assert order_after["shift_count"] == 0
    shifts, meta = validate_paginated(api.list_order_shifts(order["id"], make_scheduler_headers(fac["id"])))
    assert meta["total_count"] == 0


def test_shift_duration_below_minimum_returns_error(api):
    """PRD 3.3: "The shift's duration — the span from `scheduled_start` to
    `scheduled_end` — must be at least 4 hours and at most 16 hours, and
    `scheduled_end` must be strictly after `scheduled_start`; a violation raises
    `ERR_SHIFT_DURATION_INVALID`."

    Design: Corner/validations/shift_duration_below_minimum_returns_duration_invalid
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Sable")
    fx.add_rate_card(fac["id"])
    order = fx.new_order(fac["id"], headcount=2)
    resp = api.create_shift(
        order["id"],
        {"scheduled_start": "2026-06-08T07:00:00Z", "scheduled_end": "2026-06-08T10:00:00Z"},
        make_scheduler_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_DURATION_INVALID.value, 422)
    order_after = validate_success(api.get_order(order["id"], make_scheduler_headers(fac["id"])), 200)
    assert order_after["shift_count"] == 0


def test_shift_outside_order_window_returns_error(api):
    """PRD 3.3: "The shift must sit inside the order's window, meaning
    `scheduled_start` is at or after `window_start` and `scheduled_end` is at or
    before `window_end`; otherwise `ERR_SHIFT_OUTSIDE_ORDER_WINDOW`."

    Design: Corner/validations/shift_outside_order_window_returns_error
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Thistle")
    fx.add_rate_card(fac["id"])
    order = fx.new_order(fac["id"], headcount=2)
    resp = api.create_shift(
        order["id"],
        {"scheduled_start": "2026-06-16T07:00:00Z", "scheduled_end": "2026-06-16T19:00:00Z"},
        make_scheduler_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OUTSIDE_ORDER_WINDOW.value, 422)
    order_after = validate_success(api.get_order(order["id"], make_scheduler_headers(fac["id"])), 200)
    assert order_after["shift_count"] == 0


def test_headcount_exceeded_on_second_shift_returns_error(api):
    """PRD 3.3: "Finally, the order's `shift_count` excluding cancelled shifts, plus
    the shift being created, must not exceed the order's `headcount`, or the post
    fails with `ERR_HEADCOUNT_EXCEEDED`."

    Design: Corner/validations/headcount_exceeded_on_second_shift_returns_error
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Umber", unit_capacity=2)
    fx.add_rate_card(fac["id"])
    order = fx.new_order(fac["id"], headcount=1)
    fx.add_shift(order["id"], fac["id"], scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    resp = api.create_shift(
        order["id"],
        {"scheduled_start": "2026-06-09T07:00:00Z", "scheduled_end": "2026-06-09T19:00:00Z"},
        make_scheduler_headers(fac["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_HEADCOUNT_EXCEEDED.value, 422)
    assert err["error_id"] != ApiErrorId.ERR_UNIT_CAPACITY_EXCEEDED.value
    order_after = validate_success(api.get_order(order["id"], make_scheduler_headers(fac["id"])), 200)
    assert order_after["shift_count"] == 1


# --------------------------------------------------------------------------- #
# Difficulty: facility unit capacity over closed intervals rejects a touching shift
# --------------------------------------------------------------------------- #
def _setup_unit_capacity_one():
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Stonegate", unit_capacity=1)
    fx.add_rate_card(fac["id"])
    order = fx.new_order(fac["id"], headcount=2)
    fx.add_shift(order["id"], fac["id"], scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    return fac["id"], order["id"]


def test_unit_capacity_rejects_touching_shift_with_capacity_error(api):
    """PRD 3.3: "A unit-capacity check then counts, including the shift being created,
    how many of the facility's shifts in `OPEN`, `ASSIGNED`, or `COMPLETED` status
    have a closed interval `[scheduled_start, scheduled_end]` that intersects the new
    shift's closed interval; if that count exceeds the facility's `unit_capacity`, it
    fails with `ERR_UNIT_CAPACITY_EXCEEDED`."
    PRD 3.3: "Note that under this capacity rule, touching endpoints — where one shift
    ends exactly when another begins — do count as intersecting."

    Design: Difficulty/resource_temporal_overlap/facility_unit_closed_interval_aggregate_capacity_rejects_touching_shift
    """
    fac_id, order_id = _setup_unit_capacity_one()
    resp = api.create_shift(
        order_id,
        {"scheduled_start": "2026-06-08T19:00:00Z", "scheduled_end": "2026-06-08T23:00:00Z"},
        make_scheduler_headers(fac_id),
    )
    err = validate_error(resp, ApiErrorId.ERR_UNIT_CAPACITY_EXCEEDED.value, 409)
    assert err["error_id"] != ApiErrorId.ERR_HEADCOUNT_EXCEEDED.value


def test_unit_capacity_touching_shift_creates_nothing(api):
    """PRD 3.3: "A unit-capacity check then counts, including the shift being created,
    how many of the facility's shifts in `OPEN`, `ASSIGNED`, or `COMPLETED` status
    have a closed interval `[scheduled_start, scheduled_end]` that intersects the new
    shift's closed interval; if that count exceeds the facility's `unit_capacity`, it
    fails with `ERR_UNIT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/facility_unit_closed_interval_aggregate_capacity_rejects_touching_shift
    """
    fac_id, order_id = _setup_unit_capacity_one()
    resp = api.create_shift(
        order_id,
        {"scheduled_start": "2026-06-08T19:00:00Z", "scheduled_end": "2026-06-08T23:00:00Z"},
        make_scheduler_headers(fac_id),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_CAPACITY_EXCEEDED.value, 409)
    order_after = validate_success(api.get_order(order_id, make_scheduler_headers(fac_id)), 200)
    assert order_after["shift_count"] == 1 and order_after["open_count"] == 1
    shifts, meta = validate_paginated(api.list_order_shifts(order_id, make_scheduler_headers(fac_id)))
    assert meta["total_count"] == 1
