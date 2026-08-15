"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Ops / logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/api/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/api/venues/{venue_id}", headers=headers)

    # --- Suites ---
    def create_suite(self, payload, headers):
        return self._request("POST", "/api/suites", payload, headers)

    def get_suite(self, suite_id, headers):
        return self._request("GET", f"/api/suites/{suite_id}", headers=headers)

    def list_suites(self, headers, params=None):
        return self._request("GET", "/api/suites", headers=headers, params=params)

    def set_suite_status(self, suite_id, payload, headers):
        return self._request("POST", f"/api/suites/{suite_id}/set_status", payload, headers)

    # --- Seasons ---
    def create_season(self, payload, headers):
        return self._request("POST", "/api/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/api/seasons/{season_id}", headers=headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/api/seasons", headers=headers, params=params)

    def publish_season(self, season_id, headers):
        return self._request("POST", f"/api/seasons/{season_id}/publish", {}, headers)

    def settle_season(self, season_id, headers):
        return self._request("POST", f"/api/seasons/{season_id}/settle", {}, headers)

    # --- Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/api/events", headers=headers, params=params)

    def set_event_status(self, event_id, payload, headers):
        return self._request("POST", f"/api/events/{event_id}/set_status", payload, headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/api/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    def update_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/api/accounts/{account_id}", payload, headers)

    def set_account_status(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/set_status", payload, headers)

    # --- License agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/api/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/api/agreements", headers=headers, params=params)

    def submit_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/agreements/{agreement_id}/submit", {}, headers)

    def execute_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/agreements/{agreement_id}/execute", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/agreements/{agreement_id}/terminate", {}, headers)

    def cure_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/agreements/{agreement_id}/cure", {}, headers)

    # --- Invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/api/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", {}, headers)

    # --- Payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/api/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/api/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/api/payments", headers=headers, params=params)

    def set_payment_status(self, payment_id, payload, headers):
        return self._request("POST", f"/api/payments/{payment_id}/set_status", payload, headers)

    # --- Catering orders ---
    def create_catering_order(self, payload, headers):
        return self._request("POST", "/api/catering-orders", payload, headers)

    def get_catering_order(self, order_id, headers):
        return self._request("GET", f"/api/catering-orders/{order_id}", headers=headers)

    def list_catering_orders(self, headers, params=None):
        return self._request("GET", "/api/catering-orders", headers=headers, params=params)

    def amend_catering_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/api/catering-orders/{order_id}", payload, headers)

    def set_catering_order_status(self, order_id, payload, headers):
        return self._request("POST", f"/api/catering-orders/{order_id}/set_status", payload, headers)

    # --- Access credentials ---
    def create_credential(self, payload, headers):
        return self._request("POST", "/api/credentials", payload, headers)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/api/credentials/{credential_id}", headers=headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/api/credentials", headers=headers, params=params)

    def set_credential_status(self, credential_id, payload, headers):
        return self._request("POST", f"/api/credentials/{credential_id}/set_status", payload, headers)

    # --- Single-event rentals ---
    def create_rental(self, payload, headers):
        return self._request("POST", "/api/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/api/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/api/rentals", headers=headers, params=params)

    def set_rental_status(self, rental_id, payload, headers):
        return self._request("POST", f"/api/rentals/{rental_id}/set_status", payload, headers)

    # --- Transfer requests ---
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/api/transfer-requests", payload, headers)

    def get_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"/api/transfer-requests/{transfer_id}", headers=headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", "/api/transfer-requests", headers=headers, params=params)

    def set_transfer_status(self, transfer_id, payload, headers):
        return self._request("POST", f"/api/transfer-requests/{transfer_id}/set_status", payload, headers)

    def complete_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfer-requests/{transfer_id}/complete", {}, headers)

    # --- Renewal offers ---
    def create_renewal_offer(self, payload, headers):
        return self._request("POST", "/api/renewal-offers", payload, headers)

    def get_renewal_offer(self, offer_id, headers):
        return self._request("GET", f"/api/renewal-offers/{offer_id}", headers=headers)

    def list_renewal_offers(self, headers, params=None):
        return self._request("GET", "/api/renewal-offers", headers=headers, params=params)

    def set_renewal_offer_status(self, offer_id, payload, headers):
        return self._request("POST", f"/api/renewal-offers/{offer_id}/set_status", payload, headers)

    # --- Waitlist entries ---
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/api/waitlist-entries", payload, headers)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/api/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/api/waitlist-entries", headers=headers, params=params)

    def set_waitlist_entry_status(self, entry_id, payload, headers):
        return self._request("POST", f"/api/waitlist-entries/{entry_id}/set_status", payload, headers)

    # --- Assessments ---
    def create_assessment(self, payload, headers):
        return self._request("POST", "/api/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/api/assessments", headers=headers, params=params)

    def set_assessment_status(self, assessment_id, payload, headers):
        return self._request("POST", f"/api/assessments/{assessment_id}/set_status", payload, headers)

    def levy_assessment(self, assessment_id, headers):
        return self._request("POST", f"/api/assessments/{assessment_id}/levy", {}, headers)


api_client = ApiClient()
