"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires both
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Borrowers — PRD §3.1 / §4
    # =======================================================================
    def create_borrower(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/borrowers/{borrower_id}", headers=headers,
        )

    # =======================================================================
    # Loan applications — PRD §3.1, §3.2, §3.7, §3.8, §3.10 / §4
    # =======================================================================
    def create_loan_application(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/loan-applications", payload, headers,
        )

    def get_loan_application(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/loan-applications/{app_id}", headers=headers,
        )

    def list_loan_applications(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/loan-applications", headers=headers, params=params,
        )

    def pre_qualify(self, app_id: str,
                    payload: Optional[Dict[str, Any]],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/pre-qualify",
            payload if payload is not None else {}, headers,
        )

    def submit_underwriting(self, app_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}/submit-underwriting",
            payload, headers,
        )

    def underwrite_decision(self, app_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}/underwrite-decision",
            payload, headers,
        )

    def clear_to_close(self, app_id: str,
                       payload: Optional[Dict[str, Any]],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/clear-to-close",
            payload if payload is not None else {}, headers,
        )

    def close_application(self, app_id: str,
                          payload: Optional[Dict[str, Any]],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/close",
            payload if payload is not None else {}, headers,
        )

    def withdraw_application(self, app_id: str,
                             payload: Optional[Dict[str, Any]],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Income verifications — PRD §3.3 / §4
    # =======================================================================
    def create_income_verification(self, app_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}/income-verifications",
            payload, headers,
        )

    def verify_income(self, app_id: str, verification_id: str,
                      payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}"
            f"/income-verifications/{verification_id}/verify",
            payload if payload is not None else {}, headers,
        )

    def reject_income(self, app_id: str, verification_id: str,
                      payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}"
            f"/income-verifications/{verification_id}/reject",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Asset verifications — PRD §3.3 / §4
    # =======================================================================
    def create_asset_verification(self, app_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}/asset-verifications",
            payload, headers,
        )

    def verify_asset(self, app_id: str, verification_id: str,
                     payload: Optional[Dict[str, Any]],
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}"
            f"/asset-verifications/{verification_id}/verify",
            payload if payload is not None else {}, headers,
        )

    def reject_asset(self, app_id: str, verification_id: str,
                     payload: Optional[Dict[str, Any]],
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}"
            f"/asset-verifications/{verification_id}/reject",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Appraisal — PRD §3.4 / §4
    # =======================================================================
    def order_appraisal(self, app_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/appraisal",
            payload, headers,
        )

    def complete_appraisal(self, app_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}/appraisal/complete",
            payload, headers,
        )

    def reject_appraisal(self, app_id: str,
                         payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}/appraisal/reject",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Title search — PRD §3.4 / §4
    # =======================================================================
    def order_title_search(self, app_id: str,
                           payload: Optional[Dict[str, Any]],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/title-search",
            payload if payload is not None else {}, headers,
        )

    def complete_title_search(self, app_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}/title-search/complete",
            payload, headers,
        )

    def resolve_title_search(self, app_id: str,
                             payload: Optional[Dict[str, Any]],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}/title-search/resolve",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Rate lock — PRD §3.5 / §4
    # =======================================================================
    def place_rate_lock(self, app_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/rate-lock",
            payload, headers,
        )

    def extend_rate_lock(self, app_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/rate-lock/extend",
            payload, headers,
        )

    def cancel_rate_lock(self, app_id: str,
                         payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/rate-lock/cancel",
            payload if payload is not None else {}, headers,
        )

    def get_rate_lock(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/loan-applications/{app_id}/rate-lock",
            headers=headers,
        )

    # =======================================================================
    # Disclosures — PRD §3.6 / §4
    # =======================================================================
    def issue_disclosure(self, app_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/disclosures",
            payload, headers,
        )

    def acknowledge_disclosure(self, app_id: str, disclosure_id: str,
                               payload: Optional[Dict[str, Any]],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/loan-applications/{app_id}"
            f"/disclosures/{disclosure_id}/acknowledge",
            payload if payload is not None else {}, headers,
        )

    def list_disclosures(self, app_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/loan-applications/{app_id}/disclosures",
            headers=headers, params=params,
        )

    # =======================================================================
    # UDAAP — PRD §3.9 / §4
    # =======================================================================
    def submit_udaap_review(self, app_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/loan-applications/{app_id}/udaap-reviews",
            payload, headers,
        )

    def list_udaap_reviews(self, app_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/loan-applications/{app_id}/udaap-reviews",
            headers=headers, params=params,
        )

    # =======================================================================
    # System clock — PRD §2.9 / §4
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
