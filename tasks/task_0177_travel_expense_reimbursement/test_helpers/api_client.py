"""API client — one method per endpoint defined in PRD §4.

Subclasses GenericApiClient; the base `_request()` handles HTTP plumbing.
Path-parameter resolution proceeds left-to-right per PRD §2.5; the
caller is responsible for assembling URLs from real ids.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Trip — PRD §3.1
    # ======================================================================
    def create_trip(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/trips", payload, headers)

    def list_trips(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/trips", headers=headers, params=params,
        )

    def get_trip(self, trip_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/trips/{trip_id}", headers=headers,
        )

    def update_trip(self, trip_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/trips/{trip_id}", payload, headers,
        )

    def submit_trip(self, trip_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trips/{trip_id}/submit", payload, headers,
        )

    def approve_trip(self, trip_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trips/{trip_id}/approve", payload, headers,
        )

    def reject_trip(self, trip_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trips/{trip_id}/reject", payload, headers,
        )

    def request_changes_trip(self, trip_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trips/{trip_id}/request-changes", payload, headers,
        )

    def complete_trip(self, trip_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trips/{trip_id}/complete", payload, headers,
        )

    def cancel_trip(self, trip_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trips/{trip_id}/cancel", payload, headers,
        )

    # ======================================================================
    # VirtualCard — PRD §3.2
    # ======================================================================
    def create_virtual_card(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/virtual-cards", payload, headers)

    def get_virtual_card(self, card_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/virtual-cards/{card_id}", headers=headers,
        )

    def issue_virtual_card(self, card_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/virtual-cards/{card_id}/issue", payload, headers,
        )

    def activate_virtual_card(self, card_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/virtual-cards/{card_id}/activate", payload, headers,
        )

    def lock_virtual_card(self, card_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/virtual-cards/{card_id}/lock", payload, headers,
        )

    def unlock_virtual_card(self, card_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/virtual-cards/{card_id}/unlock", payload, headers,
        )

    def close_virtual_card(self, card_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/virtual-cards/{card_id}/close", payload, headers,
        )

    # ======================================================================
    # ExpenseReport — PRD §3.3, §3.6
    # ======================================================================
    def create_expense_report(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/expense-reports", payload, headers)

    def list_expense_reports(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/expense-reports", headers=headers, params=params,
        )

    def get_expense_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/expense-reports/{report_id}", headers=headers,
        )

    def update_expense_report(self, report_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/expense-reports/{report_id}", payload, headers,
        )

    def submit_expense_report(self, report_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/expense-reports/{report_id}/submit",
            payload, headers,
        )

    def claim_expense_report(self, report_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/expense-reports/{report_id}/claim",
            payload, headers,
        )

    def approve_expense_report(self, report_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/expense-reports/{report_id}/approve",
            payload, headers,
        )

    def reject_expense_report(self, report_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/expense-reports/{report_id}/reject",
            payload, headers,
        )

    def request_changes_expense_report(self, report_id: str,
                                       headers: Dict[str, str],
                                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/expense-reports/{report_id}/request-changes",
            payload, headers,
        )

    def disburse_expense_report(self, report_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/expense-reports/{report_id}/disburse",
            payload, headers,
        )

    # ======================================================================
    # ExpenseLine — PRD §3.3
    # ======================================================================
    def create_expense_line(self, report_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/expense-reports/{report_id}/lines",
            payload, headers,
        )

    def get_expense_line(self, line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/expense-lines/{line_id}", headers=headers,
        )

    def update_expense_line(self, line_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/expense-lines/{line_id}", payload, headers,
        )

    def attach_receipt(self, line_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/expense-lines/{line_id}/attach-receipt",
            payload, headers,
        )

    def waive_ocr(self, line_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/expense-lines/{line_id}/waive-ocr",
            payload, headers,
        )

    # ======================================================================
    # Receipt — PRD §3.4
    # ======================================================================
    def create_receipt(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/receipts", payload, headers)

    def get_receipt(self, receipt_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/receipts/{receipt_id}", headers=headers,
        )

    # ======================================================================
    # OutOfPolicyApproval — PRD §3.5
    # ======================================================================
    def create_oop_approval(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/oop-approvals", payload, headers)

    def get_oop_approval(self, approval_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/oop-approvals/{approval_id}", headers=headers,
        )

    def oop_l1_approve(self, approval_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/oop-approvals/{approval_id}/l1-approve",
            payload, headers,
        )

    def oop_l2_approve(self, approval_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/oop-approvals/{approval_id}/l2-approve",
            payload, headers,
        )

    def oop_final_approve(self, approval_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/oop-approvals/{approval_id}/final-approve",
            payload, headers,
        )

    def oop_deny(self, approval_id: str, headers: Dict[str, str],
                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/oop-approvals/{approval_id}/deny",
            payload, headers,
        )

    # ======================================================================
    # PerDiemRate — PRD §3.12
    # ======================================================================
    def create_per_diem_rate(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/per-diem-rates", payload, headers,
        )

    def list_per_diem_rates(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/per-diem-rates", headers=headers, params=params,
        )

    # ======================================================================
    # Employee — PRD §3.12
    # ======================================================================
    def create_employee(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/employees/{employee_id}", headers=headers,
        )

    # ======================================================================
    # Test clock — PRD §3.12
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
