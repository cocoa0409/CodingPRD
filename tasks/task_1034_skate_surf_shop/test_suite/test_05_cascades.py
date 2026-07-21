"""Depth-3 transitive cascades.

Difficulty instances: lesson_cancel_releases_rental_frees_asset_depth3,
event_cancel_cancels_entries_reverses_loyalty_depth3.
"""
from test_helpers import validate_success, TEST_USERS
import test_helpers as th

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]


# --------------------------------------------------------------------------- #
# Lesson cancel -> Rental release -> asset freed + deposit refunded
# --------------------------------------------------------------------------- #
def _lesson_linked_reserved_rental(api):
    coach = th.create_coach(api, name="Coach A", discipline="SURF")
    customer = th.create_customer(api, email="casc@x.com", full_name="Cass Cade")
    lesson = th.create_scheduled_lesson(api, coach["id"], customer["id"], discipline="SURF",
                                        start_at="2026-07-03T10:00:00Z", end_at="2026-07-03T11:00:00Z")
    prod, asset = th.create_rentable_product_and_asset(
        api,
        product_overrides={"sku": "WS-1", "name": "Wetsuit", "category": "WETSUIT",
                           "unit_price_cents": 12000, "rental_day_rate_cents": 1500},
        asset_overrides={"asset_tag": "WS-A1"},
    )
    rental = th.create_rental(api, customer["id"], asset["id"], lesson_id=lesson["id"],
                              start_at="2026-07-03T00:00:00Z", end_at="2026-07-04T00:00:00Z", deposit_cents=3000)
    return lesson, rental, asset


def test_lesson_cancel_releases_linked_rental_and_refunds(api):
    """PRD §3.3: "Every rental whose `lesson_id` points at the cancelled lesson and whose fulfillment is still `RESERVED` is released as part of the cancellation (the first hop of the cascade): each such rental's `fulfillment_status` moves from `RESERVED` to `RELEASED`. That release in turn (the second hop) sets the rental's `payment_status` from `DEPOSIT_HELD` to `DEPOSIT_REFUNDED` and transitions its rental asset from `RESERVED` back to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/lesson_cancel_releases_rental_frees_asset_depth3
    """
    lesson, rental, asset = _lesson_linked_reserved_rental(api)
    resp = api.cancel_lesson(lesson["id"], SA)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "CANCELLED"
    rental_read = validate_success(api.get_rental(rental["id"], SA))
    assert rental_read["fulfillment_status"] == "RELEASED"
    assert rental_read["payment_status"] == "DEPOSIT_REFUNDED"


def test_lesson_cancel_frees_underlying_asset(api):
    """PRD §3.3: "That release in turn (the second hop) sets the rental's `payment_status` from `DEPOSIT_HELD` to `DEPOSIT_REFUNDED` and transitions its rental asset from `RESERVED` back to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/lesson_cancel_releases_rental_frees_asset_depth3
    """
    lesson, rental, asset = _lesson_linked_reserved_rental(api)
    validate_success(api.cancel_lesson(lesson["id"], SA))
    asset_read = validate_success(api.get_rental_asset(asset["id"], SA))
    assert asset_read["status"] == "AVAILABLE"


# --------------------------------------------------------------------------- #
# Event cancel -> entry cancel -> loyalty reversal + entry_count decrement
# --------------------------------------------------------------------------- #
def test_event_cancel_cascades_entry_cancel_and_loyalty_reversal(api):
    """PRD §3.9: "Cancelling an event cascades: every `REGISTERED` entry for the event is moved to `CANCELLED` (the first hop), and each of those entry cancellations (the second hop) reverses that entry's awarded points from the member's `loyalty_points` and decrements the event's `entry_count`."

    Design: Difficulty/transitive_cascade/event_cancel_cancels_entries_reverses_loyalty_depth3
    """
    customer = th.create_customer(api, email="ev@x.com", full_name="Eve Entrant")
    event = th.create_published_event(api, name="Summer Demo", sponsor="BrandX", venue="North Beach",
                                      start_at="2026-07-10T00:00:00Z", capacity=10, entry_fee_cents=5000)
    entry = th.create_registered_entry(api, event["id"], customer["id"], role="TEAM_RIDER")
    assert entry["points_awarded"] == 100  # floor(50 * 1.0 * 2.0) at BRONZE
    resp = api.cancel_event(event["id"], SM)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "CANCELLED"
    entry_read = validate_success(api.get_event_entry(entry["id"], SA))
    assert entry_read["status"] == "CANCELLED"
    customer_read = validate_success(api.get_customer(customer["id"], SA))
    assert customer_read["loyalty_points"] == 0


def test_event_cancel_decrements_entry_count(api):
    """PRD §3.9: "each of those entry cancellations (the second hop) reverses that entry's awarded points from the member's `loyalty_points` and decrements the event's `entry_count`."

    Design: Difficulty/transitive_cascade/event_cancel_cancels_entries_reverses_loyalty_depth3
    """
    customer = th.create_customer(api, email="ev2@x.com", full_name="Eve Two")
    event = th.create_published_event(api, name="Summer Demo 2", sponsor="BrandX", venue="South Beach",
                                      start_at="2026-07-10T00:00:00Z", capacity=10, entry_fee_cents=5000)
    entry = th.create_registered_entry(api, event["id"], customer["id"], role="TEAM_RIDER")
    resp = api.cancel_event(event["id"], SM)
    data = validate_success(resp, expected_status=200)
    assert data["entry_count"] == 0
