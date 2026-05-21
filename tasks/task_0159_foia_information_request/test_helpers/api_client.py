"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. All endpoints are mounted under `/foia` (PRD §4 endpoint
table); the liveness probe lives at `/healthz` (no auth).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Requester — PRD §3.1
    # ======================================================================
    def create_requester(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/foia/requesters", payload, headers)

    def get_requester(self, requester_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/foia/requesters/{requester_id}", headers=headers,
        )

    def patch_requester(self, requester_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/foia/requesters/{requester_id}", payload, headers,
        )

    # ======================================================================
    # Request — PRD §3.2 through §3.5, §3.8, §3.9
    # ======================================================================
    def create_request(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/foia/requests", payload, headers)

    def get_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/foia/requests/{request_id}", headers=headers,
        )

    def list_requests(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/foia/requests", headers=headers, params=params,
        )

    def acknowledge_request(self, request_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/requests/{request_id}/acknowledge",
            payload, headers,
        )

    def start_tolling(self, request_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/foia/requests/{request_id}/start-tolling",
            payload, headers,
        )

    def resume_clock(self, request_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/requests/{request_id}/resume-clock",
            payload, headers,
        )

    def start_search(self, request_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/requests/{request_id}/start-search",
            payload, headers,
        )

    def close_search(self, request_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/requests/{request_id}/close-search",
            payload, headers,
        )

    def determine_request(self, request_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/requests/{request_id}/determine",
            payload, headers,
        )

    def issue_glomar(self, request_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/foia/requests/{request_id}/issue-glomar",
            payload, headers,
        )

    def withdraw_request(self, request_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/requests/{request_id}/withdraw",
            payload, headers,
        )

    def resume_search(self, request_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/requests/{request_id}/resume-search",
            payload, headers,
        )

    # ======================================================================
    # ResponsiveRecord — PRD §3.6
    # ======================================================================
    def create_responsive_record(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/foia/responsive-records", payload, headers,
        )

    def get_responsive_record(self, record_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/foia/responsive-records/{record_id}",
            headers=headers,
        )

    def patch_record_disposition(self, record_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/foia/responsive-records/{record_id}/disposition",
            payload, headers,
        )

    # ======================================================================
    # ExemptionClaim — PRD §3.6
    # ======================================================================
    def create_exemption_claim(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/foia/exemption-claims", payload, headers,
        )

    def list_exemption_claims(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/foia/exemption-claims",
            headers=headers, params=params,
        )

    # ======================================================================
    # ThirdPartyNotice — PRD §3.7
    # ======================================================================
    def create_third_party_notice(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/foia/third-party-notices", payload, headers,
        )

    def consent_third_party_notice(self, notice_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/third-party-notices/{notice_id}/consent",
            payload, headers,
        )

    def object_third_party_notice(self, notice_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/foia/third-party-notices/{notice_id}/object",
            payload, headers,
        )

    def override_third_party_notice(self, notice_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/third-party-notices/{notice_id}/override",
            payload, headers,
        )

    def get_third_party_notice(self, notice_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/foia/third-party-notices/{notice_id}",
            headers=headers,
        )

    # ======================================================================
    # Appeal — PRD §3.9
    # ======================================================================
    def create_appeal(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/foia/appeals", payload, headers)

    def accept_appeal_for_review(self, appeal_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/appeals/{appeal_id}/accept-for-review",
            payload, headers,
        )

    def decide_appeal(self, appeal_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/foia/appeals/{appeal_id}/decide",
            payload, headers,
        )

    def dismiss_appeal(self, appeal_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/appeals/{appeal_id}/dismiss",
            payload, headers,
        )

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/foia/appeals/{appeal_id}", headers=headers,
        )

    def list_appeals(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/foia/appeals", headers=headers, params=params,
        )

    # ======================================================================
    # FeeAssessment — PRD §3.3, §3.8
    # ======================================================================
    def create_fee_assessment(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/foia/fee-assessments", payload, headers,
        )

    def estimate_fee_assessment(self, assessment_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/fee-assessments/{assessment_id}/estimate",
            payload, headers,
        )

    def accept_fee_assessment(self, assessment_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/fee-assessments/{assessment_id}/accept",
            payload, headers,
        )

    def waive_fee_assessment(self, assessment_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/foia/fee-assessments/{assessment_id}/waive",
            payload, headers,
        )

    def get_fee_assessment(self, assessment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/foia/fee-assessments/{assessment_id}",
            headers=headers,
        )

    # ======================================================================
    # AuditEntry — PRD §2.6
    # ======================================================================
    def list_audit_entries(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/foia/audit-entries",
            headers=headers, params=params,
        )

    # ======================================================================
    # Test-driving clock / sweep — PRD §2.7
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/foia/_clock/advance", payload, headers,
        )

    def sweep_run(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/foia/_sweep/run", payload, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/foia/_clock", headers=headers)

    # ======================================================================
    # Liveness — PRD §4 (no auth)
    # ======================================================================
    def healthz(self, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", "/healthz", headers=headers or {})


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
