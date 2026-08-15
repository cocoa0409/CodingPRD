"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Talents
    # ------------------------------------------------------------------
    def create_talent(self, payload, headers):
        return self._request("POST", "/api/talents", payload, headers)

    def get_talent(self, talent_id, headers):
        return self._request("GET", f"/api/talents/{talent_id}", headers=headers)

    def list_talents(self, headers, params=None):
        return self._request("GET", "/api/talents", headers=headers, params=params)

    def update_talent(self, talent_id, payload, headers):
        return self._request("PUT", f"/api/talents/{talent_id}", payload, headers)

    def list_talent_conflict_exclusions(self, talent_id, headers):
        return self._request("GET", f"/api/talents/{talent_id}/conflict_exclusions",
                             headers=headers)

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/api/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}", headers=headers)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/projects", headers=headers, params=params)

    def open_casting(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/open_casting", {}, headers)

    def select_talent(self, project_id, self_audition_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/select_talent",
                             {"self_audition_id": self_audition_id}, headers)

    def cancel_project(self, project_id, expected_project_version, headers):
        return self._request("POST", f"/api/projects/{project_id}/cancel",
                             {"expected_project_version": expected_project_version}, headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/close", {}, headers)

    def request_revision(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/request_revision",
                             {}, headers)

    # ------------------------------------------------------------------
    # Self-auditions
    # ------------------------------------------------------------------
    def submit_self_audition(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/self_auditions",
                             payload, headers)

    def list_project_auditions(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}/self_auditions",
                             headers=headers)

    def list_self_auditions(self, headers, params=None):
        return self._request("GET", "/api/self_auditions", headers=headers, params=params)

    def get_self_audition(self, audition_id, headers):
        return self._request("GET", f"/api/self_auditions/{audition_id}", headers=headers)

    def shortlist_audition(self, audition_id, headers):
        return self._request("POST", f"/api/self_auditions/{audition_id}/shortlist",
                             {}, headers)

    def reject_audition(self, audition_id, headers):
        return self._request("POST", f"/api/self_auditions/{audition_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Studios
    # ------------------------------------------------------------------
    def create_studio(self, payload, headers):
        return self._request("POST", "/api/studios", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/api/studios/{studio_id}", headers=headers)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_session(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/sessions",
                             payload, headers)

    def list_project_sessions(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}/sessions", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/api/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/api/sessions/{session_id}", headers=headers)

    def confirm_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/confirm", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Usage terms
    # ------------------------------------------------------------------
    def get_usage_terms(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}/usage_terms",
                             headers=headers)

    def update_usage_terms(self, project_id, payload, headers):
        return self._request("PUT", f"/api/projects/{project_id}/usage_terms",
                             payload, headers)

    # ------------------------------------------------------------------
    # Deliveries
    # ------------------------------------------------------------------
    def create_delivery(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/deliveries",
                             payload, headers)

    def list_project_deliveries(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}/deliveries",
                             headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/api/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/api/deliveries/{delivery_id}", headers=headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def list_project_invoices(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}/invoices", headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", {}, headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/mark_paid", {}, headers)

    # ------------------------------------------------------------------
    # Conflict exclusions
    # ------------------------------------------------------------------
    def get_conflict_exclusion(self, exclusion_id, headers):
        return self._request("GET", f"/api/conflict_exclusions/{exclusion_id}",
                             headers=headers)

    def release_conflict_exclusion(self, exclusion_id, headers):
        return self._request("POST", f"/api/conflict_exclusions/{exclusion_id}/release",
                             {}, headers)


api_client = ApiClient()
