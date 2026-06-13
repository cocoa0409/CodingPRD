"""Press booking interval validation, cleanup-buffer overlap, and buffer-edge adjacency."""
import pytest
from test_helpers import (
    api_client, get_success_data,
    validate_success, validate_error,
    create_shop, create_customer, create_product, create_press, create_order, add_line,
    setup_banner_line, book_press,
    TEST_USERS, ApiErrorId,
)

OPERATOR = TEST_USERS["production_operator_headers"]


def _banner_with_press(name, cleanup_buffer_minutes):
    """A shop with a requires_press BANNER product, a press, and two lines on the press."""
    shop = create_shop(name=name)
    cust = create_customer(shop["id"], email=f"{name.lower().replace(' ', '')}@x.com")
    prod = create_product(shop["id"], name="Vinyl Banner", category="BANNER",
                          base_unit_price_cents=5000, unit_size=2,
                          requires_proof=False, requires_press=True)
    press = create_press(shop["id"], cleanup_buffer_minutes=cleanup_buffer_minutes)
    order = create_order(shop["id"], cust["id"])
    line1 = add_line(order["id"], prod["id"], 1, cust["id"])
    line2 = add_line(order["id"], prod["id"], 1, cust["id"])
    return {"press": press, "line1": line1, "line2": line2}


# ─── Difficulty: boundary_precision (press buffer edge adjacency) ────────────
def test_press_booking_at_buffer_edge_accepted(api):
    """PRD §3.5: "a new booking whose `start_utc` lands exactly on the existing booking's
    `end_utc` plus cleanup buffer is accepted, because the occupied window is half-open at
    that extended tail."

    Design: Difficulty/boundary_precision_check/press_buffer_edge_adjacency_allowed
    """
    ctx = _banner_with_press("Press Edge Shop", 30)
    get_success_data(book_press(ctx["press"]["id"], ctx["line1"]["id"],
                                "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    # Buffer-extended end is 11:30; a booking starting exactly at 11:30 is accepted.
    booking2 = validate_success(book_press(ctx["press"]["id"], ctx["line2"]["id"],
                                           "2026-06-02T11:30:00Z", "2026-06-02T12:30:00Z"), 201)
    assert booking2["status"] == "CONFIRMED"


def test_press_booking_adjacent_zero_buffer_accepted(api):
    """PRD §3.5: "The new booking, running from its `start_utc` up to but not including its
    `end_utc`, conflicts if and only if the new booking's `start_utc` is earlier than that
    buffer-extended end of the existing booking and the existing booking's `start_utc` is
    earlier than the new booking's `end_utc`."

    Design: Difficulty/boundary_precision_check/press_buffer_edge_adjacency_allowed
    """
    ctx = _banner_with_press("Press Edge Shop 2", 0)
    get_success_data(book_press(ctx["press"]["id"], ctx["line1"]["id"],
                                "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    # Zero buffer: a booking starting exactly at the prior end (11:00) does not conflict.
    booking2 = validate_success(book_press(ctx["press"]["id"], ctx["line2"]["id"],
                                           "2026-06-02T11:00:00Z", "2026-06-02T12:00:00Z"), 201)
    assert booking2["status"] == "CONFIRMED"


# ─── Difficulty: resource_temporal_overlap (press overlap with buffer) ───────
def test_press_booking_overlap_within_buffer_rejected(api):
    """PRD §3.5: "An existing confirmed booking occupies its own interval extended at the
    tail by the press's cleanup buffer — that is, from its `start_utc` up to but not
    including its `end_utc` plus the cleanup-buffer minutes." PRD §3.5: "A conflict is
    rejected with `ERR_PRESS_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/press_booking_overlap_with_cleanup_buffer
    """
    ctx = _banner_with_press("Overlap Shop", 30)
    get_success_data(book_press(ctx["press"]["id"], ctx["line1"]["id"],
                                "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    # 11:15 falls inside [10:00, 11:30) buffer-extended window.
    res = book_press(ctx["press"]["id"], ctx["line2"]["id"],
                     "2026-06-02T11:15:00Z", "2026-06-02T12:15:00Z")
    validate_error(res, ApiErrorId.ERR_PRESS_DOUBLE_BOOKED, expected_status=409)


def test_press_booking_overlap_within_raw_interval_rejected(api):
    """PRD §3.5: "Bookings on the same press may not collide once the cleanup buffer is
    accounted for." PRD §3.5: "A conflict is rejected with `ERR_PRESS_DOUBLE_BOOKED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/press_booking_overlap_with_cleanup_buffer
    """
    ctx = _banner_with_press("Overlap Shop 2", 30)
    get_success_data(book_press(ctx["press"]["id"], ctx["line1"]["id"],
                                "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    # 10:30 is strictly inside the raw [10:00, 11:00) interval -> conflict.
    res = book_press(ctx["press"]["id"], ctx["line2"]["id"],
                     "2026-06-02T10:30:00Z", "2026-06-02T11:30:00Z")
    validate_error(res, ApiErrorId.ERR_PRESS_DOUBLE_BOOKED, expected_status=409)


# ─── Booking interval validation ─────────────────────────────────────────────
def test_press_booking_end_not_after_start_rejected(api):
    """PRD §3.5: "The booking's `end_utc` must be strictly later than its `start_utc`; an
    interval that is empty or inverted is rejected with `ERR_BOOKING_INTERVAL_INVALID`
    (HTTP 422)."

    Design: Corner/validations/press_booking_end_not_after_start_rejected
    """
    ctx = _banner_with_press("S25", 0)
    res = book_press(ctx["press"]["id"], ctx["line1"]["id"],
                     "2026-06-02T10:00:00Z", "2026-06-02T10:00:00Z")
    validate_error(res, ApiErrorId.ERR_BOOKING_INTERVAL_INVALID, expected_status=422)
