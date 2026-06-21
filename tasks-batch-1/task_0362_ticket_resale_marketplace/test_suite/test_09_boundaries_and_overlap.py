"""Boundary precision and resource/temporal overlap.

Strict-less transfer-deadline acceptance, zero/at-boundary seat availability,
unique barcode-token occupancy, and held-seat capacity windows (PRD §3.3, §3.4,
§3.6).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS, make_seller_headers, make_buyer_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]


# ==========================================================================
# boundary_precision_check
# ==========================================================================
def test_transfer_accept_at_exact_deadline_is_rejected_strict_less(api):
    """PRD §3.6: "Acceptance at or after the deadline is rejected with
    `ERR_TRANSFER_DEADLINE_PASSED` — the boundary is half-open, so acceptance is
    valid only while the clock is strictly less than `deadline_at`."
    PRD §3.6: "If the transfer is not last-minute, the deadline is the send time
    plus the standard window of 1440 minutes (one full day)."

    Design: Difficulty/boundary_precision_check/transfer_accept_at_exact_deadline_is_rejected_strict_less
    """
    fx.set_clock("2027-07-01T10:00:00.000Z")
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1,
                            doors_open_at="2027-08-01T19:00:00.000Z",
                            last_minute_cutoff_minutes=180)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="TD",
    )
    order = fx.reserve_and_charge(listing["id"], base["buyer_id"], 1, listing["version"])
    seller_h = make_seller_headers(base["seller_id"])
    buyer_h = make_buyer_headers(base["buyer_id"])

    transfer = get_success_data(api.initiate_transfer(order["id"], seller_h))
    sent = validate_success(api.send_transfer(transfer["id"], seller_h))
    # not last-minute → deadline = 2027-07-01T10:00 + 1440min = 2027-07-02T10:00:00.000Z
    assert sent["deadline_at"] == "2027-07-02T10:00:00.000Z", \
        f"standard deadline send+1440min, got {sent['deadline_at']}"

    # Clock to EXACTLY deadline → accept rejected (strict <).
    fx.set_clock("2027-07-02T10:00:00.000Z")
    resp = api.accept_transfer(transfer["id"], buyer_h)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_DEADLINE_PASSED.value)


def test_zero_available_seats_blocks_order_create_empty_inventory(api):
    """PRD §3.4: "The requested `quantity` may not exceed the listing's
    `available_seat_count`, or the reservation is rejected with
    `ERR_INSUFFICIENT_SEATS`."
    PRD §2.5: "while `available_seat_count` is greater than zero the listing is
    `ACTIVE`, and when `available_seat_count` reaches zero it becomes `SOLD_OUT`."

    Design: Difficulty/boundary_precision_check/zero_available_seats_blocks_order_create_empty_inventory
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1)
    buyer2 = fx.create_buyer("B2")
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="ZS",
    )
    # Sell the single seat → available_seat_count 0.
    fx.reserve_and_charge(listing["id"], base["buyer_id"], 1, listing["version"])

    current = validate_success(api.get_listing(listing["id"], make_buyer_headers(buyer2["id"])))
    assert current["available_seat_count"] == 0

    payload = F.create_order_payload(listing["id"], buyer2["id"], current["version"], quantity=1)
    resp = api.create_order(payload, make_buyer_headers(buyer2["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SEATS.value)


# ==========================================================================
# resource_temporal_overlap
# ==========================================================================
def test_barcode_token_uniqueness_across_live_seats_point_overlap(api):
    """PRD §3.3: "The `barcode_token` must be unique across all live (non-`VOID`)
    seats in the system; reusing a token still held by a non-`VOID` seat is
    rejected with `ERR_DUPLICATE_BARCODE`."

    Design: Difficulty/resource_temporal_overlap/barcode_token_uniqueness_across_live_seats_point_overlap
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2, open_for_sale=False)
    seller_h = make_seller_headers(base["seller_id"])
    listing = fx.create_draft_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        delivery_method="BARCODE_PDF",
    )
    get_success_data(api.create_seat(
        F.create_seat_payload(listing["id"], row_label="1", seat_number=1, barcode_token="UNQ-1"),
        seller_h))

    resp = api.create_seat(
        F.create_seat_payload(listing["id"], row_label="1", seat_number=2, barcode_token="UNQ-1"),
        seller_h)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BARCODE.value)


def test_reservation_holds_seats_blocking_overlapping_quantity_window(api):
    """PRD §3.4: "The requested `quantity` may not exceed the listing's
    `available_seat_count`, or the reservation is rejected with
    `ERR_INSUFFICIENT_SEATS`."
    PRD §3.4: "the system takes `quantity` seats from the pool in FIFO order by
    their `created_at` (earliest first), moving each from `AVAILABLE` to `HELD`
    and stamping each held seat's `order_id`; the listing's `available_seat_count`
    drops accordingly and `Listing.version` increments."

    Design: Difficulty/resource_temporal_overlap/reservation_holds_seats_blocking_overlapping_quantity_window
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=3)
    buyer1, buyer2 = base["buyer"], fx.create_buyer("B2")
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=3, barcode_prefix="OV",
    )
    # buyer1 holds 2 of 3 seats → available drops to 1.
    fx.reserve_order(listing["id"], buyer1["id"], 2, listing["version"])

    current = validate_success(api.get_listing(listing["id"], make_buyer_headers(buyer2["id"])))
    assert current["available_seat_count"] == 1, \
        f"after holding 2 of 3, available should be 1, got {current['available_seat_count']}"

    # buyer2 requests 2 → overlaps held window → insufficient.
    payload = F.create_order_payload(listing["id"], buyer2["id"], current["version"], quantity=2)
    resp = api.create_order(payload, make_buyer_headers(buyer2["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SEATS.value)


# ==========================================================================
# Companion tests (second test per Difficulty instance)
# ==========================================================================
def test_transfer_accept_strictly_before_deadline_succeeds(api):
    """PRD §3.6: "the boundary is half-open, so acceptance is valid only while the
    clock is strictly less than `deadline_at`."
    PRD §3.6: "Acceptance moves the order's `delivery_status` to `DELIVERED` and
    turns the order's `SOLD` seats into `TRANSFERRED`, and the order's
    `lifecycle_state` is recomputed."

    Design: Difficulty/boundary_precision_check/transfer_accept_at_exact_deadline_is_rejected_strict_less
    """
    fx.set_clock("2027-07-01T10:00:00.000Z")
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1,
                            doors_open_at="2027-08-01T19:00:00.000Z",
                            last_minute_cutoff_minutes=180)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="TDOK",
    )
    order = fx.reserve_and_charge(listing["id"], base["buyer_id"], 1, listing["version"])
    seller_h = make_seller_headers(base["seller_id"])
    buyer_h = make_buyer_headers(base["buyer_id"])

    transfer = get_success_data(api.initiate_transfer(order["id"], seller_h))
    sent = validate_success(api.send_transfer(transfer["id"], seller_h))
    assert sent["deadline_at"] == "2027-07-02T10:00:00.000Z"

    # One minute before the deadline → accept succeeds.
    fx.set_clock("2027-07-02T09:59:00.000Z")
    accepted = validate_success(api.accept_transfer(transfer["id"], buyer_h))
    assert accepted["status"] == "ACCEPTED"
    delivered = validate_success(api.get_order(order["id"], buyer_h))
    assert delivered["delivery_status"] == "DELIVERED"


def test_reservation_with_available_seats_succeeds_at_boundary(api):
    """PRD §3.4: "The requested `quantity` may not exceed the listing's
    `available_seat_count`, or the reservation is rejected with
    `ERR_INSUFFICIENT_SEATS`."

    Design: Difficulty/boundary_precision_check/zero_available_seats_blocks_order_create_empty_inventory
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, barcode_prefix="AV1",
    )
    # quantity == available_seat_count (1) is the inclusive boundary → succeeds.
    order = fx.reserve_order(listing["id"], base["buyer_id"], 1, listing["version"])
    assert order["quantity"] == 1
    after = validate_success(api.get_listing(listing["id"], make_buyer_headers(base["buyer_id"])))
    assert after["available_seat_count"] == 0
    assert after["status"] == "SOLD_OUT"


def test_distinct_barcode_tokens_both_addable(api):
    """PRD §3.3: "The `barcode_token` must be unique across all live (non-`VOID`)
    seats in the system; reusing a token still held by a non-`VOID` seat is
    rejected with `ERR_DUPLICATE_BARCODE`."

    Design: Difficulty/resource_temporal_overlap/barcode_token_uniqueness_across_live_seats_point_overlap
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=2, open_for_sale=False)
    seller_h = make_seller_headers(base["seller_id"])
    listing = fx.create_draft_listing(
        base["event_id"], base["seller_id"], base["section_id"], delivery_method="BARCODE_PDF")

    # Adding a seat creates a new stand-alone resource → 201 Created (PRD §4).
    s1 = validate_success(api.create_seat(
        F.create_seat_payload(listing["id"], row_label="1", seat_number=1, barcode_token="DST-1"),
        seller_h), 201)
    s2 = validate_success(api.create_seat(
        F.create_seat_payload(listing["id"], row_label="1", seat_number=2, barcode_token="DST-2"),
        seller_h), 201)
    assert s1["barcode_token"] == "DST-1"
    assert s2["barcode_token"] == "DST-2"
    assert s1["status"] == "AVAILABLE" and s2["status"] == "AVAILABLE"


def test_reservation_within_available_capacity_window_succeeds(api):
    """PRD §3.4: "the system takes `quantity` seats from the pool in FIFO order by
    their `created_at` (earliest first), moving each from `AVAILABLE` to `HELD`
    and stamping each held seat's `order_id`; the listing's `available_seat_count`
    drops accordingly and `Listing.version` increments."

    Design: Difficulty/resource_temporal_overlap/reservation_holds_seats_blocking_overlapping_quantity_window
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=3)
    buyer1, buyer2 = base["buyer"], fx.create_buyer("B2")
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=3, barcode_prefix="OV2",
    )
    fx.reserve_order(listing["id"], buyer1["id"], 2, listing["version"])
    current = validate_success(api.get_listing(listing["id"], make_buyer_headers(buyer2["id"])))
    assert current["available_seat_count"] == 1

    # buyer2 requests exactly the 1 remaining seat → fits the window → succeeds.
    order = fx.reserve_order(listing["id"], buyer2["id"], 1, current["version"])
    assert order["quantity"] == 1
