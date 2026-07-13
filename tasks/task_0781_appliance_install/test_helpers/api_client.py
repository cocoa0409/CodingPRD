"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Clock (test-driving) -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ----- Retailer -----
    def create_retailer(self, payload, headers):
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"/retailers/{retailer_id}", headers=headers)

    def update_retailer_status(self, retailer_id, payload, headers):
        return self._request("PATCH", f"/retailers/{retailer_id}/status", payload, headers)

    def run_settlement(self, retailer_id, payload, headers):
        return self._request("POST", f"/retailers/{retailer_id}/settlements", payload, headers)

    # ----- ServiceZone -----
    def create_service_zone(self, payload, headers):
        return self._request("POST", "/service-zones", payload, headers)

    def get_service_zone(self, zone_id, headers):
        return self._request("GET", f"/service-zones/{zone_id}", headers=headers)

    # ----- Customer -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ----- Pro -----
    def create_pro(self, payload, headers):
        return self._request("POST", "/pros", payload, headers)

    def get_pro(self, pro_id, headers):
        return self._request("GET", f"/pros/{pro_id}", headers=headers)

    def list_pros(self, headers, params=None):
        return self._request("GET", "/pros", headers=headers, params=params)

    # ----- ProApplication -----
    def create_application(self, pro_id, payload, headers):
        return self._request("POST", f"/pros/{pro_id}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/approve", {}, headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/reject", {}, headers)

    def suspend_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/suspend", {}, headers)

    def reinstate_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/reinstate", {}, headers)

    # ----- InstallTask -----
    def create_install_task(self, payload, headers):
        return self._request("POST", "/install-tasks", payload, headers)

    def get_install_task(self, task_id, headers):
        return self._request("GET", f"/install-tasks/{task_id}", headers=headers)

    # ----- AddOn -----
    def create_addon(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/add-ons/{addon_id}", headers=headers)

    # ----- WorkOrder -----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/schedule", payload, headers)

    def dispatch_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/dispatch", payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", {}, headers)

    def add_part(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/parts", payload, headers)

    def list_parts(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/parts", headers=headers, params=params)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", {}, headers)

    def request_redo(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/request-redo", {}, headers)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", payload, headers)

    def close_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/close", {}, headers)

    def create_rating(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/ratings", payload, headers)

    # ----- Rating -----
    def get_rating(self, rating_id, headers):
        return self._request("GET", f"/ratings/{rating_id}", headers=headers)

    def list_ratings(self, headers, params=None):
        return self._request("GET", "/ratings", headers=headers, params=params)

    # ----- Assignment -----
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline", {}, headers)

    def expire_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/expire", {}, headers)

    # ----- PayoutRecord -----
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payout-records/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payout-records", headers=headers, params=params)

    # ----- RetailerSettlementEntry -----
    def get_settlement_entry(self, entry_id, headers):
        return self._request("GET", f"/settlement-entries/{entry_id}", headers=headers)

    def list_settlement_entries(self, headers, params=None):
        return self._request("GET", "/settlement-entries", headers=headers, params=params)


api_client = ApiClient()
