"""API client — one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Logical clock — PRD §2.11, §3.16
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # =======================================================================
    # Estates — PRD §3.1, §4
    # =======================================================================
    def create_estate(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/estates", payload, headers)

    def get_estate(self, estate_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/estates/{estate_id}", headers=headers,
        )

    def list_estates(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/estates", headers=headers, params=params,
        )

    def update_estate(self, estate_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/estates/{estate_id}", payload, headers,
        )

    def transition_estate(self, estate_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/state", payload, headers,
        )

    # =======================================================================
    # Assets — PRD §3.1, §3.4, §4
    # =======================================================================
    def create_asset(self, estate_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/assets", payload, headers,
        )

    def get_asset(self, estate_id: str, asset_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/estates/{estate_id}/assets/{asset_id}",
            headers=headers,
        )

    def list_assets(self, estate_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/estates/{estate_id}/assets",
            headers=headers, params=params,
        )

    def update_asset(self, estate_id: str, asset_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/estates/{estate_id}/assets/{asset_id}",
            payload, headers,
        )

    def transition_asset(self, estate_id: str, asset_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/assets/{asset_id}/state",
            payload, headers,
        )

    # =======================================================================
    # Beneficiaries — PRD §3.1, §3.9, §4
    # =======================================================================
    def create_beneficiary(self, estate_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/beneficiaries",
            payload, headers,
        )

    def get_beneficiary(self, estate_id: str, beneficiary_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/estates/{estate_id}/beneficiaries/{beneficiary_id}",
            headers=headers,
        )

    def list_beneficiaries(self, estate_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/estates/{estate_id}/beneficiaries",
            headers=headers, params=params,
        )

    def transition_beneficiary(self, estate_id: str,
                               beneficiary_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/estates/{estate_id}/beneficiaries/{beneficiary_id}/state",
            payload, headers,
        )

    # =======================================================================
    # BeneficiaryDesignations — PRD §3.6, §4
    # =======================================================================
    def create_designation(self, estate_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/designations",
            payload, headers,
        )

    def get_designation(self, estate_id: str, designation_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/estates/{estate_id}/designations/{designation_id}",
            headers=headers,
        )

    def list_designations(self, estate_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/estates/{estate_id}/designations",
            headers=headers, params=params,
        )

    def delete_designation(self, estate_id: str, designation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "DELETE",
            f"/estates/{estate_id}/designations/{designation_id}",
            payload, headers,
        )

    # =======================================================================
    # Fiduciaries — PRD §3.1, §3.14, §3.15, §4
    # =======================================================================
    def create_fiduciary(self, estate_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/fiduciaries",
            payload, headers,
        )

    def get_fiduciary(self, estate_id: str, fiduciary_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/estates/{estate_id}/fiduciaries/{fiduciary_id}",
            headers=headers,
        )

    def list_fiduciaries(self, estate_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/estates/{estate_id}/fiduciaries",
            headers=headers, params=params,
        )

    def transition_fiduciary(self, estate_id: str, fiduciary_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/estates/{estate_id}/fiduciaries/{fiduciary_id}/state",
            payload, headers,
        )

    # =======================================================================
    # Guardianships — PRD §3.1, §4
    # =======================================================================
    def create_guardianship(self, estate_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/guardianships",
            payload, headers,
        )

    def get_guardianship(self, estate_id: str, guardianship_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/estates/{estate_id}/guardianships/{guardianship_id}",
            headers=headers,
        )

    def transition_guardianship(self, estate_id: str,
                                guardianship_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/estates/{estate_id}/guardianships/"
            f"{guardianship_id}/state",
            payload, headers,
        )

    # =======================================================================
    # HIPAA — PRD §3.1, §3.13, §4
    # =======================================================================
    def create_hipaa(self, estate_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/hipaa", payload, headers,
        )

    def get_hipaa(self, estate_id: str, hipaa_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/estates/{estate_id}/hipaa/{hipaa_id}",
            headers=headers,
        )

    def transition_hipaa(self, estate_id: str, hipaa_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/hipaa/{hipaa_id}/state",
            payload, headers,
        )

    # =======================================================================
    # PowerOfAttorney — PRD §3.1, §3.2, §4
    # =======================================================================
    def create_poa(self, estate_id: str,
                   payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/poas", payload, headers,
        )

    def get_poa(self, estate_id: str, poa_id: str,
                headers: Dict[str, str]):
        return self._request(
            "GET", f"/estates/{estate_id}/poas/{poa_id}",
            headers=headers,
        )

    def transition_poa(self, estate_id: str, poa_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/poas/{poa_id}/state",
            payload, headers,
        )

    # =======================================================================
    # EndOfLifeDirectives — PRD §3.1, §3.13, §4
    # =======================================================================
    def create_directive(self, estate_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/directives",
            payload, headers,
        )

    def get_directive(self, estate_id: str, directive_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/estates/{estate_id}/directives/{directive_id}",
            headers=headers,
        )

    def transition_directive(self, estate_id: str, directive_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/estates/{estate_id}/directives/{directive_id}/state",
            payload, headers,
        )

    # =======================================================================
    # ProbateFilings — PRD §3.7, §4
    # =======================================================================
    def create_filing(self, estate_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/filings", payload, headers,
        )

    def get_filing(self, estate_id: str, filing_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "GET", f"/estates/{estate_id}/filings/{filing_id}",
            headers=headers,
        )

    def list_filings(self, estate_id: str,
                     headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/estates/{estate_id}/filings",
            headers=headers, params=params,
        )

    def transition_filing(self, estate_id: str, filing_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/estates/{estate_id}/filings/{filing_id}/state",
            payload, headers,
        )

    # =======================================================================
    # Distributions — PRD §3.11, §4
    # =======================================================================
    def get_distribution(self, estate_id: str, distribution_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/estates/{estate_id}/distributions/{distribution_id}",
            headers=headers,
        )

    def list_distributions(self, estate_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/estates/{estate_id}/distributions",
            headers=headers, params=params,
        )

    def transition_distribution(self, estate_id: str,
                                distribution_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/estates/{estate_id}/distributions/"
            f"{distribution_id}/state",
            payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
