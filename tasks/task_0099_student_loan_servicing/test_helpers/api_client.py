"""API client: one method per endpoint defined in PRD §4.

Subclasses GenericApiClient — the base _request() method handles HTTP
plumbing. Callers pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ------------------------------------------------------------------
    # Simulation clock (PRD §2.6)
    # ------------------------------------------------------------------
    def advance_clock(self, to: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"to": to}, headers,
        )

    def health(self, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "GET", "/_health", headers=(headers or {}),
        )

    # ------------------------------------------------------------------
    # Borrowers (PRD §3.1)
    # ------------------------------------------------------------------
    def create_borrower(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/borrowers", payload, headers)

    def list_borrowers(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/borrowers", headers=headers, params=params,
        )

    def get_borrower(self, borrower_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/borrowers/{borrower_id}", headers=headers,
        )

    def update_borrower(self, borrower_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/borrowers/{borrower_id}", payload, headers,
        )

    # ------------------------------------------------------------------
    # Loans (PRD §3.2)
    # ------------------------------------------------------------------
    def create_loan(self, borrower_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/borrowers/{borrower_id}/loans", payload, headers,
        )

    def list_loans(self, borrower_id: str,
                   headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/loans",
            headers=headers, params=params,
        )

    def get_loan(self, borrower_id: str, loan_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/loans/{loan_id}",
            headers=headers,
        )

    def separate_loan(self, borrower_id: str, loan_id: str,
                      payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/borrowers/{borrower_id}/loans/{loan_id}/separate",
            payload or {}, headers,
        )

    def record_collections_action(self, borrower_id: str, loan_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/borrowers/{borrower_id}/loans/{loan_id}/collections",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Payments (PRD §3.4)
    # ------------------------------------------------------------------
    def create_payment(self, borrower_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/borrowers/{borrower_id}/payments", payload, headers,
        )

    def list_payments(self, borrower_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/payments",
            headers=headers, params=params,
        )

    def get_payment(self, borrower_id: str, payment_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/payments/{payment_id}",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Repayment plans (PRD §3.7)
    # ------------------------------------------------------------------
    def create_plan(self, borrower_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/borrowers/{borrower_id}/plans", payload, headers,
        )

    def list_plans(self, borrower_id: str,
                   headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/plans",
            headers=headers, params=params,
        )

    def get_plan(self, borrower_id: str, plan_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/plans/{plan_id}",
            headers=headers,
        )

    def activate_plan(self, borrower_id: str, plan_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/borrowers/{borrower_id}/plans/{plan_id}/activate",
            {}, headers,
        )

    def cancel_plan(self, borrower_id: str, plan_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/borrowers/{borrower_id}/plans/{plan_id}",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Hardship requests (PRD §3.5)
    # ------------------------------------------------------------------
    def create_hardship_request(self, borrower_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/borrowers/{borrower_id}/hardship-requests",
            payload, headers,
        )

    def list_hardship_requests(self, borrower_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/hardship-requests",
            headers=headers, params=params,
        )

    def update_hardship_request(self, borrower_id: str, request_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/borrowers/{borrower_id}/hardship-requests/{request_id}",
            payload, headers,
        )

    def cancel_hardship_request(self, borrower_id: str, request_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/borrowers/{borrower_id}/hardship-requests/{request_id}",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Discharge applications (PRD §3.9)
    # ------------------------------------------------------------------
    def create_discharge_application(self, borrower_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/borrowers/{borrower_id}/discharge-applications",
            payload, headers,
        )

    def list_discharge_applications(self, borrower_id: str,
                                    headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/discharge-applications",
            headers=headers, params=params,
        )

    def update_discharge_application(self, borrower_id: str,
                                     application_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/borrowers/{borrower_id}/discharge-applications/{application_id}",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Employment certifications (PRD §3.8)
    # ------------------------------------------------------------------
    def create_employment_certification(self, borrower_id: str,
                                        payload: Dict[str, Any],
                                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/borrowers/{borrower_id}/employment-certifications",
            payload, headers,
        )

    def list_employment_certifications(self, borrower_id: str,
                                       headers: Dict[str, str],
                                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/borrowers/{borrower_id}/employment-certifications",
            headers=headers, params=params,
        )

    def update_employment_certification(self, borrower_id: str,
                                        certification_id: str,
                                        payload: Dict[str, Any],
                                        headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/borrowers/{borrower_id}/employment-certifications/{certification_id}",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Computed reads (PRD §3.10)
    # ------------------------------------------------------------------
    def get_risk_score(self, borrower_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/risk-score",
            headers=headers,
        )

    def get_collections_summary(self, borrower_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/collections-summary",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
