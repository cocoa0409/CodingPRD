"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- configuration / actors ---
    def create_package_plan(self, payload, headers):
        return self._request("POST", "/package-plans", payload, headers)

    def get_package_plan(self, plan_id, headers):
        return self._request("GET", f"/package-plans/{plan_id}", headers=headers)

    def list_package_plans(self, headers, params=None):
        return self._request("GET", "/package-plans", headers=headers, params=params)

    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def create_coach(self, payload, headers):
        return self._request("POST", "/coaches", payload, headers)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/coaches/{coach_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", {}, headers)

    def accept_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/accept", {}, headers)

    def list_order_deliverables(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/deliverables", headers=headers, params=params)

    def list_order_addons(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/addons", headers=headers, params=params)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/payments", headers=headers, params=params)

    def list_order_guarantee_claims(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/guarantee-claims", headers=headers, params=params)

    def create_addon(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/addons", payload, headers)

    def create_session(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/sessions", payload, headers)

    def create_guarantee_claim(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/guarantee-claims", payload, headers)

    # --- deliverables ---
    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    def list_deliverable_revisions(self, deliverable_id, headers, params=None):
        return self._request("GET", f"/deliverables/{deliverable_id}/revisions", headers=headers, params=params)

    def list_deliverable_ats_scans(self, deliverable_id, headers, params=None):
        return self._request("GET", f"/deliverables/{deliverable_id}/ats-scans", headers=headers, params=params)

    def create_draft(self, deliverable_id, payload, headers):
        return self._request("POST", f"/deliverables/{deliverable_id}/drafts", payload, headers)

    def create_revision(self, deliverable_id, payload, headers):
        return self._request("POST", f"/deliverables/{deliverable_id}/revisions", payload, headers)

    def approve_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/deliverables/{deliverable_id}/approve", {}, headers)

    def create_ats_scan(self, deliverable_id, payload, headers):
        return self._request("POST", f"/deliverables/{deliverable_id}/ats-scans", payload, headers)

    # --- revisions ---
    def withdraw_revision(self, revision_id, headers):
        return self._request("POST", f"/revisions/{revision_id}/withdraw", {}, headers)

    # --- sessions ---
    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    def no_show_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/no-show", {}, headers)

    # --- guarantee claims ---
    def get_guarantee_claim(self, claim_id, headers):
        return self._request("GET", f"/guarantee-claims/{claim_id}", headers=headers)

    def approve_guarantee_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/approve", {}, headers)

    def reject_guarantee_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/reject", {}, headers)


api_client = ApiClient()
