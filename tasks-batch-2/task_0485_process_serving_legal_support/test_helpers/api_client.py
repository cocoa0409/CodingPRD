"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving) ────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Client ──────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def deposit(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/deposits", payload, headers)

    def set_client_state(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/state", payload, headers)

    # ─── County ──────────────────────────────────────────────────────────
    def create_county(self, payload, headers):
        return self._request("POST", "/counties", payload, headers)

    def get_county(self, county_id, headers):
        return self._request("GET", f"/counties/{county_id}", headers=headers)

    def list_county_territories(self, county_id, headers, params=None):
        return self._request(
            "GET", f"/counties/{county_id}/territories", headers=headers, params=params
        )

    # ─── Server ──────────────────────────────────────────────────────────
    def create_server(self, payload, headers):
        return self._request("POST", "/servers", payload, headers)

    def get_server(self, server_id, headers):
        return self._request("GET", f"/servers/{server_id}", headers=headers)

    def set_server_state(self, server_id, payload, headers):
        return self._request("POST", f"/servers/{server_id}/state", payload, headers)

    def reliability_projection(self, server_id, headers):
        return self._request(
            "GET", f"/servers/{server_id}/reliability-projection", headers=headers
        )

    def create_territory(self, server_id, payload, headers):
        return self._request(
            "POST", f"/servers/{server_id}/territories", payload, headers
        )

    def list_server_territories(self, server_id, headers, params=None):
        return self._request(
            "GET", f"/servers/{server_id}/territories", headers=headers, params=params
        )

    def list_server_stakeouts(self, server_id, headers, params=None):
        return self._request(
            "GET", f"/servers/{server_id}/stakeouts", headers=headers, params=params
        )

    # ─── Assignments (top-level reads) ───────────────────────────────────
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/accept", {}, headers
        )

    def set_assignment_state(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/state", payload, headers
        )

    def create_attempt(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/attempts", payload, headers
        )

    def list_assignment_attempts(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/assignments/{assignment_id}/attempts", headers=headers, params=params
        )

    def create_stakeout(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/stakeouts", payload, headers
        )

    def list_assignment_stakeouts(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/assignments/{assignment_id}/stakeouts", headers=headers, params=params
        )

    def list_assignment_services(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/assignments/{assignment_id}/services", headers=headers, params=params
        )

    # ─── ServiceRequest ──────────────────────────────────────────────────
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def get_service_request(self, sr_id, headers):
        return self._request("GET", f"/service-requests/{sr_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def create_document(self, sr_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{sr_id}/documents", payload, headers
        )

    def list_documents(self, sr_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{sr_id}/documents", headers=headers, params=params
        )

    def submit_request(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/submit", {}, headers)

    def create_skip_trace(self, sr_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{sr_id}/skip-traces", payload, headers
        )

    def list_skip_traces(self, sr_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{sr_id}/skip-traces", headers=headers, params=params
        )

    def offer_assignment(self, sr_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{sr_id}/assignments", payload, headers
        )

    def list_request_assignments(self, sr_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{sr_id}/assignments", headers=headers, params=params
        )

    def reassign(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/reassign", {}, headers)

    def record_service(self, sr_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{sr_id}/services", payload, headers
        )

    def list_request_services(self, sr_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{sr_id}/services", headers=headers, params=params
        )

    def non_est(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/non-est", {}, headers)

    def cancel_request(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/cancel", {}, headers)

    def complete_request(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/complete", {}, headers)

    def list_invoice_lines(self, sr_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{sr_id}/invoice-lines", headers=headers, params=params
        )

    def list_request_attempts(self, sr_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{sr_id}/attempts", headers=headers, params=params
        )

    # ─── SkipTrace ───────────────────────────────────────────────────────
    def get_skip_trace(self, st_id, headers):
        return self._request("GET", f"/skip-traces/{st_id}", headers=headers)

    def set_skip_trace_state(self, st_id, payload, headers):
        return self._request("POST", f"/skip-traces/{st_id}/state", payload, headers)

    # ─── Stakeout ────────────────────────────────────────────────────────
    def set_stakeout_state(self, stakeout_id, payload, headers):
        return self._request(
            "POST", f"/stakeouts/{stakeout_id}/state", payload, headers
        )

    # ─── Affidavit ───────────────────────────────────────────────────────
    def get_affidavit(self, affidavit_id, headers):
        return self._request("GET", f"/affidavits/{affidavit_id}", headers=headers)

    def list_request_affidavits(self, sr_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{sr_id}/affidavits", headers=headers, params=params
        )

    def list_affidavits(self, headers, params=None):
        return self._request("GET", "/affidavits", headers=headers, params=params)

    def sign_affidavit(self, affidavit_id, headers):
        return self._request("POST", f"/affidavits/{affidavit_id}/sign", {}, headers)

    def notarize_affidavit(self, affidavit_id, headers):
        return self._request("POST", f"/affidavits/{affidavit_id}/notarize", {}, headers)

    # ─── Filing ──────────────────────────────────────────────────────────
    def create_filing(self, sr_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{sr_id}/filings", payload, headers
        )

    def list_request_filings(self, sr_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{sr_id}/filings", headers=headers, params=params
        )

    def list_filings(self, headers, params=None):
        return self._request("GET", "/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def set_filing_state(self, filing_id, payload, headers):
        return self._request("POST", f"/filings/{filing_id}/state", payload, headers)


api_client = ApiClient()
