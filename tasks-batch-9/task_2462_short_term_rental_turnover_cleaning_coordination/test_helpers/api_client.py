"""API client: one method per endpoint defined in the PRD (§4)."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Short-Term Rental Turnover Coordination API."""

    # ─── Properties ────────────────────────────────────────────────────────

    def create_property(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # ─── Supply lines ──────────────────────────────────────────────────────

    def create_supply_line(self, property_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"/properties/{property_id}/supply-lines",
                             payload, headers)

    def list_property_supply_lines(self, property_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request("GET", f"/properties/{property_id}/supply-lines",
                             payload=params, headers=headers)

    def get_supply_line(self, supply_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/supply-lines/{supply_line_id}", headers=headers)

    def replenish_supply_line(self, supply_line_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/supply-lines/{supply_line_id}/replenish",
                             payload, headers)

    # ─── Stock movements ───────────────────────────────────────────────────

    def list_stock_movements(self, headers: Dict[str, str],
                            params: Optional[Dict] = None):
        return self._request("GET", "/stock-movements", payload=params, headers=headers)

    def get_stock_movement(self, movement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stock-movements/{movement_id}", headers=headers)

    # ─── Cleaners ──────────────────────────────────────────────────────────

    def create_cleaner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cleaners", payload, headers)

    def get_cleaner(self, cleaner_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cleaners/{cleaner_id}", headers=headers)

    def set_cleaner_status(self, cleaner_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/cleaners/{cleaner_id}/status", payload, headers)

    # ─── Pay lines ─────────────────────────────────────────────────────────

    def list_pay_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/pay-lines", payload=params, headers=headers)

    def get_pay_line(self, pay_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pay-lines/{pay_line_id}", headers=headers)

    # ─── Bookings ──────────────────────────────────────────────────────────

    def create_booking(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/bookings", payload=params, headers=headers)

    def get_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def schedule_change_booking(self, booking_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/schedule-change",
                             payload, headers)

    def checkout_booking(self, booking_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/checkout", payload, headers)

    def cancel_booking(self, booking_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    def submit_guest_review(self, booking_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/guest-review",
                             payload, headers)

    # ─── Turnovers ─────────────────────────────────────────────────────────

    def create_turnover(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/turnovers", payload, headers)

    def list_turnovers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/turnovers", payload=params, headers=headers)

    def get_turnover(self, turnover_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/turnovers/{turnover_id}", headers=headers)

    def list_turnover_checklist_tasks(self, turnover_id: str, headers: Dict[str, str],
                                      params: Optional[Dict] = None):
        return self._request("GET", f"/turnovers/{turnover_id}/checklist-tasks",
                             payload=params, headers=headers)

    def get_pay_preview(self, turnover_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/turnovers/{turnover_id}/pay-preview",
                             headers=headers)

    def assign_turnover(self, turnover_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"/turnovers/{turnover_id}/assign", payload, headers)

    def start_turnover(self, turnover_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"/turnovers/{turnover_id}/start", payload, headers)

    def complete_turnover(self, turnover_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/turnovers/{turnover_id}/complete",
                             payload, headers)

    # ─── Assignments ───────────────────────────────────────────────────────

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/assignments", payload=params, headers=headers)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/assignments/{assignment_id}/accept",
                             payload, headers)

    def decline_assignment(self, assignment_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"/assignments/{assignment_id}/decline",
                             payload, headers)

    # ─── Checklist tasks ───────────────────────────────────────────────────

    def submit_checklist_task(self, task_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/checklist-tasks/{task_id}/submit",
                             payload, headers)

    def review_checklist_task(self, task_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/checklist-tasks/{task_id}/review",
                             payload, headers)

    # ─── Issue reports ─────────────────────────────────────────────────────

    def create_issue_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/issue-reports", payload, headers)

    def list_issue_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/issue-reports", payload=params, headers=headers)

    def get_issue_report(self, issue_report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issue-reports/{issue_report_id}", headers=headers)

    def dispatch_issue_report(self, issue_report_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/issue-reports/{issue_report_id}/dispatch",
                             payload, headers)

    # ─── Repair orders ─────────────────────────────────────────────────────

    def list_repair_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/repair-orders", payload=params, headers=headers)

    def get_repair_order(self, repair_order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/repair-orders/{repair_order_id}", headers=headers)

    def complete_repair_order(self, repair_order_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/repair-orders/{repair_order_id}/complete",
                             payload, headers)

    # ─── Quality audits ────────────────────────────────────────────────────

    def create_quality_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/quality-audits", payload, headers)

    def list_quality_audits(self, headers: Dict[str, str],
                            params: Optional[Dict] = None):
        return self._request("GET", "/quality-audits", payload=params, headers=headers)

    def get_quality_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/quality-audits/{audit_id}", headers=headers)

    def finalize_quality_audit(self, audit_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"/quality-audits/{audit_id}/finalize",
                             payload, headers)

    # ─── Logical clock ─────────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
