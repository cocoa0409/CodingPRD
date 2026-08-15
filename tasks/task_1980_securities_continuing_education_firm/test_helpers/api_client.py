"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Representatives ---
    def create_representative(self, payload, headers):
        return self._request("POST", "/representatives", payload, headers)

    def list_representatives(self, headers, params=None):
        return self._request("GET", "/representatives", headers=headers, params=params)

    def get_representative(self, rep_id, headers):
        return self._request("GET", f"/representatives/{rep_id}", headers=headers)

    def terminate_representative(self, rep_id, headers):
        return self._request("POST", f"/representatives/{rep_id}/terminate", {}, headers)

    # --- Training content ---
    def create_content(self, payload, headers):
        return self._request("POST", "/contents", payload, headers)

    def list_contents(self, headers, params=None):
        return self._request("GET", "/contents", headers=headers, params=params)

    def get_content(self, content_id, headers):
        return self._request("GET", f"/contents/{content_id}", headers=headers)

    def update_content(self, content_id, payload, headers):
        return self._request("PUT", f"/contents/{content_id}", payload, headers)

    def submit_content(self, content_id, headers):
        return self._request("POST", f"/contents/{content_id}/submit", {}, headers)

    def approve_content(self, content_id, headers):
        return self._request("POST", f"/contents/{content_id}/approve", {}, headers)

    def reject_content(self, content_id, payload, headers):
        return self._request("POST", f"/contents/{content_id}/reject", payload, headers)

    def retire_content(self, content_id, headers):
        return self._request("POST", f"/contents/{content_id}/retire", {}, headers)

    # --- Course sessions ---
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    # --- Enrollments ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def start_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/start", {}, headers)

    def complete_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/complete", payload, headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancel", {}, headers)

    def reattempt_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/reattempt", {}, headers)

    def void_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/void", payload, headers)

    # --- Regulatory assignments ---
    def create_regulatory_assignment(self, payload, headers):
        return self._request("POST", "/regulatory-assignments", payload, headers)

    def list_regulatory_assignments(self, headers, params=None):
        return self._request("GET", "/regulatory-assignments", headers=headers, params=params)

    def get_regulatory_assignment(self, assignment_id, headers):
        return self._request("GET", f"/regulatory-assignments/{assignment_id}", headers=headers)

    # --- Firm element plans ---
    def create_firm_element_plan(self, payload, headers):
        return self._request("POST", "/firm-element-plans", payload, headers)

    def list_firm_element_plans(self, headers, params=None):
        return self._request("GET", "/firm-element-plans", headers=headers, params=params)

    def get_firm_element_plan(self, plan_id, headers):
        return self._request("GET", f"/firm-element-plans/{plan_id}", headers=headers)

    def record_needs_analysis(self, plan_id, payload, headers):
        return self._request("POST", f"/firm-element-plans/{plan_id}/needs-analysis", payload, headers)

    def publish_plan(self, plan_id, headers):
        return self._request("POST", f"/firm-element-plans/{plan_id}/publish", {}, headers)

    def close_plan(self, plan_id, headers):
        return self._request("POST", f"/firm-element-plans/{plan_id}/close", {}, headers)

    # --- Annual attestations ---
    def list_attestations(self, headers, params=None):
        return self._request("GET", "/attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"/attestations/{attestation_id}", headers=headers)

    def attest(self, attestation_id, payload, headers):
        return self._request("POST", f"/attestations/{attestation_id}/attest", payload, headers)

    # --- Product offerings & certifications ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def launch_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/launch", {}, headers)

    def withdraw_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/withdraw", {}, headers)

    def list_product_certifications(self, headers, params=None):
        return self._request("GET", "/product-certifications", headers=headers, params=params)

    def get_product_certification(self, cert_id, headers):
        return self._request("GET", f"/product-certifications/{cert_id}", headers=headers)

    def reinstate_certification(self, cert_id, headers):
        return self._request("POST", f"/product-certifications/{cert_id}/reinstate", {}, headers)

    # --- State CE licenses ---
    def create_state_ce_license(self, payload, headers):
        return self._request("POST", "/state-ce-licenses", payload, headers)

    def list_state_ce_licenses(self, headers, params=None):
        return self._request("GET", "/state-ce-licenses", headers=headers, params=params)

    def get_state_ce_license(self, license_id, headers):
        return self._request("GET", f"/state-ce-licenses/{license_id}", headers=headers)

    def renew_state_ce_license(self, license_id, payload, headers):
        return self._request("POST", f"/state-ce-licenses/{license_id}/renew", payload, headers)

    # --- Blackout windows ---
    def create_blackout_window(self, payload, headers):
        return self._request("POST", "/blackout-windows", payload, headers)

    def list_blackout_windows(self, headers, params=None):
        return self._request("GET", "/blackout-windows", headers=headers, params=params)

    def get_blackout_window(self, window_id, headers):
        return self._request("GET", f"/blackout-windows/{window_id}", headers=headers)

    # --- Enforcement sweep / logical clock / audit evidence ---
    def run_enforcement_sweep(self, headers):
        return self._request("POST", "/enforcement/sweep", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)


api_client = ApiClient()
