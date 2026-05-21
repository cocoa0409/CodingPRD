"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.

Paths are taken verbatim from the PRD §4 endpoint table.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # SystemClock — PRD §2.9, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # =======================================================================
    # Claimants — PRD §3.1, §4
    # =======================================================================
    def create_claimant(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/claimants", payload, headers)

    def get_claimant(self, claimant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/claimants/{claimant_id}", headers=headers,
        )

    # =======================================================================
    # Employers — PRD §3.1, §3.7, §4
    # =======================================================================
    def create_employer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/employers/{employer_id}", headers=headers,
        )

    def list_employer_charges(self, employer_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/employers/{employer_id}/charges",
            headers=headers, params=params,
        )

    def relieve_employer_charge(self, employer_id: str, charge_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/employers/{employer_id}/charges/{charge_id}/relieve",
            payload, headers,
        )

    # =======================================================================
    # WageRecords — PRD §3.1, §4
    # =======================================================================
    def create_wage_record(self, claimant_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/claimants/{claimant_id}/wage-records",
            payload, headers,
        )

    def list_wage_records(self, claimant_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/claimants/{claimant_id}/wage-records",
            headers=headers, params=params,
        )

    # =======================================================================
    # Claims — PRD §3.2, §3.4, §4
    # =======================================================================
    def create_claim(self, claimant_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/claimants/{claimant_id}/claims",
            payload, headers,
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/claims/{claim_id}", headers=headers,
        )

    def submit_claim(self, claim_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/submit",
            payload or {}, headers,
        )

    def adjudicate_claim(self, claim_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/adjudicate",
            payload, headers,
        )

    def apply_extension(self, claim_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/apply-extension",
            payload, headers,
        )

    # =======================================================================
    # Weekly certifications — PRD §3.3, §3.5, §4
    # =======================================================================
    def create_weekly_certification(self, claim_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/weekly-certifications",
            payload, headers,
        )

    def list_weekly_certifications(self, claim_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/claims/{claim_id}/weekly-certifications",
            headers=headers, params=params,
        )

    def get_weekly_certification(self, cert_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/weekly-certifications/{cert_id}",
            headers=headers,
        )

    def audit_weekly_certification(self, cert_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/weekly-certifications/{cert_id}/audit",
            payload, headers,
        )

    # =======================================================================
    # Overpayments — PRD §3.5, §4
    # =======================================================================
    def get_overpayment(self, overpayment_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/overpayments/{overpayment_id}", headers=headers,
        )

    def list_claim_overpayments(self, claim_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/claims/{claim_id}/overpayments",
            headers=headers, params=params,
        )

    def repay_overpayment(self, overpayment_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/overpayments/{overpayment_id}/repay",
            payload, headers,
        )

    def waive_overpayment(self, overpayment_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/overpayments/{overpayment_id}/waive",
            payload, headers,
        )

    def write_off_overpayment(self, overpayment_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/overpayments/{overpayment_id}/write-off",
            payload or {}, headers,
        )

    # =======================================================================
    # Appeals — PRD §3.6, §4
    # =======================================================================
    def create_appeal(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appeals/{appeal_id}", headers=headers,
        )

    def start_hearing(self, appeal_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/start-hearing",
            payload or {}, headers,
        )

    def decide_appeal(self, appeal_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/decide",
            payload, headers,
        )

    def withdraw_appeal(self, appeal_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/withdraw",
            payload or {}, headers,
        )

    # =======================================================================
    # Pandemic extensions — PRD §3.4, §4
    # =======================================================================
    def create_pandemic_extension(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/pandemic-extensions", payload, headers,
        )

    def list_pandemic_extensions(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pandemic-extensions",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
