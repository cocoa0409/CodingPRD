"""API client: one method per endpoint defined in the Window Cleaning &
Pressure Washing PRD (§4 Endpoint Definitions). Subclasses GenericApiClient;
the base _request() handles HTTP, URL construction and JSON envelopes.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Accounts ────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_account_ledger_entries(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/ledger-entries", headers=headers, params=params)

    def list_account_properties(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/properties", headers=headers, params=params)

    def list_account_deposits(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/deposits", headers=headers, params=params)

    def list_account_invoices(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/invoices", headers=headers, params=params)

    def list_account_service_agreements(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/service-agreements", headers=headers, params=params)

    def list_account_quotes(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/quotes", headers=headers, params=params)

    # ─── Properties ──────────────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # ─── Quotes ──────────────────────────────────────────────────────
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", {}, headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", {}, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/decline", {}, headers)

    # ─── Service Agreements ──────────────────────────────────────────
    def create_service_agreement(self, payload, headers):
        return self._request("POST", "/service-agreements", payload, headers)

    def list_service_agreements(self, headers, params=None):
        return self._request("GET", "/service-agreements", headers=headers, params=params)

    def get_service_agreement(self, agreement_id, headers):
        return self._request("GET", f"/service-agreements/{agreement_id}", headers=headers)

    def list_agreement_visits(self, agreement_id, headers, params=None):
        return self._request("GET", f"/service-agreements/{agreement_id}/visits", headers=headers, params=params)

    def list_agreement_deposits(self, agreement_id, headers, params=None):
        return self._request("GET", f"/service-agreements/{agreement_id}/deposits", headers=headers, params=params)

    def activate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/service-agreements/{agreement_id}/activate", payload, headers)

    def pause_agreement(self, agreement_id, headers):
        return self._request("POST", f"/service-agreements/{agreement_id}/pause", {}, headers)

    def resume_agreement(self, agreement_id, headers):
        return self._request("POST", f"/service-agreements/{agreement_id}/resume", {}, headers)

    def complete_agreement(self, agreement_id, headers):
        return self._request("POST", f"/service-agreements/{agreement_id}/complete", {}, headers)

    def cancel_agreement(self, agreement_id, headers):
        return self._request("POST", f"/service-agreements/{agreement_id}/cancel", {}, headers)

    # ─── Deposits ────────────────────────────────────────────────────
    def create_deposit(self, payload, headers):
        return self._request("POST", "/deposits", payload, headers)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    # ─── Crews ───────────────────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def set_crew_status(self, crew_id, payload, headers):
        return self._request("POST", f"/crews/{crew_id}/set-status", payload, headers)

    # ─── Routes ──────────────────────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_route_visits(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/visits", headers=headers, params=params)

    def commit_visit(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/visits", payload, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", {}, headers)

    # ─── Visits ──────────────────────────────────────────────────────
    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visit_add_ons(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/add-ons", headers=headers, params=params)

    def list_visit_photos(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/photos", headers=headers, params=params)

    def attach_add_on(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/add-ons", payload, headers)

    def upload_photo(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/photos", payload, headers)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/start", {}, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def weather_reschedule_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/weather-reschedule", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def list_visit_reclean_requests(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/reclean-requests", headers=headers, params=params)

    # ─── Weather Advisories ──────────────────────────────────────────
    def create_weather_advisory(self, payload, headers):
        return self._request("POST", "/weather-advisories", payload, headers)

    def get_weather_advisory(self, advisory_id, headers):
        return self._request("GET", f"/weather-advisories/{advisory_id}", headers=headers)

    # ─── Invoices ────────────────────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    # ─── Re-clean Requests ───────────────────────────────────────────
    def create_reclean_request(self, payload, headers):
        return self._request("POST", "/reclean-requests", payload, headers)

    def get_reclean_request(self, reclean_id, headers):
        return self._request("GET", f"/reclean-requests/{reclean_id}", headers=headers)

    def approve_reclean_request(self, reclean_id, headers):
        return self._request("POST", f"/reclean-requests/{reclean_id}/approve", {}, headers)

    def deny_reclean_request(self, reclean_id, headers):
        return self._request("POST", f"/reclean-requests/{reclean_id}/deny", {}, headers)

    # ─── Test-only clock ─────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
