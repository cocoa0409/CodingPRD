"""Cart and barista scheduling: buffered cart intervals, unbuffered half-open
barista intervals, and the inventory availability boundary.

Queue A (Difficulty): boundary_precision_check, resource_temporal_overlap.
"""
from test_helpers import (
    api_client,
    fixtures as fx,
    validate_success, validate_error,
    ApiErrorId,
)

ERR = ApiErrorId


def _confirmed_morning_booking():
    """CART-A committed 2026-05-10 10:00-12:00 (buffered 08:30-13:30)."""
    ctx = fx.setup_confirmed_booking(
        package_kind="FLAT",
        booking_overrides={"event_start": "2026-05-10T10:00:00Z",
                           "event_end": "2026-05-10T12:00:00Z"})
    return ctx


def _submit_new_booking(ctx, event_start, event_end):
    booking = fx.create_quote_booking(ctx, event_start=event_start,
                                      event_end=event_end)
    fx.offer_primary_assignment(ctx, booking["id"])
    return api_submit(ctx, booking["id"])


def api_submit(ctx, booking_id):
    return fx.submit_quote_raw(
        ctx, booking_id,
        fx.current_cart_version(ctx["cart"]["id"]),
        fx.current_barista_version(ctx["barista"]["id"]))


# ─── boundary_precision_check / cart_buffer_adjacency_boundary_90min ──────

def test_booking_starting_89_minutes_after_event_end_rejected(api):
    """PRD §3.5: "Every booking occupies a buffered interval: its `event_start` minus
    ninety minutes of travel time through its `event_end` plus ninety minutes. A
    submission is rejected with `ERR_CART_DOUBLE_BOOKED` (HTTP 409) whenever that
    buffered window collides with the equally buffered window of any other booking
    in `PENDING_DEPOSIT`, `CONFIRMED`, or `IN_PROGRESS` status that shares the
    same cart — collision meaning the candidate's buffered start falls before the
    other's buffered end and the other's buffered start falls before the
    candidate's buffered end."

    Committed booking occupies buffered [08:30, 13:30). A candidate starting at
    13:29 buffers to [11:59, 15:59): its buffered start 11:59 falls before 13:30,
    so the windows collide.

    Design: Difficulty/boundary_precision_check/cart_buffer_adjacency_boundary_90min
    """
    ctx = _confirmed_morning_booking()
    res = _submit_new_booking(ctx, "2026-05-10T13:29:00Z", "2026-05-10T14:29:00Z")
    validate_error(res, ERR.ERR_CART_DOUBLE_BOOKED, expected_status=409)


def test_booking_starting_one_minute_inside_buffer_boundary_rejected(api):
    """PRD §3.5: "Every booking occupies a buffered interval: its `event_start` minus
    ninety minutes of travel time through its `event_end` plus ninety minutes. A
    submission is rejected with `ERR_CART_DOUBLE_BOOKED` (HTTP 409) whenever that
    buffered window collides with the equally buffered window of any other booking
    in `PENDING_DEPOSIT`, `CONFIRMED`, or `IN_PROGRESS` status that shares the
    same cart — collision meaning the candidate's buffered start falls before the
    other's buffered end and the other's buffered start falls before the
    candidate's buffered end."

    Both buffers extend both sides, so the true clearance is event_end plus twice
    the buffer: a candidate starting at 14:59 buffers to [13:29, 16:29), and
    13:29 still falls before the committed window's buffered end 13:30.

    Design: Difficulty/boundary_precision_check/cart_buffer_adjacency_boundary_90min
    """
    ctx = _confirmed_morning_booking()
    res = _submit_new_booking(ctx, "2026-05-10T14:59:00Z", "2026-05-10T15:59:00Z")
    validate_error(res, ERR.ERR_CART_DOUBLE_BOOKED, expected_status=409)


def test_booking_starting_exactly_at_buffer_boundary_allowed(api):
    """PRD §3.5: "Every booking occupies a buffered interval: its `event_start` minus
    ninety minutes of travel time through its `event_end` plus ninety minutes. A
    submission is rejected with `ERR_CART_DOUBLE_BOOKED` (HTTP 409) whenever that
    buffered window collides with the equally buffered window of any other booking
    in `PENDING_DEPOSIT`, `CONFIRMED`, or `IN_PROGRESS` status that shares the
    same cart — collision meaning the candidate's buffered start falls before the
    other's buffered end and the other's buffered start falls before the
    candidate's buffered end."

    A candidate starting at exactly 15:00 buffers to [13:30, 17:00); its buffered
    start equals the committed window's buffered end 13:30, so the strict-before
    collision test fails and the submission succeeds.

    Design: Difficulty/boundary_precision_check/cart_buffer_adjacency_boundary_90min
    """
    ctx = _confirmed_morning_booking()
    res = _submit_new_booking(ctx, "2026-05-10T15:00:00Z", "2026-05-10T16:00:00Z")
    submitted = validate_success(res, 200)
    assert submitted["status"] == "PENDING_DEPOSIT", submitted


# ─── resource_temporal_overlap / cart_overlap_buffered_half_open ──────────

def test_raw_disjoint_windows_with_overlapping_buffers_rejected(api):
    """PRD §3.5: "Because the buffers extend each side, two events whose raw windows
    merely touch can still collide once travel time is added."
    PRD §3.5: "A submission is rejected with `ERR_CART_DOUBLE_BOOKED` (HTTP 409)
    whenever that buffered window collides with the equally buffered window of any
    other booking in `PENDING_DEPOSIT`, `CONFIRMED`, or `IN_PROGRESS` status that
    shares the same cart"

    Raw windows 10:00-12:00 and 13:00-14:00 never intersect, yet the buffered
    windows [08:30, 13:30) and [11:30, 15:30) do.

    Design: Difficulty/resource_temporal_overlap/cart_overlap_buffered_half_open
    """
    ctx = _confirmed_morning_booking()
    res = _submit_new_booking(ctx, "2026-05-10T13:00:00Z", "2026-05-10T14:00:00Z")
    validate_error(res, ERR.ERR_CART_DOUBLE_BOOKED, expected_status=409)


def test_same_cart_booking_clear_of_travel_buffers_accepted(api):
    """PRD §3.5: "Every booking occupies a buffered interval: its `event_start` minus
    ninety minutes of travel time through its `event_end` plus ninety minutes."

    A same-cart booking the following day buffers to a window that clears the
    committed booking's buffered interval entirely, so submission succeeds.

    Design: Difficulty/resource_temporal_overlap/cart_overlap_buffered_half_open
    """
    ctx = _confirmed_morning_booking()
    res = _submit_new_booking(ctx, "2026-05-11T10:00:00Z", "2026-05-11T12:00:00Z")
    submitted = validate_success(res, 200)
    assert submitted["status"] == "PENDING_DEPOSIT", submitted


# ─── resource_temporal_overlap / barista_overlap_unbuffered_adjacency_allowed ───

def _two_bookings_same_barista(b2_start, b2_end):
    """Barista accepted on booking one (cart A, 2026-05-10 10:00-12:00); booking two
    on cart B with an OFFERED assignment for the same barista."""
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    ctx["cart_b"] = fx.create_cart(cart_code="CART-B")
    b1 = fx.create_quote_booking(ctx, event_start="2026-05-10T10:00:00Z",
                                 event_end="2026-05-10T12:00:00Z")
    asg1 = fx.offer_primary_assignment(ctx, b1["id"])
    asg1 = validate_success(
        api_client.accept_assignment(asg1["id"], ctx["barista_headers"]), 200)
    assert asg1["status"] == "ACCEPTED", asg1

    b2 = fx.create_quote_booking(
        ctx, cart_id=ctx["cart_b"]["id"], event_start=b2_start, event_end=b2_end)
    asg2 = fx.offer_primary_assignment(ctx, b2["id"])
    return ctx, b1, asg1, b2, asg2


def _accept(ctx, assignment_id):
    return api_client.accept_assignment(assignment_id, ctx["barista_headers"])


def test_back_to_back_assignments_for_same_barista_allowed(api):
    """PRD §3.4: "The double-booking check treats every booking window as a half-open
    interval: the candidate's `event_start` up to but not including its `event_end`
    overlaps another of the same barista's assignments in `ACCEPTED` or `CONFIRMED`
    status only when the candidate's start falls before the other event's end and
    the other event's start falls before the candidate's end. Back-to-back events
    are explicitly allowed — one event ending exactly when the next begins is not
    an overlap."

    An assignment starting at 12:00, exactly when the accepted one ends, is not an
    overlap and accepts cleanly.

    Design: Difficulty/resource_temporal_overlap/barista_overlap_unbuffered_adjacency_allowed
    """
    ctx, _b1, _asg1, _b2, asg2 = _two_bookings_same_barista(
        "2026-05-10T12:00:00Z", "2026-05-10T14:00:00Z")
    res = _accept(ctx, asg2["id"])
    accepted = validate_success(res, 200)
    assert accepted["status"] == "ACCEPTED", accepted


def test_overlapping_assignment_for_same_barista_rejected(api):
    """PRD §3.4: "The double-booking check treats every booking window as a half-open
    interval: the candidate's `event_start` up to but not including its `event_end`
    overlaps another of the same barista's assignments in `ACCEPTED` or `CONFIRMED`
    status only when the candidate's start falls before the other event's end and
    the other event's start falls before the candidate's end. Back-to-back events
    are explicitly allowed — one event ending exactly when the next begins is not
    an overlap. A genuine overlap is rejected with `ERR_BARISTA_DOUBLE_BOOKED`
    (HTTP 409)."

    A candidate running 11:00-13:00 starts before the accepted 10:00-12:00 window
    ends, so the half-open overlap test fires.

    Design: Difficulty/resource_temporal_overlap/barista_overlap_unbuffered_adjacency_allowed
    """
    ctx, _b1, _asg1, _b2, asg2 = _two_bookings_same_barista(
        "2026-05-10T11:00:00Z", "2026-05-10T13:00:00Z")
    res = _accept(ctx, asg2["id"])
    validate_error(res, ERR.ERR_BARISTA_DOUBLE_BOOKED, expected_status=409)


# ─── boundary_precision_check / inventory_qty_available_boundary ──────────

def _setup_item_with_partial_reservation():
    """Item with 100 on hand; booking one holds a reservation of 60, leaving 40."""
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    item = fx.create_inventory_item(on_hand_units=100)
    b1 = fx.create_quote_booking(ctx, event_start="2026-05-10T10:00:00Z",
                                 event_end="2026-05-10T12:00:00Z")
    fx.create_reservation(ctx, b1["id"], item["id"], 60)
    b2 = fx.create_quote_booking(ctx, event_start="2026-05-11T10:00:00Z",
                                 event_end="2026-05-11T12:00:00Z")
    return ctx, item, b1, b2


def test_reservation_at_exact_available_quantity_succeeds(api):
    """PRD §3.2: "Availability is strict: `qty_units` may not exceed the item's
    `on_hand_units` minus its `reserved_units`; requesting exactly the available
    amount is allowed, and requesting one more is rejected with
    `ERR_INSUFFICIENT_INVENTORY` (HTTP 422). A new reservation starts in `RESERVED`
    status, and the item's `reserved_units` immediately grows by `qty_units`."

    With 100 on hand and 60 already reserved, requesting exactly the remaining 40
    succeeds and drives reserved_units to the full 100.

    Design: Difficulty/boundary_precision_check/inventory_qty_available_boundary
    """
    ctx, item, _b1, b2 = _setup_item_with_partial_reservation()
    res = api.create_reservation(
        b2["id"], {"item_id": item["id"], "qty_units": 40}, fx.OPS)
    reservation = validate_success(res, 201)
    assert reservation["status"] == "RESERVED", reservation
    assert reservation["qty_units"] == 40, reservation

    item_after = validate_success(api.get_inventory_item(item["id"], fx.OPS), 200)
    assert item_after["reserved_units"] == 100, item_after


def test_reservation_one_above_available_quantity_rejected(api):
    """PRD §3.2: "Availability is strict: `qty_units` may not exceed the item's
    `on_hand_units` minus its `reserved_units`; requesting exactly the available
    amount is allowed, and requesting one more is rejected with
    `ERR_INSUFFICIENT_INVENTORY` (HTTP 422)."

    With 100 on hand and 60 already reserved, requesting 41 — one more than the
    40 available — is rejected.

    Design: Difficulty/boundary_precision_check/inventory_qty_available_boundary
    """
    ctx, item, _b1, b2 = _setup_item_with_partial_reservation()
    res = api.create_reservation(
        b2["id"], {"item_id": item["id"], "qty_units": 41}, fx.OPS)
    validate_error(res, ERR.ERR_INSUFFICIENT_INVENTORY, expected_status=422)

    item_after = validate_success(api.get_inventory_item(item["id"], fx.OPS), 200)
    assert item_after["reserved_units"] == 60, item_after
