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
    # Option Plans
    # =======================================================================
    def create_option_plan(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/option-plans", payload, headers)

    def list_option_plans(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/option-plans", headers=headers, params=params,
        )

    def get_option_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/option-plans/{plan_id}", headers=headers,
        )

    def activate_option_plan(self, plan_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/option-plans/{plan_id}/activate",
            payload or {}, headers,
        )

    def close_option_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/option-plans/{plan_id}/close", {}, headers,
        )

    def advance_clock(self, plan_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/option-plans/{plan_id}/clock/advance",
            payload, headers,
        )

    # =======================================================================
    # Grant Batches
    # =======================================================================
    def create_grant_batch(self, plan_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/option-plans/{plan_id}/grant-batches",
            payload, headers,
        )

    def list_grant_batches(self, plan_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/option-plans/{plan_id}/grant-batches",
            headers=headers, params=params,
        )

    def open_grant_batch(self, plan_id: str, batch_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/option-plans/{plan_id}/grant-batches/{batch_id}/open",
            {}, headers,
        )

    def lock_grant_batch(self, plan_id: str, batch_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/option-plans/{plan_id}/grant-batches/{batch_id}/lock",
            {}, headers,
        )

    # =======================================================================
    # Grantees
    # =======================================================================
    def create_grantee(self, plan_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/option-plans/{plan_id}/grantees",
            payload, headers,
        )

    def list_grantees(self, plan_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/option-plans/{plan_id}/grantees",
            headers=headers, params=params,
        )

    # =======================================================================
    # Grants
    # =======================================================================
    def create_grant(self, plan_id: str, batch_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/option-plans/{plan_id}/grant-batches/{batch_id}/grants",
            payload, headers,
        )

    def list_grants(self, plan_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/option-plans/{plan_id}/grants",
            headers=headers, params=params,
        )

    def get_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/grants/{grant_id}", headers=headers,
        )

    def board_approve_grant(self, grant_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/grants/{grant_id}/board-approve",
            payload or {}, headers,
        )

    def shareholder_approve_grant(self, grant_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/grants/{grant_id}/shareholder-approve",
            payload or {}, headers,
        )

    def sign_agreement(self, grant_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/grants/{grant_id}/sign-agreement",
            payload or {}, headers,
        )

    def accelerate_vesting(self, grant_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/grants/{grant_id}/accelerate-vesting",
            payload, headers,
        )

    def attest_performance(self, grant_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/grants/{grant_id}/attest-performance",
            {}, headers,
        )

    def recompute_vesting(self, grant_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/grants/{grant_id}/vesting/recompute",
            {}, headers,
        )

    def list_vesting_records(self, grant_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/grants/{grant_id}/vesting-records",
            headers=headers, params=params,
        )

    def archive_vesting_records(self, grant_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/grants/{grant_id}/vesting-records/archive",
            {}, headers,
        )

    # =======================================================================
    # Exercise Windows
    # =======================================================================
    def create_exercise_window(self, plan_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/option-plans/{plan_id}/exercise-windows",
            payload, headers,
        )

    def list_exercise_windows(self, plan_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/option-plans/{plan_id}/exercise-windows",
            headers=headers, params=params,
        )

    def sweep_exercise_windows(self, plan_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/option-plans/{plan_id}/exercise-windows/sweep",
            {}, headers,
        )

    def archive_exercise_window(self, plan_id: str, window_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/option-plans/{plan_id}/exercise-windows/{window_id}/archive",
            {}, headers,
        )

    # =======================================================================
    # Corporate Events & Exercise Price Versions
    # =======================================================================
    def create_corporate_event(self, plan_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/option-plans/{plan_id}/corporate-events",
            payload, headers,
        )

    def list_corporate_events(self, plan_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/option-plans/{plan_id}/corporate-events",
            headers=headers, params=params,
        )

    def list_exercise_price_versions(self, batch_id: str,
                                     headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/grant-batches/{batch_id}/exercise-price-versions",
            headers=headers,
        )

    def disclose_price_version(self, version_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/exercise-price-versions/{version_id}/disclose",
            {}, headers,
        )

    # =======================================================================
    # Exercise Applications
    # =======================================================================
    def create_exercise_application(self, grant_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/grants/{grant_id}/exercise-applications",
            payload, headers,
        )

    def list_exercise_applications(self, plan_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/option-plans/{plan_id}/exercise-applications",
            headers=headers, params=params,
        )

    def verify_exercise_application(self, app_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/exercise-applications/{app_id}/verify",
            {}, headers,
        )

    def pay_exercise_application(self, app_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/exercise-applications/{app_id}/pay",
            payload, headers,
        )

    def settle_exercise_application(self, app_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/exercise-applications/{app_id}/settle",
            payload, headers,
        )

    def reject_exercise_application(self, app_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/exercise-applications/{app_id}/reject",
            payload or {}, headers,
        )

    def cancel_exercise_application(self, app_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/exercise-applications/{app_id}/cancel",
            {}, headers,
        )

    # =======================================================================
    # Tax Events
    # =======================================================================
    def create_tax_event(self, grant_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/grants/{grant_id}/tax-events",
            payload, headers,
        )

    def list_tax_events(self, grant_id: str,
                        headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/grants/{grant_id}/tax-events",
            headers=headers, params=params,
        )

    def issue_tax_document(self, event_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/tax-events/{event_id}/issue-document",
            {}, headers,
        )

    # =======================================================================
    # Departures
    # =======================================================================
    def create_departure_record(self, plan_id: str, grantee_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/option-plans/{plan_id}/grantees/{grantee_id}/departure-records",
            payload, headers,
        )

    def settle_departure_record(self, grantee_id: str, dep_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/grantees/{grantee_id}/departure-records/{dep_id}/settle",
            {}, headers,
        )

    def list_departure_records(self, plan_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/option-plans/{plan_id}/departure-records",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit log
    # =======================================================================
    def list_audit_log(self, plan_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/option-plans/{plan_id}/audit-log",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
