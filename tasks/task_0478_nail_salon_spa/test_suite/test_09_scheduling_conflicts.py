"""Confirmation-time scheduling guards: the zero-buffer technician double-book
rule (half-open intervals) and the 10-minute station turnover-buffer rule."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    make_station, make_menu_item, make_technician, make_client,
    book_appointment, confirm, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: technician double-book — zero buffer, half-open intervals
# ---------------------------------------------------------------------------
def test_technician_overlap_rejected(api):
    """PRD §3.7: "the confirmation enforces a **technician double-book guard**: the
    appointment's half-open window from `start_at` to `end_at` must not overlap the
    window of any other appointment on the same `technician_id` that is in
    `CONFIRMED`, `CHECKED_IN`, or `IN_SERVICE`. Any such overlap with zero buffer is
    rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technician_double_book_touching_intervals_allowed
    """
    set_clock("2026-04-15T12:00:00Z")
    st1 = make_station(requires_autoclave=False)
    st2 = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4000, duration_minutes=60,
                          requires_sterile_station=False)
    tech = make_technician(st1["id"])
    client = make_client()
    a1 = book_appointment(client["id"], tech["id"], st1["id"], menu["id"],
                          origin="APPOINTMENT", start_at="2026-04-15T13:00:00Z")
    confirm(a1["id"])   # 13:00-14:00 on the tech
    a_overlap = book_appointment(client["id"], tech["id"], st2["id"], menu["id"],
                                 origin="APPOINTMENT", start_at="2026-04-15T13:59:00Z")

    res = api.confirm_appointment(a_overlap["id"], FRONT_DESK)
    validate_error(res, "ERR_TECHNICIAN_DOUBLE_BOOKED")


def test_technician_touching_window_allowed(api):
    """PRD §3.7: "the appointment's half-open window from `start_at` to `end_at`
    must not overlap the window of any other appointment on the same
    `technician_id`".
    PRD §3.6: the booking window is "a half-open interval that includes the start
    instant and excludes the end instant."

    Design: Difficulty/resource_temporal_overlap/technician_double_book_touching_intervals_allowed
    """
    set_clock("2026-04-15T12:00:00Z")
    st1 = make_station(requires_autoclave=False)
    st2 = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4000, duration_minutes=60,
                          requires_sterile_station=False)
    tech = make_technician(st1["id"])
    client = make_client()
    a1 = book_appointment(client["id"], tech["id"], st1["id"], menu["id"],
                          origin="APPOINTMENT", start_at="2026-04-15T13:00:00Z")
    confirm(a1["id"])   # 13:00-14:00 on the tech
    a_touch = book_appointment(client["id"], tech["id"], st2["id"], menu["id"],
                               origin="APPOINTMENT", start_at="2026-04-15T14:00:00Z")

    confirmed = validate_success(api.confirm_appointment(a_touch["id"], FRONT_DESK))
    assert confirmed["booking_status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Difficulty: station turnover buffer — 10 minutes, inclusive boundary
# ---------------------------------------------------------------------------
def test_station_within_turnover_buffer_rejected(api):
    """PRD §3.7: "the confirmation enforces a **station turnover-buffer guard**:
    for every other appointment on the same `station_id` in `CONFIRMED`,
    `CHECKED_IN`, or `IN_SERVICE`, the two windows must be separated by a gap of at
    least the 10-minute station turnover allowance."
    PRD §3.7: "A new `start_at` that falls strictly less than the other's `end_at`
    plus 10 minutes — while not lying entirely before that other window — conflicts
    and is rejected with `ERR_STATION_TURNOVER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/station_turnover_buffer_blocks_adjacent
    """
    set_clock("2026-04-16T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(category="PEDICURE", base_price_cents=5000,
                          duration_minutes=60, requires_sterile_station=False)
    t1 = make_technician(station["id"])
    t2 = make_technician(station["id"])
    client = make_client()
    a1 = book_appointment(client["id"], t1["id"], station["id"], menu["id"],
                          origin="APPOINTMENT", start_at="2026-04-16T13:00:00Z")
    confirm(a1["id"])   # 13:00-14:00 on the station
    # Second on the SAME station, different tech, starts at 14:00 — only a 0-min
    # gap from the prior end_at, inside the 10-minute buffer.
    a_buf = book_appointment(client["id"], t2["id"], station["id"], menu["id"],
                             origin="APPOINTMENT", start_at="2026-04-16T14:00:00Z")

    res = api.confirm_appointment(a_buf["id"], FRONT_DESK)
    validate_error(res, "ERR_STATION_TURNOVER_CONFLICT")


def test_station_exact_ten_minute_gap_allowed(api):
    """PRD §3.7: "the new appointment satisfies the guard only if its `start_at` is
    at or after the other appointment's `end_at` plus 10 minutes, or its own
    `end_at` plus 10 minutes is at or before the other's `start_at`."
    PRD §3.7: "The boundary is inclusive: a gap of exactly 10 minutes is allowed."

    Design: Difficulty/resource_temporal_overlap/station_turnover_buffer_blocks_adjacent
    """
    set_clock("2026-04-16T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(category="PEDICURE", base_price_cents=5000,
                          duration_minutes=60, requires_sterile_station=False)
    t1 = make_technician(station["id"])
    t2 = make_technician(station["id"])
    client = make_client()
    a1 = book_appointment(client["id"], t1["id"], station["id"], menu["id"],
                          origin="APPOINTMENT", start_at="2026-04-16T13:00:00Z")
    confirm(a1["id"])   # 13:00-14:00 on the station
    # Start at 14:10 — exactly a 10-minute gap from the prior end_at (14:00).
    a_ok = book_appointment(client["id"], t2["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-04-16T14:10:00Z")

    confirmed = validate_success(api.confirm_appointment(a_ok["id"], FRONT_DESK))
    assert confirmed["booking_status"] == "CONFIRMED"
