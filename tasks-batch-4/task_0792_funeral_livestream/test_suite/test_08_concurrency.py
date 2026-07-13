"""Optimistic concurrency on venue reservation.

Queue-B corner instances under cross_cutting_complexity_layers.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    setup_draft_order, create_booking, get_order,
    create_venue_booking_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def test_second_booking_with_stale_order_version_rejected(api):
    """PRD §2.9: "If that value does not equal the order's current `version` —
    meaning another writer has advanced the order since the client last read it
    — the reservation is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_second_booking_returns_412
    """
    base = setup_draft_order(
        scheduled_start="2026-06-24T10:00:00Z", scheduled_end="2026-06-24T11:00:00Z",
    )
    order = base["order"]
    stale_version = order["version"]  # observed at version 1
    # First booking supersedes and advances the order to version 2.
    create_booking(order["id"], base["venue"]["id"],
                   "2026-06-24T10:00:00Z", "2026-06-24T11:00:00Z", stale_version)
    payload = create_venue_booking_payload(
        order["id"], base["venue"]["id"],
        "2026-06-24T10:00:00Z", "2026-06-24T11:00:00Z", stale_version,  # still 1 -> stale
    )
    validate_error(api.create_venue_booking(payload, ADMIN), ApiErrorId.ERR_STALE_ORDER_VERSION)


def test_booking_create_advances_order_version(api):
    """PRD §3.4: "A new booking is born in `HELD` status, copies the order's
    `home_id`, advances the order's `version` by one, and moves any prior `HELD`
    booking of the same order to `RELEASED`".

    Design: Corner/cross_cutting_complexity_layers/order_version_increments_on_booking_create
    """
    base = setup_draft_order(
        scheduled_start="2026-06-24T10:00:00Z", scheduled_end="2026-06-24T11:00:00Z",
    )
    order = base["order"]
    payload = create_venue_booking_payload(
        order["id"], base["venue"]["id"],
        "2026-06-24T10:00:00Z", "2026-06-24T11:00:00Z", order["version"],
    )
    booking = validate_success(api.create_venue_booking(payload, ADMIN), 201)
    assert booking["status"] == "HELD"
    assert get_order(order["id"])["version"] == 2
