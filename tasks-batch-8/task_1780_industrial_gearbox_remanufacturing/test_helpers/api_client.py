"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.8)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/reman/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Customers (PRD §3.1)
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/reman/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/reman/customers/{customer_id}", headers=headers)

    def list_customer_units(self, customer_id, headers, params=None):
        return self._request("GET", f"/reman/customers/{customer_id}/units",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Gear units (PRD §3.1)
    # ------------------------------------------------------------------
    def create_unit(self, customer_id, payload, headers):
        return self._request("POST", f"/reman/customers/{customer_id}/units",
                             payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/reman/units/{unit_id}", headers=headers)

    def record_service_hours(self, unit_id, hours, headers):
        return self._request("POST", f"/reman/units/{unit_id}/record-service-hours",
                             {"hours": hours}, headers)

    def check_in_unit(self, unit_id, headers):
        return self._request("POST", f"/reman/units/{unit_id}/check-in", {}, headers)

    def scrap_unit(self, unit_id, headers):
        return self._request("POST", f"/reman/units/{unit_id}/scrap", {}, headers)

    # ------------------------------------------------------------------
    # Reman orders (PRD §3.2, §3.3)
    # ------------------------------------------------------------------
    def create_order(self, unit_id, payload, headers):
        return self._request("POST", f"/reman/units/{unit_id}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/reman/orders/{order_id}", headers=headers)

    def list_unit_orders(self, unit_id, headers, params=None):
        return self._request("GET", f"/reman/units/{unit_id}/orders",
                             headers=headers, params=params)

    def start_teardown(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/start-teardown",
                             {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Teardown findings (PRD §3.2)
    # ------------------------------------------------------------------
    def create_finding(self, order_id, payload, headers):
        return self._request("POST", f"/reman/orders/{order_id}/findings",
                             payload, headers)

    def list_findings(self, order_id, headers, params=None):
        return self._request("GET", f"/reman/orders/{order_id}/findings",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Component decisions (PRD §3.2, §3.3)
    # ------------------------------------------------------------------
    def create_decision(self, order_id, payload, headers):
        return self._request("POST", f"/reman/orders/{order_id}/decisions",
                             payload, headers)

    def list_decisions(self, order_id, headers, params=None):
        return self._request("GET", f"/reman/orders/{order_id}/decisions",
                             headers=headers, params=params)

    def submit_scope(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/submit-scope",
                             {}, headers)

    def revise_scope(self, order_id, expected_order_version, headers):
        return self._request("POST", f"/reman/orders/{order_id}/revise-scope",
                             {"expected_order_version": expected_order_version}, headers)

    def approve_scope(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/approve-scope",
                             {}, headers)

    # ------------------------------------------------------------------
    # Build / assembly / run-in (PRD §3.4)
    # ------------------------------------------------------------------
    def start_build(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/start-build",
                             {}, headers)

    def start_assembly(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/start-assembly",
                             {}, headers)

    def create_assembly_record(self, order_id, payload, headers):
        return self._request("POST", f"/reman/orders/{order_id}/assembly-records",
                             payload, headers)

    def list_assembly_records(self, order_id, headers, params=None):
        return self._request("GET", f"/reman/orders/{order_id}/assembly-records",
                             headers=headers, params=params)

    def submit_assembly(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/submit-assembly",
                             {}, headers)

    def create_run_in_test(self, order_id, payload, headers):
        return self._request("POST", f"/reman/orders/{order_id}/run-in-tests",
                             payload, headers)

    def list_run_in_tests(self, order_id, headers, params=None):
        return self._request("GET", f"/reman/orders/{order_id}/run-in-tests",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Shipping / completion (PRD §3.5)
    # ------------------------------------------------------------------
    def ship_order(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/ship", {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/reman/orders/{order_id}/complete", {}, headers)

    # ------------------------------------------------------------------
    # Loaner fleet (PRD §3.6)
    # ------------------------------------------------------------------
    def create_loaner_unit(self, payload, headers):
        return self._request("POST", "/reman/loaner-units", payload, headers)

    def get_loaner_unit(self, loaner_id, headers):
        return self._request("GET", f"/reman/loaner-units/{loaner_id}", headers=headers)

    def list_loaner_unit_assignments(self, loaner_id, headers, params=None):
        return self._request("GET", f"/reman/loaner-units/{loaner_id}/assignments",
                             headers=headers, params=params)

    def create_loaner_assignment(self, loaner_id, payload, headers):
        return self._request("POST", f"/reman/loaner-units/{loaner_id}/assignments",
                             payload, headers)

    def list_loaner_assignments(self, headers, params=None):
        return self._request("GET", "/reman/loaner-assignments",
                             headers=headers, params=params)

    def get_loaner_assignment(self, assignment_id, headers):
        return self._request("GET", f"/reman/loaner-assignments/{assignment_id}",
                             headers=headers)

    def checkout_loaner(self, assignment_id, headers):
        return self._request("POST",
                             f"/reman/loaner-assignments/{assignment_id}/checkout",
                             {}, headers)

    def return_loaner(self, assignment_id, expected_assignment_version, headers):
        return self._request(
            "POST", f"/reman/loaner-assignments/{assignment_id}/return",
            {"expected_assignment_version": expected_assignment_version}, headers)

    def extend_loaner(self, assignment_id, new_end_date, headers):
        return self._request("POST",
                             f"/reman/loaner-assignments/{assignment_id}/extend",
                             {"new_end_date": new_end_date}, headers)

    # ------------------------------------------------------------------
    # Freight shipments (PRD §3.5)
    # ------------------------------------------------------------------
    def create_shipment(self, order_id, payload, headers):
        return self._request("POST", f"/reman/orders/{order_id}/shipments",
                             payload, headers)

    def list_shipments(self, order_id, headers, params=None):
        return self._request("GET", f"/reman/orders/{order_id}/shipments",
                             headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/reman/shipments/{shipment_id}", headers=headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/reman/shipments/{shipment_id}/dispatch",
                             {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/reman/shipments/{shipment_id}/deliver",
                             {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/reman/shipments/{shipment_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Warranty claims (PRD §3.7)
    # ------------------------------------------------------------------
    def create_warranty_claim(self, order_id, payload, headers):
        return self._request("POST", f"/reman/orders/{order_id}/warranty-claims",
                             payload, headers)

    def list_warranty_claims(self, order_id, headers, params=None):
        return self._request("GET", f"/reman/orders/{order_id}/warranty-claims",
                             headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/reman/warranty-claims/{claim_id}",
                             headers=headers)

    def review_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/reman/warranty-claims/{claim_id}/review",
                             {}, headers)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/reman/warranty-claims/{claim_id}/approve",
                             {}, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/reman/warranty-claims/{claim_id}/deny",
                             {}, headers)


api_client = ApiClient()
