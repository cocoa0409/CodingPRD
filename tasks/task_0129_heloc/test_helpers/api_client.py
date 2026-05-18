"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Borrowers — PRD §3.1, §4
    # =======================================================================
    def create_borrower(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/borrowers/{borrower_id}", headers=headers,
        )

    def create_bankruptcy_event(
        self,
        borrower_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /borrowers/{id}/bankruptcy-events — PRD §3.6."""
        return self._request(
            "POST",
            f"/borrowers/{borrower_id}/bankruptcy-events",
            payload if payload is not None else {},
            headers,
        )

    # =======================================================================
    # Properties — PRD §3.1, §4
    # =======================================================================
    def create_property(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/properties/{property_id}", headers=headers,
        )

    def create_insurance_event(
        self,
        property_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        """POST /properties/{id}/insurance-events — PRD §3.6."""
        return self._request(
            "POST",
            f"/properties/{property_id}/insurance-events",
            payload,
            headers,
        )

    # =======================================================================
    # Senior liens — PRD §3.1, §4
    # =======================================================================
    def create_senior_lien(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/senior-liens", payload, headers)

    def get_senior_lien(self, senior_lien_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/senior-liens/{senior_lien_id}", headers=headers,
        )

    def create_senior_lien_default_event(
        self,
        senior_lien_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        """POST /senior-liens/{id}/default-events — PRD §3.6."""
        return self._request(
            "POST",
            f"/senior-liens/{senior_lien_id}/default-events",
            payload if payload is not None else {},
            headers,
        )

    # =======================================================================
    # HELOCs — PRD §3.2, §3.3, §3.4, §3.5, §3.9, §4
    # =======================================================================
    def create_heloc(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/helocs", payload, headers)

    def get_heloc(self, heloc_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/helocs/{heloc_id}", headers=headers,
        )

    def list_helocs(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/helocs", headers=headers, params=params,
        )

    def activate_heloc(self, heloc_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/helocs/{heloc_id}/activate", payload, headers,
        )

    def close_heloc(self, heloc_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/helocs/{heloc_id}/close",
            payload if payload is not None else {}, headers,
        )

    # ----- Draws -----
    def create_draw(self, heloc_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/helocs/{heloc_id}/draws", payload, headers,
        )

    def list_draws(self, heloc_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/helocs/{heloc_id}/draws",
            headers=headers, params=params,
        )

    # ----- Payments -----
    def create_payment(self, heloc_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/helocs/{heloc_id}/payments", payload, headers,
        )

    def list_payments(self, heloc_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/helocs/{heloc_id}/payments",
            headers=headers, params=params,
        )

    # ----- Rate resets -----
    def create_rate_reset(self, heloc_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/helocs/{heloc_id}/rate-resets", payload, headers,
        )

    def list_rate_resets(self, heloc_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/helocs/{heloc_id}/rate-resets",
            headers=headers, params=params,
        )

    # ----- Fees / DefaultEvents (read-only) -----
    def list_fees(self, heloc_id: str, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/helocs/{heloc_id}/fees",
            headers=headers, params=params,
        )

    def list_default_events(self, heloc_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/helocs/{heloc_id}/default-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Clock + sweeps — PRD §2.11, §3.7, §3.8, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        """POST /_clock/advance — advance logical clock by `seconds`."""
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def sweep_billing_cycle(self, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        """POST /_sweep/billing-cycle — PRD §3.7."""
        return self._request(
            "POST", "/_sweep/billing-cycle",
            payload if payload is not None else {}, headers,
        )

    def sweep_annual_fees(self, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        """POST /_sweep/annual-fees — PRD §3.8."""
        return self._request(
            "POST", "/_sweep/annual-fees",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
