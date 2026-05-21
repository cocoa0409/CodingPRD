"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. Endpoints mirror PRD §4 verbatim. No path prefix is applied —
PRD §4 paths begin at `/employees`, `/cycles`, `/audit-events`, and
`/_clock/advance`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Employees — PRD §3.1, §4
    # ======================================================================
    def create_employee(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/employees", payload, headers)

    def list_employees(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/employees",
                             headers=headers, params=params)

    def get_employee(self, employee_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/employees/{employee_id}",
                             headers=headers)

    def update_employee(self, employee_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("PATCH", f"/employees/{employee_id}",
                             payload, headers)

    def terminate_employee(self, employee_id: str,
                           headers: Dict[str, str]):
        return self._request("POST",
                             f"/employees/{employee_id}/terminate",
                             None, headers)

    # ======================================================================
    # Cycles — PRD §3.2, §4
    # ======================================================================
    def create_cycle(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/cycles", payload, headers)

    def list_cycles(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/cycles",
                             headers=headers, params=params)

    def get_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def update_cycle(self, cycle_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("PATCH", f"/cycles/{cycle_id}",
                             payload, headers)

    def lock_reviews(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("POST",
                             f"/cycles/{cycle_id}/lock-reviews",
                             None, headers)

    def close_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/cycles/{cycle_id}/close",
                             None, headers)

    # ======================================================================
    # ReviewCases — PRD §3.3, §4
    # ======================================================================
    def create_review_case(self, cycle_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"/cycles/{cycle_id}/review-cases",
                             payload, headers)

    def list_review_cases(self, cycle_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/cycles/{cycle_id}/review-cases",
                             headers=headers, params=params)

    def get_review_case(self, cycle_id: str, review_case_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}",
            headers=headers,
        )

    def update_review_case(self, cycle_id: str, review_case_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}",
            payload, headers,
        )

    def submit_review_case(self, cycle_id: str, review_case_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/submit",
            None, headers,
        )

    def return_review_case(self, cycle_id: str, review_case_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/return",
            None, headers,
        )

    def reopen_review_case(self, cycle_id: str, review_case_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/reopen",
            None, headers,
        )

    # ======================================================================
    # Goals — PRD §3.3, §4
    # ======================================================================
    def create_goal(self, cycle_id: str, review_case_id: str,
                    payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/goals",
            payload, headers,
        )

    def update_goal(self, cycle_id: str, review_case_id: str,
                    goal_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/goals/{goal_id}",
            payload, headers,
        )

    def delete_goal(self, cycle_id: str, review_case_id: str,
                    goal_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/goals/{goal_id}",
            headers=headers,
        )

    # ======================================================================
    # FeedbackRequests — PRD §3.4, §4
    # ======================================================================
    def create_feedback_request(self, cycle_id: str, review_case_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/feedback-requests",
            payload, headers,
        )

    def submit_feedback_request(self, cycle_id: str, review_case_id: str,
                                feedback_request_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/feedback-requests/{feedback_request_id}/submit",
            payload, headers,
        )

    def decline_feedback_request(self, cycle_id: str, review_case_id: str,
                                 feedback_request_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/review-cases/{review_case_id}/feedback-requests/{feedback_request_id}/decline",
            None, headers,
        )

    # ======================================================================
    # CalibrationSessions — PRD §3.5, §4
    # ======================================================================
    def create_calibration_session(self, cycle_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/calibration-sessions",
            payload, headers,
        )

    def update_calibration_proposals(self, cycle_id: str,
                                     calibration_session_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/cycles/{cycle_id}/calibration-sessions/{calibration_session_id}/proposals",
            payload, headers,
        )

    def start_calibration_session(self, cycle_id: str,
                                  calibration_session_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/calibration-sessions/{calibration_session_id}/start",
            None, headers,
        )

    def commit_calibration_session(self, cycle_id: str,
                                   calibration_session_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/calibration-sessions/{calibration_session_id}/commit",
            None, headers,
        )

    def abandon_calibration_session(self, cycle_id: str,
                                    calibration_session_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/calibration-sessions/{calibration_session_id}/abandon",
            None, headers,
        )

    # ======================================================================
    # PIPCases — PRD §3.6, §4
    # ======================================================================
    def list_pip_cases(self, cycle_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cycles/{cycle_id}/pip-cases",
            headers=headers, params=params,
        )

    def get_pip_case(self, cycle_id: str, pip_case_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/cycles/{cycle_id}/pip-cases/{pip_case_id}",
            headers=headers,
        )

    def pass_pip_case(self, cycle_id: str, pip_case_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/pip-cases/{pip_case_id}/pass",
            None, headers,
        )

    def fail_pip_case(self, cycle_id: str, pip_case_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/pip-cases/{pip_case_id}/fail",
            None, headers,
        )

    def withdraw_pip_case(self, cycle_id: str, pip_case_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/pip-cases/{pip_case_id}/withdraw",
            None, headers,
        )

    # ======================================================================
    # CompPlans — PRD §3.7, §4
    # ======================================================================
    def create_comp_plan(self, cycle_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/cycles/{cycle_id}/comp-plans",
            payload, headers,
        )

    def list_comp_plans(self, cycle_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cycles/{cycle_id}/comp-plans",
            headers=headers, params=params,
        )

    def get_comp_plan(self, cycle_id: str, comp_plan_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/cycles/{cycle_id}/comp-plans/{comp_plan_id}",
            headers=headers,
        )

    def update_comp_plan(self, cycle_id: str, comp_plan_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/cycles/{cycle_id}/comp-plans/{comp_plan_id}",
            payload, headers,
        )

    def propose_comp_plan(self, cycle_id: str, comp_plan_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/comp-plans/{comp_plan_id}/propose",
            None, headers,
        )

    def approve_comp_plan(self, cycle_id: str, comp_plan_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/comp-plans/{comp_plan_id}/approve",
            None, headers,
        )

    def reject_comp_plan(self, cycle_id: str, comp_plan_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/comp-plans/{comp_plan_id}/reject",
            None, headers,
        )

    def recall_comp_plan(self, cycle_id: str, comp_plan_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cycles/{cycle_id}/comp-plans/{comp_plan_id}/recall",
            None, headers,
        )

    # ======================================================================
    # Audit ledger + clock — PRD §3.8, §2.13, §4
    # ======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-events",
                             headers=headers, params=params)

    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance",
                             payload, headers)


# Module-level singleton for test_helpers consumers
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
