"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/api/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/api/jurisdictions/{jurisdiction_id}", headers=headers)

    def update_jurisdiction(self, jurisdiction_id, payload, headers):
        return self._request("PUT", f"/api/jurisdictions/{jurisdiction_id}", payload, headers)

    def list_jurisdiction_permit_applications(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/api/jurisdictions/{jurisdiction_id}/permit-applications",
            headers=headers, params=params,
        )

    # --- Structure models ---
    def create_model(self, payload, headers):
        return self._request("POST", "/api/models", payload, headers)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/api/models/{model_id}", headers=headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def amend_order(self, order_id, payload, headers):
        return self._request("PUT", f"/api/orders/{order_id}", payload, headers)

    def submit_site_check(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/submit-site-check", payload, headers)

    def schedule_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/schedule", payload, headers)

    def start_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/start", {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/complete", {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", payload, headers)

    # --- Payments ---
    def record_order_payment(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/payments", payload, headers)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request("GET", f"/api/orders/{order_id}/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/api/payments/{payment_id}", headers=headers)

    # --- Site assessments ---
    def list_order_site_assessments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/orders/{order_id}/site-assessments", headers=headers, params=params
        )

    def get_site_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/site-assessments/{assessment_id}", headers=headers)

    def report_site_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/api/site-assessments/{assessment_id}/report", payload, headers)

    # --- Permit applications ---
    def list_order_permit_applications(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/orders/{order_id}/permit-applications", headers=headers, params=params
        )

    def get_permit_application(self, application_id, headers):
        return self._request("GET", f"/api/permit-applications/{application_id}", headers=headers)

    def approve_permit_application(self, application_id, headers):
        return self._request("POST", f"/api/permit-applications/{application_id}/approve", {}, headers)

    def deny_permit_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/permit-applications/{application_id}/deny", payload, headers)

    # --- RTO contracts ---
    def get_order_rto_contract(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/rto-contract", headers=headers)

    def get_rto_contract(self, contract_id, headers):
        return self._request("GET", f"/api/rto-contracts/{contract_id}", headers=headers)

    def record_rto_payment(self, contract_id, payload, headers):
        return self._request("POST", f"/api/rto-contracts/{contract_id}/payments", payload, headers)

    def list_rto_contract_payments(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/api/rto-contracts/{contract_id}/payments", headers=headers, params=params
        )

    def run_billing(self, headers):
        return self._request("POST", "/api/billing/run", {}, headers)

    # --- Service tickets ---
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/api/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/api/service-tickets/{ticket_id}", headers=headers)

    def list_order_service_tickets(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/orders/{order_id}/service-tickets", headers=headers, params=params
        )

    def schedule_service_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/schedule", payload, headers)

    def resolve_service_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/resolve", payload, headers)

    def reopen_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/reopen", {}, headers)

    # --- Logical clock (mounted outside /api per PRD §4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
