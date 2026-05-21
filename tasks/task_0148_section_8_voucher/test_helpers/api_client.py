"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.

PRD §1: "The system mounts under the path prefix /housing-voucher.
All paths in §4 are relative to this prefix."
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _p(suffix: str) -> str:
    """Prefix every endpoint with PRD §1's /housing-voucher mount."""
    return f"{API_PREFIX}{suffix}"


class ApiClient(GenericApiClient):

    # =======================================================================
    # Applicants — PRD §3.1, §4
    # =======================================================================
    def create_applicant(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", _p("/applicants"), payload, headers)

    def get_applicant(self, applicant_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", _p(f"/applicants/{applicant_id}"), headers=headers,
        )

    def revoke_applicant(self, applicant_id: str,
                         payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/applicants/{applicant_id}/revoke"),
            payload, headers,
        )

    # =======================================================================
    # Vouchers — PRD §3.2, §4
    # =======================================================================
    def create_voucher(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", _p("/vouchers"), payload, headers)

    def get_voucher(self, voucher_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", _p(f"/vouchers/{voucher_id}"), headers=headers,
        )

    def list_vouchers(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", _p("/vouchers"), headers=headers, params=params,
        )

    # =======================================================================
    # Units — PRD §3.3, §4
    # =======================================================================
    def create_unit(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", _p("/units"), payload, headers)

    def get_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", _p(f"/units/{unit_id}"), headers=headers,
        )

    def list_units(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", _p("/units"), headers=headers, params=params,
        )

    # =======================================================================
    # Payment Standards — PRD §3.3, §4
    # =======================================================================
    def create_payment_standard(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", _p("/payment-standards"), payload, headers,
        )

    def list_payment_standards(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", _p("/payment-standards"),
            headers=headers, params=params,
        )

    # =======================================================================
    # Tenancies (RFTA) — PRD §3.4, §3.7, §3.8, §4
    # =======================================================================
    def create_tenancy(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", _p("/tenancies"), payload, headers)

    def get_tenancy(self, tenancy_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", _p(f"/tenancies/{tenancy_id}"), headers=headers,
        )

    def finalize_tenancy(self, tenancy_id: str,
                         payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/tenancies/{tenancy_id}/finalize"),
            payload, headers,
        )

    def move_out_tenancy(self, tenancy_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/tenancies/{tenancy_id}/move-out"),
            payload, headers,
        )

    # =======================================================================
    # Inspections — PRD §3.5, §4
    # =======================================================================
    def create_inspection(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", _p("/inspections"), payload, headers,
        )

    def complete_inspection(self, inspection_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/inspections/{inspection_id}/complete"),
            payload, headers,
        )

    def get_inspection(self, inspection_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", _p(f"/inspections/{inspection_id}"),
            headers=headers,
        )

    # =======================================================================
    # Rent Reasonableness — PRD §3.6, §4
    # =======================================================================
    def create_rent_reasonableness_record(self,
                                          payload: Dict[str, Any],
                                          headers: Dict[str, str]):
        return self._request(
            "POST", _p("/rent-reasonableness-records"),
            payload, headers,
        )

    # =======================================================================
    # Annual Reviews — PRD §3.9, §4
    # =======================================================================
    def get_annual_review(self, review_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", _p(f"/annual-reviews/{review_id}"), headers=headers,
        )

    def submit_annual_review(self, review_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/annual-reviews/{review_id}/submit"),
            payload, headers,
        )

    def mark_deficient_annual_review(self, review_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST",
            _p(f"/annual-reviews/{review_id}/mark-deficient"),
            payload, headers,
        )

    def resubmit_annual_review(self, review_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/annual-reviews/{review_id}/resubmit"),
            payload, headers,
        )

    def approve_annual_review(self, review_id: str,
                              payload: Optional[Dict[str, Any]],
                              headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/annual-reviews/{review_id}/approve"),
            payload, headers,
        )

    def deny_annual_review(self, review_id: str,
                           payload: Optional[Dict[str, Any]],
                           headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/annual-reviews/{review_id}/deny"),
            payload, headers,
        )

    # =======================================================================
    # Portability — PRD §3.10, §4
    # =======================================================================
    def create_portability_request(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", _p("/portability-requests"), payload, headers,
        )

    def absorb_portability_request(self, request_id: str,
                                   payload: Optional[Dict[str, Any]],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            _p(f"/portability-requests/{request_id}/absorb"),
            payload, headers,
        )

    def bill_portability_request(self, request_id: str,
                                 payload: Optional[Dict[str, Any]],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/portability-requests/{request_id}/bill"),
            payload, headers,
        )

    def deny_portability_request(self, request_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", _p(f"/portability-requests/{request_id}/deny"),
            payload, headers,
        )

    # =======================================================================
    # HAP Payments — PRD §3.11, §4
    # =======================================================================
    def list_hap_payments(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", _p("/hap-payments"), headers=headers, params=params,
        )

    # =======================================================================
    # Clock + sweeps — PRD §2.7, §3.12, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", _p("/_clock/advance"), payload, headers,
        )

    def sweep_expirations(self, payload: Optional[Dict[str, Any]],
                          headers: Dict[str, str]):
        return self._request(
            "POST", _p("/_sweep/expirations"), payload, headers,
        )

    def sweep_abatements(self, payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST", _p("/_sweep/abatements"), payload, headers,
        )

    def sweep_reviews(self, payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST", _p("/_sweep/reviews"), payload, headers,
        )

    def sweep_monthly_hap(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", _p("/_sweep/monthly-hap"), payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
