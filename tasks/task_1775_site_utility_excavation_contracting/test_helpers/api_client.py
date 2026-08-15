"""API client: one method per endpoint defined in the PRD (§4).

All resources live under the single mount point ``/site-utility``.
"""

from prd_bench_local_runner.testing import GenericApiClient

_BASE = "/site-utility"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{_BASE}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---------------- projects ----------------
    def create_project(self, payload, headers):
        return self._request("POST", f"{_BASE}/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{_BASE}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{_BASE}/projects/{project_id}", headers=headers)

    def begin_closeout(self, project_id, headers):
        return self._request(
            "POST", f"{_BASE}/projects/{project_id}/begin-closeout", {}, headers
        )

    def close_project(self, project_id, headers):
        return self._request(
            "POST", f"{_BASE}/projects/{project_id}/close", {}, headers
        )

    def list_audit_events(self, project_id, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/projects/{project_id}/audit-events",
            headers=headers, params=params,
        )

    # ---------------- utility owners ----------------
    def create_utility_owner(self, payload, headers):
        return self._request("POST", f"{_BASE}/utility-owners", payload, headers)

    def list_utility_owners(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/utility-owners", headers=headers, params=params
        )

    def get_utility_owner(self, owner_id, headers):
        return self._request(
            "GET", f"{_BASE}/utility-owners/{owner_id}", headers=headers
        )

    # ---------------- locate tickets ----------------
    def create_locate_ticket(self, payload, headers):
        return self._request("POST", f"{_BASE}/locate-tickets", payload, headers)

    def list_locate_tickets(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/locate-tickets", headers=headers, params=params
        )

    def get_locate_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"{_BASE}/locate-tickets/{ticket_id}", headers=headers
        )

    def submit_locate_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"{_BASE}/locate-tickets/{ticket_id}/submit", {}, headers
        )

    def renew_locate_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"{_BASE}/locate-tickets/{ticket_id}/renew", {}, headers
        )

    # ---------------- pothole verifications ----------------
    def create_pothole_verification(self, payload, headers):
        return self._request("POST", f"{_BASE}/pothole-verifications", payload, headers)

    def list_pothole_verifications(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/pothole-verifications", headers=headers, params=params
        )

    def get_pothole_verification(self, pothole_id, headers):
        return self._request(
            "GET", f"{_BASE}/pothole-verifications/{pothole_id}", headers=headers
        )

    def perform_pothole(self, pothole_id, payload, headers):
        return self._request(
            "POST", f"{_BASE}/pothole-verifications/{pothole_id}/perform",
            payload, headers,
        )

    def verify_pothole(self, pothole_id, headers):
        return self._request(
            "POST", f"{_BASE}/pothole-verifications/{pothole_id}/verify", {}, headers
        )

    def mark_pothole_conflict(self, pothole_id, headers):
        return self._request(
            "POST", f"{_BASE}/pothole-verifications/{pothole_id}/mark-conflict",
            {}, headers,
        )

    # ---------------- trench safety plans ----------------
    def create_trench_safety_plan(self, payload, headers):
        return self._request("POST", f"{_BASE}/trench-safety-plans", payload, headers)

    def list_trench_safety_plans(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/trench-safety-plans", headers=headers, params=params
        )

    def get_trench_safety_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{_BASE}/trench-safety-plans/{plan_id}", headers=headers
        )

    def submit_trench_safety_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{_BASE}/trench-safety-plans/{plan_id}/submit", {}, headers
        )

    def review_trench_safety_plan(self, plan_id, decision, headers):
        return self._request(
            "POST", f"{_BASE}/trench-safety-plans/{plan_id}/review",
            {"decision": decision}, headers,
        )

    def revise_trench_safety_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{_BASE}/trench-safety-plans/{plan_id}/revise", payload, headers
        )

    # ---------------- pipe segments ----------------
    def create_pipe_segment(self, payload, headers):
        return self._request("POST", f"{_BASE}/pipe-segments", payload, headers)

    def list_pipe_segments(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/pipe-segments", headers=headers, params=params
        )

    def get_pipe_segment(self, segment_id, headers):
        return self._request(
            "GET", f"{_BASE}/pipe-segments/{segment_id}", headers=headers
        )

    def mark_segment_ready(self, segment_id, headers):
        return self._request(
            "POST", f"{_BASE}/pipe-segments/{segment_id}/mark-ready", {}, headers
        )

    def start_install(self, segment_id, headers):
        return self._request(
            "POST", f"{_BASE}/pipe-segments/{segment_id}/start-install", {}, headers
        )

    def complete_install(self, segment_id, headers):
        return self._request(
            "POST", f"{_BASE}/pipe-segments/{segment_id}/complete-install", {}, headers
        )

    def reopen_install(self, segment_id, headers):
        return self._request(
            "POST", f"{_BASE}/pipe-segments/{segment_id}/reopen-install", {}, headers
        )

    def start_backfill(self, segment_id, headers):
        return self._request(
            "POST", f"{_BASE}/pipe-segments/{segment_id}/start-backfill", {}, headers
        )

    def complete_segment(self, segment_id, headers):
        return self._request(
            "POST", f"{_BASE}/pipe-segments/{segment_id}/complete", {}, headers
        )

    # ---------------- installation inspections ----------------
    def create_installation_inspection(self, payload, headers):
        return self._request(
            "POST", f"{_BASE}/installation-inspections", payload, headers
        )

    def list_installation_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/installation-inspections", headers=headers, params=params
        )

    def get_installation_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{_BASE}/installation-inspections/{inspection_id}", headers=headers
        )

    def confirm_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{_BASE}/installation-inspections/{inspection_id}/confirm",
            {}, headers,
        )

    def dispute_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{_BASE}/installation-inspections/{inspection_id}/dispute",
            {}, headers,
        )

    # ---------------- shutdown windows ----------------
    def create_shutdown_window(self, payload, headers):
        return self._request("POST", f"{_BASE}/shutdown-windows", payload, headers)

    def list_shutdown_windows(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/shutdown-windows", headers=headers, params=params
        )

    def get_shutdown_window(self, window_id, headers):
        return self._request(
            "GET", f"{_BASE}/shutdown-windows/{window_id}", headers=headers
        )

    def review_shutdown_window(self, window_id, decision, headers):
        return self._request(
            "POST", f"{_BASE}/shutdown-windows/{window_id}/review",
            {"decision": decision}, headers,
        )

    def cancel_shutdown_window(self, window_id, headers):
        return self._request(
            "POST", f"{_BASE}/shutdown-windows/{window_id}/cancel", {}, headers
        )

    def complete_shutdown_window(self, window_id, headers):
        return self._request(
            "POST", f"{_BASE}/shutdown-windows/{window_id}/complete", {}, headers
        )

    # ---------------- discharge permits & readings ----------------
    def create_discharge_permit(self, payload, headers):
        return self._request("POST", f"{_BASE}/discharge-permits", payload, headers)

    def list_discharge_permits(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/discharge-permits", headers=headers, params=params
        )

    def get_discharge_permit(self, permit_id, headers):
        return self._request(
            "GET", f"{_BASE}/discharge-permits/{permit_id}", headers=headers
        )

    def reinstate_discharge_permit(self, permit_id, headers):
        return self._request(
            "POST", f"{_BASE}/discharge-permits/{permit_id}/reinstate", {}, headers
        )

    def list_discharge_readings(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/discharge-permits/{permit_id}/readings",
            headers=headers, params=params,
        )

    def create_discharge_reading(self, payload, headers):
        return self._request("POST", f"{_BASE}/discharge-readings", payload, headers)

    # ---------------- compaction tests ----------------
    def create_compaction_test(self, payload, headers):
        return self._request("POST", f"{_BASE}/compaction-tests", payload, headers)

    def list_compaction_tests(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/compaction-tests", headers=headers, params=params
        )

    def get_compaction_test(self, test_id, headers):
        return self._request(
            "GET", f"{_BASE}/compaction-tests/{test_id}", headers=headers
        )

    def review_compaction_test(self, test_id, decision, headers):
        return self._request(
            "POST", f"{_BASE}/compaction-tests/{test_id}/review",
            {"decision": decision}, headers,
        )

    # ---------------- as-built packages ----------------
    def create_as_built_package(self, payload, headers):
        return self._request("POST", f"{_BASE}/as-built-packages", payload, headers)

    def list_as_built_packages(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/as-built-packages", headers=headers, params=params
        )

    def get_as_built_package(self, package_id, headers):
        return self._request(
            "GET", f"{_BASE}/as-built-packages/{package_id}", headers=headers
        )

    def submit_as_built_package(self, package_id, headers):
        return self._request(
            "POST", f"{_BASE}/as-built-packages/{package_id}/submit", {}, headers
        )

    def review_as_built_package(self, package_id, decision, headers):
        return self._request(
            "POST", f"{_BASE}/as-built-packages/{package_id}/review",
            {"decision": decision}, headers,
        )

    def revise_as_built_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"{_BASE}/as-built-packages/{package_id}/revise", payload, headers
        )

    # ---------------- unforeseen conditions ----------------
    def create_unforeseen_condition(self, payload, headers):
        return self._request("POST", f"{_BASE}/unforeseen-conditions", payload, headers)

    def list_unforeseen_conditions(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/unforeseen-conditions", headers=headers, params=params
        )

    def get_unforeseen_condition(self, condition_id, headers):
        return self._request(
            "GET", f"{_BASE}/unforeseen-conditions/{condition_id}", headers=headers
        )

    def resolve_unforeseen_condition(self, condition_id, outcome, headers):
        return self._request(
            "POST", f"{_BASE}/unforeseen-conditions/{condition_id}/resolve",
            {"outcome": outcome}, headers,
        )

    # ---------------- change orders ----------------
    def create_change_order(self, payload, headers):
        return self._request("POST", f"{_BASE}/change-orders", payload, headers)

    def list_change_orders(self, headers, params=None):
        return self._request(
            "GET", f"{_BASE}/change-orders", headers=headers, params=params
        )

    def get_change_order(self, order_id, headers):
        return self._request("GET", f"{_BASE}/change-orders/{order_id}", headers=headers)

    def submit_change_order(self, order_id, headers):
        return self._request(
            "POST", f"{_BASE}/change-orders/{order_id}/submit", {}, headers
        )

    def review_change_order(self, order_id, decision, headers):
        return self._request(
            "POST", f"{_BASE}/change-orders/{order_id}/review",
            {"decision": decision}, headers,
        )

    def revise_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{_BASE}/change-orders/{order_id}/revise", payload, headers
        )

    def complete_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{_BASE}/change-orders/{order_id}/complete", payload, headers
        )


api_client = ApiClient()
# The runner restarts the server before every test (per-test-server
# isolation). A pooled keep-alive connection from the previous test points
# at the killed process and intermittently fails with RemoteDisconnected.
# Forcing Connection: close makes every request open a fresh connection.
api_client.session.headers["Connection"] = "close"
