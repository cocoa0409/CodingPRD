"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", headers=headers)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def get_technician_risk_score(self, technician_id, headers, params=None):
        return self._request(
            "GET", f"/technicians/{technician_id}/risk-score", headers=headers, params=params)

    # ---- Route ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # ---- ServiceQuote ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def add_line_item(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/line-items", payload, headers)

    def list_line_items(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/line-items", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", headers=headers)

    def revise_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/revise", headers=headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", headers=headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/decline", headers=headers)

    # ---- RecurringPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/recurring-plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/recurring-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/recurring-plans/{plan_id}", headers=headers)

    def cancel_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/cancel", headers=headers)

    def generate_visit(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/recurring-plans/{plan_id}/generate-visit", payload, headers)

    # ---- Visit ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def schedule_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/schedule", payload, headers)

    def unschedule_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/unschedule", headers=headers)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/start", headers=headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", headers=headers)

    def list_photos(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/photos", headers=headers, params=params)

    def upload_photo(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/photos", payload, headers)

    # ---- CrewAssignment ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/crew-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/crew-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/crew-assignments/{assignment_id}/confirm", headers=headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/crew-assignments/{assignment_id}/release", headers=headers)

    # ---- WeatherWindow ----
    def create_weather_window(self, payload, headers):
        return self._request("POST", "/weather-windows", payload, headers)

    def list_weather_windows(self, headers, params=None):
        return self._request("GET", "/weather-windows", headers=headers, params=params)

    def get_weather_window(self, window_id, headers):
        return self._request("GET", f"/weather-windows/{window_id}", headers=headers)

    # ---- Invoice ----
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", headers=headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    # ---- SatisfactionClaim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/satisfaction-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/satisfaction-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/satisfaction-claims/{claim_id}", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/satisfaction-claims/{claim_id}/approve", headers=headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/satisfaction-claims/{claim_id}/reject", headers=headers)


api_client = ApiClient()
