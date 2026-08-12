"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def patch_client(self, client_id, payload, headers):
        return self._request("PATCH", f"/clients/{client_id}", payload, headers)

    # --- Family members ---
    def create_family_member(self, payload, headers):
        return self._request("POST", "/family-members", payload, headers)

    def get_family_member(self, member_id, headers):
        return self._request("GET", f"/family-members/{member_id}", headers=headers)

    def list_family_members(self, headers, params=None):
        return self._request("GET", "/family-members", headers=headers, params=params)

    def revoke_family_member(self, member_id, headers):
        return self._request("POST", f"/family-members/{member_id}/revoke", headers=headers)

    # --- Drivers ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    def driver_status_event(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/status-events", payload, headers)

    # --- Compliance docs ---
    def create_compliance_doc(self, payload, headers):
        return self._request("POST", "/compliance-docs", payload, headers)

    def get_compliance_doc(self, doc_id, headers):
        return self._request("GET", f"/compliance-docs/{doc_id}", headers=headers)

    def list_compliance_docs(self, headers, params=None):
        return self._request("GET", "/compliance-docs", headers=headers, params=params)

    def review_compliance_doc(self, doc_id, payload, headers):
        return self._request("POST", f"/compliance-docs/{doc_id}/review", payload, headers)

    # --- Rate cards ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def get_rate_card(self, card_id, headers):
        return self._request("GET", f"/rate-cards/{card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/rate-cards", headers=headers, params=params)

    def activate_rate_card(self, card_id, headers):
        return self._request("POST", f"/rate-cards/{card_id}/activate", headers=headers)

    def retire_rate_card(self, card_id, headers):
        return self._request("POST", f"/rate-cards/{card_id}/retire", headers=headers)

    # --- Standing rides ---
    def create_standing_ride(self, payload, headers):
        return self._request("POST", "/standing-rides", payload, headers)

    def get_standing_ride(self, series_id, headers):
        return self._request("GET", f"/standing-rides/{series_id}", headers=headers)

    def list_standing_rides(self, headers, params=None):
        return self._request("GET", "/standing-rides", headers=headers, params=params)

    def update_standing_ride(self, series_id, payload, headers):
        return self._request("PUT", f"/standing-rides/{series_id}", payload, headers)

    def standing_ride_status_event(self, series_id, payload, headers):
        return self._request("POST", f"/standing-rides/{series_id}/status-events", payload, headers)

    # --- Rides ---
    def create_ride(self, payload, headers):
        return self._request("POST", "/rides", payload, headers)

    def get_ride(self, ride_id, headers):
        return self._request("GET", f"/rides/{ride_id}", headers=headers)

    def list_rides(self, headers, params=None):
        return self._request("GET", "/rides", headers=headers, params=params)

    def cancel_ride(self, ride_id, payload, headers):
        return self._request("POST", f"/rides/{ride_id}/cancel", payload, headers)

    def dispatch_ride(self, ride_id, headers):
        return self._request("POST", f"/rides/{ride_id}/dispatch", headers=headers)

    def ride_execution_event(self, ride_id, payload, headers):
        return self._request("POST", f"/rides/{ride_id}/execution-events", payload, headers)

    def list_ride_events(self, ride_id, headers, params=None):
        return self._request("GET", f"/rides/{ride_id}/events", headers=headers, params=params)

    # --- Assignments ---
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def respond_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/respond", payload, headers)

    def release_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/release", payload, headers)

    # --- Billing ---
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/invoices/generate", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/lines", headers=headers, params=params)

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/invoice-lines/{line_id}", headers=headers)

    def list_invoice_lines_root(self, headers, params=None):
        return self._request("GET", "/invoice-lines", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", headers=headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)

    def invoice_dispute_event(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute-events", payload, headers)

    # --- Payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def refund_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", payload, headers)

    # --- Ops & clock ---
    def run_cycle(self, headers):
        return self._request("POST", "/ops/run-cycle", headers=headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
