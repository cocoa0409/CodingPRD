"""Capacity geometry: restaurant prep-slot half-open time-interval overlap vs
dasher batch aggregate-count capacity.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    make_admin_headers, make_customer_headers, make_dasher_headers,
    create_zone, create_restaurant, create_menu_item, create_customer, create_dasher,
    place_simple_order, place_order, line_item, dispatch, set_clock,
)

ADMIN = make_admin_headers()


# ===========================================================================
# resource_temporal_overlap — prep-slot half-open interval overlap
# ===========================================================================
class TestPrepSlotOverlap:
    def _setup_with_first_scheduled(self):
        """Clock 10:00, restaurant prep 30 / max_concurrent_prep 1, one SCHEDULED
        order at 12:00 (interval [12:00, 12:30))."""
        set_clock("2026-06-07T10:00:00Z")
        zone = create_zone()
        restaurant = create_restaurant(zone["id"], prep_minutes=30, max_concurrent_prep=1)
        item = create_menu_item(restaurant["id"])
        customer = create_customer()
        place_order(customer["id"], restaurant["id"], [line_item(item["id"], 1)],
                    scheduled_for="2026-06-07T12:00:00Z")
        return zone, restaurant, item, customer

    def test_overlapping_scheduled_order_rejected(self, api):
        """PRD §3.6: "If accepting the new order would make the number of mutually overlapping windows exceed the restaurant's `max_concurrent_prep` — that is, if the count of overlapping existing windows plus the new one is greater than `max_concurrent_prep` — the placement is rejected with `ERR_PREP_SLOT_CONFLICT`."

        A 12:15 order ([12:15,12:45)) overlaps the existing [12:00,12:30) with
        max_concurrent_prep 1 -> conflict.

        Design: Difficulty/resource_temporal_overlap/prep_slot_half_open_overlap_on_restaurant
        """
        zone, restaurant, item, customer = self._setup_with_first_scheduled()
        resp = api_client.create_order(
            {"customer_id": customer["id"], "restaurant_id": restaurant["id"],
             "line_items": [{"menu_item_id": item["id"], "quantity": 1}],
             "scheduled_for": "2026-06-07T12:15:00Z"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PREP_SLOT_CONFLICT.value, expected_status=409)

    def test_touching_endpoint_does_not_overlap(self, api):
        """PRD §3.6: "That window is the half-open interval that begins at `scheduled_for` and ends `prep_minutes` later — the start instant is occupied, the end instant is not. ... windows that merely touch at an endpoint (one ending exactly when the next begins) do not overlap."

        A 12:30 order ([12:30,13:00)) only touches the existing [12:00,12:30)
        endpoint -> NO overlap -> accepted as SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/prep_slot_half_open_overlap_on_restaurant
        """
        zone, restaurant, item, customer = self._setup_with_first_scheduled()
        resp = api_client.create_order(
            {"customer_id": customer["id"], "restaurant_id": restaurant["id"],
             "line_items": [{"menu_item_id": item["id"], "quantity": 1}],
             "scheduled_for": "2026-06-07T12:30:00Z"},
            make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["fulfillment_status"] == "SCHEDULED", \
            "an endpoint-touching window must not conflict (half-open semantics)"


# ===========================================================================
# resource_temporal_overlap — dasher batch aggregate-count capacity
# ===========================================================================
class TestDasherBatchCapacity:
    def _setup_batch_full_then_offered(self):
        """One dasher whose active deliveries exceed its batch ceiling, holding an
        OFFERED delivery that cannot be accepted.

        Dispatch eligibility (PRD §3.7) requires active_delivery_count strictly
        less than max_batch_size, so a dasher can never be *offered* a delivery
        once its active count already equals the cap. To reach the
        accept-time ceiling of PRD §3.8 ("counting this delivery the dasher's
        `active_delivery_count` does not exceed `max_batch_size`"), the dasher
        must legitimately accumulate two active deliveries under a cap of 2 and
        then lower the cap (PRD §3.3: "that same `availability`, which a dasher
        may toggle along with `max_batch_size`"). Now the OFFERED delivery's
        accept would make active (2) exceed the new cap (1)."""
        zone = create_zone()
        restaurant = create_restaurant(zone["id"])
        item = create_menu_item(restaurant["id"])
        dasher = create_dasher(zone["id"], max_batch_size=2)
        customer = create_customer()
        dh = make_dasher_headers(dasher["id"])
        # Delivery A: dispatched (active 1) and accepted (still active 1).
        order_a = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=0)
        delivery_a = dispatch(order_a["id"], restaurant["id"], order_a["version"])
        validate_success(api_client.accept_delivery(delivery_a["id"], dh))
        # Delivery B: dispatched to the same dasher (active 1 < cap 2) -> OFFERED
        # (active now 2).
        order_b = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=0)
        delivery_b = dispatch(order_b["id"], restaurant["id"], order_b["version"])
        # Lower the batch ceiling so accepting B would exceed it.
        validate_success(api_client.update_dasher(dasher["id"], {"max_batch_size": 1}, dh))
        return delivery_b["id"], dasher["id"]

    def test_accept_beyond_batch_limit_rejected(self, api):
        """PRD §3.8: "Accepting an offer is permitted ... only if counting this delivery the dasher's `active_delivery_count` does not exceed `max_batch_size` (otherwise `ERR_BATCH_LIMIT_EXCEEDED`)."

        A max_batch_size 1 dasher already holding one ACCEPTED delivery cannot
        accept a second.

        Design: Difficulty/resource_temporal_overlap/dasher_batch_aggregate_capacity_overlap
        """
        delivery_b_id, dasher_id = self._setup_batch_full_then_offered()
        resp = api_client.accept_delivery(delivery_b_id, make_dasher_headers(dasher_id))
        validate_error(resp, ApiErrorId.ERR_BATCH_LIMIT_EXCEEDED.value, expected_status=409)

    def test_batch_limit_is_aggregate_count_not_time(self, api):
        """PRD §3.6: "This time-interval capacity check is distinct from the
        dasher batching check in §3.7, which is a plain count of concurrent
        deliveries rather than an overlap of time windows."

        Confirms the batch ceiling rejects purely on active-delivery count.

        Design: Difficulty/resource_temporal_overlap/dasher_batch_aggregate_capacity_overlap
        """
        delivery_b_id, dasher_id = self._setup_batch_full_then_offered()
        resp = api_client.accept_delivery(delivery_b_id, make_dasher_headers(dasher_id))
        assert resp.status_code == 409
        validate_error(resp, ApiErrorId.ERR_BATCH_LIMIT_EXCEEDED.value)
