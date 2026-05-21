"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. Endpoints follow PRD §4 verbatim.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Employee — PRD §3.1
    # ======================================================================
    def create_employee(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/employees/{employee_id}", headers=headers,
        )

    def update_employee(self, employee_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/employees/{employee_id}", payload, headers,
        )

    def list_employees(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/employees", headers=headers, params=params,
        )

    # ======================================================================
    # I9Document — PRD §3.2
    # ======================================================================
    def create_i9_document(self, employee_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/employees/{employee_id}/i9-documents",
            payload, headers,
        )

    def list_i9_documents(self, employee_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/employees/{employee_id}/i9-documents",
            headers=headers, params=params,
        )

    # ======================================================================
    # I9Form — PRD §3.3
    # ======================================================================
    def create_i9_form(self, employee_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/employees/{employee_id}/i9-forms",
            payload, headers,
        )

    def list_i9_forms(self, employee_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/employees/{employee_id}/i9-forms",
            headers=headers, params=params,
        )

    def attest_section1(self, employee_id: str, form_id: str,
                        payload: Optional[Dict[str, Any]],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/employees/{employee_id}/i9-forms/{form_id}/section1",
            payload, headers,
        )

    def sign_section2(self, employee_id: str, form_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/employees/{employee_id}/i9-forms/{form_id}/section2",
            payload, headers,
        )

    def void_i9_form(self, form_id: str,
                     payload: Optional[Dict[str, Any]],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/i9-forms/{form_id}/void",
            payload, headers,
        )

    # ======================================================================
    # EVerifyCase — PRD §3.5, §3.6
    # ======================================================================
    def submit_everify_case(self, employee_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/employees/{employee_id}/everify-cases",
            payload, headers,
        )

    def get_everify_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/everify-cases/{case_id}", headers=headers,
        )

    def deliver_everify_result(self, case_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/everify-cases/{case_id}/result",
            payload, headers,
        )

    def submit_tnc_decision(self, case_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/everify-cases/{case_id}/tnc-decision",
            payload, headers,
        )

    def close_everify_case(self, case_id: str,
                           payload: Optional[Dict[str, Any]],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/everify-cases/{case_id}/close",
            payload, headers,
        )

    # ======================================================================
    # ReverificationEvent — PRD §3.4
    # ======================================================================
    def list_reverification_events(self, employee_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/employees/{employee_id}/reverification-events",
            headers=headers, params=params,
        )

    # ======================================================================
    # AuditEvent — PRD §2.8
    # ======================================================================
    def list_audit_events(self, employee_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/employees/{employee_id}/audit-events",
            headers=headers, params=params,
        )

    # ======================================================================
    # Logical clock / sweep — PRD §2.6, §2.11
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload, headers,
        )


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
