"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Categories ---
    def create_category(self, payload, headers):
        return self._request("POST", "/nabs/categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/nabs/categories", headers=headers, params=params)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/nabs/categories/{category_id}", headers=headers)

    def list_category_skus(self, category_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/categories/{category_id}/skus", headers=headers, params=params
        )

    # --- SKUs ---
    def create_sku(self, payload, headers):
        return self._request("POST", "/nabs/skus", payload, headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/nabs/skus", headers=headers, params=params)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/nabs/skus/{sku_id}", headers=headers)

    def update_sku(self, sku_id, payload, headers):
        return self._request("PATCH", f"/nabs/skus/{sku_id}", payload, headers)

    def list_sku_flight_items(self, sku_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/skus/{sku_id}/flight-items", headers=headers, params=params
        )

    def list_sku_special_orders(self, sku_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/skus/{sku_id}/special-orders", headers=headers, params=params
        )

    def list_sku_order_lines(self, sku_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/skus/{sku_id}/order-lines", headers=headers, params=params
        )

    # --- Inventory Lots ---
    def create_lot(self, sku_id, payload, headers):
        return self._request("POST", f"/nabs/skus/{sku_id}/lots", payload, headers)

    def list_lots(self, sku_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/skus/{sku_id}/lots", headers=headers, params=params
        )

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/nabs/lots/{lot_id}", headers=headers)

    def quarantine_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/nabs/lots/{lot_id}/quarantine", payload, headers)

    def release_quarantine(self, lot_id, headers):
        return self._request(
            "POST", f"/nabs/lots/{lot_id}/release-quarantine", {}, headers
        )

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/nabs/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/nabs/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/nabs/members/{member_id}", headers=headers)

    def list_member_orders(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/members/{member_id}/orders", headers=headers, params=params
        )

    def list_member_club_subscriptions(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/members/{member_id}/club-subscriptions",
            headers=headers,
            params=params,
        )

    def list_member_special_orders(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/members/{member_id}/special-orders",
            headers=headers,
            params=params,
        )

    def list_member_attestations(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/members/{member_id}/attestations",
            headers=headers,
            params=params,
        )

    def create_wallet_adjustment(self, member_id, payload, headers):
        return self._request(
            "POST", f"/nabs/members/{member_id}/wallet/adjustments", payload, headers
        )

    def list_member_tasting_events(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/members/{member_id}/tasting-events",
            headers=headers,
            params=params,
        )

    def list_member_tasting_seats(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/members/{member_id}/tasting-seats",
            headers=headers,
            params=params,
        )

    # --- Attestations ---
    def create_attestation(self, member_id, payload, headers):
        return self._request(
            "POST", f"/nabs/members/{member_id}/attestations", payload, headers
        )

    def approve_attestation(self, member_id, attestation_id, headers):
        return self._request(
            "POST",
            f"/nabs/members/{member_id}/attestations/{attestation_id}/approve",
            {},
            headers,
        )

    def reject_attestation(self, member_id, attestation_id, headers):
        return self._request(
            "POST",
            f"/nabs/members/{member_id}/attestations/{attestation_id}/reject",
            {},
            headers,
        )

    def revoke_attestation(self, member_id, headers):
        return self._request(
            "POST", f"/nabs/members/{member_id}/attestations/revoke", {}, headers
        )

    # --- Club Plans ---
    def create_club_plan(self, payload, headers):
        return self._request("POST", "/nabs/club-plans", payload, headers)

    def list_club_plans(self, headers, params=None):
        return self._request("GET", "/nabs/club-plans", headers=headers, params=params)

    def get_club_plan(self, plan_id, headers):
        return self._request("GET", f"/nabs/club-plans/{plan_id}", headers=headers)

    def list_plan_subscriptions(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/club-plans/{plan_id}/subscriptions",
            headers=headers,
            params=params,
        )

    # --- Club Subscriptions ---
    def create_club_subscription(self, payload, headers):
        return self._request("POST", "/nabs/club-subscriptions", payload, headers)

    def get_club_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/nabs/club-subscriptions/{subscription_id}", headers=headers
        )

    def pause_club_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/nabs/club-subscriptions/{subscription_id}/pause", payload, headers
        )

    def resume_club_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/nabs/club-subscriptions/{subscription_id}/resume", {}, headers
        )

    def cancel_club_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/nabs/club-subscriptions/{subscription_id}/cancel", {}, headers
        )

    # --- Tasting Events ---
    def create_tasting_event(self, payload, headers):
        return self._request("POST", "/nabs/tasting-events", payload, headers)

    def list_tasting_events(self, headers, params=None):
        return self._request(
            "GET", "/nabs/tasting-events", headers=headers, params=params
        )

    def get_tasting_event(self, event_id, headers):
        return self._request("GET", f"/nabs/tasting-events/{event_id}", headers=headers)

    def list_event_flight_items(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/tasting-events/{event_id}/flight-items",
            headers=headers,
            params=params,
        )

    def list_event_seats(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/tasting-events/{event_id}/seats", headers=headers, params=params
        )

    def add_flight_item(self, event_id, payload, headers):
        return self._request(
            "POST", f"/nabs/tasting-events/{event_id}/flight-items", payload, headers
        )

    def publish_tasting_event(self, event_id, headers):
        return self._request(
            "POST", f"/nabs/tasting-events/{event_id}/publish", {}, headers
        )

    def cancel_tasting_event(self, event_id, headers):
        return self._request(
            "POST", f"/nabs/tasting-events/{event_id}/cancel", {}, headers
        )

    def reschedule_tasting_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/nabs/tasting-events/{event_id}/reschedule", payload, headers
        )

    # --- Tasting Seats ---
    def book_seat(self, event_id, payload, headers):
        return self._request(
            "POST", f"/nabs/tasting-events/{event_id}/seats", payload, headers
        )

    def confirm_seat(self, seat_id, headers):
        return self._request("POST", f"/nabs/tasting-seats/{seat_id}/confirm", {}, headers)

    def cancel_seat(self, seat_id, headers):
        return self._request("POST", f"/nabs/tasting-seats/{seat_id}/cancel", {}, headers)

    def check_in_seat(self, seat_id, headers):
        return self._request(
            "POST", f"/nabs/tasting-seats/{seat_id}/check-in", {}, headers
        )

    def refund_seat(self, seat_id, headers):
        return self._request("POST", f"/nabs/tasting-seats/{seat_id}/refund", {}, headers)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/nabs/tasting-seats/{seat_id}", headers=headers)

    # --- Special Orders ---
    def create_special_order(self, payload, headers):
        return self._request("POST", "/nabs/special-orders", payload, headers)

    def get_special_order(self, special_order_id, headers):
        return self._request(
            "GET", f"/nabs/special-orders/{special_order_id}", headers=headers
        )

    def approve_special_order(self, special_order_id, payload, headers):
        return self._request(
            "POST", f"/nabs/special-orders/{special_order_id}/approve", payload, headers
        )

    def decline_special_order(self, special_order_id, payload, headers):
        return self._request(
            "POST", f"/nabs/special-orders/{special_order_id}/decline", payload, headers
        )

    def mark_special_order_sourced(self, special_order_id, headers):
        return self._request(
            "POST", f"/nabs/special-orders/{special_order_id}/mark-sourced", {}, headers
        )

    def receive_special_order(self, special_order_id, payload, headers):
        return self._request(
            "POST", f"/nabs/special-orders/{special_order_id}/receive", payload, headers
        )

    def fulfill_special_order(self, special_order_id, headers):
        return self._request(
            "POST", f"/nabs/special-orders/{special_order_id}/fulfill", {}, headers
        )

    def cancel_special_order(self, special_order_id, headers):
        return self._request(
            "POST", f"/nabs/special-orders/{special_order_id}/cancel", {}, headers
        )

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/nabs/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/nabs/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/nabs/orders/{order_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/orders/{order_id}/lines", headers=headers, params=params
        )

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/nabs/orders/{order_id}/lines", payload, headers)

    def delete_order_line(self, order_id, line_id, headers):
        return self._request(
            "DELETE", f"/nabs/orders/{order_id}/lines/{line_id}", headers=headers
        )

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"/nabs/orders/{order_id}/submit", payload, headers)

    def pack_order(self, order_id, headers):
        return self._request("POST", f"/nabs/orders/{order_id}/pack", {}, headers)

    def pickup_order(self, order_id, headers):
        return self._request("POST", f"/nabs/orders/{order_id}/pickup", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/nabs/orders/{order_id}/cancel", {}, headers)

    def create_shipment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/nabs/orders/{order_id}/shipments", payload, headers
        )

    # --- Shipments ---
    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/nabs/shipments/{shipment_id}", headers=headers)

    def list_order_shipments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/nabs/orders/{order_id}/shipments", headers=headers, params=params
        )

    def list_subscription_shipments(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/club-subscriptions/{subscription_id}/shipments",
            headers=headers,
            params=params,
        )

    def list_subscription_orders(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/nabs/club-subscriptions/{subscription_id}/orders",
            headers=headers,
            params=params,
        )

    def mark_shipment_in_transit(self, shipment_id, headers):
        return self._request(
            "POST", f"/nabs/shipments/{shipment_id}/mark-in-transit", {}, headers
        )

    def mark_shipment_out_for_delivery(self, shipment_id, headers):
        return self._request(
            "POST", f"/nabs/shipments/{shipment_id}/mark-out-for-delivery", {}, headers
        )

    def mark_shipment_delivered(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/nabs/shipments/{shipment_id}/mark-delivered", payload, headers
        )

    def mark_shipment_returned(self, shipment_id, headers):
        return self._request(
            "POST", f"/nabs/shipments/{shipment_id}/mark-returned", {}, headers
        )

    def mark_shipment_lost(self, shipment_id, headers):
        return self._request(
            "POST", f"/nabs/shipments/{shipment_id}/mark-lost", {}, headers
        )

    # --- Shipping State Rules ---
    def create_shipping_state_rule(self, payload, headers):
        return self._request("POST", "/nabs/shipping-state-rules", payload, headers)

    def list_shipping_state_rules(self, headers, params=None):
        return self._request(
            "GET", "/nabs/shipping-state-rules", headers=headers, params=params
        )

    def get_shipping_state_rule(self, rule_id, headers):
        return self._request(
            "GET", f"/nabs/shipping-state-rules/{rule_id}", headers=headers
        )

    # --- Test-driving endpoints (logical clock + billing simulation) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/nabs/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def simulate_billing(self, club_subscription_id, outcome, headers):
        return self._request(
            "POST",
            "/nabs/_billing/simulate",
            {"club_subscription_id": club_subscription_id, "outcome": outcome},
            headers,
        )


api_client = ApiClient()
