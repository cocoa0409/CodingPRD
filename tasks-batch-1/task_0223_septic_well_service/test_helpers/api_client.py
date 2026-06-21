"""API client: one method per endpoint defined in the PRD (Septic & Well Service)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Account -----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_account_sites(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/sites", headers=headers, params=params)

    def hold_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/hold", {}, headers)

    def release_account_hold(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/release-hold", {}, headers)

    # ----- Technician -----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def suspend_technician(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/suspend", {}, headers)

    def reinstate_technician(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/reinstate", {}, headers)

    def list_technician_routes(self, technician_id, headers, params=None):
        return self._request("GET", f"/technicians/{technician_id}/routes", headers=headers, params=params)

    # ----- Site -----
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_site_assets(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/assets", headers=headers, params=params)

    def list_site_service_plans(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/service-plans", headers=headers, params=params)

    def list_site_reminders(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/reminders", headers=headers, params=params)

    # ----- Asset -----
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    # ----- ServicePlan -----
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    # ----- WorkOrder -----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/schedule", payload, headers)

    def dispatch_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/dispatch", {}, headers)

    def revert_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/revert", {}, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", {}, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    def invoice_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/invoice", {}, headers)

    def pay_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/pay", {}, headers)

    def list_work_order_repair_lines(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/repair-lines", headers=headers, params=params)

    def list_work_order_inspection_reports(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/inspection-reports", headers=headers, params=params)

    # ----- RepairLine -----
    def create_repair_line(self, payload, headers):
        return self._request("POST", "/repair-lines", payload, headers)

    # ----- Route -----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_route_work_orders(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/work-orders", headers=headers, params=params)

    def optimize_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/optimize", {}, headers)

    def lock_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/lock", {}, headers)

    # ----- InspectionReport -----
    def create_inspection_report(self, payload, headers):
        return self._request("POST", "/inspection-reports", payload, headers)

    def get_inspection_report(self, report_id, headers):
        return self._request("GET", f"/inspection-reports/{report_id}", headers=headers)

    def patch_inspection_report(self, report_id, payload, headers):
        return self._request("PATCH", f"/inspection-reports/{report_id}", payload, headers)

    def finalize_inspection_report(self, report_id, payload, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/finalize", payload, headers)

    # ----- PermitFiling -----
    def create_permit_filing(self, payload, headers):
        return self._request("POST", "/permit-filings", payload, headers)

    def get_permit_filing(self, filing_id, headers):
        return self._request("GET", f"/permit-filings/{filing_id}", headers=headers)

    def list_permit_filings(self, headers, params=None):
        return self._request("GET", "/permit-filings", headers=headers, params=params)

    def submit_permit_filing(self, filing_id, headers):
        return self._request("POST", f"/permit-filings/{filing_id}/submit", {}, headers)

    def decide_permit_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/permit-filings/{filing_id}/decide", payload, headers)

    def reopen_permit_filing(self, filing_id, headers):
        return self._request("POST", f"/permit-filings/{filing_id}/reopen", {}, headers)

    # ----- Reminder -----
    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/reminders/{reminder_id}", headers=headers)

    def acknowledge_reminder(self, reminder_id, headers):
        return self._request("POST", f"/reminders/{reminder_id}/acknowledge", {}, headers)

    # ----- Test-driving clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
