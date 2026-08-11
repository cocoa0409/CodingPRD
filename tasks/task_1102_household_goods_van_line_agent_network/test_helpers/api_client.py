"""API client: one method per endpoint defined in the PRD section 4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Agents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def suspend_agent(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/suspend", payload, headers)

    def reactivate_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/reactivate", {}, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Tariffs ---
    def create_tariff(self, payload, headers):
        return self._request("POST", "/tariffs", payload, headers)

    def publish_tariff(self, tariff_id, headers):
        return self._request("POST", f"/tariffs/{tariff_id}/publish", {}, headers)

    def list_tariffs(self, headers, params=None):
        return self._request("GET", "/tariffs", headers=headers, params=params)

    def get_tariff(self, tariff_id, headers):
        return self._request("GET", f"/tariffs/{tariff_id}", headers=headers)

    # --- Move orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def book_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/book", {}, headers)

    def dispatch_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/dispatch", {}, headers)

    def deliver_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", payload, headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/close", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def post_payment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/payments", payload, headers)

    # --- Estimates ---
    def create_estimate(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/estimates", payload, headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def accept_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/accept", {}, headers)

    def decline_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/decline", {}, headers)

    # --- Order agent assignments ---
    def create_agent_assignment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/agent-assignments", payload, headers
        )

    def confirm_agent_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/order-agent-assignments/{assignment_id}/confirm", {}, headers
        )

    def release_agent_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/order-agent-assignments/{assignment_id}/release", {}, headers
        )

    def list_agent_assignments(self, headers, params=None):
        return self._request(
            "GET", "/order-agent-assignments", headers=headers, params=params
        )

    def get_agent_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/order-agent-assignments/{assignment_id}", headers=headers
        )

    # --- Valuation coverages ---
    def create_valuation_coverage(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/valuation-coverages", payload, headers
        )

    def list_valuation_coverages(self, headers, params=None):
        return self._request("GET", "/valuation-coverages", headers=headers, params=params)

    def get_valuation_coverage(self, coverage_id, headers):
        return self._request(
            "GET", f"/valuation-coverages/{coverage_id}", headers=headers
        )

    # --- Weight tickets ---
    def create_weight_ticket(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/weight-tickets", payload, headers
        )

    def list_weight_tickets(self, headers, params=None):
        return self._request("GET", "/weight-tickets", headers=headers, params=params)

    def get_weight_ticket(self, ticket_id, headers):
        return self._request("GET", f"/weight-tickets/{ticket_id}", headers=headers)

    # --- Re-weigh requests ---
    def create_reweigh_request(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/reweigh-requests", payload, headers
        )

    def perform_reweigh(self, request_id, payload, headers):
        return self._request(
            "POST", f"/reweigh-requests/{request_id}/perform", payload, headers
        )

    def apply_reweigh(self, request_id, headers):
        return self._request("POST", f"/reweigh-requests/{request_id}/apply", {}, headers)

    def decline_reweigh(self, request_id, headers):
        return self._request(
            "POST", f"/reweigh-requests/{request_id}/decline", {}, headers
        )

    def cancel_reweigh(self, request_id, headers):
        return self._request(
            "POST", f"/reweigh-requests/{request_id}/cancel", {}, headers
        )

    def list_reweigh_requests(self, headers, params=None):
        return self._request("GET", "/reweigh-requests", headers=headers, params=params)

    def get_reweigh_request(self, request_id, headers):
        return self._request("GET", f"/reweigh-requests/{request_id}", headers=headers)

    # --- Warehouses ---
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/warehouses", payload, headers)

    def deactivate_warehouse(self, warehouse_id, headers):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/deactivate", {}, headers
        )

    def list_warehouses(self, headers, params=None):
        return self._request("GET", "/warehouses", headers=headers, params=params)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}", headers=headers)

    # --- SIT lots ---
    def create_sit_lot(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/sit-lots", payload, headers)

    def release_sit_lot(self, lot_id, headers):
        return self._request("POST", f"/sit-lots/{lot_id}/release", {}, headers)

    def list_sit_lots(self, headers, params=None):
        return self._request("GET", "/sit-lots", headers=headers, params=params)

    def get_sit_lot(self, lot_id, headers):
        return self._request("GET", f"/sit-lots/{lot_id}", headers=headers)

    # --- Crew assignments ---
    def create_crew_assignment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/crew-assignments", payload, headers
        )

    def confirm_crew_assignment(self, crew_id, headers):
        return self._request(
            "POST", f"/crew-assignments/{crew_id}/confirm", {}, headers
        )

    def complete_crew_assignment(self, crew_id, headers):
        return self._request(
            "POST", f"/crew-assignments/{crew_id}/complete", {}, headers
        )

    def cancel_crew_assignment(self, crew_id, headers):
        return self._request("POST", f"/crew-assignments/{crew_id}/cancel", {}, headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    def get_crew_assignment(self, crew_id, headers):
        return self._request("GET", f"/crew-assignments/{crew_id}", headers=headers)

    # --- Revenue statements ---
    def list_revenue_statements(self, headers, params=None):
        return self._request("GET", "/revenue-statements", headers=headers, params=params)

    def get_revenue_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/revenue-statements/{statement_id}", headers=headers
        )

    def finalize_revenue_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/revenue-statements/{statement_id}/finalize", {}, headers
        )

    def post_chargeback(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/revenue-statements/{statement_id}/chargebacks", payload, headers
        )

    def reconcile_revenue_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/revenue-statements/{statement_id}/reconcile", {}, headers
        )

    # --- Claims ---
    def create_claim(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def offer_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/offer", payload, headers)

    def accept_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/accept", {}, headers)

    def reject_claim_offer(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reject-offer", {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/pay", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/withdraw", {}, headers)

    # --- Disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def respond_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/respond", payload, headers)

    def escalate_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/escalate-to-arbitration", {}, headers
        )

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/decide", payload, headers)

    def close_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/close", {}, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", {}, headers)


api_client = ApiClient()
