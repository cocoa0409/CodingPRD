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
    # Catalog & party registration (PRD §3.1)
    # =======================================================================
    def create_design_category(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", "/design-categories", payload, headers)

    def list_design_categories(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/design-categories", headers=headers,
                             params=params)

    def create_client(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/clients", payload, headers)

    def create_designer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/designers", payload, headers)

    def get_designer(self, designer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/designers/{designer_id}",
                             headers=headers)

    def create_reviewer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/reviewer-pool", payload, headers)

    # =======================================================================
    # Projects (PRD §3.2, §3.7, §3.10)
    # =======================================================================
    def create_project(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/projects/{project_id}",
                             headers=headers)

    def list_projects(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/projects", headers=headers,
                             params=params)

    def create_prize_tier(self, project_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/prize-tiers",
            payload, headers,
        )

    def create_review_stage(self, project_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/review-stages",
            payload, headers,
        )

    def submit_project_for_review(self, project_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/submit-for-review",
            payload or {}, headers,
        )

    def approve_project(self, project_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/approve",
            payload or {}, headers,
        )

    def reject_project(self, project_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/reject",
            payload, headers,
        )

    def cancel_project(self, project_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/cancel",
            payload or {}, headers,
        )

    def award_project(self, project_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/award",
            payload, headers,
        )

    def close_project(self, project_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/close",
            payload or {}, headers,
        )

    # =======================================================================
    # Submissions (PRD §3.3)
    # =======================================================================
    def create_submission(self, project_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/submissions",
            payload, headers,
        )

    def list_submissions(self, project_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/projects/{project_id}/submissions",
            headers=headers, params=params,
        )

    def get_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/submissions/{submission_id}", headers=headers,
        )

    def patch_submission(self, submission_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/submissions/{submission_id}", payload, headers,
        )

    def withdraw_submission(self, submission_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "DELETE", f"/submissions/{submission_id}",
            payload or {}, headers,
        )

    # =======================================================================
    # Review stages / assignments (PRD §3.4, §3.5)
    # =======================================================================
    def start_aggregation(self, review_stage_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/review-stages/{review_stage_id}/start-aggregation",
            payload or {}, headers,
        )

    def publish_stage(self, review_stage_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/review-stages/{review_stage_id}/publish",
            payload or {}, headers,
        )

    def create_review_assignment(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/review-assignments", payload, headers,
        )

    def submit_scores(self, review_assignment_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/review-assignments/{review_assignment_id}/submit-scores",
            payload, headers,
        )

    def void_assignment(self, review_assignment_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/review-assignments/{review_assignment_id}/void",
            payload or {}, headers,
        )

    def get_review_assignment(self, review_assignment_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/review-assignments/{review_assignment_id}",
            headers=headers,
        )

    # =======================================================================
    # Copyright transfers (PRD §3.8)
    # =======================================================================
    def create_copyright_transfer(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", "/copyright-transfers",
                             payload, headers)

    def issue_for_signing(self, transfer_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/copyright-transfers/{transfer_id}/issue-for-signing",
            payload or {}, headers,
        )

    def sign_transfer(self, transfer_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/copyright-transfers/{transfer_id}/sign",
            payload, headers,
        )

    def register_transfer(self, transfer_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/copyright-transfers/{transfer_id}/register",
            payload or {}, headers,
        )

    def void_transfer(self, transfer_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/copyright-transfers/{transfer_id}/void",
            payload, headers,
        )

    def get_copyright_transfer(self, transfer_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/copyright-transfers/{transfer_id}", headers=headers,
        )

    # =======================================================================
    # Prize payments (PRD §3.9)
    # =======================================================================
    def dispatch_payment(self, prize_payment_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/prize-payments/{prize_payment_id}/dispatch",
            payload, headers,
        )

    def retry_payment(self, prize_payment_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/prize-payments/{prize_payment_id}/retry",
            payload or {}, headers,
        )

    def get_prize_payment(self, prize_payment_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/prize-payments/{prize_payment_id}", headers=headers,
        )

    def list_prize_payments(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/prize-payments", headers=headers, params=params,
        )

    # =======================================================================
    # Disputes (PRD §3.6)
    # =======================================================================
    def create_dispute(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/disputes", payload, headers)

    def start_mediation(self, dispute_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/start-mediation",
            payload or {}, headers,
        )

    def escalate_dispute(self, dispute_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/escalate",
            payload or {}, headers,
        )

    def request_arbitration(self, dispute_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/request-arbitration",
            payload or {}, headers,
        )

    def resolve_dispute(self, dispute_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve",
            payload, headers,
        )

    def withdraw_dispute(self, dispute_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/withdraw",
            payload or {}, headers,
        )

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/disputes/{dispute_id}", headers=headers,
        )

    def list_disputes(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/disputes",
                             headers=headers, params=params)

    # =======================================================================
    # Audit (PRD §3.10)
    # =======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-events",
                             headers=headers, params=params)

    # =======================================================================
    # Test-harness drivers (PRD §2.11, §3.10)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
