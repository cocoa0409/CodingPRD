"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Applications (PRD §3.1, §4)
    # =======================================================================
    def create_application(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/ethics/applications", payload, headers)

    def get_application(self, application_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/ethics/applications/{application_id}", headers=headers,
        )

    def list_applications(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ethics/applications", headers=headers, params=params,
        )

    def create_submission(self, application_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/ethics/applications/{application_id}/submissions",
            payload, headers,
        )

    def list_submissions(self, application_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/ethics/applications/{application_id}/submissions",
            headers=headers, params=params,
        )

    def submit_application(self, application_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/ethics/applications/{application_id}/submit",
            payload or {}, headers,
        )

    def prescreen_application(self, application_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/ethics/applications/{application_id}/prescreen",
            payload, headers,
        )

    # =======================================================================
    # Members and conflicts (PRD §3.2, §4)
    # =======================================================================
    def create_member(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/ethics/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ethics/members/{member_id}", headers=headers,
        )

    def list_members(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ethics/members", headers=headers, params=params,
        )

    def declare_conflict(self, member_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/ethics/members/{member_id}/conflicts",
            payload, headers,
        )

    def list_member_conflicts(self, member_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/ethics/members/{member_id}/conflicts",
            headers=headers, params=params,
        )

    # =======================================================================
    # Meetings and agenda (PRD §3.3, §4)
    # =======================================================================
    def create_meeting(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/ethics/meetings", payload, headers)

    def get_meeting(self, meeting_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ethics/meetings/{meeting_id}", headers=headers,
        )

    def list_meetings(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ethics/meetings", headers=headers, params=params,
        )

    def create_agenda_item(self, meeting_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/ethics/meetings/{meeting_id}/agenda-items",
            payload, headers,
        )

    def publish_agenda(self, meeting_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/ethics/meetings/{meeting_id}/publish-agenda",
            payload or {}, headers,
        )

    def open_meeting(self, meeting_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/ethics/meetings/{meeting_id}/open",
            payload or {}, headers,
        )

    def close_meeting(self, meeting_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/ethics/meetings/{meeting_id}/close",
            payload or {}, headers,
        )

    def cancel_meeting(self, meeting_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/ethics/meetings/{meeting_id}", headers=headers,
        )

    # =======================================================================
    # Attendance, votes, resolve (PRD §3.4, §3.5, §4)
    # =======================================================================
    def confirm_attendance(self, agenda_item_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/ethics/agenda-items/{agenda_item_id}/attendance",
            payload or {}, headers,
        )

    def cast_vote(self, agenda_item_id: str,
                  payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/ethics/agenda-items/{agenda_item_id}/votes",
            payload, headers,
        )

    def resolve_agenda_item(self, agenda_item_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None,
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/ethics/agenda-items/{agenda_item_id}/resolve",
            payload or {}, headers, params=params,
        )

    def get_agenda_item(self, agenda_item_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/ethics/agenda-items/{agenda_item_id}",
            headers=headers,
        )

    def get_resolution(self, resolution_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/ethics/resolutions/{resolution_id}", headers=headers,
        )

    # =======================================================================
    # Rectifications (PRD §3.6, §4)
    # =======================================================================
    def get_rectification(self, rectification_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/ethics/rectifications/{rectification_id}",
            headers=headers,
        )

    def respond_rectification(self, rectification_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/ethics/rectifications/{rectification_id}/respond",
            payload, headers,
        )

    # =======================================================================
    # Annual reports (PRD §3.7, §4)
    # =======================================================================
    def create_annual_report(self, application_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/ethics/applications/{application_id}/annual-reports",
            payload, headers,
        )

    def list_annual_reports(self, application_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/ethics/applications/{application_id}/annual-reports",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit log (PRD §3.8, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ethics/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints (PRD §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/ethics/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/ethics/_sweep/run", payload or {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
