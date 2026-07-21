"""Oversized delivery bookings: day-capacity, half-open assembly-window overlap,
the day-full-over-crew validation ordering, the seasonal-reset confirm gate,
past-date, crew/store mismatch, and the complete precondition."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, set_clock,
    new_store, new_crew, new_order, new_booking, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DELIVERY = TEST_USERS["delivery_headers"]


# ─── delivery_day_capacity_aggregate_count (queue A) ───

def _store_slots1_with_one_booking():
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store TO1", oversized_slots_per_day=1)
    o1 = new_order(store["id"], "OVERSIZED_DELIVERY")
    o2 = new_order(store["id"], "OVERSIZED_DELIVERY")
    b1 = new_booking(o1["id"], store["id"], "2026-07-10")
    return store, o2, b1


def test_second_same_day_booking_over_capacity_rejected():
    """PRD §3.6: "a store accepts only a finite number of oversized bookings per
    calendar day: the count of bookings at the same store on the same
    `delivery_date` whose status is `SCHEDULED` or `CONFIRMED` must remain below the
    store's `oversized_slots_per_day`, and a booking that would meet or exceed that
    ceiling is rejected with `ERR_DELIVERY_DAY_FULL`."

    Design: Difficulty/resource_temporal_overlap/delivery_day_capacity_aggregate_count
    """
    store, o2, _ = _store_slots1_with_one_booking()
    resp = api_client.create_delivery_booking(
        {"order_id": o2["id"], "store_id": store["id"], "delivery_date": "2026-07-10"}, DELIVERY)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_DAY_FULL.value)


def test_first_booking_below_capacity_allowed():
    """PRD §3.6: "the count of bookings at the same store on the same
    `delivery_date` whose status is `SCHEDULED` or `CONFIRMED` must remain below the
    store's `oversized_slots_per_day`, and a booking that would meet or exceed that
    ceiling is rejected with `ERR_DELIVERY_DAY_FULL`."

    Design: Difficulty/resource_temporal_overlap/delivery_day_capacity_aggregate_count
    """
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store TO1b", oversized_slots_per_day=1)
    o1 = new_order(store["id"], "OVERSIZED_DELIVERY")
    # Count is 0 < 1, so the first booking of the day is accepted.
    b1 = new_booking(o1["id"], store["id"], "2026-07-10")
    assert b1["status"] == "SCHEDULED", f"expected SCHEDULED, got {b1['status']}"


# ─── assembly_crew_halfopen_interval_overlap (queue A) ───

def _crew_holding_ten_to_twelve():
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store TO2", oversized_slots_per_day=5)
    crew = new_crew(store["id"], "Crew Alpha")
    o1 = new_order(store["id"], "OVERSIZED_DELIVERY")
    o2 = new_order(store["id"], "OVERSIZED_DELIVERY")
    new_booking(o1["id"], store["id"], "2026-07-10", needs_assembly=True, crew_id=crew["id"],
                assembly_window_start="2026-07-10T10:00:00Z",
                assembly_window_end="2026-07-10T12:00:00Z")
    return store, crew, o2


def test_overlapping_assembly_window_rejected():
    """PRD §3.6: "The requested assembly window `[assembly_window_start,
    assembly_window_end)` is treated as half-open: it conflicts with an existing
    booking on the same crew (in `SCHEDULED` or `CONFIRMED` status) when the
    requested start falls before the existing end and the existing start falls
    before the requested end."

    Design: Difficulty/resource_temporal_overlap/assembly_crew_halfopen_interval_overlap
    """
    store, crew, o2 = _crew_holding_ten_to_twelve()
    resp = api_client.create_delivery_booking(
        {"order_id": o2["id"], "store_id": store["id"], "delivery_date": "2026-07-10",
         "needs_assembly": True, "crew_id": crew["id"],
         "assembly_window_start": "2026-07-10T11:00:00Z",
         "assembly_window_end": "2026-07-10T13:00:00Z"}, DELIVERY)
    validate_error(resp, ApiErrorId.ERR_ASSEMBLY_CREW_UNAVAILABLE.value)


def test_touching_assembly_window_allowed():
    """PRD §3.6: "Two windows that merely touch at an endpoint — the requested start
    exactly equal to an existing end — do not overlap and are allowed."

    Design: Difficulty/resource_temporal_overlap/assembly_crew_halfopen_interval_overlap
    """
    store, crew, o2 = _crew_holding_ten_to_twelve()
    booking = new_booking(o2["id"], store["id"], "2026-07-10", needs_assembly=True,
                          crew_id=crew["id"],
                          assembly_window_start="2026-07-10T12:00:00Z",
                          assembly_window_end="2026-07-10T14:00:00Z")
    assert booking["status"] == "SCHEDULED", f"expected SCHEDULED, got {booking['status']}"


# ─── delivery_day_full_beats_crew_unavailable (queue A) ───

def _day_full_and_crew_overlap_attempt():
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store PC1", oversized_slots_per_day=1)
    crew = new_crew(store["id"], "Crew Alpha")
    o1 = new_order(store["id"], "OVERSIZED_DELIVERY")
    o2 = new_order(store["id"], "OVERSIZED_DELIVERY")
    new_booking(o1["id"], store["id"], "2026-07-10", needs_assembly=True, crew_id=crew["id"],
                assembly_window_start="2026-07-10T10:00:00Z",
                assembly_window_end="2026-07-10T12:00:00Z")
    return api_client.create_delivery_booking(
        {"order_id": o2["id"], "store_id": store["id"], "delivery_date": "2026-07-10",
         "needs_assembly": True, "crew_id": crew["id"],
         "assembly_window_start": "2026-07-10T11:00:00Z",
         "assembly_window_end": "2026-07-10T13:00:00Z"}, DELIVERY)


def test_day_full_reported_over_crew_conflict():
    """PRD §3.6: "Booking creation enforces three guards. First, the `delivery_date`
    may not fall before the current clock date... Second, a store accepts only a
    finite number of oversized bookings per calendar day... Third, when assembly is
    required, the chosen crew must belong to the same store as the booking..."

    Design: Difficulty/priority_pair_validation_conflict/delivery_day_full_beats_crew_unavailable
    """
    resp = _day_full_and_crew_overlap_attempt()
    validate_error(resp, ApiErrorId.ERR_DELIVERY_DAY_FULL.value)


def test_crew_unavailable_suppressed_by_day_capacity():
    """PRD §2.1: "Validation across the API follows a fixed priority order, and the
    first check that fails determines the error returned."
    PRD §2.1: "(7) temporal-window rules; and (8) resource-occupation constraints".

    Design: Difficulty/priority_pair_validation_conflict/delivery_day_full_beats_crew_unavailable
    """
    resp = _day_full_and_crew_overlap_attempt()
    actual = resp.json()["data"]["error_id"]
    assert actual == ApiErrorId.ERR_DELIVERY_DAY_FULL.value, f"day-capacity must win; got {actual}"
    assert actual != ApiErrorId.ERR_ASSEMBLY_CREW_UNAVAILABLE.value, (
        "the crew-window constraint must be suppressed by the earlier day-capacity check")


# ─── booking_confirm_requires_store_active (queue A) ───

def _scheduled_booking_then_lock():
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store CE1")
    order = new_order(store["id"], "OVERSIZED_DELIVERY")
    booking = new_booking(order["id"], store["id"], "2026-07-10")
    validate_success(api_client.lock_store(store["id"], ADMIN))
    return booking


def test_confirm_blocked_while_store_reset_locked():
    """PRD §3.6: "Confirming a booking moves it from `SCHEDULED` to `CONFIRMED`,
    which requires the booking to be `SCHEDULED` and the owning store to be
    `ACTIVE`; confirmation is blocked while the store is in seasonal reset and then
    carries `ERR_STORE_RESET_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_store_active
    """
    booking = _scheduled_booking_then_lock()
    resp = api_client.confirm_delivery_booking(booking["id"], DELIVERY)
    validate_error(resp, ApiErrorId.ERR_STORE_RESET_LOCKED.value)


def test_booking_stays_scheduled_after_blocked_confirm():
    """PRD §2.11: "While a store is `RESET_LOCKED`, two operations are blocked at
    that store: creating a new order and confirming a delivery booking. Both
    rejections carry `ERR_STORE_RESET_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_store_active
    """
    booking = _scheduled_booking_then_lock()
    api_client.confirm_delivery_booking(booking["id"], DELIVERY)
    read = validate_success(api_client.get_delivery_booking(booking["id"], DELIVERY))
    assert read["status"] == "SCHEDULED", f"expected SCHEDULED after blocked confirm, got {read['status']}"


# ─── booking_delivery_date_in_past_rejected (queue B) ───

def test_delivery_date_in_past_rejected():
    """PRD §3.6: "First, the `delivery_date` may not fall before the current clock
    date; a past date is rejected with `ERR_DELIVERY_DATE_IN_PAST`."

    Design: Corner/validations/booking_delivery_date_in_past_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store V2")
    order = new_order(store["id"], "OVERSIZED_DELIVERY")
    resp = api_client.create_delivery_booking(
        {"order_id": order["id"], "store_id": store["id"], "delivery_date": "2026-06-01"}, DELIVERY)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_DATE_IN_PAST.value)


# ─── booking_crew_from_other_store_rejected (queue B) ───

def test_crew_from_other_store_rejected():
    """PRD §3.6: "when assembly is required, the chosen crew must belong to the same
    store as the booking — otherwise `ERR_CREW_STORE_MISMATCH`".

    Design: Corner/validations/booking_crew_from_other_store_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    store_a = new_store(name="Store A", region_code="CA")
    store_b = new_store(name="Store B", region_code="NY")
    crew_b = new_crew(store_b["id"], "Crew B")
    order = new_order(store_a["id"], "OVERSIZED_DELIVERY")
    resp = api_client.create_delivery_booking(
        {"order_id": order["id"], "store_id": store_a["id"], "delivery_date": "2026-07-10",
         "needs_assembly": True, "crew_id": crew_b["id"],
         "assembly_window_start": "2026-07-10T09:00:00Z",
         "assembly_window_end": "2026-07-10T11:00:00Z"}, DELIVERY)
    validate_error(resp, ApiErrorId.ERR_CREW_STORE_MISMATCH.value)


# ─── complete_booking_from_scheduled_returns_invalid_state (queue B) ───

def test_complete_from_scheduled_is_invalid_state():
    """PRD §3.6: "Completing a booking moves it from `CONFIRMED` to `COMPLETED` and
    is permitted only once the current clock date is on or after the
    `delivery_date`."
    PRD §3.5: "A transition attempted from a state the machine does not permit is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_booking_from_scheduled_returns_invalid_state
    """
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store SM4")
    order = new_order(store["id"], "OVERSIZED_DELIVERY")
    booking = new_booking(order["id"], store["id"], "2026-07-10")
    resp = api_client.complete_delivery_booking(booking["id"], DELIVERY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
