"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clients — PRD §3.1, §4
    # =======================================================================
    def create_client(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/clients/{client_id}", headers=headers,
        )

    # =======================================================================
    # Cases — PRD §3.1, §3.2, §3.9, §4
    # =======================================================================
    def create_case(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/pi-cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pi-cases/{case_id}", headers=headers,
        )

    def list_cases(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pi-cases", headers=headers, params=params,
        )

    def patch_case_costs(self, case_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/pi-cases/{case_id}/costs", payload, headers,
        )

    def toll_case(self, case_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/pi-cases/{case_id}/toll", payload, headers,
        )

    def dismiss_case(self, case_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/pi-cases/{case_id}/dismiss", payload, headers,
        )

    def approve_disbursement(self, case_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/pi-cases/{case_id}/disbursement/approve",
            payload, headers,
        )

    # =======================================================================
    # Contingency Fee — PRD §3.1, §4
    # =======================================================================
    def create_contingency_fee(self, case_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/pi-cases/{case_id}/contingency-fee",
            payload, headers,
        )

    def get_contingency_fee(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pi-cases/{case_id}/contingency-fee",
            headers=headers,
        )

    # =======================================================================
    # Medical Record Requests — PRD §3.3, §4
    # =======================================================================
    def create_medical_record_request(
        self, case_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/pi-cases/{case_id}/medical-record-requests",
            payload, headers,
        )

    def send_medical_record_request(
        self, case_id: str, request_id: str,
        headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/pi-cases/{case_id}/medical-record-requests/{request_id}/send",
            payload or {}, headers,
        )

    def patch_medical_record_request(
        self, case_id: str, request_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PATCH",
            f"/pi-cases/{case_id}/medical-record-requests/{request_id}",
            payload, headers,
        )

    def list_medical_record_requests(
        self, case_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/pi-cases/{case_id}/medical-record-requests",
            headers=headers, params=params,
        )

    def delete_medical_record_request(
        self, case_id: str, request_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "DELETE",
            f"/pi-cases/{case_id}/medical-record-requests/{request_id}",
            headers=headers,
        )

    # =======================================================================
    # Damages — PRD §3.4, §4
    # =======================================================================
    def create_damages(
        self, case_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/pi-cases/{case_id}/damages", payload, headers,
        )

    def patch_damages(
        self, case_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PATCH", f"/pi-cases/{case_id}/damages", payload, headers,
        )

    def get_damages(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pi-cases/{case_id}/damages", headers=headers,
        )

    def recompute_damages(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/pi-cases/{case_id}/damages/recompute",
            {}, headers,
        )

    # =======================================================================
    # Liens — PRD §3.8, §4
    # =======================================================================
    def create_lien(
        self, case_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/pi-cases/{case_id}/liens", payload, headers,
        )

    def negotiate_lien(
        self, case_id: str, lien_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/pi-cases/{case_id}/liens/{lien_id}/negotiate",
            payload or {}, headers,
        )

    def patch_lien(
        self, case_id: str, lien_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PATCH", f"/pi-cases/{case_id}/liens/{lien_id}",
            payload, headers,
        )

    def dispute_lien(
        self, case_id: str, lien_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/pi-cases/{case_id}/liens/{lien_id}/dispute",
            payload or {}, headers,
        )

    def list_liens(
        self, case_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/pi-cases/{case_id}/liens",
            headers=headers, params=params,
        )

    # =======================================================================
    # Demand Letters — PRD §3.5, §4
    # =======================================================================
    def create_demand_letter(
        self, case_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/pi-cases/{case_id}/demand-letters",
            payload, headers,
        )

    def send_demand_letter(
        self, case_id: str, letter_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/pi-cases/{case_id}/demand-letters/{letter_id}/send",
            payload or {}, headers,
        )

    def withdraw_demand_letter(
        self, case_id: str, letter_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/pi-cases/{case_id}/demand-letters/{letter_id}/withdraw",
            payload or {}, headers,
        )

    # =======================================================================
    # Settlement Offers — PRD §3.6, §4
    # =======================================================================
    def create_settlement_offer(
        self, case_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/pi-cases/{case_id}/settlement-offers",
            payload, headers,
        )

    def patch_settlement_offer(
        self, case_id: str, offer_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PATCH",
            f"/pi-cases/{case_id}/settlement-offers/{offer_id}",
            payload, headers,
        )

    def list_settlement_offers(
        self, case_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/pi-cases/{case_id}/settlement-offers",
            headers=headers, params=params,
        )

    # =======================================================================
    # Court Events — PRD §3.7, §4
    # =======================================================================
    def create_court_event(
        self, case_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/pi-cases/{case_id}/court-events",
            payload, headers,
        )

    def patch_court_event(
        self, case_id: str, event_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PATCH",
            f"/pi-cases/{case_id}/court-events/{event_id}",
            payload, headers,
        )

    def delete_court_event(
        self, case_id: str, event_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "DELETE",
            f"/pi-cases/{case_id}/court-events/{event_id}",
            headers=headers,
        )

    def list_court_events(
        self, case_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/pi-cases/{case_id}/court-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints — PRD §3.6, §4 (clock + sweeps)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def get_clock_now(self, headers: Dict[str, str]):
        return self._request(
            "GET", "/_clock/now", headers=headers,
        )

    def sweep_settlement_offers(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/settlement_offers", {}, headers,
        )

    def sweep_sol(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/sol", {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
