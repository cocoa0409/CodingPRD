"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every standard endpoint.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Clients
    # ======================================================================
    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/clients/{client_id}", headers=headers,
        )

    def update_client(self, client_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/clients/{client_id}", payload, headers,
        )

    # ======================================================================
    # Testers
    # ======================================================================
    def create_tester(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/testers", payload, headers)

    def get_tester(self, tester_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/testers/{tester_id}", headers=headers,
        )

    def update_tester(self, tester_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/testers/{tester_id}", payload, headers,
        )

    def list_testers(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/testers", headers=headers, params=params,
        )

    # ======================================================================
    # Reviewers & Signatories
    # ======================================================================
    def create_reviewer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/reviewers", payload, headers)

    def create_signatory(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/signatories", payload, headers)

    # ======================================================================
    # Instruments
    # ======================================================================
    def create_instrument(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/instruments", payload, headers)

    def get_instrument(self, instrument_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/instruments/{instrument_id}", headers=headers,
        )

    def update_instrument(self, instrument_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/instruments/{instrument_id}", payload, headers,
        )

    def report_instrument_failure(self, instrument_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/instruments/{instrument_id}/report-failure",
            {}, headers,
        )

    def return_instrument_to_service(self, instrument_id: str,
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/instruments/{instrument_id}/return-to-service",
            {}, headers,
        )

    def delete_instrument(self, instrument_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/instruments/{instrument_id}", headers=headers,
        )

    def create_instrument_booking(self, instrument_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/instruments/{instrument_id}/bookings",
            payload, headers,
        )

    def list_instrument_bookings(self, instrument_id: str,
                                 headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/instruments/{instrument_id}/bookings",
            headers=headers, params=params,
        )

    # ======================================================================
    # Samples
    # ======================================================================
    def create_sample(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/samples", payload, headers)

    def get_sample(self, sample_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/samples/{sample_id}", headers=headers,
        )

    def list_samples(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/samples", headers=headers, params=params,
        )

    def delete_sample(self, sample_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/samples/{sample_id}", headers=headers,
        )

    # ======================================================================
    # Test tasks
    # ======================================================================
    def create_test_task(self, sample_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/samples/{sample_id}/tasks", payload, headers,
        )

    def get_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tasks/{task_id}", headers=headers,
        )

    def assign_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tasks/{task_id}/assign", {}, headers,
        )

    def reassign_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tasks/{task_id}/reassign", {}, headers,
        )

    def start_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tasks/{task_id}/start", {}, headers,
        )

    def complete_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tasks/{task_id}/complete", {}, headers,
        )

    def cancel_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tasks/{task_id}/cancel", {}, headers,
        )

    # ======================================================================
    # Records / Data modifications
    # ======================================================================
    def create_record(self, task_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/tasks/{task_id}/records", payload, headers,
        )

    def list_records(self, task_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tasks/{task_id}/records",
            headers=headers, params=params,
        )

    def update_record(self, record_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/records/{record_id}", payload, headers,
        )

    def list_record_modifications(self, record_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/records/{record_id}/modifications",
            headers=headers, params=params,
        )

    # ======================================================================
    # Reports
    # ======================================================================
    def create_report(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tasks/{task_id}/report", {}, headers,
        )

    def submit_report_for_review(self, report_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/reports/{report_id}/submit-for-review", {}, headers,
        )

    def approve_review(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/reports/{report_id}/approve-review", {}, headers,
        )

    def send_back_review(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/reports/{report_id}/send-back", {}, headers,
        )

    def sign_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/reports/{report_id}/sign", {}, headers,
        )

    def issue_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/reports/{report_id}/issue", {}, headers,
        )

    def recall_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/reports/{report_id}/recall", {}, headers,
        )

    def reopen_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/reports/{report_id}/reopen", {}, headers,
        )

    def get_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/reports/{report_id}", headers=headers,
        )

    # ======================================================================
    # Invoices
    # ======================================================================
    def create_invoice(self, client_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/clients/{client_id}/invoices", payload, headers,
        )

    def void_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/invoices/{invoice_id}/void", {}, headers,
        )

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/invoices/{invoice_id}", headers=headers,
        )

    # ======================================================================
    # Audit & system endpoints
    # ======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-events", headers=headers, params=params,
        )

    def run_internal_audit(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_audit/run-internal", {}, headers,
        )

    def respond_external_inspection(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", "/_audit/respond-external", payload, headers,
        )

    def advance_clock(self, payload: Dict[str, Any],
                      headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def emit_event(self, payload: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_events/emit", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
