"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/panel-shop/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/panel-shop/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/panel-shop/customers", headers=headers, params=params)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/panel-shop/customers/{customer_id}", payload, headers)

    def list_customer_jobs(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/panel-shop/customers/{customer_id}/jobs", headers=headers, params=params
        )

    # --- jobs ---
    def create_job(self, payload, headers):
        return self._request("POST", "/panel-shop/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/panel-shop/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/panel-shop/jobs", headers=headers, params=params)

    def advance_job(self, job_id, headers):
        return self._request("POST", f"/panel-shop/jobs/{job_id}/advance", {}, headers)

    def hold_job(self, job_id, headers):
        return self._request("POST", f"/panel-shop/jobs/{job_id}/hold", {}, headers)

    def resume_job(self, job_id, headers):
        return self._request("POST", f"/panel-shop/jobs/{job_id}/resume", {}, headers)

    def ship_job(self, job_id, headers):
        return self._request("POST", f"/panel-shop/jobs/{job_id}/ship", {}, headers)

    def close_job(self, job_id, headers):
        return self._request("POST", f"/panel-shop/jobs/{job_id}/close", {}, headers)

    def list_job_panels(self, job_id, headers, params=None):
        return self._request(
            "GET", f"/panel-shop/jobs/{job_id}/panels", headers=headers, params=params
        )

    def list_job_change_orders(self, job_id, headers, params=None):
        return self._request(
            "GET", f"/panel-shop/jobs/{job_id}/change-orders", headers=headers, params=params
        )

    def list_job_warranty_claims(self, job_id, headers, params=None):
        return self._request(
            "GET", f"/panel-shop/jobs/{job_id}/warranty-claims", headers=headers, params=params
        )

    # --- panels ---
    def create_panel(self, job_id, payload, headers):
        return self._request("POST", f"/panel-shop/jobs/{job_id}/panels", payload, headers)

    def get_panel(self, panel_id, headers):
        return self._request("GET", f"/panel-shop/panels/{panel_id}", headers=headers)

    def list_panels(self, headers, params=None):
        return self._request("GET", "/panel-shop/panels", headers=headers, params=params)

    def submit_review(self, panel_id, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/submit-review", {}, headers)

    def approve_design(self, panel_id, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/approve-design", {}, headers)

    def reject_design(self, panel_id, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/reject-design", {}, headers)

    def release_procurement(self, panel_id, headers):
        return self._request(
            "POST", f"/panel-shop/panels/{panel_id}/release-procurement", {}, headers
        )

    def start_wiring(self, panel_id, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/start-wiring", {}, headers)

    def begin_test(self, panel_id, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/begin-test", {}, headers)

    def rework_panel(self, panel_id, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/rework", {}, headers)

    def request_label(self, panel_id, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/request-label", {}, headers)

    def affix_label(self, panel_id, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/affix-label", {}, headers)

    # --- panel BOM lines ---
    def add_panel_component(self, panel_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/panels/{panel_id}/components", payload, headers
        )

    def list_panel_components(self, panel_id, headers, params=None):
        return self._request(
            "GET", f"/panel-shop/panels/{panel_id}/components", headers=headers, params=params
        )

    def get_panel_component(self, line_id, headers):
        return self._request("GET", f"/panel-shop/panel-components/{line_id}", headers=headers)

    def list_all_panel_components(self, headers, params=None):
        return self._request("GET", "/panel-shop/panel-components", headers=headers, params=params)

    def list_component_panel_components(self, component_id, headers, params=None):
        return self._request(
            "GET",
            f"/panel-shop/components/{component_id}/panel-components",
            headers=headers,
            params=params,
        )

    def update_panel_component(self, line_id, payload, headers):
        return self._request(
            "PATCH", f"/panel-shop/panel-components/{line_id}", payload, headers
        )

    def receive_panel_component(self, line_id, headers):
        return self._request(
            "POST", f"/panel-shop/panel-components/{line_id}/receive", {}, headers
        )

    # --- catalog components ---
    def create_component(self, payload, headers):
        return self._request("POST", "/panel-shop/components", payload, headers)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/panel-shop/components/{component_id}", headers=headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/panel-shop/components", headers=headers, params=params)

    def update_component(self, component_id, payload, headers):
        return self._request(
            "PATCH", f"/panel-shop/components/{component_id}", payload, headers
        )

    # --- substitution requests ---
    def create_substitution_request(self, panel_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/panels/{panel_id}/substitution-requests", payload, headers
        )

    def get_substitution_request(self, request_id, headers):
        return self._request(
            "GET", f"/panel-shop/substitution-requests/{request_id}", headers=headers
        )

    def list_panel_substitution_requests(self, panel_id, headers, params=None):
        return self._request(
            "GET",
            f"/panel-shop/panels/{panel_id}/substitution-requests",
            headers=headers,
            params=params,
        )

    def list_substitution_requests(self, headers, params=None):
        return self._request(
            "GET", "/panel-shop/substitution-requests", headers=headers, params=params
        )

    def counter_substitution(self, request_id, headers):
        return self._request(
            "POST", f"/panel-shop/substitution-requests/{request_id}/counter", {}, headers
        )

    def resubmit_substitution(self, request_id, headers):
        return self._request(
            "POST", f"/panel-shop/substitution-requests/{request_id}/resubmit", {}, headers
        )

    def approve_substitution(self, request_id, headers):
        return self._request(
            "POST", f"/panel-shop/substitution-requests/{request_id}/approve", {}, headers
        )

    def reject_substitution(self, request_id, headers):
        return self._request(
            "POST", f"/panel-shop/substitution-requests/{request_id}/reject", {}, headers
        )

    def withdraw_substitution(self, request_id, headers):
        return self._request(
            "POST", f"/panel-shop/substitution-requests/{request_id}/withdraw", {}, headers
        )

    # --- test points & sessions ---
    def create_test_point(self, panel_id, payload, headers):
        return self._request("POST", f"/panel-shop/panels/{panel_id}/test-points", payload, headers)

    def list_test_points(self, panel_id, headers, params=None):
        return self._request(
            "GET", f"/panel-shop/panels/{panel_id}/test-points", headers=headers, params=params
        )

    def create_test_session(self, panel_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/panels/{panel_id}/test-sessions", payload, headers
        )

    def get_test_session(self, session_id, headers):
        return self._request("GET", f"/panel-shop/test-sessions/{session_id}", headers=headers)

    def list_panel_test_sessions(self, panel_id, headers, params=None):
        return self._request(
            "GET", f"/panel-shop/panels/{panel_id}/test-sessions", headers=headers, params=params
        )

    def record_result(self, session_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/test-sessions/{session_id}/record-result", payload, headers
        )

    def complete_test_session(self, session_id, headers):
        return self._request(
            "POST", f"/panel-shop/test-sessions/{session_id}/complete", {}, headers
        )

    def abort_test_session(self, session_id, headers):
        return self._request(
            "POST", f"/panel-shop/test-sessions/{session_id}/abort", {}, headers
        )

    # --- program versions ---
    def create_program_version(self, panel_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/panels/{panel_id}/program-versions", payload, headers
        )

    def get_program_version(self, version_id, headers):
        return self._request("GET", f"/panel-shop/program-versions/{version_id}", headers=headers)

    def list_panel_program_versions(self, panel_id, headers, params=None):
        return self._request(
            "GET",
            f"/panel-shop/panels/{panel_id}/program-versions",
            headers=headers,
            params=params,
        )

    def archive_program_version(self, version_id, headers):
        return self._request(
            "POST", f"/panel-shop/program-versions/{version_id}/archive", {}, headers
        )

    def mark_site_backup(self, version_id, headers):
        return self._request(
            "POST", f"/panel-shop/program-versions/{version_id}/mark-site-backup", {}, headers
        )

    # --- startup sessions ---
    def create_startup_session(self, panel_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/panels/{panel_id}/startup-sessions", payload, headers
        )

    def get_startup_session(self, session_id, headers):
        return self._request("GET", f"/panel-shop/startup-sessions/{session_id}", headers=headers)

    def list_panel_startup_sessions(self, panel_id, headers, params=None):
        return self._request(
            "GET",
            f"/panel-shop/panels/{panel_id}/startup-sessions",
            headers=headers,
            params=params,
        )

    def start_startup_session(self, session_id, headers):
        return self._request(
            "POST", f"/panel-shop/startup-sessions/{session_id}/start", {}, headers
        )

    def complete_startup_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/startup-sessions/{session_id}/complete", payload, headers
        )

    def cancel_startup_session(self, session_id, headers):
        return self._request(
            "POST", f"/panel-shop/startup-sessions/{session_id}/cancel", {}, headers
        )

    # --- change orders ---
    def create_change_order(self, job_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/jobs/{job_id}/change-orders", payload, headers
        )

    def get_change_order(self, order_id, headers):
        return self._request("GET", f"/panel-shop/change-orders/{order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/panel-shop/change-orders", headers=headers, params=params)

    def revise_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/change-orders/{order_id}/revise", payload, headers
        )

    def repropose_change_order(self, order_id, headers):
        return self._request(
            "POST", f"/panel-shop/change-orders/{order_id}/repropose", {}, headers
        )

    def approve_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/change-orders/{order_id}/approve", payload, headers
        )

    def reject_change_order(self, order_id, headers):
        return self._request(
            "POST", f"/panel-shop/change-orders/{order_id}/reject", {}, headers
        )

    def withdraw_change_order(self, order_id, headers):
        return self._request(
            "POST", f"/panel-shop/change-orders/{order_id}/withdraw", {}, headers
        )

    def rescind_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/change-orders/{order_id}/rescind", payload, headers
        )

    # --- warranty claims ---
    def create_warranty_claim(self, job_id, payload, headers):
        return self._request(
            "POST", f"/panel-shop/jobs/{job_id}/warranty-claims", payload, headers
        )

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/panel-shop/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/panel-shop/warranty-claims", headers=headers, params=params)

    def triage_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/panel-shop/warranty-claims/{claim_id}/triage", {}, headers
        )

    def accept_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/panel-shop/warranty-claims/{claim_id}/accept", {}, headers
        )

    def deny_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/panel-shop/warranty-claims/{claim_id}/deny", {}, headers
        )

    def settle_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/panel-shop/warranty-claims/{claim_id}/settle", {}, headers
        )

    def close_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/panel-shop/warranty-claims/{claim_id}/close", {}, headers
        )

    # --- as-built packages ---
    def get_asbuilt_package(self, package_id, headers):
        return self._request(
            "GET", f"/panel-shop/as-built-packages/{package_id}", headers=headers
        )

    def list_panel_asbuilt_packages(self, panel_id, headers):
        return self._request(
            "GET", f"/panel-shop/panels/{panel_id}/as-built-packages", headers=headers
        )

    def update_asbuilt_package(self, package_id, payload, headers):
        return self._request(
            "PATCH", f"/panel-shop/as-built-packages/{package_id}", payload, headers
        )

    def approve_asbuilt_package(self, package_id, headers):
        return self._request(
            "POST", f"/panel-shop/as-built-packages/{package_id}/approve", {}, headers
        )

    def return_asbuilt_for_rework(self, package_id, headers):
        return self._request(
            "POST", f"/panel-shop/as-built-packages/{package_id}/return-for-rework", {}, headers
        )

    def release_asbuilt_package(self, package_id, headers):
        return self._request(
            "POST", f"/panel-shop/as-built-packages/{package_id}/release", {}, headers
        )


api_client = ApiClient()
