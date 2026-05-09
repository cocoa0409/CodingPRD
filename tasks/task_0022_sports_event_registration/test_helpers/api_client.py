"""API client: one method per endpoint defined in the PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response. Tests pass headers in every call because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every request.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Events
    # =====================================================================
    def create_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/events", headers=headers, params=params)

    def open_event(self, event_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/events/{event_id}/open", payload or {}, headers)

    def close_registration(self, event_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/events/{event_id}/close-registration", payload or {}, headers
        )

    def draw_event(self, event_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/events/{event_id}/draw", payload or {}, headers)

    def start_event(self, event_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/events/{event_id}/start", payload or {}, headers)

    def complete_event(self, event_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/events/{event_id}/complete", payload or {}, headers)

    def cancel_event(self, event_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/events/{event_id}/cancel", payload or {}, headers)

    # =====================================================================
    # Participants
    # =====================================================================
    def register_participant(self, event_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/events/{event_id}/participants", payload, headers)

    def list_participants(self, event_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/events/{event_id}/participants", headers=headers, params=params
        )

    def withdraw_participant(self, participant_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/participants/{participant_id}/withdraw", payload or {}, headers
        )

    # =====================================================================
    # Referees + Assignments
    # =====================================================================
    def create_referee(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/referees", payload, headers)

    def list_referees(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/referees", headers=headers, params=params)

    def assign_referee(self, match_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/matches/{match_id}/referee-assignments", payload, headers
        )

    def activate_assignment(self, assignment_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/referee-assignments/{assignment_id}/activate",
            payload or {},
            headers,
        )

    def revoke_assignment(self, assignment_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/referee-assignments/{assignment_id}/revoke",
            payload or {},
            headers,
        )

    # =====================================================================
    # Matches + Results + Disputes
    # =====================================================================
    def list_matches(self, event_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/events/{event_id}/matches", headers=headers, params=params
        )

    def submit_result(self, match_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"/matches/{match_id}/results", payload, headers)

    def file_dispute(self, match_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/matches/{match_id}/disputes", payload, headers)

    def resolve_dispute(self, dispute_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", payload, headers
        )

    # =====================================================================
    # Doping
    # =====================================================================
    def open_sample(self, event_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/events/{event_id}/doping-samples", payload, headers
        )

    def append_custody(self, sample_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/doping-samples/{sample_id}/custody", payload, headers
        )

    def submit_lab_result(self, sample_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/doping-samples/{sample_id}/result", payload, headers
        )

    def void_sample(self, sample_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/doping-samples/{sample_id}/void", payload or {}, headers
        )

    # =====================================================================
    # Sanctions + Appeals
    # =====================================================================
    def get_sanction(self, sanction_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sanctions/{sanction_id}", headers=headers)

    def file_appeal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appeals", payload, headers)

    def decide_appeal(self, appeal_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # =====================================================================
    # Rankings + Prize Payments
    # =====================================================================
    def list_rankings(self, event_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/events/{event_id}/rankings", headers=headers, params=params
        )

    def list_prize_payments(self, event_id: str, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/events/{event_id}/prize-payments", headers=headers, params=params
        )

    # =====================================================================
    # Audit + Sync
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    def list_sync_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/sync-events", headers=headers, params=params)

    # =====================================================================
    # System / clock / sweep
    # =====================================================================
    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"to": to_iso}, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)


api_client = ApiClient()
