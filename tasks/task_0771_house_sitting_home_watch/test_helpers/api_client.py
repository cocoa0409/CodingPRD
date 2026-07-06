"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/home-watch/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/home-watch/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/home-watch/clients/{client_id}", headers=headers)

    # ---- Properties ----
    def create_property(self, payload, headers):
        return self._request("POST", "/home-watch/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/home-watch/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/home-watch/properties/{property_id}", headers=headers)

    # ---- Sitters ----
    def create_sitter(self, payload, headers):
        return self._request("POST", "/home-watch/sitters", payload, headers)

    def list_sitters(self, headers, params=None):
        return self._request("GET", "/home-watch/sitters", headers=headers, params=params)

    def get_sitter(self, sitter_id, headers):
        return self._request("GET", f"/home-watch/sitters/{sitter_id}", headers=headers)

    # ---- Background checks ----
    def create_background_check(self, payload, headers):
        return self._request("POST", "/home-watch/background-checks", payload, headers)

    def decide_background_check(self, bgcheck_id, payload, headers):
        return self._request("POST", f"/home-watch/background-checks/{bgcheck_id}/decide",
                             payload, headers)

    def list_background_checks(self, headers, params=None):
        return self._request("GET", "/home-watch/background-checks", headers=headers, params=params)

    def get_background_check(self, bgcheck_id, headers):
        return self._request("GET", f"/home-watch/background-checks/{bgcheck_id}", headers=headers)

    # ---- Coverage policies ----
    def create_coverage_policy(self, payload, headers):
        return self._request("POST", "/home-watch/coverage-policies", payload, headers)

    def list_coverage_policies(self, headers, params=None):
        return self._request("GET", "/home-watch/coverage-policies", headers=headers, params=params)

    def get_coverage_policy(self, policy_id, headers):
        return self._request("GET", f"/home-watch/coverage-policies/{policy_id}", headers=headers)

    # ---- Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/home-watch/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/home-watch/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/home-watch/bookings/{booking_id}", headers=headers)

    def submit_booking(self, booking_id, headers):
        return self._request("POST", f"/home-watch/bookings/{booking_id}/submit", {}, headers)

    def assign_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/home-watch/bookings/{booking_id}/assign", payload, headers)

    def unassign_booking(self, booking_id, headers):
        return self._request("POST", f"/home-watch/bookings/{booking_id}/unassign", {}, headers)

    def activate_booking(self, booking_id, headers):
        return self._request("POST", f"/home-watch/bookings/{booking_id}/activate", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/home-watch/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/home-watch/bookings/{booking_id}/cancel", {}, headers)

    # ---- Visits ----
    def list_visits(self, headers, params=None):
        return self._request("GET", "/home-watch/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/home-watch/visits/{visit_id}", headers=headers)

    def check_in_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/home-watch/visits/{visit_id}/check-in", payload, headers)

    def check_out_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/home-watch/visits/{visit_id}/check-out", payload, headers)

    def mark_missed_visit(self, visit_id, headers):
        return self._request("POST", f"/home-watch/visits/{visit_id}/mark-missed", {}, headers)

    # ---- Visit log entries ----
    def create_visit_log(self, payload, headers):
        return self._request("POST", "/home-watch/visit-logs", payload, headers)

    def list_visit_logs(self, headers, params=None):
        return self._request("GET", "/home-watch/visit-logs", headers=headers, params=params)

    def get_visit_log(self, log_id, headers):
        return self._request("GET", f"/home-watch/visit-logs/{log_id}", headers=headers)

    # ---- Key assignments ----
    def create_key_assignment(self, payload, headers):
        return self._request("POST", "/home-watch/key-assignments", payload, headers)

    def check_out_key(self, key_id, headers):
        return self._request("POST", f"/home-watch/key-assignments/{key_id}/check-out", {}, headers)

    def return_key(self, key_id, headers):
        return self._request("POST", f"/home-watch/key-assignments/{key_id}/return", {}, headers)

    def report_lost_key(self, key_id, headers):
        return self._request("POST", f"/home-watch/key-assignments/{key_id}/report-lost", {}, headers)

    def list_key_assignments(self, headers, params=None):
        return self._request("GET", "/home-watch/key-assignments", headers=headers, params=params)

    def get_key_assignment(self, key_id, headers):
        return self._request("GET", f"/home-watch/key-assignments/{key_id}", headers=headers)

    # ---- Incidents ----
    def create_incident(self, payload, headers):
        return self._request("POST", "/home-watch/incidents", payload, headers)

    def escalate_incident(self, incident_id, headers):
        return self._request("POST", f"/home-watch/incidents/{incident_id}/escalate", {}, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/home-watch/incidents/{incident_id}/resolve", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/home-watch/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/home-watch/incidents/{incident_id}", headers=headers)

    # ---- Invoices ----
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/home-watch/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/home-watch/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/home-watch/invoices/{invoice_id}/pay", {}, headers)


api_client = ApiClient()
