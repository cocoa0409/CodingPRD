"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Taxpayers — PRD §4
    # =======================================================================
    def create_taxpayer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/taxpayers", payload, headers)

    def get_taxpayer(self, taxpayer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/taxpayers/{taxpayer_id}", headers=headers,
        )

    def compliance_lock(self, taxpayer_id: str,
                        payload: Optional[Dict[str, Any]],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/taxpayers/{taxpayer_id}/compliance-lock",
            payload if payload is not None else {}, headers,
        )

    def compliance_unlock(self, taxpayer_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/taxpayers/{taxpayer_id}/compliance-unlock",
            {}, headers,
        )

    # =======================================================================
    # Tax Returns — PRD §4
    # =======================================================================
    def create_tax_return(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/tax-returns", payload, headers)

    def get_tax_return(self, tax_return_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/tax-returns/{tax_return_id}", headers=headers,
        )

    def list_tax_returns(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/tax-returns", headers=headers, params=params,
        )

    def patch_tax_return(self, tax_return_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/tax-returns/{tax_return_id}", payload, headers,
        )

    def compute_tax_return(self, tax_return_id: str,
                           payload: Optional[Dict[str, Any]],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/tax-returns/{tax_return_id}/compute",
            payload if payload is not None else {}, headers,
        )

    def efile_tax_return(self, tax_return_id: str,
                         payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/tax-returns/{tax_return_id}/efile",
            payload if payload is not None else {}, headers,
        )

    def unlock_for_correction(self, tax_return_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tax-returns/{tax_return_id}/unlock-for-correction",
            {}, headers,
        )

    def get_safe_harbor(self, tax_return_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/tax-returns/{tax_return_id}/safe-harbor",
            headers=headers,
        )

    # =======================================================================
    # Income Documents — PRD §4
    # =======================================================================
    def create_income_document(self, tax_return_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tax-returns/{tax_return_id}/income-documents",
            payload, headers,
        )

    def list_income_documents(self, tax_return_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tax-returns/{tax_return_id}/income-documents",
            headers=headers, params=params,
        )

    def patch_income_document(self, income_document_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/income-documents/{income_document_id}",
            payload, headers,
        )

    def delete_income_document(self, income_document_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/income-documents/{income_document_id}",
            headers=headers,
        )

    # =======================================================================
    # Schedules — PRD §4
    # =======================================================================
    def create_schedule(self, tax_return_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/tax-returns/{tax_return_id}/schedules",
            payload, headers,
        )

    def list_schedules(self, tax_return_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tax-returns/{tax_return_id}/schedules",
            headers=headers, params=params,
        )

    def patch_schedule(self, schedule_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/schedules/{schedule_id}", payload, headers,
        )

    # =======================================================================
    # Tax Credits — PRD §4
    # =======================================================================
    def create_credit(self, tax_return_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/tax-returns/{tax_return_id}/credits",
            payload, headers,
        )

    def list_credits(self, tax_return_id: str,
                     headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tax-returns/{tax_return_id}/credits",
            headers=headers, params=params,
        )

    def delete_credit(self, credit_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/credits/{credit_id}", headers=headers,
        )

    # =======================================================================
    # EFilings — PRD §4
    # =======================================================================
    def get_efiling(self, efiling_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/efilings/{efiling_id}", headers=headers,
        )

    def decide_efiling(self, efiling_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/efilings/{efiling_id}/decide", payload, headers,
        )

    # =======================================================================
    # Amendments — PRD §4
    # =======================================================================
    def create_amendment(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/amendments", payload, headers)

    def get_amendment(self, amendment_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/amendments/{amendment_id}", headers=headers,
        )

    def submit_amendment(self, amendment_id: str,
                         payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/amendments/{amendment_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def decide_amendment(self, amendment_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/amendments/{amendment_id}/decide",
            payload, headers,
        )

    # =======================================================================
    # Estimated Tax Payments — PRD §4
    # =======================================================================
    def create_estimated_payment(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/estimated-payments", payload, headers,
        )

    def list_estimated_payments(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/estimated-payments",
            headers=headers, params=params,
        )

    def cancel_estimated_payment(self, payment_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/estimated-payments/{payment_id}/cancel",
            {}, headers,
        )

    # =======================================================================
    # Audit Logs — PRD §4 / §2.11
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Virtual Clock — PRD §2.9 / §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
