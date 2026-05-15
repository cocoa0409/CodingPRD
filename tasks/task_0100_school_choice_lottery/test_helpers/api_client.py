"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call. All paths are mounted under
/enrollment per PRD §4.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Districts (PRD §3.1)
    # =======================================================================
    def create_district(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enrollment/districts", payload, headers)

    def list_districts(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/enrollment/districts", headers=headers, params=params)

    def get_district(self, district_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/enrollment/districts/{district_id}", headers=headers)

    def patch_district(self, district_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/enrollment/districts/{district_id}", payload, headers)

    # =======================================================================
    # Schools (PRD §3.1)
    # =======================================================================
    def create_school(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enrollment/schools", payload, headers)

    def list_schools(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/enrollment/schools", headers=headers, params=params)

    # =======================================================================
    # Programs (PRD §3.1, §3.5)
    # =======================================================================
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enrollment/programs", payload, headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/enrollment/programs", headers=headers, params=params)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/enrollment/programs/{program_id}", headers=headers)

    def patch_program(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/enrollment/programs/{program_id}", payload, headers)

    def draw_lottery(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollment/programs/{program_id}/lottery/draw", {}, headers,
        )

    def list_waitlist_events(
        self, program_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/enrollment/programs/{program_id}/waitlist-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Families (PRD §3.2)
    # =======================================================================
    def create_family(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enrollment/families", payload, headers)

    def get_family(self, family_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/enrollment/families/{family_id}", headers=headers)

    # =======================================================================
    # Students (PRD §3.2)
    # =======================================================================
    def create_student(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enrollment/students", payload, headers)

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/enrollment/students/{student_id}", headers=headers)

    # =======================================================================
    # Applications (PRD §3.4, §3.6)
    # =======================================================================
    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enrollment/applications", payload, headers)

    def list_applications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", "/enrollment/applications", headers=headers, params=params)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollment/applications/{application_id}", headers=headers,
        )

    def submit_application(
        self, application_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/enrollment/applications/{application_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def accept_application(
        self, application_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/enrollment/applications/{application_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def decline_application(
        self, application_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/enrollment/applications/{application_id}/decline",
            payload if payload is not None else {}, headers,
        )

    def withdraw_application(
        self, application_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/enrollment/applications/{application_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Transfer requests (PRD §3.3)
    # =======================================================================
    def create_transfer_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enrollment/transfer-requests", payload, headers)

    def list_transfer_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/enrollment/transfer-requests", headers=headers, params=params,
        )

    def approve_transfer_request(
        self, transfer_request_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/enrollment/transfer-requests/{transfer_request_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def deny_transfer_request(
        self, transfer_request_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/enrollment/transfer-requests/{transfer_request_id}/deny",
            payload if payload is not None else {}, headers,
        )

    def revoke_transfer_request(
        self, transfer_request_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/enrollment/transfer-requests/{transfer_request_id}/revoke",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Lottery runs (PRD §3.8)
    # =======================================================================
    def get_lottery_run(self, lottery_run_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollment/lottery-runs/{lottery_run_id}", headers=headers,
        )

    # =======================================================================
    # Test clock (PRD §2.10)
    # =======================================================================
    def advance_clock(self, target_now: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/enrollment/_clock/advance", {"target_now": target_now}, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/enrollment/_clock", headers=headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
