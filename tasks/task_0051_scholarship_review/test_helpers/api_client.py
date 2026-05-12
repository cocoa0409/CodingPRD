"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID / X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Scholarship (PRD §3.1, §3.2, §3.11, §4)
    # =======================================================================
    def create_scholarship(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/scholarships", payload, headers,
        )

    def get_scholarship(self, scholarship_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/scholarships/{scholarship_id}", headers=headers,
        )

    def patch_scholarship(self, scholarship_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/scholarships/{scholarship_id}", payload, headers,
        )

    def transition_scholarship(self, scholarship_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/scholarships/{scholarship_id}/state",
            payload, headers,
        )

    # =======================================================================
    # QuotaAllocation (PRD §3.1, §4)
    # =======================================================================
    def create_quota_allocation(self, scholarship_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/quota-allocations",
            payload, headers,
        )

    def list_quota_allocations(self, scholarship_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/scholarships/{scholarship_id}/quota-allocations",
            headers=headers, params=params,
        )

    # =======================================================================
    # Reviewer pool (PRD §3.5, §4)
    # =======================================================================
    def create_reviewer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", "/reviewers", payload, headers,
        )

    def get_reviewer(self, reviewer_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/reviewers/{reviewer_id}", headers=headers,
        )

    def patch_reviewer(self, reviewer_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/reviewers/{reviewer_id}", payload, headers,
        )

    # =======================================================================
    # Application (PRD §3.3, §3.4, §4)
    # =======================================================================
    def create_application(self, scholarship_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/applications",
            payload, headers,
        )

    def get_application(self, scholarship_id: str,
                        application_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/scholarships/{scholarship_id}/applications/{application_id}",
            headers=headers,
        )

    def patch_application(self, scholarship_id: str,
                          application_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/scholarships/{scholarship_id}/applications/{application_id}",
            payload, headers,
        )

    def submit_application(self, scholarship_id: str,
                           application_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/applications/"
            f"{application_id}/submit",
            payload or {}, headers,
        )

    def withdraw_application(self, scholarship_id: str,
                             application_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/applications/"
            f"{application_id}/withdraw",
            payload or {}, headers,
        )

    def modify_application(self, scholarship_id: str,
                           application_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/applications/"
            f"{application_id}/modify",
            payload or {}, headers,
        )

    def dept_review_application(self, scholarship_id: str,
                                application_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/applications/"
            f"{application_id}/dept-review",
            payload, headers,
        )

    def correct_application(self, scholarship_id: str,
                            application_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/applications/"
            f"{application_id}/correct",
            payload, headers,
        )

    def assign_reviewers(self, scholarship_id: str,
                         application_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/applications/"
            f"{application_id}/assign-reviewers",
            payload, headers,
        )

    # =======================================================================
    # Score (PRD §3.5, §3.6, §4)
    # =======================================================================
    def submit_score(self, scholarship_id: str,
                     application_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/applications/"
            f"{application_id}/scores",
            payload, headers,
        )

    def list_scores(self, scholarship_id: str,
                    application_id: str,
                    headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/scholarships/{scholarship_id}/applications/"
            f"{application_id}/scores",
            headers=headers, params=params,
        )

    # =======================================================================
    # Objection (PRD §3.9, §4)
    # =======================================================================
    def create_objection(self, scholarship_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/objections",
            payload, headers,
        )

    def get_objection(self, scholarship_id: str,
                      objection_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/scholarships/{scholarship_id}/objections/{objection_id}",
            headers=headers,
        )

    def rule_objection(self, scholarship_id: str,
                       objection_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/objections/"
            f"{objection_id}/rule",
            payload, headers,
        )

    # =======================================================================
    # DisbursementPlan (PRD §3.10, §4)
    # =======================================================================
    def create_disbursement_plan(self, scholarship_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/disbursement-plans",
            payload, headers,
        )

    def get_disbursement_plan(self, scholarship_id: str,
                              plan_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/scholarships/{scholarship_id}/disbursement-plans/{plan_id}",
            headers=headers,
        )

    def approve_disbursement_plan(self, scholarship_id: str,
                                  plan_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/disbursement-plans/"
            f"{plan_id}/approve",
            payload, headers,
        )

    def revert_disbursement_plan(self, scholarship_id: str,
                                 plan_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/disbursement-plans/"
            f"{plan_id}/revert",
            payload or {}, headers,
        )

    def execute_disbursement_plan(self, scholarship_id: str,
                                  plan_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/scholarships/{scholarship_id}/disbursement-plans/"
            f"{plan_id}/execute",
            payload or {}, headers,
        )

    def list_disbursement_records(self, scholarship_id: str,
                                  plan_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/scholarships/{scholarship_id}/disbursement-plans/"
            f"{plan_id}/records",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit & external sync (read-only)
    # =======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-events", headers=headers, params=params,
        )

    def list_external_sync_events(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/external-sync-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints (PRD §2.10, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        """POST /_clock/advance with body {to: ISO 8601 datetime}."""
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
