"""Resource temporal overlap: the animal's buffered half-open rest window and
the handler's strict-overlap + 480-minute aggregate daily capacity
(PRD §3.2, §3.3, §3.4).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    fixtures as fx,
)


# =====================================================================
# Difficulty/resource_temporal_overlap/animal_buffered_window_conflict
# =====================================================================
def _setup_confirmed_morning_goat():
    """Goat (default 4h rest buffer) CONFIRMED on booking A
    2026-06-06 10:00-12:00: buffered occupation [06:00, 16:00)."""
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"])
    goat = fx.create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000)
    booking_a = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-06T10:00:00Z", end_time="2026-06-06T12:00:00Z",
        guest_count=10, child_guest_count=0, planned_handwash_stations=1,
    )
    ba_a = fx.attach_animal(booking_a["id"], goat["id"])
    fx.confirm_booking_animal(booking_a["id"], ba_a["id"])
    return customer, venue, goat, booking_a


def test_buffered_rest_window_overlap_rejected(api):
    """PRD §3.4: "The new booking's buffered interval conflicts with an
    existing one when the existing interval opens before the new interval
    closes and the new interval opens before the existing interval closes;
    buffered endpoints that merely touch do not conflict. A collision is
    rejected with `ERR_ANIMAL_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/animal_buffered_window_conflict
    """
    customer, venue, goat, _ = _setup_confirmed_morning_goat()
    # B 15:00-17:00 -> buffered [11:00, 21:00): opens before A's buffered end
    # 16:00 and closes after A's buffered open 06:00 -> intersection.
    booking_b = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-06T15:00:00Z", end_time="2026-06-06T17:00:00Z",
        guest_count=10, child_guest_count=0, planned_handwash_stations=1,
    )
    ba_b = fx.attach_animal(booking_b["id"], goat["id"])
    resp = api.confirm_booking_animal(booking_b["id"], ba_b["id"], fx.COORD)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_SCHEDULE_CONFLICT)

    attachments = fx.list_booking_animals(booking_b["id"])
    ba_after = [a for a in attachments if a["id"] == ba_b["id"]][0]
    assert ba_after["status"] == "PROPOSED", ba_after["status"]


def test_buffered_endpoints_touching_do_not_conflict(api):
    """PRD §3.4: "buffered endpoints that merely touch do not conflict."
    PRD §3.2: "An animal's `rest_buffer_hours` defaults to 4 when not
    supplied: that many hours are blocked before and after each confirmed
    event window for that animal."

    Design: Difficulty/resource_temporal_overlap/animal_buffered_window_conflict
    """
    customer, venue, goat, _ = _setup_confirmed_morning_goat()
    # C 20:00-22:00 -> buffered [16:00, ...): opens exactly at A's buffered
    # end 16:00 — touching endpoints, so no conflict.
    booking_c = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-06T20:00:00Z", end_time="2026-06-06T22:00:00Z",
        guest_count=10, child_guest_count=0, planned_handwash_stations=1,
    )
    ba_c = fx.attach_animal(booking_c["id"], goat["id"])
    confirmed = validate_success(
        api.confirm_booking_animal(booking_c["id"], ba_c["id"], fx.COORD))
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]


# =====================================================================
# Difficulty/resource_temporal_overlap/handler_daily_aggregate_capacity
# =====================================================================
def _setup_handler_with_three_bookings():
    """Handler Hank plus three non-overlapping bookings on 2026-06-20:
    A 09:00-13:00 (240min), B 14:00-18:00 (240min), C 18:30-19:30 (60min)."""
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"])
    handler = fx.create_handler("Hank", ["FIRST_AID"])

    def mk(start, end):
        return fx.create_booking(
            customer["id"], venue["id"], start_time=start, end_time=end,
            guest_count=10, child_guest_count=0, planned_handwash_stations=1,
        )

    return (
        handler,
        mk("2026-06-20T09:00:00Z", "2026-06-20T13:00:00Z"),
        mk("2026-06-20T14:00:00Z", "2026-06-20T18:00:00Z"),
        mk("2026-06-20T18:30:00Z", "2026-06-20T19:30:00Z"),
    )


def test_exactly_480_aggregate_minutes_allowed(api):
    """PRD §3.3: "**Aggregate capacity:** the sum of the existing event
    durations plus the new event's duration must not exceed 480 minutes — an
    eight-hour working day. Exactly 480 minutes in total is allowed; 481 is
    not."
    PRD §3.3: "Windows that merely touch at an endpoint (one ends exactly when
    the other begins) are allowed."

    Design: Difficulty/resource_temporal_overlap/handler_daily_aggregate_capacity
    """
    handler, bk_a, bk_b, _ = _setup_handler_with_three_bookings()
    fx.assign_handler(bk_a["id"], handler["id"], "LEAD")  # 240 min
    fx.assign_handler(bk_b["id"], handler["id"], "LEAD")  # 240 min, no overlap
    # 240 + 240 = 480 exactly: the <= boundary admits it.
    assert fx.get_handler(handler["id"])["scheduled_minutes_total"] == 480


def test_481st_minute_rejected_as_overbooked(api):
    """PRD §3.3: "Two capacity guards protect the handler's day, and a
    violation of either is rejected with `ERR_HANDLER_OVERBOOKED` (HTTP 409)."
    PRD §3.3: "**Aggregate capacity:** the sum of the existing event
    durations plus the new event's duration must not exceed 480 minutes — an
    eight-hour working day. Exactly 480 minutes in total is allowed; 481 is
    not."

    Design: Difficulty/resource_temporal_overlap/handler_daily_aggregate_capacity
    """
    handler, bk_a, bk_b, bk_c = _setup_handler_with_three_bookings()
    fx.assign_handler(bk_a["id"], handler["id"], "LEAD")
    fx.assign_handler(bk_b["id"], handler["id"], "LEAD")
    resp = api.create_staff_assignment(
        bk_c["id"], {"handler_id": handler["id"], "role": "LEAD"}, fx.COORD)
    # 480 + 60 = 540 > 480 daily capacity
    validate_error(resp, ApiErrorId.ERR_HANDLER_OVERBOOKED)
    assert fx.get_handler(handler["id"])["scheduled_minutes_total"] == 480
