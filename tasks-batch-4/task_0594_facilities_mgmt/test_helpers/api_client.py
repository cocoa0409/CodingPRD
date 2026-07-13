"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the /fm prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fm"


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Buildings ----
    def create_building(self, payload, headers):
        return self._request("POST", f"{PREFIX}/buildings", payload, headers)

    def get_building(self, building_id, headers):
        return self._request("GET", f"{PREFIX}/buildings/{building_id}", headers=headers)

    def get_building_kpi(self, building_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/buildings/{building_id}/kpi", headers=headers, params=params
        )

    def ops_run(self, building_id, headers):
        return self._request(
            "POST", f"{PREFIX}/buildings/{building_id}/ops-run", {}, headers
        )

    # ---- Spaces ----
    def create_space(self, building_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buildings/{building_id}/spaces", payload, headers
        )

    def list_building_spaces(self, building_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/buildings/{building_id}/spaces", headers=headers, params=params
        )

    def get_space(self, space_id, headers):
        return self._request("GET", f"{PREFIX}/spaces/{space_id}", headers=headers)

    # ---- Assets ----
    def create_asset(self, payload, headers):
        return self._request("POST", f"{PREFIX}/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"{PREFIX}/assets/{asset_id}", headers=headers)

    def list_building_assets(self, building_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/buildings/{building_id}/assets", headers=headers, params=params
        )

    def report_asset_failure(self, asset_id, headers):
        return self._request(
            "POST", f"{PREFIX}/assets/{asset_id}/report-failure", {}, headers
        )

    # ---- Preventive maintenance ----
    def create_pm_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pm-plans", payload, headers)

    def list_asset_pm_plans(self, asset_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assets/{asset_id}/pm-plans", headers=headers, params=params
        )

    # ---- Vendors ----
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", headers=headers)

    # ---- Work orders ----
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/work-orders/{work_order_id}", headers=headers
        )

    def list_work_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/work-orders", headers=headers, params=params
        )

    def create_dispatch(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/dispatches", payload, headers
        )

    def qa_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/qa", payload, headers
        )

    def cancel_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/cancel", {}, headers
        )

    # ---- Dispatches ----
    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"{PREFIX}/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dispatches", headers=headers, params=params
        )

    def accept_dispatch(self, dispatch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/dispatches/{dispatch_id}/accept", {}, headers
        )

    def decline_dispatch(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/dispatches/{dispatch_id}/decline", payload or {}, headers
        )

    def complete_dispatch(self, dispatch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dispatches/{dispatch_id}/complete", payload, headers
        )

    # ---- Soft services ----
    def create_shift(self, payload, headers):
        return self._request("POST", f"{PREFIX}/soft-service-shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request(
            "GET", f"{PREFIX}/soft-service-shifts/{shift_id}", headers=headers
        )

    def list_shifts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/soft-service-shifts", headers=headers, params=params
        )

    def complete_shift(self, shift_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/soft-service-shifts/{shift_id}/complete", payload, headers
        )

    # ---- Energy / sustainability ----
    def create_utility_reading(self, payload, headers):
        return self._request("POST", f"{PREFIX}/utility-readings", payload, headers)

    def list_building_utility_readings(self, building_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/buildings/{building_id}/utility-readings",
            headers=headers, params=params,
        )

    # ---- Leases / occupancy ----
    def create_lease(self, payload, headers):
        return self._request("POST", f"{PREFIX}/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"{PREFIX}/leases/{lease_id}", headers=headers)

    def list_building_leases(self, building_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/buildings/{building_id}/leases", headers=headers, params=params
        )

    def activate_lease(self, lease_id, headers):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/activate", {}, headers
        )

    def create_allocation(self, lease_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/allocations", payload, headers
        )

    def get_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/lease-allocations/{allocation_id}", headers=headers
        )

    def list_allocations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lease-allocations", headers=headers, params=params
        )

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "DELETE", f"{PREFIX}/lease-allocations/{allocation_id}", headers=headers
        )

    # ---- Chargeback ----
    def create_statement(self, lease_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/statements", payload, headers
        )

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/statements/{statement_id}", headers=headers
        )

    def list_lease_statements(self, lease_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/leases/{lease_id}/statements", headers=headers, params=params
        )

    def issue_statement(self, statement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/statements/{statement_id}/issue", {}, headers
        )

    def dispute_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/statements/{statement_id}/dispute", payload, headers
        )

    def settle_statement(self, statement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/statements/{statement_id}/settle", {}, headers
        )

    # ---- Capital projects ----
    def create_capital_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/capital-projects", payload, headers)

    def get_capital_project(self, project_id, headers):
        return self._request(
            "GET", f"{PREFIX}/capital-projects/{project_id}", headers=headers
        )

    def list_building_capital_projects(self, building_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/buildings/{building_id}/capital-projects",
            headers=headers, params=params,
        )

    def approve_capital_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/capital-projects/{project_id}/approve", payload, headers
        )


api_client = ApiClient()
