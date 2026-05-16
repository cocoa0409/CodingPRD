"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Family — PRD §4
    # =======================================================================
    def create_family(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/camp/families", payload, headers)

    def get_family(self, family_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/camp/families/{family_id}", headers=headers,
        )

    def patch_family(self, family_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/camp/families/{family_id}", payload, headers,
        )

    def delete_family(self, family_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/camp/families/{family_id}", headers=headers,
        )

    def get_family_invoice(self, family_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/camp/families/{family_id}/invoice",
            headers=headers, params=params,
        )

    # =======================================================================
    # Guardian — PRD §4
    # =======================================================================
    def create_guardian(self, family_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/families/{family_id}/guardians",
            payload, headers,
        )

    def list_guardians(self, family_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/camp/families/{family_id}/guardians",
            headers=headers, params=params,
        )

    # =======================================================================
    # Child — PRD §4
    # =======================================================================
    def create_child(self, family_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/families/{family_id}/children",
            payload, headers,
        )

    def get_child(self, child_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/camp/children/{child_id}", headers=headers,
        )

    # =======================================================================
    # EmergencyContact — PRD §4
    # =======================================================================
    def create_emergency_contact(self, child_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/children/{child_id}/emergency-contacts",
            payload, headers,
        )

    def delete_emergency_contact(self, contact_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/camp/emergency-contacts/{contact_id}",
            headers=headers,
        )

    # =======================================================================
    # Authorization — PRD §4
    # =======================================================================
    def create_authorization(self, child_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/children/{child_id}/authorizations",
            payload, headers,
        )

    def revoke_authorization(self, authorization_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/authorizations/{authorization_id}/revoke",
            {}, headers,
        )

    # =======================================================================
    # Session — PRD §4
    # =======================================================================
    def create_session(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/camp/sessions", payload, headers)

    def open_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/sessions/{session_id}/open", {}, headers,
        )

    def close_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/sessions/{session_id}/close", {}, headers,
        )

    def cancel_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/sessions/{session_id}/cancel", {}, headers,
        )

    def list_sessions(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/camp/sessions", headers=headers, params=params,
        )

    def get_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/camp/sessions/{session_id}", headers=headers,
        )

    def get_session_roster(self, session_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/camp/sessions/{session_id}/roster",
            headers=headers, params=params,
        )

    # =======================================================================
    # Enrollment — PRD §4
    # =======================================================================
    def create_enrollment(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/camp/enrollments", payload, headers,
        )

    def confirm_enrollment(self, enrollment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/enrollments/{enrollment_id}/confirm",
            {}, headers,
        )

    def cancel_enrollment(self, enrollment_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/enrollments/{enrollment_id}/cancel",
            {}, headers,
        )

    def get_enrollment(self, enrollment_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/camp/enrollments/{enrollment_id}",
            headers=headers,
        )

    def get_fee_quote(self, enrollment_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/camp/enrollments/{enrollment_id}/fee-quote",
            headers=headers,
        )

    # =======================================================================
    # ScholarshipAward — PRD §4
    # =======================================================================
    def create_scholarship(self, family_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/families/{family_id}/scholarships",
            payload, headers,
        )

    def revoke_scholarship(self, scholarship_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/scholarships/{scholarship_id}/revoke",
            {}, headers,
        )

    # =======================================================================
    # SessionDay — PRD §4
    # =======================================================================
    def get_session_day(self, session_day_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/camp/session-days/{session_day_id}",
            headers=headers,
        )

    def set_weather(self, session_day_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/camp/session-days/{session_day_id}/set-weather",
            payload, headers,
        )

    def reroute_preview(self, session_day_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/camp/session-days/{session_day_id}/reroute-preview",
            headers=headers,
        )

    # =======================================================================
    # Clock — PRD §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
