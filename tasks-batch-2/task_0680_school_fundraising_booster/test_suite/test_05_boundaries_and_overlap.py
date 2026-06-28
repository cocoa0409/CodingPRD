"""Numeric boundaries (prize-tier threshold, stock headroom) and the shift
overlap guard (half-open intervals, buffer extension).

Covers difficulty queue A rules: boundary_precision_check, resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_active_catalog, setup_active_event,
    place_simple_order, add_prize_tier, add_volunteer, add_shift, book_shift,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


# ─── boundary_precision_check / prize_tier_earned_at_exact_threshold ───────

class TestPrizeTierExactThreshold:
    def _setup_two_tiers_at_and_above(self):
        """Tiers AT(10825) and ABOVE(10826); one PLACED order of 5 units
        (total 10825). Returns (seller, tier_at_id, order)."""
        camp, seller, product = setup_active_catalog()
        # setup_active_catalog adds T1@5000; add the two boundary tiers.
        tier_at = add_prize_tier(camp["id"], label="AT", threshold_cents=10825)
        add_prize_tier(camp["id"], label="ABOVE", threshold_cents=10826)
        order = place_simple_order(camp["id"], seller["id"], product["id"], 5)  # total 10825
        return seller, tier_at["id"], order

    def test_credit_equal_to_threshold_earns_tier(self, api):
        """PRD §3.6: "The boundary is inclusive: a `credited_cents` exactly equal
        to a tier's `threshold_cents` earns that tier, while a
        `credited_cents` one cent below does not."

        Design: Difficulty/boundary_precision_check/prize_tier_earned_at_exact_threshold
        """
        seller, tier_at_id, order = self._setup_two_tiers_at_and_above()
        api_client.pay_order(order["id"], ADMIN)
        after = validate_success(api_client.get_seller(seller["id"], TREASURER), 200)
        assert after["credited_cents"] == 10825
        assert after["earned_prize_tier_id"] == tier_at_id, \
            "credited == threshold (10825) must earn the AT tier, not the 10826 tier"

    def test_above_tier_not_earned_at_exact_lower_threshold(self, api):
        """PRD §3.6: "the seller earns the single highest tier whose
        `threshold_cents` is less than or equal to their `credited_cents`."

        Design: Difficulty/boundary_precision_check/prize_tier_earned_at_exact_threshold
        """
        seller, tier_at_id, order = self._setup_two_tiers_at_and_above()
        api_client.pay_order(order["id"], ADMIN)
        after = validate_success(api_client.get_seller(seller["id"], TREASURER), 200)
        # The earned tier is the 10825 one; the 10826 tier must NOT be the result.
        assert after["earned_prize_tier_id"] == tier_at_id, \
            "the 10826 tier must not be earned at credited 10825"


# ─── boundary_precision_check / order_create_exactly_at_stock_headroom_succeeds

class TestStockHeadroomBoundary:
    def test_order_exactly_at_headroom_succeeds(self, api, admin_headers):
        """PRD §3.4: "the requested quantity for a product must be no greater
        than that product's `stock_qty` minus its current `reserved_qty`, with
        the boundary inclusive so that exactly exhausting the headroom is
        allowed."

        Design: Difficulty/boundary_precision_check/order_create_exactly_at_stock_headroom_succeeds
        """
        camp, seller, product = setup_active_catalog(stock_qty=10)
        res = api.create_order({
            "campaign_id": camp["id"], "seller_id": seller["id"],
            "buyer_name": "B", "buyer_email": "b@x.com",
            "lines": [{"product_id": product["id"], "quantity": 10}],
        }, admin_headers)
        order = validate_success(res, 201)
        assert order["fulfillment_status"] == "PLACED"

    def test_order_exactly_at_headroom_reserves_all_units(self, api, admin_headers):
        """PRD §3.4: "A product's `reserved_qty` is itself a roll-up: it is the
        sum, over every order of the campaign whose `fulfillment_status` is
        `PLACED` or `CONFIRMED`, of the quantities of that order's lines
        naming the product."

        Design: Difficulty/boundary_precision_check/order_create_exactly_at_stock_headroom_succeeds
        """
        camp, seller, product = setup_active_catalog(stock_qty=10)
        validate_success(api.create_order({
            "campaign_id": camp["id"], "seller_id": seller["id"],
            "buyer_name": "B", "buyer_email": "b@x.com",
            "lines": [{"product_id": product["id"], "quantity": 10}],
        }, admin_headers), 201)
        prod = validate_success(api.get_product(product["id"], admin_headers), 200)
        assert prod["reserved_qty"] == 10, \
            f"an order at exactly the headroom reserves all 10 units, got {prod['reserved_qty']}"


# ─── resource_temporal_overlap / shift_overlap_half_open_no_buffer ─────────

class TestShiftOverlapHalfOpenNoBuffer:
    def _setup_overlapping_open_shift(self):
        """Volunteer with shift A [09:00,12:00) BOOKED; shift B [11:00,13:00)
        OPEN, buffer 0. Returns (volunteer, shift_b)."""
        camp, _ = setup_active_event()
        volunteer = add_volunteer(camp["id"])
        shift_a = add_shift(camp["id"], "2026-04-10T09:00:00Z", "2026-04-10T12:00:00Z",
                            role_label="A", setup_buffer_minutes=0)
        book_shift(shift_a["id"], volunteer["id"])
        shift_b = add_shift(camp["id"], "2026-04-10T11:00:00Z", "2026-04-10T13:00:00Z",
                            role_label="B", setup_buffer_minutes=0)
        return volunteer, shift_b

    def test_overlapping_book_rejected(self, api, admin_headers):
        """PRD §3.9: "the requested shift's buffer-extended interval — from
        `setup_buffer_minutes` before its `starts_at` up to but not including
        its `ends_at` — must not overlap any other shift the same volunteer
        already has `BOOKED`. A booking that would overlap is rejected with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/shift_overlap_half_open_no_buffer
        """
        volunteer, shift_b = self._setup_overlapping_open_shift()
        res = api.book_shift(shift_b["id"], {"volunteer_id": volunteer["id"]}, admin_headers)
        validate_error(res, "ERR_SHIFT_OVERLAP", expected_status=409)

    def test_overlapping_book_leaves_shift_open(self, api, admin_headers):
        """PRD §3.9: "Booking a shift moves it from `OPEN` to `BOOKED` and
        assigns a `volunteer_id`."

        Design: Difficulty/resource_temporal_overlap/shift_overlap_half_open_no_buffer
        """
        volunteer, shift_b = self._setup_overlapping_open_shift()
        api.book_shift(shift_b["id"], {"volunteer_id": volunteer["id"]}, admin_headers)
        after = validate_success(api.get_shift(shift_b["id"], admin_headers), 200)
        assert after["status"] == "OPEN", "a rejected overlapping book must leave the shift OPEN"


# ─── resource_temporal_overlap / shift_overlap_only_via_setup_buffer ───────

class TestShiftOverlapViaBuffer:
    def _setup_buffer_overlap_open_shift(self):
        """Shift A [09:00,12:00) BOOKED; shift B [12:30,14:00) OPEN with
        setup_buffer_minutes 45 (guard back to 11:45). Returns (volunteer, shift_b)."""
        camp, _ = setup_active_event()
        volunteer = add_volunteer(camp["id"])
        shift_a = add_shift(camp["id"], "2026-04-10T09:00:00Z", "2026-04-10T12:00:00Z",
                            role_label="A", setup_buffer_minutes=0)
        book_shift(shift_a["id"], volunteer["id"])
        shift_b = add_shift(camp["id"], "2026-04-10T12:30:00Z", "2026-04-10T14:00:00Z",
                            role_label="B", setup_buffer_minutes=45)
        return volunteer, shift_b

    def test_buffer_extension_causes_overlap_rejection(self, api, admin_headers):
        """PRD §3.9: "Booking is further guarded against double-booking: the
        requested shift's buffer-extended interval — from
        `setup_buffer_minutes` before its `starts_at` up to but not including
        its `ends_at` — must not overlap any other shift the same volunteer
        already has `BOOKED`. A booking that would overlap is rejected with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/shift_overlap_only_via_setup_buffer
        """
        volunteer, shift_b = self._setup_buffer_overlap_open_shift()
        res = api.book_shift(shift_b["id"], {"volunteer_id": volunteer["id"]}, admin_headers)
        validate_error(res, "ERR_SHIFT_OVERLAP", expected_status=409)

    def test_buffer_overlap_leaves_shift_open(self, api, admin_headers):
        """PRD §3.9: "The `setup_buffer_minutes` does not count toward
        `committed_minutes`; it only widens the overlap-guard interval at
        booking time."

        Design: Difficulty/resource_temporal_overlap/shift_overlap_only_via_setup_buffer
        """
        volunteer, shift_b = self._setup_buffer_overlap_open_shift()
        api.book_shift(shift_b["id"], {"volunteer_id": volunteer["id"]}, admin_headers)
        after = validate_success(api.get_shift(shift_b["id"], admin_headers), 200)
        assert after["status"] == "OPEN"
