"""Slot seat accounting (jump seat vs party guest seats), capacity boundary
(OPEN->FULL flip and over-subscription), cancellation-cutoff boundary, room
turnover-buffer overlap, aggregate slot-capacity overlap, and OCC slot-version checks.

Translates difficulty queue dual_variant_calc (seat accounting),
boundary_precision_check, resource_temporal_overlap, and corner
cross_cutting_complexity_layers / errors / consistency.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park_with_clock, set_clock, create_slot, get_slot, get_slot_version,
    create_adult, create_reservation_pass, create_jump_pass, create_paid_reservation_pass,
    setup_party_prereqs, create_party_booking, hold_party_deposit, create_room, create_package,
    create_jump_pass_payload, create_party_booking_payload,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["park_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─────────────────────────────────────────────────────────────────────
# dual_variant_calc / seat_accounting_jump_seat_vs_party_guest_seats_on_slot  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_seat_accounting_one_pass_plus_six_guest_booking(api):
    """PRD §3.2: "The `seats_taken` figure is the number of jump passes against this
    slot whose `admission_status` is `RESERVED` or `CHECKED_IN` (each such pass holds
    exactly one seat regardless of how many sock pairs or add-ons it carries), plus the
    sum of `guest_count` across all party bookings against this slot whose
    `booking_status` is `DEPOSIT_HELD`, `CONFIRMED`, or `CHECKED_IN`."

    One reservation pass (1 seat) + one DEPOSIT_HELD 6-guest booking (6 seats) on a
    capacity-20 slot -> seats_taken == 7, status OPEN.

    Design: Difficulty/dual_variant_calc/seat_accounting_jump_seat_vs_party_guest_seats_on_slot
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 20, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    participant = create_adult(park["id"], full_name="Solo Jumper")
    create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                            sock_count=1)
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=6)
    hold_party_deposit(booking["id"], slot["id"])
    final_slot = get_slot(slot["id"])
    assert final_slot["seats_taken"] == 7, \
        f"1 pass + 6 guests == 7 seats, got {final_slot['seats_taken']}"
    assert final_slot["status"] == "OPEN"


def test_seat_accounting_socks_addons_do_not_change_seat_count(api):
    """PRD §3.2: "each such pass holds exactly one seat regardless of how many sock
    pairs or add-ons it carries".

    A single reservation pass with 5 socks still consumes exactly 1 seat
    (seat count is independent of sock_count), distinct from a party booking's
    per-guest seat contribution.

    Design: Difficulty/dual_variant_calc/seat_accounting_jump_seat_vs_party_guest_seats_on_slot
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=20, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Many Socks")
    create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                            sock_count=5)
    final_slot = get_slot(slot["id"])
    assert final_slot["seats_taken"] == 1, \
        f"one pass holds exactly 1 seat regardless of socks, got {final_slot['seats_taken']}"
    assert final_slot["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────
# boundary_precision_check / slot_capacity_exact_fill_flips_to_full_zero_remaining (3 tests)
# ─────────────────────────────────────────────────────────────────────
def test_capacity_one_below_stays_open(api):
    """PRD §3.2: "if `seats_taken` is greater than or equal to `jump_capacity`, the
    `status` is `FULL`; otherwise it is `OPEN`."

    Capacity-2 slot with one reservation pass: seats_taken 1 < 2 -> status OPEN.

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_fill_flips_to_full_zero_remaining
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=2, base_price_cents=2000)
    p1 = create_adult(park["id"], full_name="Fill1")
    create_reservation_pass(slot["id"], p1["id"], get_slot_version(slot["id"]))
    s = get_slot(slot["id"])
    assert s["seats_taken"] == 1
    assert s["status"] == "OPEN"


def test_capacity_exact_fill_flips_to_full(api):
    """PRD §3.2: "the slot automatically flips from `OPEN` to `FULL` at the moment
    `seats_taken` reaches `jump_capacity` exactly".

    Capacity-2 slot: the second reservation pass makes seats_taken == 2 == capacity,
    flipping status OPEN -> FULL with zero remaining.

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_fill_flips_to_full_zero_remaining
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=2, base_price_cents=2000)
    p1 = create_adult(park["id"], full_name="Fill1")
    create_reservation_pass(slot["id"], p1["id"], get_slot_version(slot["id"]))
    p2 = create_adult(park["id"], full_name="Fill2")
    create_reservation_pass(slot["id"], p2["id"], get_slot_version(slot["id"]))
    s = get_slot(slot["id"])
    assert s["seats_taken"] == 2
    assert s["status"] == "FULL"


def test_capacity_one_above_create_rejected(api):
    """PRD §3.8: "the slot's `seats_taken` plus this booking's `guest_count` does not
    exceed the slot's `jump_capacity` (else `ERR_SLOT_CAPACITY_EXCEEDED`)."
    PRD §3.2: "Once `CLOSED`, the slot admits no further seat consumption."

    A capacity-2 slot already at seats_taken 2 (FULL): the next jump-pass create is
    rejected ERR_SLOT_CAPACITY_EXCEEDED.

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_fill_flips_to_full_zero_remaining
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=2, base_price_cents=2000)
    p1 = create_adult(park["id"], full_name="Fill1")
    create_reservation_pass(slot["id"], p1["id"], get_slot_version(slot["id"]))
    p2 = create_adult(park["id"], full_name="Fill2")
    create_reservation_pass(slot["id"], p2["id"], get_slot_version(slot["id"]))
    p3 = create_adult(park["id"], full_name="Fill3")
    validate_error(
        api.create_jump_pass(
            create_jump_pass_payload(slot["id"], p3["id"], get_slot_version(slot["id"])), FD),
        ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value)


# ─────────────────────────────────────────────────────────────────────
# boundary_precision_check / cancellation_cutoff_exact_boundary_full_refund  (3 tests)
# ─────────────────────────────────────────────────────────────────────
def _setup_paid_reservation_for_cancel(clock_for_cancel):
    """Create a paid reservation pass (base 2000 + 1 sock = paid 2350), then move clock."""
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Bndry J")
    pas = create_paid_reservation_pass(slot, participant["id"])
    set_clock(clock_for_cancel)
    return pas


def test_cancel_exactly_at_cutoff_full_refund(api):
    """PRD §3.6: "If `minutes_before` is at least the park's `cancellation_cutoff_minutes`
    (the boundary is inclusive), the cancellation is within the cutoff and earns a full
    refund: the refund equals everything actually paid (`amount_paid_cents`) and
    `payment_status` becomes `REFUNDED`."

    Clock exactly 120 min before slot start (10:00 - 120m = 08:00); paid 2350
    -> full refund 2350, REFUNDED.

    Design: Difficulty/boundary_precision_check/cancellation_cutoff_exact_boundary_full_refund
    """
    pas = _setup_paid_reservation_for_cancel("2026-06-20T08:00:00Z")
    cancelled = validate_success(api.cancel_jump_pass(pas["id"], FD), 200)
    assert cancelled["amount_refunded_cents"] == 2350, \
        f"full refund at boundary == 2350, got {cancelled['amount_refunded_cents']}"
    assert cancelled["payment_status"] == "REFUNDED"


def test_cancel_just_inside_cutoff_full_refund(api):
    """PRD §3.6: "If `minutes_before` is at least the park's `cancellation_cutoff_minutes`
    (the boundary is inclusive), the cancellation is within the cutoff and earns a full
    refund: the refund equals everything actually paid (`amount_paid_cents`) and
    `payment_status` becomes `REFUNDED`."

    Clock 121 min before start (07:59): minutes_before 121 >= 120 -> full refund 2350.

    Design: Difficulty/boundary_precision_check/cancellation_cutoff_exact_boundary_full_refund
    """
    pas = _setup_paid_reservation_for_cancel("2026-06-20T07:59:00Z")
    cancelled = validate_success(api.cancel_jump_pass(pas["id"], FD), 200)
    assert cancelled["amount_refunded_cents"] == 2350
    assert cancelled["payment_status"] == "REFUNDED"


def test_cancel_one_minute_late_partial_refund(api):
    """PRD §3.6: "Otherwise the cancellation is late: the pass price is forfeited and
    only the socks-and-add-ons portion is refundable ... `payment_status` becomes
    `PARTIALLY_REFUNDED` if that refund is strictly less than `amount_paid_cents`".

    Clock 119 min before start (08:01): minutes_before 119 < 120 -> only socks 350
    refunded, PARTIALLY_REFUNDED (one minute past the inclusive boundary).

    Design: Difficulty/boundary_precision_check/cancellation_cutoff_exact_boundary_full_refund
    """
    pas = _setup_paid_reservation_for_cancel("2026-06-20T08:01:00Z")
    cancelled = validate_success(api.cancel_jump_pass(pas["id"], FD), 200)
    assert cancelled["amount_refunded_cents"] == 350, \
        f"late cancel refunds only socks 350, got {cancelled['amount_refunded_cents']}"
    assert cancelled["payment_status"] == "PARTIALLY_REFUNDED"


# ─────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / party_room_turnover_buffer_overlap_rejected  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_room_turnover_buffer_overlap_rejected(api):
    """PRD §3.8: "the room interval — the window from the slot's `starts_at` to its
    `ends_at` — does not collide with any other non-`CANCELLED` booking on the same
    room, where the room's `turnover_buffer_minutes` must separate two bookings on each
    side (else `ERR_ROOM_CONFLICT`)".

    Room buffer 30; B1 holds 10:00-12:00; B2 on the same room at 12:15-13:00 starts only
    15 min after B1 ends (< 30 buffer) -> hold-deposit rejected ERR_ROOM_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/party_room_turnover_buffer_overlap_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot1 = create_slot(park["id"], starts_at="2026-06-20T10:00:00Z",
                        ends_at="2026-06-20T12:00:00Z", jump_capacity=30, base_price_cents=2000)
    slot2 = create_slot(park["id"], starts_at="2026-06-20T12:15:00Z",
                        ends_at="2026-06-20T13:00:00Z", jump_capacity=30, base_price_cents=2000)
    room = create_room(park["id"], name="Room A", room_capacity=30, turnover_buffer_minutes=30)
    package = create_package(park["id"], per_guest_cents=1500, base_room_fee_cents=10000,
                             min_guests=4)
    b1 = create_party_booking(package["id"], room["id"], slot1["id"], guest_count=6)
    hold_party_deposit(b1["id"], slot1["id"])
    b2 = create_party_booking(package["id"], room["id"], slot2["id"], guest_count=6)
    validate_error(
        api.hold_deposit(b2["id"], {"expected_slot_version": get_slot_version(slot2["id"])}, FD),
        ApiErrorId.ERR_ROOM_CONFLICT.value)


def test_room_booking_beyond_buffer_allowed(api):
    """PRD §3.8: "the room interval ... does not collide with any other non-`CANCELLED`
    booking on the same room, where the room's `turnover_buffer_minutes` must separate
    two bookings on each side".

    Room buffer 30; B1 holds 10:00-12:00; B2 at 12:45-13:45 starts 45 min after B1 ends
    (>= 30 buffer) -> hold-deposit succeeds (DEPOSIT_HELD), the complementary side of the
    buffer boundary.

    Design: Difficulty/resource_temporal_overlap/party_room_turnover_buffer_overlap_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot1 = create_slot(park["id"], starts_at="2026-06-20T10:00:00Z",
                        ends_at="2026-06-20T12:00:00Z", jump_capacity=30, base_price_cents=2000)
    slot2 = create_slot(park["id"], starts_at="2026-06-20T12:45:00Z",
                        ends_at="2026-06-20T13:45:00Z", jump_capacity=30, base_price_cents=2000)
    room = create_room(park["id"], name="Room A", room_capacity=30, turnover_buffer_minutes=30)
    package = create_package(park["id"], per_guest_cents=1500, base_room_fee_cents=10000,
                             min_guests=4)
    b1 = create_party_booking(package["id"], room["id"], slot1["id"], guest_count=6)
    hold_party_deposit(b1["id"], slot1["id"])
    b2 = create_party_booking(package["id"], room["id"], slot2["id"], guest_count=6)
    held = validate_success(
        api.hold_deposit(b2["id"], {"expected_slot_version": get_slot_version(slot2["id"])}, FD),
        200)
    assert held["booking_status"] == "DEPOSIT_HELD"


# ─────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / slot_aggregate_capacity_overlap_rejected  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_slot_aggregate_capacity_exceeded_rejected(api):
    """PRD §3.2: "if `seats_taken` is greater than or equal to `jump_capacity`, the
    `status` is `FULL`".
    PRD §2.7: "on a seat-consuming create the `expected_slot_version` mismatch
    (`ERR_STALE_SLOT_VERSION`) is evaluated before the capacity test
    (`ERR_SLOT_CAPACITY_EXCEEDED`)."

    Capacity-3 slot at seats_taken 3 (three reservation passes); a 4th create with the
    fresh version is rejected ERR_SLOT_CAPACITY_EXCEEDED — aggregate summed-capacity
    breach, not pairwise interval geometry.

    Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_overlap_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=3, base_price_cents=2000)
    for i in range(3):
        p = create_adult(park["id"], full_name=f"G{i+1}")
        create_reservation_pass(slot["id"], p["id"], get_slot_version(slot["id"]))
    p4 = create_adult(park["id"], full_name="G4")
    validate_error(
        api.create_jump_pass(
            create_jump_pass_payload(slot["id"], p4["id"], get_slot_version(slot["id"])), FD),
        ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value)


def test_party_guests_exceeding_remaining_capacity_rejected(api):
    """PRD §3.8: "It requires that the slot is not `CLOSED` and that the slot's
    `seats_taken` plus this booking's `guest_count` does not exceed the slot's
    `jump_capacity` (else `ERR_SLOT_CAPACITY_EXCEEDED`)".

    Capacity-3 slot already at seats_taken 1 (one pass); a party booking of 4 guests
    would make 5 > 3 -> hold-deposit rejected ERR_SLOT_CAPACITY_EXCEEDED (aggregate
    seat breach on the party path).

    Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_overlap_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=3, base_price_cents=2000)
    room = create_room(park["id"], name="Room A", room_capacity=30)
    package = create_package(park["id"], per_guest_cents=1500, base_room_fee_cents=10000,
                             min_guests=4)
    p = create_adult(park["id"], full_name="One Seat")
    create_reservation_pass(slot["id"], p["id"], get_slot_version(slot["id"]))
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=4)
    validate_error(
        api.hold_deposit(booking["id"],
                         {"expected_slot_version": get_slot_version(slot["id"])}, FD),
        ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value)


# ─────────────────────────────────────────────────────────────────────
# Corner cross_cutting / errors / consistency — OCC + immediate visibility
# ─────────────────────────────────────────────────────────────────────
def test_occ_correct_slot_version_succeeds_and_bumps(api):
    """PRD §2.6: "The create must carry `expected_slot_version` equal to the target
    slot's current `version`."
    PRD §3.5: "it adds one to the slot's `seats_taken`, recomputes the slot's `status`,
    and increments the slot's `version` by 1."

    Fresh slot version 1; create with expected_slot_version 1 succeeds (201), then the
    slot reads version 2 and seats_taken 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_slot_version_succeeds
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="OK J")
    validate_success(
        api.create_jump_pass(
            create_jump_pass_payload(slot["id"], participant["id"], slot["version"]), FD), 201)
    after = get_slot(slot["id"])
    assert after["version"] == 2
    assert after["seats_taken"] == 1


def test_stale_slot_version_on_pass_create_rejected(api):
    """PRD §2.6: "If another writer has advanced the slot's `version` since the client
    last read it — for example by legitimately consuming the last remaining seat — the
    create is rejected with `ERR_STALE_SLOT_VERSION` at HTTP 412".

    First pass bumps version 1->2; a second create still carrying expected_slot_version 1
    is stale -> ERR_STALE_SLOT_VERSION (412).

    Design: Corner/errors/stale_slot_version_on_pass_create
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    p1 = create_adult(park["id"], full_name="First J")
    create_reservation_pass(slot["id"], p1["id"], slot["version"])  # bumps version to 2
    p2 = create_adult(park["id"], full_name="Stale J")
    validate_error(
        api.create_jump_pass(
            create_jump_pass_payload(slot["id"], p2["id"], slot["version"]), FD),  # stale v1
        ApiErrorId.ERR_STALE_SLOT_VERSION.value)


def test_party_hold_deposit_stale_slot_version_rejected(api):
    """PRD §2.6: "That request likewise must carry `expected_slot_version` matching the
    target slot's current `version`, and a mismatch is rejected with
    `ERR_STALE_SLOT_VERSION` at HTTP 412 for the same reason: a stale view of guest
    capacity would over-subscribe the slot."

    A pending booking observes slot version v; an intervening jump-pass create bumps the
    slot; the hold-deposit with the now-stale v is rejected ERR_STALE_SLOT_VERSION.

    Design: Corner/cross_cutting_complexity_layers/party_hold_deposit_stale_slot_version_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=20, base_price_cents=2000)
    room = create_room(park["id"], name="Room A", room_capacity=30)
    package = create_package(park["id"], per_guest_cents=1500, base_room_fee_cents=10000,
                             min_guests=4)
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=6)
    observed_v = get_slot_version(slot["id"])
    # Intervening jump-pass create bumps the slot version past observed_v.
    p = create_adult(park["id"], full_name="Bump J")
    create_reservation_pass(slot["id"], p["id"], observed_v)
    validate_error(
        api.hold_deposit(booking["id"], {"expected_slot_version": observed_v}, FD),
        ApiErrorId.ERR_STALE_SLOT_VERSION.value)


def test_immediate_visibility_of_seats_taken_on_create(api):
    """PRD §2.4: "A `SessionSlot` in particular recomputes `seats_taken` and `status`
    whenever a pass or booking consumes or releases its capacity, and also recomputes
    them when the slot is read, so a fetched slot always reflects current occupancy."

    After a jump-pass create, the immediate slot GET already shows seats_taken == 1.

    Design: Corner/consistency_model/immediate_visibility_of_seats_taken_on_create_response
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Imm J")
    create_reservation_pass(slot["id"], participant["id"], slot["version"])
    assert get_slot(slot["id"])["seats_taken"] == 1
