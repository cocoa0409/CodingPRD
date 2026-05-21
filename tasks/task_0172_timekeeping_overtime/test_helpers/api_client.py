"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. Endpoints follow PRD §4 verbatim. All paths are mounted under
the `/timekeeping` prefix.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Employee — PRD §3.1
    # ======================================================================
    def create_employee(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", "/timekeeping/employees", payload, headers,
        )

    def get_employee(self, employee_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/timekeeping/employees/{employee_id}", headers=headers,
        )

    def update_employee(self, employee_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/timekeeping/employees/{employee_id}",
            payload, headers,
        )

    def list_employees(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/timekeeping/employees", headers=headers, params=params,
        )

    # ======================================================================
    # Shift — PRD §3.2
    # ======================================================================
    def create_shift(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", "/timekeeping/shifts", payload, headers,
        )

    def get_shift(self, shift_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/timekeeping/shifts/{shift_id}", headers=headers,
        )

    def list_shifts(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/timekeeping/shifts", headers=headers, params=params,
        )

    def delete_shift(self, shift_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/timekeeping/shifts/{shift_id}", headers=headers,
        )

    def create_punch(self, shift_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/timekeeping/shifts/{shift_id}/punches",
            payload, headers,
        )

    def finalize_shift(self, shift_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/timekeeping/shifts/{shift_id}/finalize",
            payload, headers,
        )

    def create_tip_declaration(self, shift_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/timekeeping/shifts/{shift_id}/tip-declaration",
            payload, headers,
        )

    # ======================================================================
    # TimeEdit — PRD §3.5
    # ======================================================================
    def create_time_edit(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", "/timekeeping/time-edits", payload, headers,
        )

    def get_time_edit(self, time_edit_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/timekeeping/time-edits/{time_edit_id}",
            headers=headers,
        )

    def list_time_edits(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/timekeeping/time-edits",
            headers=headers, params=params,
        )

    def approve_time_edit(self, time_edit_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/timekeeping/time-edits/{time_edit_id}/approve",
            payload, headers,
        )

    def reject_time_edit(self, time_edit_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/timekeeping/time-edits/{time_edit_id}/reject",
            payload, headers,
        )

    def revert_time_edit(self, time_edit_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/timekeeping/time-edits/{time_edit_id}/revert",
            payload, headers,
        )

    # ======================================================================
    # Workweek — PRD §3.6
    # ======================================================================
    def get_workweek(self, workweek_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/timekeeping/workweeks/{workweek_id}",
            headers=headers,
        )

    def list_workweeks(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/timekeeping/workweeks",
            headers=headers, params=params,
        )

    def lock_workweek(self, workweek_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/timekeeping/workweeks/{workweek_id}/lock",
            payload, headers,
        )

    # ======================================================================
    # Audit — PRD §3.8
    # ======================================================================
    def list_audit(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/timekeeping/audit",
            headers=headers, params=params,
        )

    # ======================================================================
    # Test clock — PRD §3.8 ("clock-advance" / "clock-set")
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/timekeeping/_clock/advance", payload, headers,
        )

    def clock_set(self, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", "/timekeeping/_clock/set", payload, headers,
        )


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
