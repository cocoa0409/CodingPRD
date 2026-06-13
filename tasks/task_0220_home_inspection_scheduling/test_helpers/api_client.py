"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Territory ---
    def create_territory(self, payload, headers):
        return self._request("POST", "/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"/territories/{territory_id}", headers=headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", "/territories", headers=headers, params=params)

    # --- FeeSchedule ---
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def publish_fee_schedule(self, fee_schedule_id, headers):
        return self._request("POST", f"/fee-schedules/{fee_schedule_id}/publish", {}, headers)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)

    # --- Inspector ---
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/inspectors", headers=headers, params=params)

    def suspend_inspector(self, inspector_id, headers):
        return self._request("POST", f"/inspectors/{inspector_id}/suspend", {}, headers)

    def get_inspector_daily_load(self, inspector_id, headers, params=None):
        return self._request("GET", f"/inspectors/{inspector_id}/daily-load",
                             headers=headers, params=params)

    # --- Client / Agent ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # --- InspectionOrder lifecycle ---
    def create_inspection_order(self, payload, headers):
        return self._request("POST", "/inspection-orders", payload, headers)

    def get_inspection_order(self, order_id, headers):
        return self._request("GET", f"/inspection-orders/{order_id}", headers=headers)

    def list_inspection_orders(self, headers, params=None):
        return self._request("GET", "/inspection-orders", headers=headers, params=params)

    def schedule_order(self, order_id, payload, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/schedule", payload, headers)

    def unschedule_order(self, order_id, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/unschedule", {}, headers)

    def start_order(self, order_id, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/start", {}, headers)

    def create_report(self, order_id, payload, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/report", payload, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/pay", payload, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/cancel", {}, headers)

    def reinspect_order(self, order_id, payload, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/reinspect", payload, headers)

    # --- AddOn (child of order) ---
    def create_addon(self, order_id, payload, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/addons", payload, headers)

    def list_addons(self, order_id, headers, params=None):
        return self._request("GET", f"/inspection-orders/{order_id}/addons",
                             headers=headers, params=params)

    def remove_addon(self, addon_id, headers):
        return self._request("POST", f"/addons/{addon_id}/remove", {}, headers)

    # --- Report ---
    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_order_reports(self, order_id, headers, params=None):
        return self._request("GET", f"/inspection-orders/{order_id}/reports",
                             headers=headers, params=params)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/submit", {}, headers)

    def approve_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/approve", {}, headers)

    def reject_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/reject", {}, headers)

    def revise_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/revise", {}, headers)

    # --- Defect (child of report) ---
    def create_defect(self, report_id, payload, headers):
        return self._request("POST", f"/reports/{report_id}/defects", payload, headers)

    def list_defects(self, report_id, headers, params=None):
        return self._request("GET", f"/reports/{report_id}/defects",
                             headers=headers, params=params)

    # --- Delivery (child of order) ---
    def list_deliveries(self, order_id, headers, params=None):
        return self._request("GET", f"/inspection-orders/{order_id}/deliveries",
                             headers=headers, params=params)


api_client = ApiClient()
