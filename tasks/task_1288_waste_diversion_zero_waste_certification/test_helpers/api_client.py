"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # per-test-server isolation kill -9's and rebinds the server before
        # every test; a pooled keep-alive connection to the killed process
        # races urllib3's liveness check and surfaces as ConnectionResetError.
        # Connection: close forces a fresh connection per request, removing
        # the stale-socket race entirely.
        merged = {"Connection": "close"}
        merged.update(headers or {})
        return super()._request(method, path, payload=payload, headers=merged,
                                params=params)

    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    # --- Vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def set_vendor_status(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/set_status", payload, headers)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", {}, headers)

    # --- Tickets ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def validate_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/validate", {}, headers)

    def reject_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/reject", payload, headers)

    def resubmit_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/resubmit", payload, headers)

    def void_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/void", payload, headers)

    # --- Audits ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    # --- Contamination events ---
    def create_contamination_event(self, payload, headers):
        return self._request("POST", "/contamination_events", payload, headers)

    def get_contamination_event(self, event_id, headers):
        return self._request("GET", f"/contamination_events/{event_id}", headers=headers)

    def list_contamination_events(self, headers, params=None):
        return self._request("GET", "/contamination_events", headers=headers, params=params)

    def assign_training(self, event_id, payload, headers):
        return self._request("POST", f"/contamination_events/{event_id}/assign_training", payload, headers)

    def complete_training(self, event_id, headers):
        return self._request("POST", f"/contamination_events/{event_id}/complete_training", {}, headers)

    def verify_event(self, event_id, payload, headers):
        return self._request("POST", f"/contamination_events/{event_id}/verify", payload, headers)

    def dismiss_event(self, event_id, payload, headers):
        return self._request("POST", f"/contamination_events/{event_id}/dismiss", payload, headers)

    # --- Goals ---
    def create_goal(self, payload, headers):
        return self._request("POST", "/goals", payload, headers)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"/goals/{goal_id}", headers=headers)

    def list_goals(self, headers, params=None):
        return self._request("GET", "/goals", headers=headers, params=params)

    def cancel_goal(self, goal_id, headers):
        return self._request("POST", f"/goals/{goal_id}/cancel", {}, headers)

    # --- Scorecard periods ---
    def create_period(self, payload, headers):
        return self._request("POST", "/scorecard_periods", payload, headers)

    def get_period(self, period_id, headers):
        return self._request("GET", f"/scorecard_periods/{period_id}", headers=headers)

    def list_periods(self, headers, params=None):
        return self._request("GET", "/scorecard_periods", headers=headers, params=params)

    def close_period(self, period_id, headers):
        return self._request("POST", f"/scorecard_periods/{period_id}/close", {}, headers)

    # --- Certification applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/certification_applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/certification_applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/certification_applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/certification_applications/{application_id}/submit", {}, headers)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/certification_applications/{application_id}/start_review", {}, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/certification_applications/{application_id}/decide", payload, headers)

    def revise_application(self, application_id, headers):
        return self._request("POST", f"/certification_applications/{application_id}/revise", {}, headers)


api_client = ApiClient()
