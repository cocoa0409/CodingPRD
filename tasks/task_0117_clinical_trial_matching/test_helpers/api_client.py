"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the inherited _request() handles HTTP
plumbing. Headers are passed explicitly because PRD §2.1 requires both
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Trial CRUD + lifecycle — PRD §4 / §3.1 / §3.3
    # =======================================================================
    def create_trial(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/trials", payload, headers)

    def list_trials(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/trials", headers=headers, params=params,
        )

    def get_trial(self, trial_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/trials/{trial_id}", headers=headers,
        )

    def patch_trial(self, trial_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/trials/{trial_id}", payload, headers,
        )

    def submit_for_irb(self, trial_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trials/{trial_id}/submit-for-irb",
            payload if payload is not None else {}, headers,
        )

    def create_irb_review(self, trial_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/trials/{trial_id}/irb-reviews", payload, headers,
        )

    def list_irb_reviews(self, trial_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/trials/{trial_id}/irb-reviews",
            headers=headers, params=params,
        )

    def open_enrollment(self, trial_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trials/{trial_id}/open-enrollment",
            payload if payload is not None else {}, headers,
        )

    def close_enrollment(self, trial_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trials/{trial_id}/close-enrollment",
            payload if payload is not None else {}, headers,
        )

    def complete_trial(self, trial_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trials/{trial_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def terminate_trial(self, trial_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/trials/{trial_id}/terminate", payload, headers,
        )

    # =======================================================================
    # Arms — PRD §4 / §3.1
    # =======================================================================
    def create_arm(self, trial_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/trials/{trial_id}/arms", payload, headers,
        )

    def list_arms(self, trial_id: str, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/trials/{trial_id}/arms",
            headers=headers, params=params,
        )

    # =======================================================================
    # Consent versions — PRD §4 / §2.10
    # =======================================================================
    def create_consent_version(self, trial_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/trials/{trial_id}/consent-versions",
            payload, headers,
        )

    def list_consent_versions(self, trial_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/trials/{trial_id}/consent-versions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Participants — PRD §4 / §3.4 / §3.5
    # =======================================================================
    def create_participant(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/participants/{participant_id}", headers=headers,
        )

    def evaluate_participant(self, participant_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/participants/{participant_id}/evaluate",
            payload if payload is not None else {}, headers,
        )

    def get_eligibility_history(self, participant_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/participants/{participant_id}/eligibility-history",
            headers=headers,
        )

    def request_consent(self, participant_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/participants/{participant_id}/request-consent",
            payload if payload is not None else {}, headers,
        )

    def sign_consent(self, participant_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/participants/{participant_id}/sign-consent",
            payload, headers,
        )

    def withdraw_participant(self, participant_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/participants/{participant_id}/withdraw",
            payload, headers,
        )

    def complete_participant(self, participant_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/participants/{participant_id}/complete",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Visits — PRD §4 / §3.6
    # =======================================================================
    def create_visit(self, participant_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/participants/{participant_id}/visits",
            payload, headers,
        )

    def list_visits(self, participant_id: str,
                    headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/participants/{participant_id}/visits",
            headers=headers, params=params,
        )

    def complete_visit(self, visit_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/visits/{visit_id}/complete", payload, headers,
        )

    def mark_visit_missed(self, visit_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/visits/{visit_id}/mark-missed",
            payload if payload is not None else {}, headers,
        )

    def delete_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/visits/{visit_id}", headers=headers,
        )

    # =======================================================================
    # Adverse events — PRD §4 / §3.7
    # =======================================================================
    def create_adverse_event(self, participant_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/participants/{participant_id}/adverse-events",
            payload, headers,
        )

    def list_adverse_events(self, participant_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/adverse-events",
            headers=headers, params=params,
        )

    def start_review_adverse_event(self, participant_id: str,
                                   adverse_event_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None
                                   ):
        return self._request(
            "POST",
            f"/participants/{participant_id}/adverse-events/"
            f"{adverse_event_id}/start-review",
            payload if payload is not None else {}, headers,
        )

    def escalate_adverse_event(self, participant_id: str,
                               adverse_event_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/participants/{participant_id}/adverse-events/"
            f"{adverse_event_id}/escalate",
            payload if payload is not None else {}, headers,
        )

    def resolve_adverse_event(self, participant_id: str,
                              adverse_event_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/participants/{participant_id}/adverse-events/"
            f"{adverse_event_id}/resolve",
            payload, headers,
        )

    # =======================================================================
    # Payments — PRD §4 / §3.8
    # =======================================================================
    def list_payments(self, participant_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/participants/{participant_id}/payments",
            headers=headers, params=params,
        )

    # =======================================================================
    # Clock — PRD §2.12 / §4 (test-only)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
