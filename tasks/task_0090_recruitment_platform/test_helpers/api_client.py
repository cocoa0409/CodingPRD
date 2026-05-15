"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.

Path prefix is /recruitment (PRD §4 lists every path under this prefix).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = "/recruitment"


class ApiClient(GenericApiClient):

    # =======================================================================
    # Companies (PRD §3.1)
    # =======================================================================
    def create_company(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/companies", payload, headers)

    def get_company(self, company_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/companies/{company_id}",
                             headers=headers)

    def submit_verification(self, company_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/companies/{company_id}/submit-verification",
            payload or {}, headers,
        )

    def approve_verification(self, company_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/companies/{company_id}/approve-verification",
            payload or {}, headers,
        )

    def reject_verification(self, company_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/companies/{company_id}/reject-verification",
            payload or {}, headers,
        )

    def blacklist_company(self, company_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/companies/{company_id}/blacklist",
            payload, headers,
        )

    def create_hr_binding(self, company_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/companies/{company_id}/hr-bindings",
            payload, headers,
        )

    # =======================================================================
    # Job postings (PRD §3.2)
    # =======================================================================
    def create_job_posting(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/job-postings", payload, headers)

    def get_job_posting(self, posting_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/job-postings/{posting_id}",
                             headers=headers)

    def list_job_postings(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/job-postings",
                             headers=headers, params=params)

    def submit_review_posting(self, posting_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/job-postings/{posting_id}/submit-review",
            payload or {}, headers,
        )

    def approve_posting(self, posting_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/job-postings/{posting_id}/approve",
            payload or {}, headers,
        )

    def reject_posting(self, posting_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/job-postings/{posting_id}/reject",
            payload, headers,
        )

    def revise_posting(self, posting_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/job-postings/{posting_id}/revise",
            payload or {}, headers,
        )

    def take_off_shelf(self, posting_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/job-postings/{posting_id}/take-off-shelf",
            payload or {}, headers,
        )

    # =======================================================================
    # Candidates (PRD §3.3)
    # =======================================================================
    def create_candidate(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/candidates", payload, headers)

    def update_candidate(self, candidate_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("PATCH", f"{PREFIX}/candidates/{candidate_id}",
                             payload, headers)

    def get_candidate(self, candidate_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/candidates/{candidate_id}",
                             headers=headers)

    # =======================================================================
    # Applications (PRD §3.4)
    # =======================================================================
    def create_application(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/applications/{application_id}",
                             headers=headers)

    def mark_application_read(self, application_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/mark-read",
            payload or {}, headers,
        )

    def forward_application(self, application_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/forward",
            payload or {}, headers,
        )

    def reject_application(self, application_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/reject",
            payload or {}, headers,
        )

    def create_interview_round(self, application_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/interview-rounds",
            payload, headers,
        )

    # =======================================================================
    # Interview rounds (PRD §3.5)
    # =======================================================================
    def publish_slots(self, round_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/interview-rounds/{round_id}/publish-slots",
            payload, headers,
        )

    def candidate_confirm_slot(self, round_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/interview-rounds/{round_id}/candidate-confirm",
            payload, headers,
        )

    def submit_round_feedback(self, round_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/interview-rounds/{round_id}/submit-feedback",
            payload, headers,
        )

    def get_interview_round(self, round_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/interview-rounds/{round_id}", headers=headers,
        )

    # =======================================================================
    # Offers (PRD §3.6)
    # =======================================================================
    def create_offer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/offers", payload, headers)

    def submit_offer_approval(self, offer_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/submit-approval",
            payload or {}, headers,
        )

    def approve_offer(self, offer_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/approve",
            payload or {}, headers,
        )

    def reject_offer_approval(self, offer_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/reject-approval",
            payload or {}, headers,
        )

    def accept_offer(self, offer_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/accept",
            payload or {}, headers,
        )

    def decline_offer(self, offer_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/decline",
            payload or {}, headers,
        )

    def rescind_offer(self, offer_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/rescind",
            payload, headers,
        )

    def get_offer(self, offer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/offers/{offer_id}",
                             headers=headers)

    # =======================================================================
    # Onboardings (PRD §3.7)
    # =======================================================================
    def create_onboarding(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/onboardings", payload, headers)

    def start_checks(self, onboarding_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/onboardings/{onboarding_id}/start-checks",
            payload or {}, headers,
        )

    def record_check(self, onboarding_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/onboardings/{onboarding_id}/record-check",
            payload, headers,
        )

    def confirm_onboarded(self, onboarding_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/onboardings/{onboarding_id}/confirm-onboarded",
            payload or {}, headers,
        )

    def record_no_show(self, onboarding_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{PREFIX}/onboardings/{onboarding_id}/record-no-show",
            payload or {}, headers,
        )

    def conversion_decision(self, onboarding_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/onboardings/{onboarding_id}/conversion-decision",
            payload, headers,
        )

    def submit_onboarding_feedback(self, onboarding_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/onboardings/{onboarding_id}/feedback",
            payload, headers,
        )

    def get_onboarding(self, onboarding_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/onboardings/{onboarding_id}",
                             headers=headers)

    # =======================================================================
    # Headhunter contracts & commission records (PRD §3.8)
    # =======================================================================
    def create_headhunter_contract(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/headhunter-contracts",
                             payload, headers)

    def get_commission_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/commission-records/{record_id}", headers=headers,
        )

    def list_commission_records(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/commission-records",
                             headers=headers, params=params)

    # =======================================================================
    # Audit events (PRD §3.9)
    # =======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/audit-events",
                             headers=headers, params=params)

    # =======================================================================
    # Test-driver endpoints (PRD §3.9)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/_clock/advance",
                             payload, headers)

    def run_settlement_sweep(self, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/_settlement-sweep/run",
                             payload or {}, headers)

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/_events/emit",
                             payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
