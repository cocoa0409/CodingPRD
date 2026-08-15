"""Shipments and crane slots: OCC, buffer overlap, dispatch clock, release (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_crane_slot_invariant,
    book_shipment,
    create_shipment_payload,
    get_success_data,
    setup_accepted_test,
    setup_booked_shipment,
    setup_crane_slot,
    setup_delivered_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/shipment_create_requires_ready_to_ship
# ---------------------------------------------------------------------------

def test_shipment_create_requires_ready_to_ship(api):
    """PRD §3.8: "Booking requires the order's `build_status` to be
    `READY_TO_SHIP` (else `ERR_INVALID_BUILD_STATE`)."

    While the order is still TESTING (test PASSED but not yet accepted), the
    booking is rejected; once acceptance advances the order to READY_TO_SHIP,
    the identical booking succeeds.

    Design: Difficulty/cross_entity_state_dependency/shipment_create_requires_ready_to_ship
    """
    from test_helpers import create_factory_test, make_test_engineer_headers, record_passing_test
    # Build to TESTING with a PASSED-but-not-accepted test.
    from test_helpers import setup_testing_order
    ctx = setup_testing_order()
    test = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"]
    )
    test = record_passing_test(test["id"], "eng-rec-10")
    assert test["status"] == "PASSED"
    order = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "TESTING"

    slot = setup_crane_slot(service_date="2026-09-10", window_start_hour=8, window_end_hour=16)
    slot_now = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    payload = create_shipment_payload(
        order_id=ctx["order"]["id"], crane_slot_id=slot["id"],
        expected_crane_slot_version=slot_now["version"],
        freight_class="HEAVY_HAUL",
    )
    resp = api.create_shipment(payload, LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_INVALID_BUILD_STATE)

    # Accept the test; the order auto-advances to READY_TO_SHIP.
    get_success_data(api.accept_factory_test(test["id"], make_test_engineer_headers("eng-acc-10")))
    order = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "READY_TO_SHIP"

    slot_now = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    payload["expected_crane_slot_version"] = slot_now["version"]
    booked = validate_success(api.create_shipment(payload, LOGISTICS), expected_status=201)
    assert booked["status"] == "BOOKED"
    slot_after = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_after["reserved_hours"] == pytest.approx(2.5, abs=1e-6)


def test_shipment_booking_updates_slot_accounting(api):
    """PRD §3.8: "On success the shipment is `BOOKED`, the slot's
    `reserved_hours` grows by `lift_hours` plus `buffer_hours`, `free_hours` is
    recomputed, and the slot's `version` increments."

    A 2.0 h lift on a 0.5 h-buffer slot reserves 2.5 h of an 8 h window.

    Design: Difficulty/cross_entity_state_dependency/shipment_create_requires_ready_to_ship
    """
    ctx = setup_accepted_test()
    slot = setup_crane_slot(service_date="2026-09-10", window_start_hour=8, window_end_hour=16)
    assert slot["free_hours"] == pytest.approx(8.0, abs=1e-6)
    shipment = book_shipment(
        ctx["order"]["id"], slot, lift_start_hour=8, lift_hours=2.0,
        freight_class="HEAVY_HAUL",
    )
    assert shipment["status"] == "BOOKED"
    slot_after = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_after["reserved_hours"] == pytest.approx(2.5, abs=1e-6)
    assert slot_after["free_hours"] == pytest.approx(5.5, abs=1e-6)
    assert_crane_slot_invariant(slot_after)


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/crane_slot_buffer_adjacency
# ---------------------------------------------------------------------------

def test_crane_slot_buffer_occupancy_collision_and_adjacency(api):
    """PRD §3.8: "The booking's occupancy is the half-open interval from
    `lift_start_hour` to `lift_start_hour` plus `lift_hours` plus the slot's
    `buffer_hours`; it may not intersect any other booking's occupancy on the
    same slot, though mere adjacency — one occupancy ending exactly where
    another begins — does not conflict. An overlap, or an occupancy that would
    push past the window, is rejected with `ERR_CRANE_WINDOW_OVERLAP`."

    A booking at 8 with lift 2.0 occupies [8, 10.5); a second booking at 10.0
    collides, while one at exactly 10.5 is legal adjacency.

    Design: Difficulty/resource_temporal_overlap/crane_slot_buffer_adjacency
    """
    ctx = setup_accepted_test()
    slot = setup_crane_slot(service_date="2026-09-10", window_start_hour=8, window_end_hour=16)
    first = book_shipment(ctx["order"]["id"], slot, lift_start_hour=8, lift_hours=2.0)
    assert first["status"] == "BOOKED"
    slot_mid = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_mid["free_hours"] == pytest.approx(5.5, abs=1e-6)

    colliding = create_shipment_payload(
        order_id=ctx["order"]["id"], crane_slot_id=slot["id"],
        lift_start_hour=10.0, lift_hours=1.0, gross_weight_kg=9000,
        expected_crane_slot_version=slot_mid["version"],
    )
    resp = api.create_shipment(colliding, LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_CRANE_WINDOW_OVERLAP)

    adjacent = create_shipment_payload(
        order_id=ctx["order"]["id"], crane_slot_id=slot["id"],
        lift_start_hour=10.5, lift_hours=1.0, gross_weight_kg=9000,
        expected_crane_slot_version=slot_mid["version"],
    )
    booked = validate_success(api.create_shipment(adjacent, LOGISTICS), expected_status=201)
    assert booked["status"] == "BOOKED"
    slot_after = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_after["free_hours"] == pytest.approx(4.0, abs=1e-6)
    assert_crane_slot_invariant(slot_after)


def test_crane_slot_occupancy_past_window_rejected(api):
    """PRD §3.8: "An overlap, or an occupancy that would push past the window,
    is rejected with `ERR_CRANE_WINDOW_OVERLAP`."

    On an 8-16 window with buffer 0.5, a 2.0 h lift starting at 14.5 would
    occupy [14.5, 17.0), past the window close.

    Design: Difficulty/resource_temporal_overlap/crane_slot_buffer_adjacency
    """
    ctx = setup_accepted_test()
    slot = setup_crane_slot(service_date="2026-09-10", window_start_hour=8, window_end_hour=16)
    slot_now = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    payload = create_shipment_payload(
        order_id=ctx["order"]["id"], crane_slot_id=slot["id"],
        lift_start_hour=14.5, lift_hours=2.0,
        expected_crane_slot_version=slot_now["version"],
    )
    resp = api.create_shipment(payload, LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_CRANE_WINDOW_OVERLAP)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/crane_hours_book_release_round_trip
# ---------------------------------------------------------------------------

def test_crane_hours_book_release_round_trip(api):
    """PRD §3.8: "The slot tracks `reserved_hours` — the sum, over its active
    bookings, of each booking's `lift_hours` plus the slot's `buffer_hours` —
    and `free_hours`, the window length minus the reserved figure; the invariant
    `free_hours` plus `reserved_hours` always equals `window_end_hour` minus
    `window_start_hour`."
    PRD §3.8: "A `BOOKED` shipment may instead be released by the
    `LogisticsCoordinator`, moving it to `RELEASED` and returning its occupancy —
    the slot's `reserved_hours` falls by `lift_hours` plus `buffer_hours`,
    `free_hours` is recomputed, and the slot's `version` increments."

    Booking (3.0 + 0.5) then releasing returns free_hours to exactly 8.0 with
    reserved 0 — no drift across the forward/compensating pair.

    Design: Difficulty/compensating_invariant/crane_hours_book_release_round_trip
    """
    ctx = setup_accepted_test()
    slot = setup_crane_slot(service_date="2026-09-10", window_start_hour=8, window_end_hour=16)
    assert slot["free_hours"] == pytest.approx(8.0, abs=1e-6)
    assert_crane_slot_invariant(slot)

    shipment = book_shipment(
        ctx["order"]["id"], slot, lift_start_hour=9, lift_hours=3.0,
        freight_class="OVERSIZE",
    )
    slot_booked = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_booked["reserved_hours"] == pytest.approx(3.5, abs=1e-6)
    assert slot_booked["free_hours"] == pytest.approx(4.5, abs=1e-6)
    assert_crane_slot_invariant(slot_booked)

    released = validate_success(api.release_shipment(shipment["id"], LOGISTICS))
    assert released["status"] == "RELEASED"
    slot_final = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_final["reserved_hours"] == pytest.approx(0.0, abs=1e-6)
    assert slot_final["free_hours"] == pytest.approx(8.0, abs=1e-6)
    assert_crane_slot_invariant(slot_final)


def test_crane_slot_version_increments_on_book_and_release(api):
    """PRD §3.8: "On success the shipment is `BOOKED`, the slot's
    `reserved_hours` grows by `lift_hours` plus `buffer_hours`, `free_hours` is
    recomputed, and the slot's `version` increments."
    PRD §2.5: "`version` (integer): starts at the value assigned at creation
    and increments by exactly 1 on every mutation of the resource, including
    mutations performed by the server itself as a cascade side effect."

    Each of book and release bumps the slot version by exactly 1.

    Design: Difficulty/compensating_invariant/crane_hours_book_release_round_trip
    """
    ctx = setup_accepted_test()
    slot = setup_crane_slot(service_date="2026-09-10", window_start_hour=8, window_end_hour=16)
    v0 = slot["version"]
    shipment = book_shipment(ctx["order"]["id"], slot, lift_start_hour=9, lift_hours=3.0)
    slot_v1 = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_v1["version"] == v0 + 1
    validate_success(api.release_shipment(shipment["id"], LOGISTICS))
    slot_v2 = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_v2["version"] == v0 + 2


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/occ_shipment_book_stale_slot_version
# ---------------------------------------------------------------------------

def test_shipment_book_stale_slot_version_rejected(api):
    """PRD §2.7: "Booking a shipment requires the request to carry
    `expected_crane_slot_version`, holding the `version` of the target
    `CraneSlot` as the client last observed it. If the slot's current `version`
    no longer matches — because another booking or a release legitimately
    changed the slot's `free_hours` in the interim — the booking is rejected
    with `ERR_STALE_CRANE_SLOT_VERSION` (HTTP 412), so capacity decisions are
    never made against a stale view of the slot."

    Design: Corner/cross_cutting_layers/occ_shipment_book_stale_slot_version
    """
    ctx = setup_accepted_test()
    slot = setup_crane_slot(service_date="2026-09-10", window_start_hour=8, window_end_hour=16)
    version_at_read = slot["version"]
    # Booking A advances the slot version.
    booking_a = book_shipment(ctx["order"]["id"], slot, lift_start_hour=8, lift_hours=2.0)
    assert booking_a["status"] == "BOOKED"

    # Booking B (non-overlapping window at 12) with the stale version is rejected.
    stale_payload = create_shipment_payload(
        order_id=ctx["order"]["id"], crane_slot_id=slot["id"],
        lift_start_hour=12, lift_hours=1.0, gross_weight_kg=9000,
        expected_crane_slot_version=version_at_read,
    )
    resp = api.create_shipment(stale_payload, LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_STALE_CRANE_SLOT_VERSION)

    # Retry with the fresh version succeeds.
    slot_now = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    fresh_payload = create_shipment_payload(
        order_id=ctx["order"]["id"], crane_slot_id=slot["id"],
        lift_start_hour=12, lift_hours=1.0, gross_weight_kg=9000,
        expected_crane_slot_version=slot_now["version"],
    )
    booked = validate_success(api.create_shipment(fresh_payload, LOGISTICS), expected_status=201)
    assert booked["status"] == "BOOKED"
    slot_final = get_success_data(api.get_crane_slot(slot["id"], LOGISTICS))
    assert slot_final["version"] == slot_now["version"] + 1


# ---------------------------------------------------------------------------
# Corner/validations/dispatch_before_service_date_rejected
# ---------------------------------------------------------------------------

def test_dispatch_before_service_date_rejected(api):
    """PRD §3.8: "Dispatch moves a `BOOKED` shipment to `DISPATCHED`, but only
    once the logical-clock date has reached the slot's `service_date` — an
    earlier dispatch is rejected with `ERR_SHIPMENT_DATE_NOT_REACHED`."

    Design: Corner/validations/dispatch_before_service_date_rejected
    """
    from test_helpers import set_clock
    ctx = setup_booked_shipment(
        slot_overrides={"service_date": "2026-09-10"},
    )
    # Default clock is 2026-08-01, before the 2026-09-10 slot date.
    resp = api.dispatch_shipment(ctx["shipment"]["id"], LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_DATE_NOT_REACHED)

    set_clock("2026-09-10T00:00:00Z")
    dispatched = validate_success(api.dispatch_shipment(ctx["shipment"]["id"], LOGISTICS))
    assert dispatched["status"] == "DISPATCHED"


# ---------------------------------------------------------------------------
# Corner/state_machines/terminal_state_lockdown_delivered_shipment_release_rejected
# ---------------------------------------------------------------------------

def test_delivered_shipment_release_rejected(api):
    """PRD §3.8: "Delivery moves `DISPATCHED` → `DELIVERED` and lands two
    cascades on the order: `build_status` `READY_TO_SHIP` → `DELIVERED`, and, if
    the order's `commercial_status` is currently `AUTHORIZED`, `AUTHORIZED` →
    `INVOICED`."
    PRD §5 error catalogue: `ERR_SHIPMENT_STATE_INVALID` — releasing a
    DELIVERED (terminal) shipment fails the from-state check.

    Design: Corner/state_machines/terminal_state_lockdown_delivered_shipment_release_rejected
    """
    ctx = setup_delivered_order()
    shipment = ctx["shipment"]
    assert shipment["status"] == "DELIVERED"
    order = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "DELIVERED"
    assert order["commercial_status"] == "INVOICED"

    resp = api.release_shipment(shipment["id"], LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_STATE_INVALID)
    current = get_success_data(api.get_shipment(shipment["id"], LOGISTICS))
    assert current["status"] == "DELIVERED"


# ---------------------------------------------------------------------------
# Corner/entities/crane_slot_derived_fields_at_creation
# ---------------------------------------------------------------------------

def test_crane_slot_derived_fields_at_creation(api):
    """PRD §3.8: "A `PlatformAdmin` opens a `CraneSlot` for a `service_date` with
    a `window_start_hour` and `window_end_hour` bounding the working window
    (start at least 0 and strictly before end; end at most 24), a `buffer_hours`
    setup allowance appended to every booking's occupancy (defaulting to 0.5),
    and a `status` of `OPEN` or `CLOSED` (defaulting to `OPEN`). The slot tracks
    `reserved_hours` — the sum, over its active bookings, of each booking's
    `lift_hours` plus the slot's `buffer_hours` — and `free_hours`, the window
    length minus the reserved figure..."

    A slot created without buffer_hours defaults to 0.5, reserved 0, and
    free_hours equal to the full 12-hour window.

    Design: Corner/entities/crane_slot_derived_fields_at_creation
    """
    slot = setup_crane_slot(
        service_date="2026-10-01", window_start_hour=6, window_end_hour=18
    )
    assert slot["buffer_hours"] == pytest.approx(0.5, abs=1e-6)
    assert slot["reserved_hours"] == pytest.approx(0.0, abs=1e-6)
    assert slot["free_hours"] == pytest.approx(12.0, abs=1e-6)
    assert slot["status"] == "OPEN"
