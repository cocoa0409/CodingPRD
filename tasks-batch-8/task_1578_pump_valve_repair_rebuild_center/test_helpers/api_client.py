"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Repair orders
    # ------------------------------------------------------------------
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, ro_id, headers):
        return self._request("GET", f"/repair-orders/{ro_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def start_teardown(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/start-teardown", {}, headers)

    def start_repair(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/start-repair", {}, headers)

    def log_assembly(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/log-assembly", {}, headers)

    def submit_for_test(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/submit-for-test", {}, headers)

    def close_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/close", {}, headers)

    def cancel_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Inspection reports
    # ------------------------------------------------------------------
    def create_inspection_report(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/inspection-reports",
                             payload, headers)

    def list_inspection_reports(self, ro_id, headers):
        return self._request("GET", f"/repair-orders/{ro_id}/inspection-reports",
                             headers=headers)

    def finalize_inspection_report(self, report_id, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/finalize",
                             {}, headers)

    # ------------------------------------------------------------------
    # Quotes
    # ------------------------------------------------------------------
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def issue_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/issue", {}, headers)

    def approve_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/approve", {}, headers)

    def request_quote_revision(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/request-revision", {}, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/decline", {}, headers)

    # ------------------------------------------------------------------
    # Parts
    # ------------------------------------------------------------------
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def mark_part_obsolete(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/mark-obsolete", payload, headers)

    # ------------------------------------------------------------------
    # Pool units
    # ------------------------------------------------------------------
    def create_pool_unit(self, payload, headers):
        return self._request("POST", "/pool-units", payload, headers)

    def get_pool_unit(self, unit_id, headers):
        return self._request("GET", f"/pool-units/{unit_id}", headers=headers)

    def list_pool_units(self, headers, params=None):
        return self._request("GET", "/pool-units", headers=headers, params=params)

    def reserve_pool_unit(self, unit_id, repair_order_id, headers):
        return self._request("POST", f"/pool-units/{unit_id}/reserve",
                             {"repair_order_id": repair_order_id}, headers)

    def release_pool_unit(self, unit_id, headers):
        return self._request("POST", f"/pool-units/{unit_id}/release", {}, headers)

    def issue_pool_unit(self, unit_id, headers):
        return self._request("POST", f"/pool-units/{unit_id}/issue", {}, headers)

    def withdraw_pool_unit(self, unit_id, headers):
        return self._request("POST", f"/pool-units/{unit_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Test runs
    # ------------------------------------------------------------------
    def create_test_run(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/test-runs", payload, headers)

    def list_test_runs(self, ro_id, headers):
        return self._request("GET", f"/repair-orders/{ro_id}/test-runs", headers=headers)

    # ------------------------------------------------------------------
    # Certifications
    # ------------------------------------------------------------------
    def create_certification(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/certifications",
                             payload, headers)

    def list_certifications(self, ro_id, headers):
        return self._request("GET", f"/repair-orders/{ro_id}/certifications",
                             headers=headers)

    def void_certification(self, cert_id, void_reason, headers):
        return self._request("POST", f"/certifications/{cert_id}/void",
                             {"void_reason": void_reason}, headers)

    # ------------------------------------------------------------------
    # Capacity windows
    # ------------------------------------------------------------------
    def create_capacity_window(self, payload, headers):
        return self._request("POST", "/capacity-windows", payload, headers)

    def get_capacity_window(self, window_id, headers):
        return self._request("GET", f"/capacity-windows/{window_id}", headers=headers)

    def list_capacity_windows(self, headers, params=None):
        return self._request("GET", "/capacity-windows", headers=headers, params=params)


api_client = ApiClient()
