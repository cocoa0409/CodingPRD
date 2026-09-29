"""One client method per endpoint declared by the PRD endpoint table."""

from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX
from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Thin transport wrapper: one method per documented endpoint.

    Every method returns the raw response so tests can assert both the HTTP
    status and the response envelope.
    """

    # ------------------------------------------------------------------
    # Test-support endpoints
    # ------------------------------------------------------------------

    def set_current_utc(self, to_iso8601: str, headers: Optional[Headers] = None):
        """POST /_clock/set_current_utc — advance the logical clock."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def seed_rnd_record(
        self, phone_number: str, reassigned_on: str, headers: Optional[Headers] = None
    ):
        """POST /_rnd/records — seed the reassigned-numbers database."""
        return self._request(
            "POST",
            "/_rnd/records",
            {"phone_number": phone_number, "reassigned_on": reassigned_on},
            headers,
        )

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    def create_contact(self, payload: Payload, headers: Headers):
        """POST /compliance/contacts"""
        return self._request("POST", f"{API_PREFIX}/contacts", payload, headers)

    def get_contact(self, contact_id: str, headers: Headers):
        """GET /compliance/contacts/{id}"""
        return self._request("GET", f"{API_PREFIX}/contacts/{contact_id}", None, headers)

    def number_status_check(self, contact_id: str, payload: Payload, headers: Headers):
        """POST /compliance/contacts/{id}/number-status-check"""
        return self._request(
            "POST",
            f"{API_PREFIX}/contacts/{contact_id}/number-status-check",
            payload,
            headers,
        )

    def list_contact_revocation_requests(
        self, contact_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        """GET /compliance/contacts/{id}/revocation-requests"""
        return self._request(
            "GET",
            f"{API_PREFIX}/contacts/{contact_id}/revocation-requests",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Consent records
    # ------------------------------------------------------------------

    def create_consent_record(self, payload: Payload, headers: Headers):
        """POST /compliance/consent-records"""
        return self._request("POST", f"{API_PREFIX}/consent-records", payload, headers)

    def get_consent_record(self, consent_record_id: str, headers: Headers):
        """GET /compliance/consent-records/{id}"""
        return self._request(
            "GET", f"{API_PREFIX}/consent-records/{consent_record_id}", None, headers
        )

    def list_consent_records(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        """GET /compliance/consent-records"""
        return self._request("GET", f"{API_PREFIX}/consent-records", params, headers)

    def suspend_consent_record(
        self, consent_record_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/consent-records/{id}/suspend"""
        return self._request(
            "POST",
            f"{API_PREFIX}/consent-records/{consent_record_id}/suspend",
            payload,
            headers,
        )

    def reinstate_consent_record(
        self, consent_record_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/consent-records/{id}/reinstate"""
        return self._request(
            "POST",
            f"{API_PREFIX}/consent-records/{consent_record_id}/reinstate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Revocation requests
    # ------------------------------------------------------------------

    def create_revocation_request(self, payload: Payload, headers: Headers):
        """POST /compliance/revocation-requests"""
        return self._request(
            "POST", f"{API_PREFIX}/revocation-requests", payload, headers
        )

    def get_revocation_request(self, revocation_request_id: str, headers: Headers):
        """GET /compliance/revocation-requests/{id}"""
        return self._request(
            "GET",
            f"{API_PREFIX}/revocation-requests/{revocation_request_id}",
            None,
            headers,
        )

    def validate_revocation_request(
        self, revocation_request_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/revocation-requests/{id}/validate"""
        return self._request(
            "POST",
            f"{API_PREFIX}/revocation-requests/{revocation_request_id}/validate",
            payload,
            headers,
        )

    def reject_revocation_request(
        self, revocation_request_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/revocation-requests/{id}/reject"""
        return self._request(
            "POST",
            f"{API_PREFIX}/revocation-requests/{revocation_request_id}/reject",
            payload,
            headers,
        )

    def propagate_revocation_request(
        self, revocation_request_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/revocation-requests/{id}/propagate"""
        return self._request(
            "POST",
            f"{API_PREFIX}/revocation-requests/{revocation_request_id}/propagate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Suppression entries
    # ------------------------------------------------------------------

    def create_suppression_entry(self, payload: Payload, headers: Headers):
        """POST /compliance/suppression-entries"""
        return self._request(
            "POST", f"{API_PREFIX}/suppression-entries", payload, headers
        )

    def list_suppression_entries(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        """GET /compliance/suppression-entries"""
        return self._request(
            "GET", f"{API_PREFIX}/suppression-entries", params, headers
        )

    def remove_suppression_entry(
        self, suppression_entry_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/suppression-entries/{id}/remove"""
        return self._request(
            "POST",
            f"{API_PREFIX}/suppression-entries/{suppression_entry_id}/remove",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Scrub jobs
    # ------------------------------------------------------------------

    def create_scrub_job(self, payload: Payload, headers: Headers):
        """POST /compliance/scrub-jobs"""
        return self._request("POST", f"{API_PREFIX}/scrub-jobs", payload, headers)

    def get_scrub_job(self, scrub_job_id: str, headers: Headers):
        """GET /compliance/scrub-jobs/{id}"""
        return self._request(
            "GET", f"{API_PREFIX}/scrub-jobs/{scrub_job_id}", None, headers
        )

    def execute_scrub_job(self, scrub_job_id: str, headers: Headers):
        """POST /compliance/scrub-jobs/{id}/execute"""
        return self._request(
            "POST", f"{API_PREFIX}/scrub-jobs/{scrub_job_id}/execute", {}, headers
        )

    def list_campaign_scrub_jobs(
        self, campaign_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        """GET /compliance/campaigns/{id}/scrub-jobs"""
        return self._request(
            "GET", f"{API_PREFIX}/campaigns/{campaign_id}/scrub-jobs", params, headers
        )

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    def create_campaign(self, payload: Payload, headers: Headers):
        """POST /compliance/campaigns"""
        return self._request("POST", f"{API_PREFIX}/campaigns", payload, headers)

    def get_campaign(self, campaign_id: str, headers: Headers):
        """GET /compliance/campaigns/{id}"""
        return self._request(
            "GET", f"{API_PREFIX}/campaigns/{campaign_id}", None, headers
        )

    def list_campaigns(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        """GET /compliance/campaigns"""
        return self._request("GET", f"{API_PREFIX}/campaigns", params, headers)

    def launch_campaign(self, campaign_id: str, payload: Payload, headers: Headers):
        """POST /compliance/campaigns/{id}/launch"""
        return self._request(
            "POST", f"{API_PREFIX}/campaigns/{campaign_id}/launch", payload, headers
        )

    def suspend_campaign(self, campaign_id: str, payload: Payload, headers: Headers):
        """POST /compliance/campaigns/{id}/suspend"""
        return self._request(
            "POST", f"{API_PREFIX}/campaigns/{campaign_id}/suspend", payload, headers
        )

    def resume_campaign(self, campaign_id: str, payload: Payload, headers: Headers):
        """POST /compliance/campaigns/{id}/resume"""
        return self._request(
            "POST", f"{API_PREFIX}/campaigns/{campaign_id}/resume", payload, headers
        )

    def close_campaign(self, campaign_id: str, payload: Payload, headers: Headers):
        """POST /compliance/campaigns/{id}/close"""
        return self._request(
            "POST", f"{API_PREFIX}/campaigns/{campaign_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Dialer profiles
    # ------------------------------------------------------------------

    def create_dialer_profile(self, payload: Payload, headers: Headers):
        """POST /compliance/dialer-profiles"""
        return self._request("POST", f"{API_PREFIX}/dialer-profiles", payload, headers)

    def get_dialer_profile(self, dialer_profile_id: str, headers: Headers):
        """GET /compliance/dialer-profiles/{id}"""
        return self._request(
            "GET", f"{API_PREFIX}/dialer-profiles/{dialer_profile_id}", None, headers
        )

    def approve_dialer_profile(
        self, dialer_profile_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/dialer-profiles/{id}/approve"""
        return self._request(
            "POST",
            f"{API_PREFIX}/dialer-profiles/{dialer_profile_id}/approve",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Agent scripts
    # ------------------------------------------------------------------

    def create_agent_script(self, payload: Payload, headers: Headers):
        """POST /compliance/agent-scripts"""
        return self._request("POST", f"{API_PREFIX}/agent-scripts", payload, headers)

    def get_agent_script(self, agent_script_id: str, headers: Headers):
        """GET /compliance/agent-scripts/{id}"""
        return self._request(
            "GET", f"{API_PREFIX}/agent-scripts/{agent_script_id}", None, headers
        )

    def submit_agent_script_review(self, agent_script_id: str, headers: Headers):
        """POST /compliance/agent-scripts/{id}/submit-review"""
        return self._request(
            "POST",
            f"{API_PREFIX}/agent-scripts/{agent_script_id}/submit-review",
            {},
            headers,
        )

    def approve_agent_script(
        self, agent_script_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/agent-scripts/{id}/approve"""
        return self._request(
            "POST",
            f"{API_PREFIX}/agent-scripts/{agent_script_id}/approve",
            payload,
            headers,
        )

    def request_agent_script_changes(
        self, agent_script_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/agent-scripts/{id}/request-changes"""
        return self._request(
            "POST",
            f"{API_PREFIX}/agent-scripts/{agent_script_id}/request-changes",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Calling window policies
    # ------------------------------------------------------------------

    def create_calling_window_policy(self, payload: Payload, headers: Headers):
        """POST /compliance/calling-window-policies"""
        return self._request(
            "POST", f"{API_PREFIX}/calling-window-policies", payload, headers
        )

    def get_calling_window_policy(self, policy_id: str, headers: Headers):
        """GET /compliance/calling-window-policies/{id}"""
        return self._request(
            "GET", f"{API_PREFIX}/calling-window-policies/{policy_id}", None, headers
        )

    def list_calling_window_policies(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        """GET /compliance/calling-window-policies"""
        return self._request(
            "GET", f"{API_PREFIX}/calling-window-policies", params, headers
        )

    def declare_policy_emergency(
        self, policy_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/calling-window-policies/{id}/declare-emergency"""
        return self._request(
            "POST",
            f"{API_PREFIX}/calling-window-policies/{policy_id}/declare-emergency",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Contact attempts
    # ------------------------------------------------------------------

    def create_contact_attempt(self, payload: Payload, headers: Headers):
        """POST /compliance/contact-attempts"""
        return self._request("POST", f"{API_PREFIX}/contact-attempts", payload, headers)

    def get_contact_attempt(self, attempt_id: str, headers: Headers):
        """GET /compliance/contact-attempts/{id}"""
        return self._request(
            "GET", f"{API_PREFIX}/contact-attempts/{attempt_id}", None, headers
        )

    def list_contact_attempts(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        """GET /compliance/contact-attempts"""
        return self._request("GET", f"{API_PREFIX}/contact-attempts", params, headers)

    def record_attempt_outcome(
        self, attempt_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/contact-attempts/{id}/outcome"""
        return self._request(
            "POST",
            f"{API_PREFIX}/contact-attempts/{attempt_id}/outcome",
            payload,
            headers,
        )

    def void_contact_attempt(self, attempt_id: str, payload: Payload, headers: Headers):
        """POST /compliance/contact-attempts/{id}/void"""
        return self._request(
            "POST", f"{API_PREFIX}/contact-attempts/{attempt_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------

    def create_complaint(self, payload: Payload, headers: Headers):
        """POST /compliance/complaints"""
        return self._request("POST", f"{API_PREFIX}/complaints", payload, headers)

    def get_complaint(self, complaint_id: str, headers: Headers):
        """GET /compliance/complaints/{id}"""
        return self._request(
            "GET", f"{API_PREFIX}/complaints/{complaint_id}", None, headers
        )

    def list_complaints(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        """GET /compliance/complaints"""
        return self._request("GET", f"{API_PREFIX}/complaints", params, headers)

    def substantiate_complaint(
        self, complaint_id: str, payload: Payload, headers: Headers
    ):
        """POST /compliance/complaints/{id}/substantiate"""
        return self._request(
            "POST",
            f"{API_PREFIX}/complaints/{complaint_id}/substantiate",
            payload,
            headers,
        )

    def dismiss_complaint(self, complaint_id: str, payload: Payload, headers: Headers):
        """POST /compliance/complaints/{id}/dismiss"""
        return self._request(
            "POST", f"{API_PREFIX}/complaints/{complaint_id}/dismiss", payload, headers
        )


api_client = ApiClient()
