"""API client: one method per endpoint defined in the PRD."""
from typing import Optional
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD-specific API client — one method per endpoint."""

    # ---- configuration (PlatformAdmin) ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def create_carrier_route(self, payload, headers):
        return self._request("POST", "/carrier-routes", payload, headers)

    def get_carrier_route(self, route_id, headers):
        return self._request("GET", f"/carrier-routes/{route_id}", headers=headers)

    def list_carrier_route_shipments(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/carrier-routes/{route_id}/shipments", headers=headers, params=params
        )

    def create_substitution_rule(self, payload, headers):
        return self._request("POST", "/substitution-rules", payload, headers)

    def list_substitution_rules(self, headers, params=None):
        return self._request("GET", "/substitution-rules", headers=headers, params=params)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_wallet_entries(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/wallet-entries", headers=headers, params=params
        )

    def list_customer_win_back_offers(self, customer_id, headers, params=None):
        return self._request(
            "GET",
            f"/customers/{customer_id}/win-back-offers",
            headers=headers,
            params=params,
        )

    # ---- subscriptions ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscription_shipments(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/subscriptions/{subscription_id}/shipments",
            headers=headers,
            params=params,
        )

    def list_subscription_charges(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/subscriptions/{subscription_id}/charges",
            headers=headers,
            params=params,
        )

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/pause", payload, headers
        )

    def resume_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/resume", payload, headers
        )

    def change_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/change", payload, headers
        )

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", payload, headers
        )

    def cancel_preview_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/cancel-preview", headers=headers
        )

    def renew_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/renew", payload, headers
        )

    # ---- shipments / fulfillment ----
    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def skip_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/skip", payload, headers)

    def source_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/source", payload, headers)

    def create_shipment_allocation(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/shipments/{shipment_id}/allocations", payload, headers
        )

    def list_shipment_allocations(self, shipment_id, headers, params=None):
        return self._request(
            "GET", f"/shipments/{shipment_id}/allocations", headers=headers, params=params
        )

    def confirm_sourced_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/shipments/{shipment_id}/confirm-sourced", payload, headers
        )

    def ship_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/ship", payload, headers)

    def deliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", payload, headers)

    # ---- stem lots ----
    def create_stem_lot(self, payload, headers):
        return self._request("POST", "/stem-lots", payload, headers)

    def get_stem_lot(self, lot_id, headers):
        return self._request("GET", f"/stem-lots/{lot_id}", headers=headers)

    def list_stem_lot_allocations(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/stem-lots/{lot_id}/allocations", headers=headers, params=params
        )

    # ---- billing / win-back ----
    def simulate_payment(self, charge_id, payload, headers):
        return self._request(
            "POST", f"/charges/{charge_id}/simulate-payment", payload, headers
        )

    def refund_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/refund", payload, headers)

    def redeem_win_back_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/win-back-offers/{offer_id}/redeem", payload, headers
        )


api_client = ApiClient()
