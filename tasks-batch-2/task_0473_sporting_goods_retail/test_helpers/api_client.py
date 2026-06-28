"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() handles the
envelope, base URL, and header plumbing.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- SKUs ----
    def create_sku(self, payload, headers):
        return self._request("POST", "/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/skus", headers=headers, params=params)

    # ---- Stores ----
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Store inventory ----
    def create_store_inventory(self, payload, headers):
        return self._request("POST", "/store-inventory", payload, headers)

    def get_store_inventory(self, inventory_id, headers):
        return self._request(
            "GET", f"/store-inventory/{inventory_id}", headers=headers
        )

    def list_store_inventory(self, headers, params=None):
        return self._request(
            "GET", "/store-inventory", headers=headers, params=params
        )

    def receive_store_inventory(self, inventory_id, payload, headers):
        return self._request(
            "POST", f"/store-inventory/{inventory_id}/receive", payload, headers
        )

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/lines", payload, headers
        )

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/lines", headers=headers, params=params
        )

    def filter_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def place_order(self, order_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/place", {}, headers
        )

    def ready_order(self, order_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/ready", {}, headers
        )

    def fulfill_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/fulfill", payload, headers
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/cancel", {}, headers
        )

    # ---- Service tickets ----
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/service-tickets/{ticket_id}", headers=headers
        )

    def list_service_tickets(self, headers, params=None):
        return self._request(
            "GET", "/service-tickets", headers=headers, params=params
        )

    def start_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/start", {}, headers
        )

    def flag_parts_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/flag-parts", {}, headers
        )

    def resume_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/resume", {}, headers
        )

    def complete_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/complete", {}, headers
        )

    def cancel_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/cancel", {}, headers
        )

    # ---- Fishing licenses ----
    def create_fishing_license(self, payload, headers):
        return self._request("POST", "/fishing-licenses", payload, headers)

    def get_fishing_license(self, license_id, headers):
        return self._request(
            "GET", f"/fishing-licenses/{license_id}", headers=headers
        )

    def list_fishing_licenses(self, headers, params=None):
        return self._request(
            "GET", "/fishing-licenses", headers=headers, params=params
        )

    # ---- Markdowns ----
    def create_markdown(self, payload, headers):
        return self._request("POST", "/markdowns", payload, headers)

    def get_markdown(self, markdown_id, headers):
        return self._request("GET", f"/markdowns/{markdown_id}", headers=headers)

    def list_markdowns(self, headers, params=None):
        return self._request("GET", "/markdowns", headers=headers, params=params)

    # ---- Price-match claims ----
    def create_price_match_claim(self, payload, headers):
        return self._request("POST", "/price-match-claims", payload, headers)

    def get_price_match_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/price-match-claims/{claim_id}", headers=headers
        )

    def list_price_match_claims(self, headers, params=None):
        return self._request(
            "GET", "/price-match-claims", headers=headers, params=params
        )

    def approve_price_match_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/price-match-claims/{claim_id}/approve", {}, headers
        )

    def reject_price_match_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/price-match-claims/{claim_id}/reject", {}, headers
        )

    # ---- Team orders ----
    def create_team_order(self, payload, headers):
        return self._request("POST", "/team-orders", payload, headers)

    def get_team_order(self, team_order_id, headers):
        return self._request(
            "GET", f"/team-orders/{team_order_id}", headers=headers
        )

    def list_team_orders(self, headers, params=None):
        return self._request("GET", "/team-orders", headers=headers, params=params)

    def create_team_order_line(self, team_order_id, payload, headers):
        return self._request(
            "POST", f"/team-orders/{team_order_id}/lines", payload, headers
        )

    def list_team_order_lines(self, team_order_id, headers, params=None):
        return self._request(
            "GET", f"/team-orders/{team_order_id}/lines",
            headers=headers, params=params,
        )

    def filter_team_order_lines(self, headers, params=None):
        return self._request(
            "GET", "/team-order-lines", headers=headers, params=params
        )

    def get_team_order_line(self, line_id, headers):
        return self._request(
            "GET", f"/team-order-lines/{line_id}", headers=headers
        )

    def submit_team_order(self, team_order_id, headers):
        return self._request(
            "POST", f"/team-orders/{team_order_id}/submit", {}, headers
        )

    def approve_team_order(self, team_order_id, headers):
        return self._request(
            "POST", f"/team-orders/{team_order_id}/approve", {}, headers
        )

    def reject_team_order(self, team_order_id, headers):
        return self._request(
            "POST", f"/team-orders/{team_order_id}/reject", {}, headers
        )


api_client = ApiClient()
