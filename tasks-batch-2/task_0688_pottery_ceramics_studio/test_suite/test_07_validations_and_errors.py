"""Validation and error corners: deposit mismatch, past booking date, enrollment
window closed, insufficient/discontinued stock, firing-temp mismatch, duplicate
enrollment, insufficient points, visit-not-open on add-piece.

Queue B (Corner): sections validations and errors (non-stub instances).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of, get_success_data,
    create_member, create_open_visit, add_piece, create_batch, create_series,
    create_booking, create_item, load_piece, fire_piece_to_ready,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── validations ────────────────────────────────────────────────────────────

def test_deposit_amount_mismatch_rejected(api):
    """PRD §3.6: "the payment supplies an amount_cents that must exactly equal the
    booking's deposit_due_cents (a mismatch is rejected with
    ERR_DEPOSIT_AMOUNT_MISMATCH, HTTP 422)."

    Design: Corner/validations/deposit_amount_mismatch_rejected
    """
    member = create_member()
    booking = create_booking(member["id"], package_tier="BASIC", guest_count=6,
                             scheduled_for="2026-09-01T18:00:00Z")  # deposit_due 6750
    res = api.pay_deposit(booking["id"], {"amount_cents": 5000}, STAFF)
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH")
    after = validate_success(api.get_booking(booking["id"], STAFF), 200)
    assert after["status"] == "DEPOSIT_PENDING", after["status"]


def test_booking_date_in_past_rejected(api):
    """PRD §3.6: "The scheduled time must be strictly after the current logical clock
    at creation; a booking whose scheduled_for is not strictly in the future is
    rejected with ERR_BOOKING_DATE_PAST (HTTP 422)." PRD §2.4: at startup "the clock
    reads exactly 2026-04-01T00:00:00Z."

    Design: Corner/validations/booking_date_in_past_rejected
    """
    member = create_member()
    res = api.create_booking(
        {"member_id": member["id"], "package_tier": "BASIC", "guest_count": 6,
         "scheduled_for": "2026-04-01T00:00:00Z"}, STAFF)
    validate_error(res, "ERR_BOOKING_DATE_PAST")


def test_enrollment_closed_after_start_time(api):
    """PRD §3.10: "an enrollment attempted once the logical clock has reached or
    passed the series' starts_at is rejected with ERR_ENROLLMENT_CLOSED because the
    window has closed." PRD §3.11: "when the clock is advanced to or past a series'
    starts_at, the series-start sweep starts it... Once a series is STARTED, further
    enrollment is rejected."

    Design: Corner/validations/enrollment_closed_after_start_time
    """
    member = create_member()
    series = create_series(session_count=4, seat_capacity=5, price_cents=12000,
                           starts_at="2026-05-01T18:00:00Z")
    api.set_clock({"to_iso8601": "2026-05-02T00:00:00Z"}, MANAGER)  # past starts_at; sweep STARTs
    res = api.enroll(series["id"], {"member_id": member["id"]}, STAFF)
    validate_error_is_one_of(res, ["ERR_ENROLLMENT_CLOSED", "ERR_INVALID_STATE"])
    after = validate_success(api.get_series(series["id"], MANAGER), 200)
    assert after["enrolled_count"] == 0, after["enrolled_count"]


def test_insufficient_stock_on_consume(api):
    """PRD §3.7: "The item must be ACTIVE and must have at least the requested
    quantity on hand — if the item is discontinued or its on_hand_qty is below the
    requested qty, the consume is rejected with ERR_INSUFFICIENT_STOCK."

    Design: Corner/validations/insufficient_stock_on_consume
    """
    item = create_item(unit_price_cents=500, on_hand=3, sku="GLZ-E", name="Glaze E")
    visit = create_open_visit()
    res = api.consume_supply(visit["id"], {"paint_bar_item_id": item["id"], "qty": 10}, STAFF)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")
    item_after = validate_success(api.get_paint_bar_item(item["id"], STAFF), 200)
    assert item_after["on_hand_qty"] == 3, item_after["on_hand_qty"]


def test_firing_temp_mismatch_on_load(api):
    """PRD §3.4: "the batch's firing_temp must equal the piece's firing_temp." PRD
    §3.4: "a temperature disagreement between the piece and the batch is reported as
    ERR_FIRING_TEMP_MISMATCH."

    Design: Corner/validations/firing_temp_mismatch_on_load
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="HOT-1", name="Hot Piece",
                      firing_temp="CONE_6")
    batch = create_batch(firing_temp="CONE_06", capacity_slots=4)  # version 1
    fresh = validate_success(api.get_batch(batch["id"], STAFF), 200)
    res = api.load_piece(
        batch["id"],
        {"bisque_piece_id": piece["id"], "expected_kiln_batch_version": fresh["version"]},
        STAFF)
    validate_error(res, "ERR_FIRING_TEMP_MISMATCH")
    batch_after = validate_success(api.get_batch(batch["id"], STAFF), 200)
    assert batch_after["occupied_slots"] == 0, batch_after["occupied_slots"]


def test_duplicate_enrollment_rejected(api):
    """PRD §3.10: "a member who already holds a non-cancelled enrollment in this
    series is rejected with ERR_DUPLICATE_ENROLLMENT."

    Design: Corner/validations/duplicate_enrollment_rejected
    """
    member = create_member()
    series = create_series(session_count=4, seat_capacity=5, price_cents=12000,
                           starts_at="2026-07-01T18:00:00Z")
    api.enroll(series["id"], {"member_id": member["id"]}, STAFF)
    res = api.enroll(series["id"], {"member_id": member["id"]}, STAFF)
    validate_error(res, "ERR_DUPLICATE_ENROLLMENT")
    after = validate_success(api.get_series(series["id"], MANAGER), 200)
    assert after["enrolled_count"] == 1, after["enrolled_count"]


def test_discontinued_item_cannot_be_consumed(api):
    """PRD §3.7: "if the item is discontinued or its on_hand_qty is below the
    requested qty, the consume is rejected with ERR_INSUFFICIENT_STOCK." PRD §3.7: "a
    discontinued item can no longer be consumed."

    Design: Corner/validations/discontinued_item_cannot_be_consumed
    """
    item = create_item(unit_price_cents=500, on_hand=20, sku="GLZ-F", name="Glaze F")
    api.discontinue_paint_bar_item(item["id"], MANAGER)
    visit = create_open_visit()
    res = api.consume_supply(visit["id"], {"paint_bar_item_id": item["id"], "qty": 1}, STAFF)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")
    item_after = validate_success(api.get_paint_bar_item(item["id"], STAFF), 200)
    assert item_after["on_hand_qty"] == 20, item_after["on_hand_qty"]


# ─── errors ─────────────────────────────────────────────────────────────────

def test_insufficient_points_on_checkout(api):
    """PRD §3.8: "the requested points_redeemed must not exceed the member's
    point_balance (an over-redemption is rejected with ERR_INSUFFICIENT_POINTS, HTTP
    422)."

    Design: Corner/errors/insufficient_points_on_checkout
    """
    member = create_member()  # balance 0
    visit = create_open_visit(member_id=member["id"])
    fire_piece_to_ready(visit["id"], bisque_price_cents=3000)
    res = api.checkout_visit(visit["id"], {"points_redeemed": 10}, STAFF)
    validate_error(res, "ERR_INSUFFICIENT_POINTS")
    after = validate_success(api.get_visit(visit["id"], STAFF), 200)
    assert after["status"] == "OPEN", after["status"]


def test_visit_not_open_on_add_piece(api):
    """PRD §3.3: "A piece may only be added to a visit whose status is OPEN; an
    attempt to add a piece to a visit that is not OPEN is rejected with
    ERR_VISIT_NOT_OPEN." PRD §3.9: voiding moves the visit "from OPEN to VOIDED,
    which is terminal."

    Design: Corner/errors/visit_not_open_on_add_piece
    """
    visit = create_open_visit()
    api.void_visit(visit["id"], MANAGER)
    res = api.add_piece(visit["id"],
                        {"sku": "MUG-12OZ", "name": "Mug", "bisque_price_cents": 3000}, STAFF)
    validate_error_is_one_of(res, ["ERR_VISIT_NOT_OPEN", "ERR_INVALID_STATE"])
