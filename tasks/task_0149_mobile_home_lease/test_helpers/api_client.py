"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.

Endpoint paths are taken verbatim from PRD §4's endpoint table.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Parks — PRD §3.1, §4
    # =======================================================================
    def create_park(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/parks", payload, headers)

    def get_park(self, park_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/parks/{park_id}", headers=headers)

    # =======================================================================
    # Lots — PRD §3.1, §4
    # =======================================================================
    def create_lot(self, park_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/lots", payload, headers,
        )

    def list_lots(self, park_id: str, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/parks/{park_id}/lots",
            headers=headers, params=params,
        )

    def get_lot(self, lot_id: str, headers: Dict[str, str]):
        # PRD has no explicit GET /lots/{lot_id} — but PATCH exists.
        # Fall back to the parent-park list endpoint when needed.
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def patch_lot(self, lot_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/lots/{lot_id}", payload, headers,
        )

    # =======================================================================
    # Homes — PRD §3.1, §4
    # =======================================================================
    def create_home(self, park_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/homes", payload, headers,
        )

    def get_home(self, home_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/homes/{home_id}", headers=headers)

    # =======================================================================
    # Residents — PRD §3.1, §4
    # =======================================================================
    def create_resident(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/residents", payload, headers)

    def get_resident(self, resident_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/residents/{resident_id}", headers=headers,
        )

    # =======================================================================
    # Leases — PRD §3.2, §3.3, §3.4, §4
    # =======================================================================
    def create_lease(self, lot_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/lots/{lot_id}/leases", payload, headers,
        )

    def sign_lease(self, lease_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/leases/{lease_id}/sign", payload, headers,
        )

    def pay_lease(self, lease_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/leases/{lease_id}/pay", payload, headers,
        )

    def get_lease(self, lease_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    # =======================================================================
    # Rent-increase notices — PRD §3.5, §4
    # =======================================================================
    def create_rent_increase_notice(self, lease_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/leases/{lease_id}/rent-increase-notices",
            payload, headers,
        )

    def issue_rent_increase_notice(self, notice_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rent-increase-notices/{notice_id}/issue",
            payload, headers,
        )

    def get_rent_increase_notice(self, notice_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/rent-increase-notices/{notice_id}", headers=headers,
        )

    # =======================================================================
    # Eviction cases — PRD §3.6, §4
    # =======================================================================
    def create_eviction_case(self, lease_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/leases/{lease_id}/eviction-cases", payload, headers,
        )

    def cure_eviction_case(self, case_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/eviction-cases/{case_id}/cure", payload, headers,
        )

    def dismiss_eviction_case(self, case_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/eviction-cases/{case_id}/dismiss", payload, headers,
        )

    def get_eviction_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/eviction-cases/{case_id}", headers=headers,
        )

    # =======================================================================
    # Utility bills — PRD §3.3, §4
    # =======================================================================
    def list_utility_bills(self, lot_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/lots/{lot_id}/utility-bills",
            headers=headers, params=params,
        )

    # =======================================================================
    # Home sale transfers — PRD §3.7, §4
    # =======================================================================
    def create_home_sale_transfer(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/home-sale-transfers", payload, headers,
        )

    def approve_home_sale_transfer(self, transfer_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/home-sale-transfers/{transfer_id}/approve",
            payload, headers,
        )

    def reject_home_sale_transfer(self, transfer_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/home-sale-transfers/{transfer_id}/reject",
            payload, headers,
        )

    def close_home_sale_transfer(self, transfer_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/home-sale-transfers/{transfer_id}/close",
            payload, headers,
        )

    def get_home_sale_transfer(self, transfer_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/home-sale-transfers/{transfer_id}", headers=headers,
        )

    # =======================================================================
    # Conversion requests — PRD §3.8, §4
    # =======================================================================
    def create_conversion_request(self, lot_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/lots/{lot_id}/conversion-requests", payload, headers,
        )

    def accept_conversion_request(self, conv_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/conversion-requests/{conv_id}/accept", payload, headers,
        )

    def reject_conversion_request(self, conv_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/conversion-requests/{conv_id}/reject", payload, headers,
        )

    def finalize_conversion_request(self, conv_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/conversion-requests/{conv_id}/finalize",
            payload, headers,
        )

    def get_conversion_request(self, conv_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/conversion-requests/{conv_id}", headers=headers,
        )

    # =======================================================================
    # Test-harness endpoints — PRD §2.11, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def sweep_billing(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/billing", payload, headers,
        )

    def sweep_evictions(self, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/evictions", payload, headers,
        )

    def sweep_rent_effective(self, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/rent-effective", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
