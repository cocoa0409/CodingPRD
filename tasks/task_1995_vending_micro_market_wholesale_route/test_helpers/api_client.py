"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Operators (PRD §3.1)
    # ------------------------------------------------------------------
    def create_operator(self, payload, headers):
        return self._request("POST", "/wholesale/operators", payload, headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", "/wholesale/operators", headers=headers, params=params)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/wholesale/operators/{operator_id}", headers=headers)

    def suspend_operator(self, operator_id, headers):
        return self._request("POST", f"/wholesale/operators/{operator_id}/suspend", {}, headers)

    def reinstate_operator(self, operator_id, headers):
        return self._request("POST", f"/wholesale/operators/{operator_id}/reinstate", {}, headers)

    # ------------------------------------------------------------------
    # Delivery routes (PRD §3.2)
    # ------------------------------------------------------------------
    def create_route(self, payload, headers):
        return self._request("POST", "/wholesale/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/wholesale/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/wholesale/routes/{route_id}", headers=headers)

    def get_route_availability(self, route_id, date, headers):
        return self._request("GET", f"/wholesale/routes/{route_id}/availability",
                             {"date": date}, headers)

    # ------------------------------------------------------------------
    # Products (PRD §3.2)
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/wholesale/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/wholesale/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/wholesale/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/wholesale/products/{product_id}/discontinue", {}, headers)

    # ------------------------------------------------------------------
    # Locations (PRD §3.3)
    # ------------------------------------------------------------------
    def create_location(self, payload, headers):
        return self._request("POST", "/wholesale/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/wholesale/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/wholesale/locations/{location_id}", headers=headers)

    def list_location_telemetry_events(self, location_id, headers, params=None):
        return self._request("GET", f"/wholesale/locations/{location_id}/telemetry-events",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Planograms (PRD §3.3)
    # ------------------------------------------------------------------
    def create_planogram(self, payload, headers):
        return self._request("POST", "/wholesale/planograms", payload, headers)

    def list_planograms(self, headers, params=None):
        return self._request("GET", "/wholesale/planograms", headers=headers, params=params)

    def get_planogram(self, planogram_id, headers):
        return self._request("GET", f"/wholesale/planograms/{planogram_id}", headers=headers)

    def activate_planogram(self, planogram_id, payload, headers):
        return self._request("POST", f"/wholesale/planograms/{planogram_id}/activate",
                             payload, headers)

    def cull_evaluate_planogram(self, planogram_id, headers):
        return self._request("POST", f"/wholesale/planograms/{planogram_id}/cull-evaluate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Promotions (PRD §3.5)
    # ------------------------------------------------------------------
    def create_promotion(self, payload, headers):
        return self._request("POST", "/wholesale/promotions", payload, headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/wholesale/promotions", headers=headers, params=params)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/wholesale/promotions/{promotion_id}", headers=headers)

    def terminate_promotion(self, promotion_id, headers):
        return self._request("POST", f"/wholesale/promotions/{promotion_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Telemetry events (PRD §3.4; append-only DEX log)
    # ------------------------------------------------------------------
    def create_telemetry_event(self, payload, headers):
        return self._request("POST", "/wholesale/telemetry-events", payload, headers)

    # ------------------------------------------------------------------
    # Replenishment orders (PRD §3.5, §3.6)
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/wholesale/orders", payload, headers)

    def generate_order_from_telemetry(self, payload, headers):
        return self._request("POST", "/wholesale/orders/generate-from-telemetry",
                             payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/wholesale/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/wholesale/orders/{order_id}", headers=headers)

    def patch_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/wholesale/orders/{order_id}", payload, headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/submit", {}, headers)

    def revise_order(self, order_id, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/revise", {}, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/confirm", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/cancel", {}, headers)

    def mark_order_delivered(self, order_id, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/mark-delivered", {}, headers)

    def apply_credit_to_order(self, order_id, payload, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/apply-credit",
                             payload, headers)

    def settle_order(self, order_id, payload, headers):
        return self._request("POST", f"/wholesale/orders/{order_id}/settle", payload, headers)

    # ------------------------------------------------------------------
    # Credit claims (PRD §3.7)
    # ------------------------------------------------------------------
    def create_credit_claim(self, payload, headers):
        return self._request("POST", "/wholesale/credit-claims", payload, headers)

    def list_credit_claims(self, headers, params=None):
        return self._request("GET", "/wholesale/credit-claims", headers=headers, params=params)

    def get_credit_claim(self, claim_id, headers):
        return self._request("GET", f"/wholesale/credit-claims/{claim_id}", headers=headers)

    def approve_credit_claim(self, claim_id, headers):
        return self._request("POST", f"/wholesale/credit-claims/{claim_id}/approve", {}, headers)

    def reject_credit_claim(self, claim_id, headers):
        return self._request("POST", f"/wholesale/credit-claims/{claim_id}/reject", {}, headers)

    def void_credit_claim(self, claim_id, headers):
        return self._request("POST", f"/wholesale/credit-claims/{claim_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Service tickets (PRD §3.8)
    # ------------------------------------------------------------------
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/wholesale/service-tickets", payload, headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/wholesale/service-tickets", headers=headers, params=params)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/wholesale/service-tickets/{ticket_id}", headers=headers)

    def schedule_service_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/wholesale/service-tickets/{ticket_id}/schedule",
                             payload, headers)

    def complete_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/wholesale/service-tickets/{ticket_id}/complete", {}, headers)


api_client = ApiClient()
