"""Ripening-room scheduling: overlap buffers, ethylene safety, lifecycle, expiry
(PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    certify_inspection,
    create_accepted_lot,
    create_booking,
    create_commodity,
    create_ordered_lot,
    create_room,
    create_shipper,
    file_inspection,
    get_lot,
    get_success_data,
    post_daily_price,
    receive_lot,
    run_day_close,
    set_clock,
    setup_accepted_lot,
    setup_market_day,
    validate_error,
    validate_success,
)
from test_helpers import RECEIVER_HEADERS

BANANA = {"code": "BAN", "name": "Banana", "ethylene_class": "PRODUCER",
          "temp_min_f": 56, "temp_max_f": 62}


def _setup_banana_room():
    """BAN commodity (band 56-62F) + ACCEPTED lot + one ethylene-capable room."""
    base = setup_market_day(commodity_overrides=dict(BANANA),
                            low_price=5.00, high_price=9.00)
    lot = create_accepted_lot(base["shipper"]["id"], base["commodity"]["id"],
                              defect_pct=0, quantity_units=50,
                              shipper_unit_price=7.00)
    room = create_room(name="R1", capacity_pallets=50, ethylene_capable=True)
    base["lot"] = lot
    base["room"] = room
    return base


def _setup_two_commodities():
    """TOM (PRODUCER) and LET (SENSITIVE) accepted lots on one shipper."""
    set_clock("2026-05-01T08:00:00Z")
    com1 = create_commodity(code="TOM", name="Tomato", ethylene_class="PRODUCER",
                            temp_min_f=45, temp_max_f=55)
    com2 = create_commodity(code="LET", name="Lettuce", ethylene_class="SENSITIVE",
                            temp_min_f=32, temp_max_f=36)
    shipper = create_shipper()
    post_daily_price(com1["id"], market_date="2026-05-01", low_price=8.00,
                     high_price=12.00)
    post_daily_price(com2["id"], market_date="2026-05-01", low_price=1.00,
                     high_price=3.00)
    lot1 = create_accepted_lot(shipper["id"], com1["id"], defect_pct=0,
                               quantity_units=50, shipper_unit_price=10.00)
    lot2 = create_accepted_lot(shipper["id"], com2["id"], defect_pct=0,
                               quantity_units=50, shipper_unit_price=2.00)
    room = create_room(name="R1", capacity_pallets=50, ethylene_capable=True)
    return {"com1": com1, "com2": com2, "shipper": shipper, "lot1": lot1,
            "lot2": lot2, "room": room}


# --- Ethylene conflict beats room overlap (priority pair) --------------------

def test_sensitive_lot_against_ethylene_booking_returns_ethylene_conflict(api):
    """PRD §3.5: "Symmetrically, if the new booking's lot is `SENSITIVE` and its
    interval overlaps an active booking with `ethylene_enabled` true, the create is
    likewise rejected with `ERR_ETHYLENE_CONFLICT`."
    PRD §2.8: "cold-chain and ethylene safety (`ERR_COLD_CHAIN_VIOLATION`,
    `ERR_ETHYLENE_CONFLICT`); temporal rules (`ERR_CUTOFF_PASSED`, `ERR_ROOM_OVERLAP`,
    `ERR_WINDOW_OVERLAP`)"

    Design: Difficulty/priority_pair_validation_conflict/ethylene_conflict_beats_room_overlap
    """
    env = _setup_two_commodities()
    create_booking(env["room"]["id"], env["lot1"]["id"],
                   start_time="2026-05-01T10:00:00Z", end_time="2026-05-01T14:00:00Z",
                   pallet_count=5, ethylene_enabled=True)
    # 12:00-16:00 overlaps B1's uninflated [10:00,14:00) AND its inflated
    # [08:00,16:00): both rules fail; safety must win over temporal.
    resp = api.create_ripening_booking(
        {"room_id": env["room"]["id"], "purchase_lot_id": env["lot2"]["id"],
         "pallet_count": 5, "start_time": "2026-05-01T12:00:00Z",
         "end_time": "2026-05-01T16:00:00Z", "ethylene_enabled": False,
         "target_stage": "STAGE_2"}, RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_ETHYLENE_CONFLICT)


def test_rejected_conflicting_booking_leaves_room_schedule_unchanged(api):
    """PRD §2.8: "When more than one validation could reject a request, the server
    evaluates checks in a fixed priority order and surfaces the first failure."
    PRD §3.5: "if the new booking's lot is `SENSITIVE` and its interval overlaps an
    active booking with `ethylene_enabled` true, the create is likewise rejected with
    `ERR_ETHYLENE_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/ethylene_conflict_beats_room_overlap
    """
    env = _setup_two_commodities()
    first = create_booking(env["room"]["id"], env["lot1"]["id"],
                           start_time="2026-05-01T10:00:00Z",
                           end_time="2026-05-01T14:00:00Z", pallet_count=5,
                           ethylene_enabled=True)
    resp = api.create_ripening_booking(
        {"room_id": env["room"]["id"], "purchase_lot_id": env["lot2"]["id"],
         "pallet_count": 5, "start_time": "2026-05-01T12:00:00Z",
         "end_time": "2026-05-01T16:00:00Z", "ethylene_enabled": False,
         "target_stage": "STAGE_2"}, RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_ETHYLENE_CONFLICT)
    bookings = get_success_data(
        api_client.list_room_bookings(env["room"]["id"], RECEIVER_HEADERS))
    assert len(bookings) == 1
    assert bookings[0]["id"] == first["id"], "the rejected create must not persist"


# --- Booking start gated on lot ACCEPTED (cross-entity state) -----------------

def _setup_inspected_lot_with_booking():
    """Lot RECEIVED with a SUBMITTED inspection (lot INSPECTED, never certified);
    booking 10:00-12:00 SCHEDULED; clock inside the window at 10:30."""
    base = setup_market_day(commodity_overrides=dict(BANANA),
                            low_price=5.00, high_price=9.00)
    lot = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                             quantity_units=50, shipper_unit_price=7.00)
    receive_lot(lot["id"])
    inspection = file_inspection(lot["id"], defect_pct=0, result="PASS")
    room = create_room(name="R1", capacity_pallets=50, ethylene_capable=True)
    booking = create_booking(room["id"], lot["id"],
                             start_time="2026-05-01T10:00:00Z",
                             end_time="2026-05-01T12:00:00Z", pallet_count=4,
                             ethylene_enabled=True, target_stage="STAGE_5")
    set_clock("2026-05-01T10:30:00Z")
    return {"lot": lot, "inspection": inspection, "room": room, "booking": booking}


def test_start_booking_on_unaccepted_lot_returns_lot_not_accepted(api):
    """PRD §3.5: "Starting requires that the booking is `SCHEDULED`, that the lot is
    `ACCEPTED` (otherwise `ERR_LOT_NOT_ACCEPTED`), and that the logical clock is
    inside the half-open interval `[start_time, end_time)` — starting too early or
    too late is `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/ripening_start_requires_lot_accepted
    """
    env = _setup_inspected_lot_with_booking()
    assert get_lot(env["lot"]["id"])["status"] == "INSPECTED"
    resp = api.start_booking(env["booking"]["id"], RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_ACCEPTED)
    refreshed = get_success_data(
        api_client.list_lot_bookings(env["lot"]["id"], RECEIVER_HEADERS))
    assert refreshed[0]["status"] == "SCHEDULED", (
        "the lot-state gate fired even though the clock was inside [10:00, 12:00)")


def test_start_booking_succeeds_once_lot_accepted(api):
    """PRD §3.5: "Starting requires that the booking is `SCHEDULED`, that the lot is
    `ACCEPTED` (otherwise `ERR_LOT_NOT_ACCEPTED`), and that the logical clock is
    inside the half-open interval `[start_time, end_time)` — starting too early or
    too late is `ERR_INVALID_STATE`."
    PRD §3.4: "When the result is `PASS`, the inspection becomes `CERTIFIED` and the
    lot transitions `INSPECTED → ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/ripening_start_requires_lot_accepted
    """
    env = _setup_inspected_lot_with_booking()
    certify_inspection(env["inspection"]["id"])  # lot INSPECTED -> ACCEPTED
    assert get_lot(env["lot"]["id"])["status"] == "ACCEPTED"
    started = get_success_data(api_client.start_booking(env["booking"]["id"],
                                                        RECEIVER_HEADERS))
    assert started["status"] == "IN_PROCESS", (
        "with the same clock inside the window, clearing the lot gate lets start fire")


# --- Buffer-inflated room overlap (resource temporal overlap) -----------------

def test_booking_starting_inside_buffer_rejected(api):
    """PRD §3.5: "a new booking is rejected with `ERR_ROOM_OVERLAP` if its interval
    intersects any other active booking's buffer-inflated interval on the same room."
    PRD §3.5: "The inflation extends each active booking's interval by two hours on
    both ends — the protected interval runs from two hours before its `start_time` to
    two hours after its `end_time`, half-open at the end."

    Design: Difficulty/resource_temporal_overlap/ripening_room_buffer_inflated_overlap
    """
    env = _setup_banana_room()
    create_booking(env["room"]["id"], env["lot"]["id"],
                   start_time="2026-05-01T10:00:00Z", end_time="2026-05-01T14:00:00Z",
                   pallet_count=5)
    # 15:30 < 14:00 + 2h buffer (16:00): intersects the protected interval.
    resp = api.create_ripening_booking(
        {"room_id": env["room"]["id"], "purchase_lot_id": env["lot"]["id"],
         "pallet_count": 5, "start_time": "2026-05-01T15:30:00Z",
         "end_time": "2026-05-01T18:00:00Z", "ethylene_enabled": False,
         "target_stage": "STAGE_4"}, RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_ROOM_OVERLAP)


def test_booking_touching_inflated_boundary_allowed(api):
    """PRD §3.5: "The inflation extends each active booking's interval by two hours on
    both ends — the protected interval runs from two hours before its `start_time` to
    two hours after its `end_time`, half-open at the end. Touching at an inflated
    boundary is allowed."

    Design: Difficulty/resource_temporal_overlap/ripening_room_buffer_inflated_overlap
    """
    env = _setup_banana_room()
    create_booking(env["room"]["id"], env["lot"]["id"],
                   start_time="2026-05-01T10:00:00Z", end_time="2026-05-01T14:00:00Z",
                   pallet_count=5)
    # Protected interval ends 16:00 half-open; starting exactly 16:00 is allowed.
    resp = api.create_ripening_booking(
        {"room_id": env["room"]["id"], "purchase_lot_id": env["lot"]["id"],
         "pallet_count": 5, "start_time": "2026-05-01T16:00:00Z",
         "end_time": "2026-05-01T18:00:00Z", "ethylene_enabled": False,
         "target_stage": "STAGE_4"}, RECEIVER_HEADERS)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


# --- Booking cancel conserves room capacity (compensating invariant) ----------

def test_cancel_scheduled_booking_succeeds(api):
    """PRD §3.5: "Cancelling is allowed only from `SCHEDULED`; a cancelled booking
    leaves the active set, so its `pallet_count` no longer counts toward the
    room-capacity invariant."
    PRD §2.4: "an integer `version` that starts at 1 and increments by exactly 1 on
    every mutation of that entity, including mutations driven by system cascades"

    Design: Difficulty/compensating_invariant/booking_cancel_conserves_room_capacity
    """
    env = _setup_banana_room()
    booking = create_booking(env["room"]["id"], env["lot"]["id"], pallet_count=10)
    assert booking["status"] == "SCHEDULED"
    cancelled = get_success_data(api_client.cancel_booking(booking["id"],
                                                           RECEIVER_HEADERS))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == booking["version"] + 1


def test_identical_interval_rebookable_after_cancel(api):
    """PRD §3.5: "Cancelling is allowed only from `SCHEDULED`; a cancelled booking
    leaves the active set, so its `pallet_count` no longer counts toward the
    room-capacity invariant."

    Design: Difficulty/compensating_invariant/booking_cancel_conserves_room_capacity
    """
    env = _setup_banana_room()
    booking = create_booking(env["room"]["id"], env["lot"]["id"], pallet_count=10)
    get_success_data(api_client.cancel_booking(booking["id"], RECEIVER_HEADERS))
    rebooked = api.create_ripening_booking(
        {"room_id": env["room"]["id"], "purchase_lot_id": env["lot"]["id"],
         "pallet_count": 10, "start_time": "2026-05-02T10:00:00Z",
         "end_time": "2026-05-02T12:00:00Z", "ethylene_enabled": False,
         "target_stage": "STAGE_4"}, RECEIVER_HEADERS)
    data = validate_success(rebooked, 201)
    assert data["status"] == "SCHEDULED", (
        "the cancelled booking contributes 0 to overlap and capacity, so the "
        "identical interval is bookable again")


# --- Breadth: lot close gate, start window, complete gate, happy path, expiry --

def test_close_lot_with_scheduled_booking_returns_invalid_state(api):
    """PRD §3.4: "An `ACCEPTED` lot is closed by the `Receiver` once no ripening
    booking for the lot is still `SCHEDULED` or `IN_PROCESS`."
    PRD §3.4: "A close attempted while an active booking remains is
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_lot_with_scheduled_booking_returns_invalid_state
    """
    env = _setup_banana_room()
    create_booking(env["room"]["id"], env["lot"]["id"], pallet_count=4)
    resp = api.close_lot(env["lot"]["id"], RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_lot(env["lot"]["id"])["status"] == "ACCEPTED"


def test_booking_start_outside_window_returns_invalid_state(api):
    """PRD §3.5: "the logical clock is inside the half-open interval `[start_time,
    end_time)` — starting too early or too late is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/booking_start_outside_window_returns_invalid_state
    """
    env = _setup_banana_room()  # clock pinned 2026-05-01T08:00
    booking = create_booking(env["room"]["id"], env["lot"]["id"],
                             start_time="2026-05-01T10:00:00Z",
                             end_time="2026-05-01T12:00:00Z", pallet_count=4)
    resp = api.start_booking(booking["id"], RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    bookings = get_success_data(
        api_client.list_room_bookings(env["room"]["id"], RECEIVER_HEADERS))
    assert bookings[0]["status"] == "SCHEDULED"


def test_complete_booking_without_start_returns_invalid_state(api):
    """PRD §3.5: "Completing requires the booking be `IN_PROCESS`."
    PRD §2.8: "the target entity's own state legality (`ERR_INVALID_STATE`, including
    the specialized `ERR_INVOICE_EXISTS` and `ERR_INSPECTION_OPEN` variants where they
    apply)"

    Design: Corner/state_machines/complete_booking_without_start_returns_invalid_state
    """
    env = _setup_banana_room()
    booking = create_booking(env["room"]["id"], env["lot"]["id"], pallet_count=4)
    resp = api.complete_booking(booking["id"], RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    bookings = get_success_data(
        api_client.list_room_bookings(env["room"]["id"], RECEIVER_HEADERS))
    assert bookings[0]["status"] == "SCHEDULED", "no state jump over IN_PROCESS"


def test_booking_start_and_complete_happy_path(api):
    """PRD §3.5: "A booking's life cycle runs `SCHEDULED → IN_PROCESS → COMPLETED`."
    PRD §3.5: "Each of these transitions increments the booking's `version`."

    Design: Corner/state_machines/booking_start_and_complete_happy_path
    """
    env = _setup_banana_room()
    booking = create_booking(env["room"]["id"], env["lot"]["id"],
                             start_time="2026-05-01T10:00:00Z",
                             end_time="2026-05-01T12:00:00Z", pallet_count=4)
    set_clock("2026-05-01T10:30:00Z")
    started = get_success_data(api_client.start_booking(booking["id"], RECEIVER_HEADERS))
    assert started["status"] == "IN_PROCESS"
    assert started["version"] == booking["version"] + 1
    completed = get_success_data(api_client.complete_booking(booking["id"],
                                                             RECEIVER_HEADERS))
    assert completed["status"] == "COMPLETED"
    assert completed["version"] == booking["version"] + 2


def test_day_close_expires_overdue_scheduled_booking(api):
    """PRD §3.7: "Third, every `SCHEDULED` ripening booking whose `end_time` is
    strictly earlier than the clock becomes `EXPIRED`."
    PRD §3.7: "returning the counts of `invoices_marked_past_due`,
    `invoices_trust_claimed`, and `bookings_expired`"

    Design: Corner/endpoints/day_close_expires_overdue_scheduled_booking
    """
    env = _setup_banana_room()
    booking = create_booking(env["room"]["id"], env["lot"]["id"],
                             start_time="2026-05-01T10:00:00Z",
                             end_time="2026-05-01T12:00:00Z", pallet_count=4)
    set_clock("2026-05-02T09:00:00Z")
    summary = run_day_close()
    assert summary["bookings_expired"] == 1
    bookings = get_success_data(
        api_client.list_room_bookings(env["room"]["id"], RECEIVER_HEADERS))
    by_id = {row["id"]: row for row in bookings}
    assert by_id[booking["id"]]["status"] == "EXPIRED"
