"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Traveler ----
    def create_traveler(self, payload, headers):
        return self._request("POST", "/travelers", payload, headers)

    def get_traveler(self, traveler_id, headers):
        return self._request("GET", f"/travelers/{traveler_id}", headers=headers)

    def list_travelers(self, headers, params=None):
        return self._request("GET", "/travelers", headers=headers, params=params)

    # ---- Approver ----
    def create_approver(self, payload, headers):
        return self._request("POST", "/approvers", payload, headers)

    def get_approver(self, approver_id, headers):
        return self._request("GET", f"/approvers/{approver_id}", headers=headers)

    # ---- TravelPolicy ----
    def create_travel_policy(self, payload, headers):
        return self._request("POST", "/travel-policies", payload, headers)

    def get_travel_policy(self, policy_id, headers):
        return self._request("GET", f"/travel-policies/{policy_id}", headers=headers)

    def activate_travel_policy(self, policy_id, headers):
        return self._request("POST", f"/travel-policies/{policy_id}/activate", headers=headers)

    def retire_travel_policy(self, policy_id, headers):
        return self._request("POST", f"/travel-policies/{policy_id}/retire", headers=headers)

    # ---- PerDiemRate ----
    def create_per_diem_rate(self, payload, headers):
        return self._request("POST", "/per-diem-rates", payload, headers)

    def get_per_diem_rate(self, rate_id, headers):
        return self._request("GET", f"/per-diem-rates/{rate_id}", headers=headers)

    def list_per_diem_rates(self, headers, params=None):
        return self._request("GET", "/per-diem-rates", headers=headers, params=params)

    # ---- TripRequest ----
    def create_trip_request(self, payload, headers):
        return self._request("POST", "/trip-requests", payload, headers)

    def get_trip_request(self, trip_id, headers):
        return self._request("GET", f"/trip-requests/{trip_id}", headers=headers)

    def list_trip_requests(self, headers, params=None):
        return self._request("GET", "/trip-requests", headers=headers, params=params)

    def submit_trip_request(self, trip_id, headers):
        return self._request("POST", f"/trip-requests/{trip_id}/submit", headers=headers)

    def decide_trip_request(self, trip_id, payload, headers):
        return self._request("POST", f"/trip-requests/{trip_id}/decision", payload, headers)

    def cancel_trip_request(self, trip_id, headers):
        return self._request("POST", f"/trip-requests/{trip_id}/cancel", headers=headers)

    # ---- VirtualCard (issued under a trip) ----
    def issue_virtual_card(self, trip_id, payload, headers):
        return self._request("POST", f"/trip-requests/{trip_id}/virtual-cards", payload, headers)

    def get_virtual_card(self, card_id, headers):
        return self._request("GET", f"/virtual-cards/{card_id}", headers=headers)

    def list_virtual_cards(self, headers, params=None):
        return self._request("GET", "/virtual-cards", headers=headers, params=params)

    def freeze_virtual_card(self, card_id, headers):
        return self._request("POST", f"/virtual-cards/{card_id}/freeze", headers=headers)

    def unfreeze_virtual_card(self, card_id, headers):
        return self._request("POST", f"/virtual-cards/{card_id}/unfreeze", headers=headers)

    def close_virtual_card(self, card_id, headers):
        return self._request("POST", f"/virtual-cards/{card_id}/close", headers=headers)

    # ---- ExpenseReport ----
    def create_expense_report(self, payload, headers):
        return self._request("POST", "/expense-reports", payload, headers)

    def get_expense_report(self, report_id, headers):
        return self._request("GET", f"/expense-reports/{report_id}", headers=headers)

    def list_expense_reports(self, headers, params=None):
        return self._request("GET", "/expense-reports", headers=headers, params=params)

    def submit_expense_report(self, report_id, headers):
        return self._request("POST", f"/expense-reports/{report_id}/submit", headers=headers)

    def decide_expense_report(self, report_id, payload, headers):
        return self._request("POST", f"/expense-reports/{report_id}/decision", payload, headers)

    def reopen_expense_report(self, report_id, headers):
        return self._request("POST", f"/expense-reports/{report_id}/reopen", headers=headers)

    # ---- ExpenseLine ----
    def create_expense_line(self, payload, headers):
        return self._request("POST", "/expense-lines", payload, headers)

    def get_expense_line(self, line_id, headers):
        return self._request("GET", f"/expense-lines/{line_id}", headers=headers)

    def list_expense_lines(self, headers, params=None):
        return self._request("GET", "/expense-lines", headers=headers, params=params)

    def delete_expense_line(self, line_id, headers):
        return self._request("DELETE", f"/expense-lines/{line_id}", headers=headers)

    # ---- Receipt ----
    def create_receipt(self, payload, headers):
        return self._request("POST", "/receipts", payload, headers)

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/receipts", headers=headers, params=params)

    def ocr_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/receipts/{receipt_id}/ocr", payload, headers)

    def verify_receipt(self, receipt_id, headers):
        return self._request("POST", f"/receipts/{receipt_id}/verify", headers=headers)

    def dispute_receipt(self, receipt_id, headers):
        return self._request("POST", f"/receipts/{receipt_id}/dispute", headers=headers)

    # ---- ApprovalStep (out-of-policy chain) ----
    def create_approval_step(self, payload, headers):
        return self._request("POST", "/approval-steps", payload, headers)

    def get_approval_step(self, step_id, headers):
        return self._request("GET", f"/approval-steps/{step_id}", headers=headers)

    def list_approval_steps(self, headers, params=None):
        return self._request("GET", "/approval-steps", headers=headers, params=params)

    def decide_approval_step(self, step_id, payload, headers):
        return self._request("POST", f"/approval-steps/{step_id}/decision", payload, headers)


api_client = ApiClient()
