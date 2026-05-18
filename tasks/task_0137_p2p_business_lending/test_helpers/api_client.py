"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. All paths are rooted under /platforms per PRD §4 ("Every
endpoint is rooted under /platforms").

Headers are passed explicitly because PRD §2.1 requires X-User-ID and
X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Platform — PRD §3.1, §4
    # =======================================================================
    def create_platform(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/platforms", payload, headers)

    def get_platform(self, platform_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/platforms/{platform_id}", headers=headers,
        )

    def advance_clock(self, platform_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/platforms/{platform_id}/advance_clock",
            payload, headers,
        )

    # =======================================================================
    # Borrower — PRD §3.2, §4
    # =======================================================================
    def create_borrower(self, platform_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/platforms/{platform_id}/borrowers",
            payload, headers,
        )

    def get_borrower(self, platform_id: str, borrower_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/borrowers/{borrower_id}",
            headers=headers,
        )

    def attach_plaid_snapshot(self, platform_id: str, borrower_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/borrowers/{borrower_id}/plaid_snapshots",
            payload, headers,
        )

    def approve_borrower(self, platform_id: str, borrower_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/borrowers/{borrower_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def suspend_borrower(self, platform_id: str, borrower_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/borrowers/{borrower_id}/suspend",
            payload if payload is not None else {}, headers,
        )

    def reinstate_borrower(self, platform_id: str, borrower_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/borrowers/{borrower_id}/reinstate",
            payload if payload is not None else {}, headers,
        )

    def ban_borrower(self, platform_id: str, borrower_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/borrowers/{borrower_id}/ban",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Investor — PRD §3.8, §4
    # =======================================================================
    def create_investor(self, platform_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/platforms/{platform_id}/investors",
            payload, headers,
        )

    def get_investor(self, platform_id: str, investor_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/investors/{investor_id}",
            headers=headers,
        )

    def deposit_to_investor(self, platform_id: str, investor_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/investors/{investor_id}/deposits",
            payload, headers,
        )

    def list_investor_investments(self, platform_id: str,
                                  investor_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/investors/{investor_id}/investments",
            headers=headers, params=params,
        )

    # =======================================================================
    # LoanListing — PRD §3.3, §4
    # =======================================================================
    def create_listing(self, platform_id: str, borrower_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/borrowers/{borrower_id}/listings",
            payload, headers,
        )

    def get_listing(self, platform_id: str, listing_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/listings/{listing_id}",
            headers=headers,
        )

    def list_listings(self, platform_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/platforms/{platform_id}/listings",
            headers=headers, params=params,
        )

    def withdraw_listing(self, platform_id: str, listing_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/listings/{listing_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    def originate_listing(self, platform_id: str, listing_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/listings/{listing_id}/originate",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Investment — PRD §3.3, §4
    # =======================================================================
    def create_investment(self, platform_id: str, listing_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/listings/{listing_id}/investments",
            payload, headers,
        )

    def get_investment(self, platform_id: str, investment_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/investments/{investment_id}",
            headers=headers,
        )

    # =======================================================================
    # Loan / Installment — PRD §3.4, §3.5, §4
    # =======================================================================
    def get_loan(self, platform_id: str, loan_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/platforms/{platform_id}/loans/{loan_id}",
            headers=headers,
        )

    def list_installments(self, platform_id: str, loan_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/loans/{loan_id}/installments",
            headers=headers, params=params,
        )

    # =======================================================================
    # Payment — PRD §3.5, §4
    # =======================================================================
    def create_payment(self, platform_id: str, loan_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/loans/{loan_id}/payments",
            payload, headers,
        )

    def get_payment(self, platform_id: str, payment_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/payments/{payment_id}",
            headers=headers,
        )

    # =======================================================================
    # Disclosure — PRD §3.7, §4
    # =======================================================================
    def get_disclosure(self, platform_id: str, disclosure_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/disclosures/{disclosure_id}",
            headers=headers,
        )

    def list_disclosures(self, platform_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/platforms/{platform_id}/disclosures",
            headers=headers, params=params,
        )

    def publish_disclosure(self, platform_id: str, disclosure_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/platforms/{platform_id}/disclosures/{disclosure_id}/publish",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # ComplianceOfficer — PRD §3.9, §4
    # =======================================================================
    def create_compliance_officer(self, platform_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/platforms/{platform_id}/compliance_officers",
            payload, headers,
        )

    def get_compliance_officer(self, platform_id: str,
                               officer_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/platforms/{platform_id}/compliance_officers/{officer_id}",
            headers=headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
