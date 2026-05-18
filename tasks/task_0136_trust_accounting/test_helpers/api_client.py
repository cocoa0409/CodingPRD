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
    # Clock — PRD §2.10 / §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        """POST /_clock/advance — advance the server's logical clock."""
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    # =======================================================================
    # Trusts — PRD §4
    # =======================================================================
    def create_trust(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/trusts", payload, headers)

    def get_trust(self, trust_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/trusts/{trust_id}", headers=headers,
        )

    def list_trusts(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/trusts", headers=headers, params=params,
        )

    def patch_trust(self, trust_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/trusts/{trust_id}", payload, headers,
        )

    def activate_trust(self, trust_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/activate", {}, headers,
        )

    def revoke_trust(self, trust_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/revoke", {}, headers,
        )

    def terminate_trust(self, trust_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/terminate", {}, headers,
        )

    # =======================================================================
    # Trustees — PRD §4
    # =======================================================================
    def create_trustee(self, trust_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/trustees", payload, headers,
        )

    def get_trustee(self, trust_id: str, trustee_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/trusts/{trust_id}/trustees/{trustee_id}",
            headers=headers,
        )

    # =======================================================================
    # Beneficiaries — PRD §4
    # =======================================================================
    def create_beneficiary(self, trust_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/beneficiaries",
            payload, headers,
        )

    def get_beneficiary(self, trust_id: str, beneficiary_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/trusts/{trust_id}/beneficiaries/{beneficiary_id}",
            headers=headers,
        )

    def terminate_beneficiary(self, trust_id: str,
                              beneficiary_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/trusts/{trust_id}/beneficiaries/{beneficiary_id}/terminate",
            {}, headers,
        )

    # =======================================================================
    # Assets — PRD §4
    # =======================================================================
    def create_asset(self, trust_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/assets", payload, headers,
        )

    def get_asset(self, trust_id: str, asset_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/trusts/{trust_id}/assets/{asset_id}",
            headers=headers,
        )

    # =======================================================================
    # Transactions — PRD §4
    # =======================================================================
    def create_transaction(self, trust_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/transactions",
            payload, headers,
        )

    def get_transaction(self, trust_id: str, transaction_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/trusts/{trust_id}/transactions/{transaction_id}",
            headers=headers,
        )

    def list_transactions(self, trust_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/trusts/{trust_id}/transactions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Distributions — PRD §4
    # =======================================================================
    def create_distribution(self, trust_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/distributions",
            payload, headers,
        )

    def get_distribution(self, trust_id: str, distribution_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/trusts/{trust_id}/distributions/{distribution_id}",
            headers=headers,
        )

    def approve_distribution(self, trust_id: str,
                             distribution_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/trusts/{trust_id}/distributions/{distribution_id}/approve",
            {}, headers,
        )

    def execute_distribution(self, trust_id: str,
                             distribution_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/trusts/{trust_id}/distributions/{distribution_id}/execute",
            {}, headers,
        )

    def reject_distribution(self, trust_id: str,
                            distribution_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/trusts/{trust_id}/distributions/{distribution_id}/reject",
            {}, headers,
        )

    # =======================================================================
    # Tax years — PRD §4
    # =======================================================================
    def create_tax_year(self, trust_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/trusts/{trust_id}/tax-years", payload, headers,
        )

    def get_tax_year(self, trust_id: str, tax_year_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/trusts/{trust_id}/tax-years/{tax_year_id}",
            headers=headers,
        )

    def begin_close_tax_year(self, trust_id: str, tax_year_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/trusts/{trust_id}/tax-years/{tax_year_id}/begin-close",
            {}, headers,
        )

    def finalize_tax_year(self, trust_id: str, tax_year_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/trusts/{trust_id}/tax-years/{tax_year_id}/finalize",
            {}, headers,
        )

    def amend_tax_year(self, trust_id: str, tax_year_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/trusts/{trust_id}/tax-years/{tax_year_id}/amend",
            {}, headers,
        )

    # =======================================================================
    # K-1 — PRD §4
    # =======================================================================
    def list_k1s(self, trust_id: str, tax_year_id: str,
                 headers: Dict[str, str],
                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/trusts/{trust_id}/tax-years/{tax_year_id}/k1s",
            headers=headers, params=params,
        )

    def get_k1(self, trust_id: str, tax_year_id: str, k1_id: str,
               headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/trusts/{trust_id}/tax-years/{tax_year_id}/k1s/{k1_id}",
            headers=headers,
        )


# Singleton instance reused across tests.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
