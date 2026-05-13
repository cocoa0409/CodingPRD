"""API client for the Travel Reimburse API.

One method per endpoint defined in PRD §4. Each method delegates to
GenericApiClient._request and returns the raw Response object. Tests
must pass headers explicitly because PRD §2.1 requires X-User-ID and
X-User-Role on every request.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Employee  (PRD §3.1, §4)
    # =======================================================================
    def create_employee(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/employees/{employee_id}", headers=headers,
        )

    # =======================================================================
    # ExpenseStandard  (PRD §3.1, §4)
    # =======================================================================
    def create_expense_standard(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", "/expense-standards", payload, headers)

    def list_expense_standards(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/expense-standards", headers=headers, params=params,
        )

    # =======================================================================
    # TravelApplication  (PRD §3.2, §4)
    # =======================================================================
    def create_travel_application(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/travel-applications", payload, headers,
        )

    def get_travel_application(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/travel-applications/{app_id}", headers=headers,
        )

    def patch_travel_application(self, app_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/travel-applications/{app_id}", payload, headers,
        )

    def submit_travel_application(self, app_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/travel-applications/{app_id}/submit",
            payload or {}, headers,
        )

    def approve_travel_application(self, app_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/travel-applications/{app_id}/approve",
            payload or {}, headers,
        )

    def reject_travel_application(self, app_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/travel-applications/{app_id}/reject",
            payload, headers,
        )

    def complete_travel_application(self, app_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/travel-applications/{app_id}/complete",
            payload or {}, headers,
        )

    def cancel_travel_application(self, app_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/travel-applications/{app_id}/cancel",
            payload or {}, headers,
        )

    def get_budget_projection(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/travel-applications/{app_id}/budget-projection",
            headers=headers,
        )

    # =======================================================================
    # ItinerarySegment  (PRD §3.3, §4)
    # =======================================================================
    def book_itinerary(self, app_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/travel-applications/{app_id}/itineraries",
            payload, headers,
        )

    def list_itineraries(self, app_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/travel-applications/{app_id}/itineraries",
            headers=headers, params=params,
        )

    def change_itinerary(self, app_id: str, seg_id: str,
                         payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/travel-applications/{app_id}/itineraries/{seg_id}/change",
            payload, headers,
        )

    def cancel_itinerary(self, app_id: str, seg_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/travel-applications/{app_id}/itineraries/{seg_id}/cancel",
            payload or {}, headers,
        )

    # =======================================================================
    # Invoice  (PRD §3.6, §4)
    # =======================================================================
    def upload_invoice(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/invoices", payload, headers)

    def ocr_invoice(self, invoice_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None,
                    idempotency_key: Optional[str] = None):
        merged_headers = dict(headers)
        if idempotency_key is not None:
            merged_headers["Idempotency-Key"] = idempotency_key
        return self._request(
            "POST", f"/invoices/{invoice_id}/ocr",
            payload or {}, merged_headers,
        )

    def verify_tax_invoice(self, invoice_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/verify-tax",
            payload or {}, headers,
        )

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/invoices/{invoice_id}", headers=headers,
        )

    # =======================================================================
    # ReimbursementForm + ReimbursementItem  (PRD §3.7, §4)
    # =======================================================================
    def create_reimbursement_form(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/reimbursement-forms", payload, headers,
        )

    def add_reimbursement_item(self, form_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/reimbursement-forms/{form_id}/items",
            payload, headers,
        )

    def delete_reimbursement_item(self, form_id: str, item_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/reimbursement-forms/{form_id}/items/{item_id}",
            headers=headers,
        )

    def submit_reimbursement_form(self, form_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reimbursement-forms/{form_id}/submit",
            payload or {}, headers,
        )

    def approve_reimbursement_form(self, form_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reimbursement-forms/{form_id}/approve",
            payload or {}, headers,
        )

    def reject_reimbursement_form(self, form_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/reimbursement-forms/{form_id}/reject",
            payload, headers,
        )

    def get_reimbursement_form(self, form_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/reimbursement-forms/{form_id}", headers=headers,
        )

    # =======================================================================
    # Payment  (PRD §3.9, §4)
    # =======================================================================
    def create_payment_batch(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/payments/batches", payload, headers,
        )

    def execute_payment(self, payment_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/payments/{payment_id}/execute",
            payload or {}, headers,
        )

    def post_payment_result(self, payment_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/payments/{payment_id}/result", payload, headers,
        )

    def retry_payment(self, payment_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/payments/{payment_id}/retry",
            payload or {}, headers,
        )

    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/payments/{payment_id}", headers=headers,
        )

    def list_payments(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/payments", headers=headers, params=params,
        )

    # =======================================================================
    # Audit and ApprovalRecord streams  (PRD §3.10, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    def list_approval_records(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/approval-records", headers=headers, params=params,
        )

    # =======================================================================
    # Test-harness endpoints  (PRD §3.10, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def pin_invoice_verify_result(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/_external/invoice-verify-result", payload, headers,
        )

    def seed_booking_options(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/_external/booking-options", payload, headers,
        )


# Module-level singleton — tests import this and pass it as the `api` fixture.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
