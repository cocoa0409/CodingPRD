"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on (almost) every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Operators (PRD §3.1, §4)
    # =======================================================================
    def create_operator(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/operators", payload, headers)

    def list_operators(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/operators", headers=headers,
                             params=params)

    def get_operator(self, operator_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/operators/{operator_id}", headers=headers,
        )

    # =======================================================================
    # Stations (PRD §3.1, §4)
    # =======================================================================
    def create_station(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/stations", payload, headers)

    def list_stations(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/stations", headers=headers,
                             params=params)

    def get_station(self, station_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/stations/{station_id}", headers=headers,
        )

    # =======================================================================
    # Piles (PRD §3.1, §4)
    # =======================================================================
    def create_pile(self, station_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/stations/{station_id}/piles", payload, headers,
        )

    def shelve_pile(self, pile_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/piles/{pile_id}/shelve",
            payload or {}, headers,
        )

    def off_shelve_pile(self, pile_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/piles/{pile_id}/off-shelve",
            payload or {}, headers,
        )

    def decommission_pile(self, pile_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/piles/{pile_id}/decommission",
            payload or {}, headers,
        )

    def patch_pile(self, pile_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/piles/{pile_id}", payload, headers,
        )

    def list_piles(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/piles", headers=headers,
                             params=params)

    def get_pile(self, pile_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/piles/{pile_id}", headers=headers,
        )

    # =======================================================================
    # Members (PRD §3.2, §4)
    # =======================================================================
    def create_member(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/members/{member_id}", headers=headers,
        )

    def wallet_credit(self, member_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/members/{member_id}/wallet-credit",
            payload, headers,
        )

    # =======================================================================
    # Pricing versions / promo activities (PRD §3.2, §4)
    # =======================================================================
    def create_pricing_version(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/pricing-versions", payload, headers,
        )

    def list_pricing_versions(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pricing-versions", headers=headers, params=params,
        )

    def create_promo_activity(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/promo-activities", payload, headers,
        )

    def list_promo_activities(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/promo-activities", headers=headers, params=params,
        )

    # =======================================================================
    # Reservations / queue (PRD §3.3, §4)
    # =======================================================================
    def create_reservation(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/reservations", payload, headers)

    def cancel_reservation(self, reservation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel",
            payload or {}, headers,
        )

    def get_reservation(self, reservation_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/reservations/{reservation_id}", headers=headers,
        )

    def create_queue_entry(self, station_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/stations/{station_id}/queue-entries",
            payload or {}, headers,
        )

    def abandon_queue_entry(self, queue_entry_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/queue-entries/{queue_entry_id}/abandon",
            payload or {}, headers,
        )

    def list_queue_entries(self, station_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/stations/{station_id}/queue-entries",
            headers=headers, params=params,
        )

    # =======================================================================
    # Sessions (PRD §3.4, §4)
    # =======================================================================
    def create_session(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/sessions", payload, headers)

    def start_session(self, session_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/sessions/{session_id}/start",
            payload or {}, headers,
        )

    def create_curve_point(self, session_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/curve-points",
            payload, headers,
        )

    def mark_abnormal(self, session_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/mark-abnormal",
            payload, headers,
        )

    def stop_session(self, session_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/sessions/{session_id}/stop",
            payload or {}, headers,
        )

    def abort_session(self, session_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/sessions/{session_id}/abort",
            payload or {}, headers,
        )

    def get_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sessions/{session_id}", headers=headers,
        )

    def get_session_estimate(self, session_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/sessions/{session_id}/estimate", headers=headers,
        )

    def list_curve_points(self, session_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sessions/{session_id}/curve-points",
            headers=headers, params=params,
        )

    # =======================================================================
    # Faults and repair tickets (PRD §3.5, §4)
    # =======================================================================
    def create_fault_report(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/fault-reports", payload, headers)

    def isolate_fault_report(self, fault_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fault-reports/{fault_id}/isolate",
            payload or {}, headers,
        )

    def get_fault_report(self, fault_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fault-reports/{fault_id}", headers=headers,
        )

    def create_repair_ticket(self, fault_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/fault-reports/{fault_id}/repair-tickets",
            payload, headers,
        )

    def dispatch_repair_ticket(self, ticket_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/dispatch",
            payload or {}, headers,
        )

    def begin_repair_ticket(self, ticket_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/begin",
            payload or {}, headers,
        )

    def complete_repair_ticket(self, ticket_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/complete",
            payload, headers,
        )

    def accept_repair_ticket(self, ticket_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/accept",
            payload or {}, headers,
        )

    def reject_repair_ticket(self, ticket_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/reject",
            payload or {}, headers,
        )

    # =======================================================================
    # Settlement and payouts (PRD §3.6, §3.7, §4)
    # =======================================================================
    def list_session_ledger_entries(self, session_id: str,
                                    headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sessions/{session_id}/ledger-entries",
            headers=headers, params=params,
        )

    def create_payout(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/payouts", payload, headers)

    def issue_payout(self, payout_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/payouts/{payout_id}/issue",
            payload or {}, headers,
        )

    def get_payout(self, payout_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/payouts/{payout_id}", headers=headers,
        )

    def list_payouts(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/payouts", headers=headers,
                             params=params)

    # =======================================================================
    # Audit logs (PRD §2.7, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-logs", headers=headers,
                             params=params)

    # =======================================================================
    # Test-harness endpoints (PRD §2.8, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers,
        )

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
