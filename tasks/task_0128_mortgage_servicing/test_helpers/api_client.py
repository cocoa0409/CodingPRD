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
    # Borrower — PRD §3.1, §4
    # =======================================================================
    def create_borrower(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/borrowers/{borrower_id}", headers=headers,
        )

    def attest_hardship(self, borrower_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/borrowers/{borrower_id}/hardship-attestation",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Loan — PRD §3.1, §4
    # =======================================================================
    def create_loan(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/loans/{loan_id}", headers=headers,
        )

    def list_loans(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/loans", headers=headers, params=params,
        )

    # =======================================================================
    # Payments — PRD §3.2, §4
    # =======================================================================
    def create_payment(self, loan_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/loans/{loan_id}/payments", payload, headers,
        )

    def reverse_payment(self, loan_id: str, payment_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/loans/{loan_id}/payments/{payment_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    def list_payments(self, loan_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/loans/{loan_id}/payments",
            headers=headers, params=params,
        )

    # =======================================================================
    # Escrow analyses — PRD §3.3, §4
    # =======================================================================
    def create_escrow_analysis(self, loan_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/loans/{loan_id}/escrow-analyses",
            payload, headers,
        )

    def finalize_escrow_analysis(self, loan_id: str, analysis_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/loans/{loan_id}/escrow-analyses/{analysis_id}/finalize",
            payload if payload is not None else {}, headers,
        )

    def list_escrow_analyses(self, loan_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/loans/{loan_id}/escrow-analyses",
            headers=headers, params=params,
        )

    # =======================================================================
    # Disbursements — PRD §3.3, §4
    # =======================================================================
    def create_disbursement(self, loan_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/loans/{loan_id}/disbursements",
            payload, headers,
        )

    def retry_disbursement(self, loan_id: str, disbursement_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/loans/{loan_id}/disbursements/{disbursement_id}/retry",
            payload if payload is not None else {}, headers,
        )

    def cancel_disbursement(self, loan_id: str, disbursement_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/loans/{loan_id}/disbursements/{disbursement_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def list_disbursements(self, loan_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/loans/{loan_id}/disbursements",
            headers=headers, params=params,
        )

    # =======================================================================
    # Forbearance plans — PRD §3.4, §4
    # =======================================================================
    def create_forbearance_plan(self, loan_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/loans/{loan_id}/forbearance-plans",
            payload, headers,
        )

    def cancel_forbearance_plan(self, loan_id: str, plan_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/loans/{loan_id}/forbearance-plans/{plan_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def list_forbearance_plans(self, loan_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/loans/{loan_id}/forbearance-plans",
            headers=headers, params=params,
        )

    # =======================================================================
    # PMI removal requests — PRD §3.5, §4
    # =======================================================================
    def create_pmi_removal_request(self, loan_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/loans/{loan_id}/pmi-removal-requests",
            payload, headers,
        )

    def approve_pmi_removal_request(self, loan_id: str,
                                    request_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/loans/{loan_id}/pmi-removal-requests/{request_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def deny_pmi_removal_request(self, loan_id: str, request_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loans/{loan_id}/pmi-removal-requests/{request_id}/deny",
            payload, headers,
        )

    # =======================================================================
    # Foreclosure cases — PRD §3.6, §4
    # =======================================================================
    def create_foreclosure_case(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/foreclosure-cases", payload, headers,
        )

    def get_foreclosure_quote(self, case_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/foreclosure-cases/{case_id}/quote",
            headers=headers,
        )

    def file_foreclosure(self, case_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/file",
            payload if payload is not None else {}, headers,
        )

    def schedule_auction(self, case_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/schedule-auction",
            payload, headers,
        )

    def reinstate_foreclosure(self, case_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/reinstate",
            payload, headers,
        )

    def list_foreclosure_cases(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/foreclosure-cases",
            headers=headers, params=params,
        )

    # =======================================================================
    # Mediation cases — PRD §3.7, §4
    # =======================================================================
    def request_mediation(self, case_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        """POST /foreclosure-cases/{id}/mediation-cases — borrower
        requests pre-foreclosure mediation."""
        return self._request(
            "POST", f"/foreclosure-cases/{case_id}/mediation-cases",
            payload if payload is not None else {}, headers,
        )

    def get_mediation_case(self, mediation_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/mediation-cases/{mediation_id}", headers=headers,
        )

    def open_mediation(self, mediation_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/mediation-cases/{mediation_id}/open",
            payload if payload is not None else {}, headers,
        )

    def extend_mediation_offer(self, mediation_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/mediation-cases/{mediation_id}/extend-offer",
            payload, headers,
        )

    def accept_mediation_offer(self, mediation_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/mediation-cases/{mediation_id}/accept-offer",
            payload if payload is not None else {}, headers,
        )

    def reject_mediation_offer(self, mediation_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/mediation-cases/{mediation_id}/reject-offer",
            payload, headers,
        )

    def complete_mediation(self, mediation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/mediation-cases/{mediation_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def fail_mediation(self, mediation_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/mediation-cases/{mediation_id}/fail",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Clock and sweep — PRD §2.9, §3.8, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_run(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
