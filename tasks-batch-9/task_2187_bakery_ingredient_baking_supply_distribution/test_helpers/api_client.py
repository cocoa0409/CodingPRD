"""API client: one method per endpoint defined in PRD §4."""

from prd_bench_local_runner.testing import GenericApiClient

P = "/bakery-distribution"


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4, §4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc", payload, headers)

    # --- Customers (PRD §3.1) ---
    def create_customer(self, payload, headers):
        return self._request("POST", f"{P}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{P}/customers/{customer_id}", headers=headers)

    def adjust_credit_limit(self, customer_id, payload, headers):
        return self._request(
            "POST", f"{P}/customers/{customer_id}/credit-limit-adjustments", payload, headers
        )

    # --- Products (PRD §3.1) ---
    def create_product(self, payload, headers):
        return self._request("POST", f"{P}/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{P}/products/{product_id}", headers=headers)

    # --- Warehouse zones (PRD §3.1) ---
    def create_warehouse_zone(self, payload, headers):
        return self._request("POST", f"{P}/warehouse-zones", payload, headers)

    def get_warehouse_zone(self, zone_id, headers):
        return self._request("GET", f"{P}/warehouse-zones/{zone_id}", headers=headers)

    def set_zone_lockout(self, zone_id, payload, headers):
        return self._request("POST", f"{P}/warehouse-zones/{zone_id}/lockout", payload, headers)

    # --- Index quotes (PRD §3.1) ---
    def create_index_quote(self, payload, headers):
        return self._request("POST", f"{P}/index-quotes", payload, headers)

    def list_index_quotes(self, headers, params=None):
        return self._request("GET", f"{P}/index-quotes", headers=headers, params=params)

    # --- Forward pricing contracts (PRD §3.2) ---
    def create_forward_contract(self, payload, headers):
        return self._request("POST", f"{P}/forward-contracts", payload, headers)

    def get_forward_contract(self, contract_id, headers):
        return self._request("GET", f"{P}/forward-contracts/{contract_id}", headers=headers)

    def list_forward_contracts(self, headers, params=None):
        return self._request("GET", f"{P}/forward-contracts", headers=headers, params=params)

    def create_contract_line(self, contract_id, payload, headers):
        return self._request("POST", f"{P}/forward-contracts/{contract_id}/lines", payload, headers)

    def list_contract_lines_of_contract(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"{P}/forward-contracts/{contract_id}/lines", headers=headers, params=params
        )

    def list_contract_lines(self, headers, params=None):
        return self._request("GET", f"{P}/contract-lines", headers=headers, params=params)

    def get_contract_line(self, contract_line_id, headers):
        return self._request("GET", f"{P}/contract-lines/{contract_line_id}", headers=headers)

    def offer_forward_contract(self, contract_id, payload, headers):
        return self._request("POST", f"{P}/forward-contracts/{contract_id}/offer", payload, headers)

    def counter_forward_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{P}/forward-contracts/{contract_id}/counter", payload, headers
        )

    def activate_forward_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{P}/forward-contracts/{contract_id}/activate", payload, headers
        )

    def terminate_forward_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{P}/forward-contracts/{contract_id}/terminate", payload, headers
        )

    # --- Lots (PRD §3.5, §3.7) ---
    def create_lot(self, payload, headers):
        return self._request("POST", f"{P}/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", f"{P}/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{P}/lots/{lot_id}", headers=headers)

    def quarantine_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{P}/lots/{lot_id}/quarantine", payload, headers)

    def release_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{P}/lots/{lot_id}/release", payload, headers)

    def dispose_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{P}/lots/{lot_id}/dispose", payload, headers)

    # --- Silos (PRD §3.6) ---
    def create_silo(self, payload, headers):
        return self._request("POST", f"{P}/silos", payload, headers)

    def list_silos(self, headers, params=None):
        return self._request("GET", f"{P}/silos", headers=headers, params=params)

    def get_silo(self, silo_id, headers):
        return self._request("GET", f"{P}/silos/{silo_id}", headers=headers)

    def create_residual_reading(self, silo_id, payload, headers):
        return self._request("POST", f"{P}/silos/{silo_id}/residual-readings", payload, headers)

    # --- Orders (PRD §3.3) ---
    def create_order(self, payload, headers):
        return self._request("POST", f"{P}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{P}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{P}/orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/lines", payload, headers)

    def list_order_lines_of_order(self, order_id, headers, params=None):
        return self._request("GET", f"{P}/orders/{order_id}/lines", headers=headers, params=params)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", f"{P}/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"{P}/order-lines/{order_line_id}", headers=headers)

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/submit", payload, headers)

    def reprice_order(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/reprice", payload, headers)

    def allocate_order(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/allocate", payload, headers)

    def deallocate_order(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/deallocate", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/cancel", payload, headers)

    def finalize_order_pricing(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/finalize-pricing", payload, headers)

    def invoice_order(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/invoice", payload, headers)

    def get_order_pricing_summary(self, order_id, headers):
        return self._request("GET", f"{P}/orders/{order_id}/pricing-summary", headers=headers)

    # --- Substitution requests (PRD §3.8) ---
    def create_substitution_request(self, payload, headers):
        return self._request("POST", f"{P}/substitution-requests", payload, headers)

    def list_substitution_requests(self, headers, params=None):
        return self._request("GET", f"{P}/substitution-requests", headers=headers, params=params)

    def get_substitution_request(self, request_id, headers):
        return self._request("GET", f"{P}/substitution-requests/{request_id}", headers=headers)

    def claim_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{P}/substitution-requests/{request_id}/claim", payload, headers
        )

    def request_substitution_revision(self, request_id, payload, headers):
        return self._request(
            "POST", f"{P}/substitution-requests/{request_id}/request-revision", payload, headers
        )

    def resubmit_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{P}/substitution-requests/{request_id}/resubmit", payload, headers
        )

    def approve_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{P}/substitution-requests/{request_id}/approve", payload, headers
        )

    def reject_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{P}/substitution-requests/{request_id}/reject", payload, headers
        )

    def withdraw_substitution_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{P}/substitution-requests/{request_id}/withdraw", payload, headers
        )

    # --- Delivery routes and stops (PRD §3.9, §3.10) ---
    def create_route(self, payload, headers):
        return self._request("POST", f"{P}/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"{P}/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", f"{P}/routes", headers=headers, params=params)

    def create_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"{P}/routes/{route_id}/stops", payload, headers)

    def list_route_stops_of_route(self, route_id, headers, params=None):
        return self._request("GET", f"{P}/routes/{route_id}/stops", headers=headers, params=params)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", f"{P}/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"{P}/route-stops/{stop_id}", headers=headers)

    def delete_route_stop(self, stop_id, headers):
        return self._request("DELETE", f"{P}/route-stops/{stop_id}", headers=headers)

    def seal_route(self, route_id, payload, headers):
        return self._request("POST", f"{P}/routes/{route_id}/seal", payload, headers)

    def unseal_route(self, route_id, payload, headers):
        return self._request("POST", f"{P}/routes/{route_id}/unseal", payload, headers)

    def dispatch_route(self, route_id, payload, headers):
        return self._request("POST", f"{P}/routes/{route_id}/dispatch", payload, headers)

    def abort_route(self, route_id, payload, headers):
        return self._request("POST", f"{P}/routes/{route_id}/abort", payload, headers)

    def deliver_route_stop(self, stop_id, payload, headers):
        return self._request("POST", f"{P}/route-stops/{stop_id}/deliver", payload, headers)

    def short_route_stop(self, stop_id, payload, headers):
        return self._request("POST", f"{P}/route-stops/{stop_id}/short", payload, headers)

    # --- Formulation support engagements (PRD §3.11) ---
    def create_tech_engagement(self, payload, headers):
        return self._request("POST", f"{P}/tech-engagements", payload, headers)

    def list_tech_engagements(self, headers, params=None):
        return self._request("GET", f"{P}/tech-engagements", headers=headers, params=params)

    def get_tech_engagement(self, engagement_id, headers):
        return self._request("GET", f"{P}/tech-engagements/{engagement_id}", headers=headers)

    def log_tech_hours(self, engagement_id, payload, headers):
        return self._request("POST", f"{P}/tech-engagements/{engagement_id}/hours", payload, headers)

    def attach_tech_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"{P}/tech-engagements/{engagement_id}/attach", payload, headers
        )

    def waive_tech_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"{P}/tech-engagements/{engagement_id}/waive", payload, headers)


api_client = ApiClient()
