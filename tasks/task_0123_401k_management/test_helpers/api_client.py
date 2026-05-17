"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Plan — PRD §3.1 / §4
    # =======================================================================
    def create_plan(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/plans", headers=headers, params=params,
        )

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/plans/{plan_id}", headers=headers,
        )

    def activate_plan(self, plan_id: str,
                      payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/plans/{plan_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def freeze_plan(self, plan_id: str,
                    payload: Optional[Dict[str, Any]],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/plans/{plan_id}/freeze",
            payload if payload is not None else {}, headers,
        )

    def advance_vesting_epoch(self, plan_id: str,
                              payload: Optional[Dict[str, Any]],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/plans/{plan_id}/advance-vesting-epoch",
            payload if payload is not None else {}, headers,
        )

    def advance_clock(self, plan_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/plans/{plan_id}/_clock/advance",
            payload, headers,
        )

    # =======================================================================
    # Participant — PRD §3.2 / §4
    # =======================================================================
    def create_participant(self, plan_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/plans/{plan_id}/participants",
            payload, headers,
        )

    def list_participants(self, plan_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/plans/{plan_id}/participants",
            headers=headers, params=params,
        )

    def get_participant(self, plan_id: str, participant_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/plans/{plan_id}/participants/{participant_id}",
            headers=headers,
        )

    def activate_participant(self, plan_id: str, participant_id: str,
                             payload: Optional[Dict[str, Any]],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def terminate_participant(self, plan_id: str, participant_id: str,
                              payload: Optional[Dict[str, Any]],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}/terminate",
            payload if payload is not None else {}, headers,
        )

    def update_deferral(self, plan_id: str, participant_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/plans/{plan_id}/participants/{participant_id}/deferral",
            payload, headers,
        )

    # =======================================================================
    # ContributionRecord — PRD §3.3 / §4
    # =======================================================================
    def create_contribution_record(self, plan_id: str,
                                   participant_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            "/contribution-records",
            payload, headers,
        )

    def list_contribution_records(self, plan_id: str,
                                  participant_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/plans/{plan_id}/participants/{participant_id}"
            "/contribution-records",
            headers=headers, params=params,
        )

    # =======================================================================
    # VestingSnapshot — PRD §3.4 / §4
    # =======================================================================
    def create_vesting_snapshot(self, plan_id: str,
                                participant_id: str,
                                payload: Optional[Dict[str, Any]],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            "/vesting-snapshots",
            payload if payload is not None else {}, headers,
        )

    def list_vesting_snapshots(self, plan_id: str,
                               participant_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/plans/{plan_id}/participants/{participant_id}"
            "/vesting-snapshots",
            headers=headers, params=params,
        )

    # =======================================================================
    # Loan — PRD §3.5 / §4
    # =======================================================================
    def create_loan(self, plan_id: str, participant_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}/loans",
            payload, headers,
        )

    def list_loans(self, plan_id: str, participant_id: str,
                   headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/plans/{plan_id}/participants/{participant_id}/loans",
            headers=headers, params=params,
        )

    def get_loan(self, plan_id: str, participant_id: str, loan_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/plans/{plan_id}/participants/{participant_id}"
            f"/loans/{loan_id}",
            headers=headers,
        )

    def approve_loan(self, plan_id: str, participant_id: str,
                     loan_id: str,
                     payload: Optional[Dict[str, Any]],
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            f"/loans/{loan_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def reject_loan(self, plan_id: str, participant_id: str,
                    loan_id: str,
                    payload: Optional[Dict[str, Any]],
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            f"/loans/{loan_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def create_loan_repayment(self, plan_id: str, participant_id: str,
                              loan_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            f"/loans/{loan_id}/repayments",
            payload, headers,
        )

    # =======================================================================
    # HardshipWithdrawal — PRD §3.6 / §4
    # =======================================================================
    def create_hardship_withdrawal(self, plan_id: str,
                                   participant_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            "/hardship-withdrawals",
            payload, headers,
        )

    def list_hardship_withdrawals(self, plan_id: str,
                                  participant_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/plans/{plan_id}/participants/{participant_id}"
            "/hardship-withdrawals",
            headers=headers, params=params,
        )

    def approve_hardship_withdrawal(self, plan_id: str,
                                    participant_id: str,
                                    withdrawal_id: str,
                                    payload: Optional[Dict[str, Any]],
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            f"/hardship-withdrawals/{withdrawal_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def deny_hardship_withdrawal(self, plan_id: str,
                                 participant_id: str,
                                 withdrawal_id: str,
                                 payload: Optional[Dict[str, Any]],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            f"/hardship-withdrawals/{withdrawal_id}/deny",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # RMDSchedule — PRD §3.7 / §4
    # =======================================================================
    def create_rmd_schedule(self, plan_id: str, participant_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            "/rmd-schedules",
            payload, headers,
        )

    def list_rmd_schedules(self, plan_id: str, participant_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/plans/{plan_id}/participants/{participant_id}"
            "/rmd-schedules",
            headers=headers, params=params,
        )

    def fulfill_rmd_schedule(self, plan_id: str, participant_id: str,
                             schedule_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plans/{plan_id}/participants/{participant_id}"
            f"/rmd-schedules/{schedule_id}/fulfill",
            payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
