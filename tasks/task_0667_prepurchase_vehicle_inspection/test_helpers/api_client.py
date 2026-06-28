"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", headers=headers)

    def list_account_orders(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/orders", headers=headers, params=params)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    # --- FeeSchedule ---
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)

    # --- Inspector ---
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def set_inspector_status(self, inspector_id, payload, headers):
        return self._request("POST", f"/inspectors/{inspector_id}/set-status", payload, headers)

    def list_inspector_assignments(self, inspector_id, headers, params=None):
        return self._request("GET", f"/inspectors/{inspector_id}/assignments", headers=headers, params=params)

    # --- InspectionOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/inspection-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/inspection-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/inspection-orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/pay", headers=headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/invoice", headers=headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/deliver", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/inspection-orders/{order_id}/cancel", headers=headers)

    # --- DispatchAssignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/dispatch-assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/dispatch-assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/dispatch-assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/dispatch-assignments/{assignment_id}/accept", headers=headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/dispatch-assignments/{assignment_id}/decline", headers=headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/dispatch-assignments/{assignment_id}/release", headers=headers)

    # --- InspectionReport ---
    def create_report(self, payload, headers):
        return self._request("POST", "/inspection-reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/inspection-reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/inspection-reports", headers=headers, params=params)

    def add_report_photo(self, report_id, payload, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/photos", payload, headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/submit", headers=headers)

    def amend_report(self, report_id, payload, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/amend", payload, headers)

    # --- ReportPhoto reads ---
    def get_report_photo(self, photo_id, headers):
        return self._request("GET", f"/report-photos/{photo_id}", headers=headers)

    def list_report_photos(self, headers, params=None):
        return self._request("GET", "/report-photos", headers=headers, params=params)

    # --- VIN history / VinReport ---
    def add_history_record(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/history-records", payload, headers)

    def get_history_record(self, record_id, headers):
        return self._request("GET", f"/vin-history-records/{record_id}", headers=headers)

    def list_history_records(self, headers, params=None):
        return self._request("GET", "/vin-history-records", headers=headers, params=params)

    def create_vin_report(self, payload, headers):
        return self._request("POST", "/vin-reports", payload, headers)

    def get_vin_report(self, vin_report_id, headers):
        return self._request("GET", f"/vin-reports/{vin_report_id}", headers=headers)

    def list_vin_reports(self, headers, params=None):
        return self._request("GET", "/vin-reports", headers=headers, params=params)

    # --- RecallRecord ---
    def create_recall(self, payload, headers):
        return self._request("POST", "/recall-records", payload, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/recall-records/{recall_id}/close", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/recall-records", headers=headers, params=params)

    # --- Dispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def start_review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/start-review", headers=headers)

    def request_info_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/request-info", headers=headers)

    def supply_info_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/supply-info", headers=headers)

    def resolve_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", headers=headers)

    def reject_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/reject", headers=headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
