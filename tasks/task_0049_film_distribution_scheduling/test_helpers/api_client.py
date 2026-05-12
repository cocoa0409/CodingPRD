"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID / X-User-Role on every call.

The PRD declares no explicit URL prefix in §4; paths are mounted under
the service root (POST /distributors, POST /cinemas, etc.).
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ===================================================================
    # Distributor (PRD §3.1, §4)
    # ===================================================================
    def create_distributor(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/distributors/{distributor_id}", headers=headers,
        )

    # ===================================================================
    # Film (PRD §3.1, §3.2, §4)
    # ===================================================================
    def create_film(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/films", payload, headers)

    def get_film(self, film_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/films/{film_id}", headers=headers)

    def release_film(self, film_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/films/{film_id}/release", payload, headers,
        )

    def shelve_film(self, film_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/films/{film_id}/shelve", payload, headers,
        )

    def delist_film(self, film_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/films/{film_id}/delist", payload, headers,
        )

    # ===================================================================
    # Cinema (PRD §3.3, §4)
    # ===================================================================
    def create_cinema(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/cinemas", payload, headers)

    def get_cinema(self, cinema_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cinemas/{cinema_id}", headers=headers,
        )

    # ===================================================================
    # Screen (PRD §3.3, §4)
    # ===================================================================
    def create_screen(self, cinema_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/cinemas/{cinema_id}/screens", payload, headers,
        )

    def get_screen(self, screen_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/screens/{screen_id}", headers=headers,
        )

    # ===================================================================
    # Showtime (PRD §3.4, §3.6, §3.7, §4)
    # ===================================================================
    def create_showtime(self, screen_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/screens/{screen_id}/showtimes", payload, headers,
        )

    def get_showtime(self, showtime_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/showtimes/{showtime_id}", headers=headers,
        )

    def list_showtimes(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/showtimes", headers=headers, params=params,
        )

    def cancel_showtime(self, showtime_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/cancel", payload, headers,
        )

    # ===================================================================
    # Ticket (PRD §3.5, §3.8, §4)
    # ===================================================================
    def purchase_ticket(self, showtime_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/tickets", payload, headers,
        )

    def get_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tickets/{ticket_id}", headers=headers,
        )

    def refund_ticket(self, ticket_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/tickets/{ticket_id}/refund", payload, headers,
        )

    def exchange_ticket(self, ticket_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/tickets/{ticket_id}/exchange", payload, headers,
        )

    # ===================================================================
    # Settlement (PRD §3.9, §4)
    # ===================================================================
    def create_settlement(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/settlements", payload, headers)

    def post_settlement(self, settlement_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/settlements/{settlement_id}/post",
            payload, headers,
        )

    def get_settlement(self, settlement_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/settlements/{settlement_id}", headers=headers,
        )

    def list_settlements(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/settlements", headers=headers, params=params,
        )

    # ===================================================================
    # Reports (PRD §3.10, §4)
    # ===================================================================
    def list_anomaly_alerts(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/anomaly-alerts", headers=headers, params=params,
        )

    def list_schedule_adjustments(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/schedule-adjustments",
            headers=headers, params=params,
        )

    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    # ===================================================================
    # Test harness (PRD §2.10, §3.10, §4)
    # ===================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)

    def emit_external_event(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/_events/external", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
