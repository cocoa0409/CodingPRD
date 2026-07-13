"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
envelope, base URL, and JSON encoding.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/care/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/care/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/care/clients/{client_id}/suspend", {}, headers)

    def create_family_contact(self, client_id, payload, headers):
        return self._request("POST", f"/care/clients/{client_id}/family-contacts", payload, headers)

    def list_family_contacts(self, client_id, headers, params=None):
        return self._request("GET", f"/care/clients/{client_id}/family-contacts", headers=headers, params=params)

    def create_schedule(self, client_id, payload, headers):
        return self._request("POST", f"/care/clients/{client_id}/schedules", payload, headers)

    def list_schedules(self, client_id, headers, params=None):
        return self._request("GET", f"/care/clients/{client_id}/schedules", headers=headers, params=params)

    def create_ltc_policy(self, client_id, payload, headers):
        return self._request("POST", f"/care/clients/{client_id}/ltc-policies", payload, headers)

    def list_ltc_policies(self, client_id, headers, params=None):
        return self._request("GET", f"/care/clients/{client_id}/ltc-policies", headers=headers, params=params)

    # ---- Caregivers, checks, bonds ----
    def create_caregiver(self, payload, headers):
        return self._request("POST", "/care/caregivers", payload, headers)

    def get_caregiver(self, caregiver_id, headers):
        return self._request("GET", f"/care/caregivers/{caregiver_id}", headers=headers)

    def create_background_check(self, caregiver_id, payload, headers):
        return self._request("POST", f"/care/caregivers/{caregiver_id}/background-checks", payload, headers)

    def list_background_checks(self, caregiver_id, headers, params=None):
        return self._request("GET", f"/care/caregivers/{caregiver_id}/background-checks", headers=headers, params=params)

    def background_check_decision(self, check_id, payload, headers):
        return self._request("POST", f"/care/background-checks/{check_id}/decision", payload, headers)

    def create_bond(self, caregiver_id, payload, headers):
        return self._request("POST", f"/care/caregivers/{caregiver_id}/bonds", payload, headers)

    def list_bonds(self, caregiver_id, headers, params=None):
        return self._request("GET", f"/care/caregivers/{caregiver_id}/bonds", headers=headers, params=params)

    # ---- Schedules ----
    def get_schedule(self, schedule_id, headers):
        return self._request("GET", f"/care/schedules/{schedule_id}", headers=headers)

    def generate_visits(self, schedule_id, payload, headers):
        return self._request("POST", f"/care/schedules/{schedule_id}/generate-visits", payload, headers)

    # ---- Visits ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/care/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/care/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/care/visits", headers=headers, params=params)

    def create_assignment(self, visit_id, payload, headers):
        return self._request("POST", f"/care/visits/{visit_id}/assignments", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/care/assignments/{assignment_id}/cancel", {}, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/care/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/care/assignments", headers=headers, params=params)

    def create_addon(self, visit_id, payload, headers):
        return self._request("POST", f"/care/visits/{visit_id}/add-ons", payload, headers)

    def list_addons(self, visit_id, headers, params=None):
        return self._request("GET", f"/care/visits/{visit_id}/add-ons", headers=headers, params=params)

    def approve_addon(self, addon_id, payload, headers):
        return self._request("POST", f"/care/add-ons/{addon_id}/approve", payload, headers)

    def clock_in(self, visit_id, payload, headers):
        return self._request("POST", f"/care/visits/{visit_id}/clock-in", payload, headers)

    def clock_out(self, visit_id, payload, headers):
        return self._request("POST", f"/care/visits/{visit_id}/clock-out", payload, headers)

    def escalate_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/care/visits/{visit_id}/escalate", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/care/visits/{visit_id}/cancel", {}, headers)

    def create_log(self, visit_id, payload, headers):
        return self._request("POST", f"/care/visits/{visit_id}/log", payload, headers)

    def list_logs(self, visit_id, headers, params=None):
        return self._request("GET", f"/care/visits/{visit_id}/log", headers=headers, params=params)

    # ---- Wellness checks ----
    def get_wellness_check(self, check_id, headers):
        return self._request("GET", f"/care/wellness-checks/{check_id}", headers=headers)

    def list_wellness_checks(self, headers, params=None):
        return self._request("GET", "/care/wellness-checks", headers=headers, params=params)

    def acknowledge_wellness_check(self, check_id, headers):
        return self._request("POST", f"/care/wellness-checks/{check_id}/acknowledge", {}, headers)

    def resolve_wellness_check(self, check_id, headers):
        return self._request("POST", f"/care/wellness-checks/{check_id}/resolve", {}, headers)

    # ---- Invoices ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/care/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/care/invoices", headers=headers, params=params)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/care/invoices/{invoice_id}/finalize", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/care/invoices/{invoice_id}/void", {}, headers)

    def create_claim(self, invoice_id, payload, headers):
        return self._request("POST", f"/care/invoices/{invoice_id}/claims", payload, headers)

    # ---- Claims ----
    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/care/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/care/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/care/claims/{claim_id}/submit", {}, headers)

    def request_info_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/care/claims/{claim_id}/request-info", payload, headers)

    def claim_decision(self, claim_id, payload, headers):
        return self._request("POST", f"/care/claims/{claim_id}/decision", payload, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/care/claims/{claim_id}/withdraw", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
