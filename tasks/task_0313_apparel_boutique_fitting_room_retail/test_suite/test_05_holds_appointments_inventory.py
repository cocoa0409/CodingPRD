"""Fitting-room holds, stylist appointments, and inventory reservation lifecycle.

Queue A (Difficulty): resource_temporal_overlap (room half-open vs stylist
closed-buffer), compensating_invariant (hold reserve/release), cross_entity_state_dependency
(appointment requires stylist active).
Queue B (Corner): state_machines (terminal lockdown), endpoints (restock, special-order ship),
cross_cutting_complexity_layers (hold expiry sweep on clock advance).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_boutique, create_customer, create_style, create_variant,
    create_fitting_room, create_hold, create_stylist, create_appointment,
    create_confirmed_appointment, advance_clock, restock_payload,
    open_order_with_line, create_special_order, create_sourced_special_order,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
MERCH = TEST_USERS["merchandiser_headers"]


# ─── Queue A: resource_temporal_overlap ───────────────────────────────────

def test_room_back_to_back_holds_allowed_interior_overlap_rejected(api):
    """PRD §3.3: "the requested interval must not overlap any other non-terminal hold
    on the same fitting room; intervals are half-open [start_minute, end_minute), so a
    hold ending exactly when another begins is back-to-back and permitted, but any true
    overlap is rejected with ERR_ROOM_DOUBLE_BOOKED (HTTP 409)."

    Hold A [600,660) on sku1; hold B [660,720) on sku2 is adjacent and ALLOWED; hold C
    [650,700) overlaps A's interior and is rejected with ERR_ROOM_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/room_hold_half_open_overlap_back_to_back_allowed
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    sv1 = create_variant(style["id"], size="S", color="Blue", on_hand=5)
    sv2 = create_variant(style["id"], size="M", color="Blue", on_hand=5)
    room = create_fitting_room(bq["id"])

    create_hold(room["id"], cu["id"], sv1["id"], start_minute=600, end_minute=660)
    hold_b = create_hold(room["id"], cu["id"], sv2["id"], start_minute=660, end_minute=720)
    assert hold_b["status"] == "ACTIVE", "back-to-back adjacency is permitted"

    res = api.create_hold(
        {"fitting_room_id": room["id"], "customer_id": cu["id"], "sku_variant_id": sv1["id"],
         "start_minute": 650, "end_minute": 700}, ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)


def test_extend_into_overlapping_interval_rejected(api):
    """PRD §3.3: "Extending a hold (ACTIVE -> EXTENDED) takes a new end_minute and
    lengthens the interval; the same half-open room-overlap check applies and yields
    ERR_ROOM_DOUBLE_BOOKED on collision, while the reservation simply persists with no
    inventory change."

    Hold A [600,660); adjacent hold B [660,720) on a second sku; extending A's end_minute
    to 700 would overlap B's interior and is rejected with ERR_ROOM_DOUBLE_BOOKED — the
    half-open overlap rule applies to extend as well as create.

    Design: Difficulty/resource_temporal_overlap/room_hold_half_open_overlap_back_to_back_allowed
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    sv1 = create_variant(style["id"], size="S", color="Blue", on_hand=5)
    sv2 = create_variant(style["id"], size="M", color="Blue", on_hand=5)
    room = create_fitting_room(bq["id"])

    hold_a = create_hold(room["id"], cu["id"], sv1["id"], start_minute=600, end_minute=660)
    create_hold(room["id"], cu["id"], sv2["id"], start_minute=660, end_minute=720)

    res = api.extend_hold(hold_a["id"], {"end_minute": 700}, ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)


def test_stylist_buffer_collision_rejected(api):
    """PRD §3.4: "the appointment must not collide with another already-CONFIRMED
    appointment on the same stylist when the stylist's buffer_minutes is taken into
    account; this overlap test is closed-buffer, meaning the cleanup gap is enforced on
    both sides of an existing appointment, and a collision is rejected with
    ERR_STYLIST_DOUBLE_BOOKED (HTTP 409)."

    With buffer_minutes=15, appointment A [600,660) CONFIRMED; appointment B [670,720)
    starts only 10 minutes after A ends (< 15 buffer) and confirmation is rejected with
    ERR_STYLIST_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/stylist_appointment_buffer_overlap_adjacency_rejected
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    stylist = create_stylist(bq["id"], buffer_minutes=15)

    appt_a = create_confirmed_appointment(stylist["id"], cu["id"], start_minute=600, end_minute=660)
    assert appt_a["status"] == "CONFIRMED"

    appt_b = create_appointment(stylist["id"], cu["id"], start_minute=670, end_minute=720)
    res = api.confirm_appointment(appt_b["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_STYLIST_DOUBLE_BOOKED.value)


def test_stylist_far_apart_appointments_both_confirm(api):
    """PRD §3.4: "the appointment must not collide with another already-CONFIRMED
    appointment on the same stylist when the stylist's buffer_minutes is taken into
    account; this overlap test is closed-buffer ... and a collision is rejected with
    ERR_STYLIST_DOUBLE_BOOKED (HTTP 409)."

    With buffer_minutes=15, appointment A [600,660) CONFIRMED and a well-separated
    appointment B [800,860) — a 140-minute gap, far beyond the buffer — confirms
    successfully, so the buffer-overlap check rejects only true within-buffer collisions.

    Design: Difficulty/resource_temporal_overlap/stylist_appointment_buffer_overlap_adjacency_rejected
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    stylist = create_stylist(bq["id"], buffer_minutes=15)

    appt_a = create_confirmed_appointment(stylist["id"], cu["id"], start_minute=600, end_minute=660)
    assert appt_a["status"] == "CONFIRMED"

    appt_b = create_appointment(stylist["id"], cu["id"], start_minute=800, end_minute=860)
    confirmed_b = validate_success(api.confirm_appointment(appt_b["id"], ASSOCIATE), 200)
    assert confirmed_b["status"] == "CONFIRMED"


# ─── Queue A: compensating_invariant (hold reserve/release) ───────────────

def test_hold_release_conserves_on_hand_units(api):
    """PRD §3.3: "On success the hold begins in ACTIVE status, the variant's reserved is
    incremented by one with available recomputed and total_available bubbled up to the
    style".
    PRD §3.3: "Releasing a hold (from ACTIVE or EXTENDED to RELEASED) frees the
    reservation by decrementing the variant's reserved by one, recomputing available, and
    bubbling total_available up to the style — a compensating action that returns the unit
    to the floor."

    Reserving a unit (reserved 1, available 4) then releasing leaves on_hand unchanged at
    5 with reserved 0 and available 5.

    Design: Difficulty/compensating_invariant/hold_reserve_then_release_conserves_on_hand_units
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="BOTTOMS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Khaki", on_hand=5)
    room = create_fitting_room(bq["id"])

    hold = create_hold(room["id"], cu["id"], variant["id"], start_minute=600, end_minute=660)
    variant_held = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_held["reserved"] == 1
    assert variant_held["available"] == 4
    assert variant_held["on_hand"] == 5

    validate_success(api.release_hold(hold["id"], ASSOCIATE), 200)

    variant_after = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after["on_hand"] == 5
    assert variant_after["reserved"] == 0
    assert variant_after["available"] == 5


def test_hold_release_restores_style_total_available(api):
    """PRD §3.3: "the variant's reserved is incremented by one with available recomputed
    and total_available bubbled up to the style".
    PRD §3.3: "Releasing a hold ... frees the reservation by decrementing the variant's
    reserved by one, recomputing available, and bubbling total_available up to the style —
    a compensating action that returns the unit to the floor."

    A hold drops Style.total_available from 5 to 4; releasing it restores total_available to
    5 — the style-level roll-up conserves across reserve+release.

    Design: Difficulty/compensating_invariant/hold_reserve_then_release_conserves_on_hand_units
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="BOTTOMS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Khaki", on_hand=5)
    room = create_fitting_room(bq["id"])

    style_before = get_success_data(api.get_style(style["id"], ASSOCIATE))
    assert style_before["total_available"] == 5

    hold = create_hold(room["id"], cu["id"], variant["id"], start_minute=600, end_minute=660)
    style_held = get_success_data(api.get_style(style["id"], ASSOCIATE))
    assert style_held["total_available"] == 4

    validate_success(api.release_hold(hold["id"], ASSOCIATE), 200)
    style_after = get_success_data(api.get_style(style["id"], ASSOCIATE))
    assert style_after["total_available"] == 5


# ─── Queue A: cross_entity_state_dependency (appointment <- stylist) ──────

def test_confirm_appointment_requires_stylist_active(api):
    """PRD §3.4: "the stylist must be ACTIVE; if the stylist's status is OFF,
    confirmation is rejected with ERR_STYLIST_NOT_ACTIVE (HTTP 409)."

    A stylist set OFF blocks confirming a REQUESTED appointment with
    ERR_STYLIST_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/appointment_confirm_requires_stylist_active
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    stylist = create_stylist(bq["id"], buffer_minutes=15)
    appt = create_appointment(stylist["id"], cu["id"], start_minute=600, end_minute=660)
    get_success_data(api.set_stylist_status(stylist["id"], {"status": "OFF"}, MANAGER))

    res = api.confirm_appointment(appt["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_STYLIST_NOT_ACTIVE.value)


def test_confirm_appointment_succeeds_when_stylist_active(api):
    """PRD §3.4: "Confirming an appointment (REQUESTED -> CONFIRMED) is a StoreAssociate
    action guarded by two checks evaluated in this order. First, the stylist must be
    ACTIVE; if the stylist's status is OFF, confirmation is rejected with
    ERR_STYLIST_NOT_ACTIVE (HTTP 409)."

    A stylist left in its default ACTIVE status confirms a REQUESTED appointment
    successfully — the same gate that blocks an OFF stylist passes when ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/appointment_confirm_requires_stylist_active
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    stylist = create_stylist(bq["id"], buffer_minutes=15)
    assert stylist["status"] == "ACTIVE"
    appt = create_appointment(stylist["id"], cu["id"], start_minute=600, end_minute=660)

    confirmed = validate_success(api.confirm_appointment(appt["id"], ASSOCIATE), 200)
    assert confirmed["status"] == "CONFIRMED"


# ─── Queue B: state_machines (terminal lockdown) ──────────────────────────

def test_release_converted_hold_rejected_invalid_state(api):
    """PRD §3.3: "CONVERTED, EXPIRED, and RELEASED are the terminal hold states."
    PRD §2.8: "then the state check that the target resource is in a state from which
    the requested transition is defined (ERR_INVALID_STATE, HTTP 409)."

    Releasing a hold already CONVERTED to a sale returns ERR_INVALID_STATE — no
    transition leaves a terminal state.

    Design: Corner/state_machines/terminal_lockdown_release_converted_hold_invalid_state
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Blue", on_hand=5)
    room = create_fitting_room(bq["id"])
    hold = create_hold(room["id"], cu["id"], variant["id"], start_minute=600, end_minute=660)

    order, _ = open_order_with_line(cu["id"], variant["id"], qty=1)
    converted = get_success_data(api.convert_hold(hold["id"], {"sales_order_id": order["id"]}, ASSOCIATE))
    assert converted["status"] == "CONVERTED"

    res = api.release_hold(hold["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Queue B: endpoints (restock) ─────────────────────────────────────────

def test_restock_increments_inventory_and_bubbles_to_style(api):
    """PRD §3.1: "To replenish stock, the merchandiser restocks a variant by supplying a
    count of units, which increases both on_hand and available by that amount and bubbles
    the increase up to the style's total_available."

    Restocking units=4 on a variant at on_hand 3 yields on_hand 7, available 7, and
    Style.total_available 7.

    Design: Corner/endpoints/restock_increments_inventory_computed_read
    """
    bq = create_boutique(tax_rate_bps=875)
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Blue", on_hand=3)

    restocked = validate_success(api.restock_sku_variant(variant["id"], restock_payload(4), MERCH), 200)
    assert restocked["on_hand"] == 7
    assert restocked["available"] == 7

    style_after = get_success_data(api.get_style(style["id"], MERCH))
    assert style_after["total_available"] == 7


# ─── Queue B: endpoints (special-order ship commits inventory) ────────────

def test_special_order_ship_commits_units_out_of_store(api):
    """PRD §3.8: "Shipping (SOURCED -> SHIPPED) commits the units: the source variant's
    on_hand and reserved are each decremented by qty, the order's reserved_units is set to
    0, and available and total_available are recomputed."

    Sourcing then shipping a qty-2 special order off a variant at on_hand 3 ends with
    on_hand 1, reserved 0, available 1.

    Design: Corner/endpoints/special_order_ship_commits_inventory
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Blue", on_hand=3)

    sourced = create_sourced_special_order(cu["id"], variant["id"], qty=2)
    shipped = validate_success(api.ship_special_order(sourced["id"], ASSOCIATE), 200)
    assert shipped["status"] == "SHIPPED"

    variant_after = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after["on_hand"] == 1
    assert variant_after["reserved"] == 0
    assert variant_after["available"] == 1


# ─── Queue B: cross_cutting (hold expiry sweep on clock advance) ──────────

def test_clock_advance_expires_hold_and_releases_reservation(api):
    """PRD §3.3: "When the store clock advances past a hold's interval, the system sweeps
    it. Any hold still in ACTIVE or EXTENDED whose end_minute is at or before the
    boutique's current minute at the sweep, or whose business day has been left behind by
    an advancing current_business_date, transitions to EXPIRED; expiry frees its
    reservation exactly as a release does — decrement the variant's reserved by one,
    recompute available, and bubble total_available up to the style."

    Advancing the business date past a hold's day sweeps the ACTIVE hold to EXPIRED and
    releases the reservation (reserved 0, available restored to 5).

    Design: Corner/cross_cutting_complexity_layers/hold_expiry_sweep_releases_reservation_on_clock_advance
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Blue", on_hand=5)
    room = create_fitting_room(bq["id"])
    hold = create_hold(room["id"], cu["id"], variant["id"], start_minute=600, end_minute=660)

    advance_clock(bq["id"], 1)

    hold_after = get_success_data(api.get_hold(hold["id"], ASSOCIATE))
    assert hold_after["status"] == "EXPIRED"

    variant_after = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after["reserved"] == 0
    assert variant_after["available"] == 5
