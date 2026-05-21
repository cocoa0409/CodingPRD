"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
the HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Accounts — PRD §3.1, §4
    # =======================================================================
    def create_account(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/accounts/{account_id}", headers=headers,
        )

    def patch_account(self, account_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/accounts/{account_id}", payload, headers,
        )

    def delete_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/accounts/{account_id}", headers=headers,
        )

    def list_accounts(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/accounts", headers=headers, params=params,
        )

    def get_account_summary(self, account_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/accounts/{account_id}/summary", headers=headers,
        )

    # =======================================================================
    # Vehicles — PRD §3.2, §4
    # =======================================================================
    def create_vehicle(self, account_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/vehicles", payload, headers,
        )

    def get_vehicle(self, account_id: str, vehicle_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/accounts/{account_id}/vehicles/{vehicle_id}",
            headers=headers,
        )

    def list_vehicles(self, account_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/vehicles",
            headers=headers, params=params,
        )

    # =======================================================================
    # Transponders — PRD §3.2, §4
    # =======================================================================
    def create_transponder(self, account_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/transponders",
            payload, headers,
        )

    def bind_transponder(self, account_id: str, transponder_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accounts/{account_id}/transponders/{transponder_id}/bind",
            payload, headers,
        )

    def unbind_transponder(self, account_id: str, transponder_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accounts/{account_id}/transponders/{transponder_id}/unbind",
            None, headers,
        )

    def delete_transponder(self, account_id: str, transponder_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/accounts/{account_id}/transponders/{transponder_id}",
            headers=headers,
        )

    # =======================================================================
    # Reloads — PRD §3.4, §4
    # =======================================================================
    def create_reload(self, account_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/accounts/{account_id}/reloads", payload, headers,
        )

    def list_reloads(self, account_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/accounts/{account_id}/reloads",
            headers=headers, params=params,
        )

    # =======================================================================
    # Toll events — PRD §3.3, §4
    # =======================================================================
    def create_toll_event(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/toll-events", payload, headers)

    def get_toll_event(self, toll_event_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/toll-events/{toll_event_id}", headers=headers,
        )

    def list_toll_events(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/toll-events", headers=headers, params=params,
        )

    def void_toll_event(self, toll_event_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/toll-events/{toll_event_id}/void", None, headers,
        )

    # =======================================================================
    # Fines — PRD §3.5, §3.6, §4
    # =======================================================================
    def get_fine(self, fine_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fines/{fine_id}", headers=headers,
        )

    def list_fines(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/fines", headers=headers, params=params,
        )

    def pay_fine(self, fine_id: str, payload: Dict[str, Any],
                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/fines/{fine_id}/pay", payload, headers,
        )

    def dispute_fine(self, fine_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/fines/{fine_id}/dispute", payload, headers,
        )

    def uphold_dispute(self, fine_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fines/{fine_id}/dispute/uphold", None, headers,
        )

    def reject_dispute(self, fine_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fines/{fine_id}/dispute/reject", None, headers,
        )

    # =======================================================================
    # Interop policies — PRD §3.7, §4
    # =======================================================================
    def create_interop_policy(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/interop-policies", payload, headers)

    def list_interop_policies(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/interop-policies", headers=headers, params=params,
        )

    # =======================================================================
    # System / clock — PRD §3.7, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", None, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
