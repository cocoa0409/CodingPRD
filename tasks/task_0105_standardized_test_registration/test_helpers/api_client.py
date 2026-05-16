"""API client: one method per endpoint defined in PRD §4.

Subclasses GenericApiClient — the base _request() method handles HTTP
plumbing. Callers pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ------------------------------------------------------------------
    # Logical clock and sweep (PRD §2.10, §3.7)
    # ------------------------------------------------------------------
    def advance_clock(self, to: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"to": to}, headers)

    def sweep_no_show_and_promote(self, test_event_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/no-show-and-promote",
            {"test_event_id": test_event_id}, headers,
        )

    # ------------------------------------------------------------------
    # TestEvent (PRD §3.1)
    # ------------------------------------------------------------------
    def create_test_event(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/test-events", payload, headers)

    def list_test_events(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/test-events",
                             headers=headers, params=params)

    def get_test_event(self, test_event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/test-events/{test_event_id}", headers=headers,
        )

    def extend_deadline(self, test_event_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/test-events/{test_event_id}/extend-deadline",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # TestCenter (PRD §3.2)
    # ------------------------------------------------------------------
    def create_test_center(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/test-centers", payload, headers)

    def list_test_centers(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/test-centers",
                             headers=headers, params=params)

    def get_test_center(self, test_center_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/test-centers/{test_center_id}", headers=headers,
        )

    # ------------------------------------------------------------------
    # TestCenterCapacity (PRD §3.2)
    # ------------------------------------------------------------------
    def create_test_center_capacity(self, test_event_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/test-events/{test_event_id}/test-center-capacities",
            payload, headers,
        )

    def list_test_center_capacities(self, test_event_id: str,
                                    headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/test-events/{test_event_id}/test-center-capacities",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Candidate (PRD §3.3)
    # ------------------------------------------------------------------
    def create_candidate(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/candidates/{candidate_id}", headers=headers,
        )

    def get_super_score(self, candidate_id: str,
                        headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/candidates/{candidate_id}/super-score",
            headers=headers, params=params,
        )

    def list_clep_credit_awards(self, candidate_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/candidates/{candidate_id}/clep-credit-awards",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Registration (PRD §3.4, §3.8)
    # ------------------------------------------------------------------
    def create_registration(self, test_event_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/test-events/{test_event_id}/registrations",
            payload, headers,
        )

    def get_registration(self, test_event_id: str, registration_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/test-events/{test_event_id}/registrations/{registration_id}",
            headers=headers,
        )

    def list_registrations(self, test_event_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/test-events/{test_event_id}/registrations",
            headers=headers, params=params,
        )

    def self_cancel_registration(self, test_event_id: str,
                                 registration_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        # PRD §2.7: the optional `version` field travels in the request body
        # (not the query string), so this DELETE must carry a JSON body.
        # GenericApiClient._request maps DELETE payloads to query params,
        # so we bypass it and call the underlying session directly.
        url = f"{self.base_url}/test-events/{test_event_id}/registrations/{registration_id}"
        return self.session.request(
            "DELETE", url, json=payload or {}, headers=headers,
        )

    def admin_cancel_registration(self, test_event_id: str,
                                  registration_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/test-events/{test_event_id}/registrations/{registration_id}/admin-cancel",
            payload or {}, headers,
        )

    def check_in_registration(self, test_event_id: str,
                              registration_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/test-events/{test_event_id}/registrations/{registration_id}/check-in",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # IDVerification (PRD §3.5)
    # ------------------------------------------------------------------
    def submit_id_verification(self, test_event_id: str,
                               registration_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/test-events/{test_event_id}/registrations/{registration_id}/id-verification/submit",
            payload, headers,
        )

    def clear_id_verification(self, test_event_id: str,
                              registration_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/test-events/{test_event_id}/registrations/{registration_id}/id-verification/clear",
            payload or {}, headers,
        )

    def reject_id_verification(self, test_event_id: str,
                               registration_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/test-events/{test_event_id}/registrations/{registration_id}/id-verification/reject",
            payload, headers,
        )

    def get_id_verification(self, test_event_id: str,
                            registration_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/test-events/{test_event_id}/registrations/{registration_id}/id-verification",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # AccommodationRequest (PRD §3.6)
    # ------------------------------------------------------------------
    def create_accommodation_request(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/accommodation-requests", payload, headers,
        )

    def start_review_accommodation(self, accommodation_request_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accommodation-requests/{accommodation_request_id}/start-review",
            {}, headers,
        )

    def request_info_accommodation(self, accommodation_request_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accommodation-requests/{accommodation_request_id}/request-info",
            {}, headers,
        )

    def resubmit_accommodation(self, accommodation_request_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/accommodation-requests/{accommodation_request_id}/resubmit",
            payload, headers,
        )

    def approve_accommodation(self, accommodation_request_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accommodation-requests/{accommodation_request_id}/approve",
            {}, headers,
        )

    def deny_accommodation(self, accommodation_request_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/accommodation-requests/{accommodation_request_id}/deny",
            {}, headers,
        )

    def get_accommodation_request(self, accommodation_request_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/accommodation-requests/{accommodation_request_id}",
            headers=headers,
        )

    def list_accommodation_requests(self, headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/accommodation-requests",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # ScoreReport + CLEPCreditAward (PRD §3.9, §3.10)
    # ------------------------------------------------------------------
    def create_score_report(self, test_event_id: str,
                            registration_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/test-events/{test_event_id}/registrations/{registration_id}/score-reports",
            payload, headers,
        )

    def list_score_reports(self, test_event_id: str,
                           registration_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/test-events/{test_event_id}/registrations/{registration_id}/score-reports",
            headers=headers, params=params,
        )

    def post_clep_credit(self, test_event_id: str,
                         registration_id: str,
                         score_report_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/test-events/{test_event_id}/registrations/{registration_id}/score-reports/{score_report_id}/clep-credit",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # RefundTransaction (PRD §3.8)
    # ------------------------------------------------------------------
    def list_refunds(self, test_event_id: str, registration_id: str,
                     headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/test-events/{test_event_id}/registrations/{registration_id}/refunds",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
