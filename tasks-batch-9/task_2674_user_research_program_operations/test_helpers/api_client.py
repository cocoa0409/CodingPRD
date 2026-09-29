"""Typed API client: one method per endpoint of the API under test.

Every endpoint is mounted at the server root; there is no additional path
prefix.
"""

from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per declared endpoint."""

    # -----------------------------------------------------------------
    # Test-driving endpoints
    # -----------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_retention_sweep(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_ops/retention-sweep", {}, headers)

    # -----------------------------------------------------------------
    # Roadmap decisions
    # -----------------------------------------------------------------
    def create_roadmap_decision(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/roadmap-decisions", payload, headers)

    def lock_roadmap_decision(
        self,
        decision_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/roadmap-decisions/{decision_id}/lock", payload or {}, headers
        )

    def get_roadmap_decision(
        self, decision_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/roadmap-decisions/{decision_id}", None, headers
        )

    def list_decision_research_requests(
        self,
        decision_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/roadmap-decisions/{decision_id}/research-requests",
            None,
            headers,
            params,
        )

    # -----------------------------------------------------------------
    # Research requests
    # -----------------------------------------------------------------
    def create_research_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/research-requests", payload, headers)

    def triage_research_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/research-requests/{request_id}/triage", payload, headers
        )

    def resubmit_research_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/research-requests/{request_id}/resubmit", payload, headers
        )

    def get_research_request(
        self, request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/research-requests/{request_id}", None, headers)

    # -----------------------------------------------------------------
    # Participant pools and participants
    # -----------------------------------------------------------------
    def create_participant_pool(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/participant-pools", payload, headers)

    def enroll_participant(
        self, pool_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/participant-pools/{pool_id}/participants", payload, headers
        )

    def create_incentive_settlement(
        self, pool_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/participant-pools/{pool_id}/incentive-settlements",
            payload,
            headers,
        )

    def get_participant_pool(
        self, pool_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/participant-pools/{pool_id}", None, headers)

    def list_pool_participants(
        self,
        pool_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/participant-pools/{pool_id}/participants",
            None,
            headers,
            params,
        )

    def get_participant(
        self, participant_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/participants/{participant_id}", None, headers)

    # -----------------------------------------------------------------
    # Studies
    # -----------------------------------------------------------------
    def create_study(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/studies", payload, headers)

    def write_study_guide(
        self, study_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PUT", f"/studies/{study_id}/guide", payload, headers)

    def approve_study_guide(
        self,
        study_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/studies/{study_id}/guide/approve", payload or {}, headers
        )

    def field_study(
        self,
        study_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/studies/{study_id}/field", payload or {}, headers
        )

    def close_study_fielding(
        self,
        study_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/studies/{study_id}/close-fielding", payload or {}, headers
        )

    def create_recruitment(
        self, study_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/studies/{study_id}/recruitments", payload, headers
        )

    def auto_invite(
        self, study_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/studies/{study_id}/recruitments/auto-invite", payload, headers
        )

    def get_study(self, study_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/studies/{study_id}", None, headers)

    def list_studies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/studies", None, headers, params)

    def get_study_metrics(
        self, study_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/studies/{study_id}/metrics", None, headers)

    def create_readout(
        self, study_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/studies/{study_id}/readouts", payload, headers)

    # -----------------------------------------------------------------
    # Recruitments
    # -----------------------------------------------------------------
    def screen_recruitment(
        self,
        recruitment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/recruitments/{recruitment_id}/screen", payload or {}, headers
        )

    def schedule_recruitment(
        self, recruitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recruitments/{recruitment_id}/schedule", payload, headers
        )

    def complete_recruitment(
        self, recruitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recruitments/{recruitment_id}/complete", payload, headers
        )

    def record_no_show(
        self, recruitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recruitments/{recruitment_id}/no-show", payload, headers
        )

    def withdraw_recruitment(
        self, recruitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recruitments/{recruitment_id}/withdraw", payload, headers
        )

    def create_artifact(
        self, recruitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recruitments/{recruitment_id}/artifacts", payload, headers
        )

    def get_recruitment(
        self, recruitment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/recruitments/{recruitment_id}", None, headers)

    def list_recruitments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/recruitments", None, headers, params)

    def list_recruitment_artifacts(
        self,
        recruitment_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/recruitments/{recruitment_id}/artifacts", None, headers, params
        )

    # -----------------------------------------------------------------
    # Artifacts
    # -----------------------------------------------------------------
    def get_artifact(
        self, artifact_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/artifacts/{artifact_id}", None, headers)

    def list_artifact_evidence_links(
        self,
        artifact_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/artifacts/{artifact_id}/evidence-links", None, headers, params
        )

    # -----------------------------------------------------------------
    # Consent records
    # -----------------------------------------------------------------
    def create_consent_record(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/consent-records", payload, headers)

    def revoke_consent_record(
        self, consent_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/consent-records/{consent_id}/revoke", payload, headers
        )

    def get_consent_record(
        self, consent_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/consent-records/{consent_id}", None, headers)

    def list_consent_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/consent-records", None, headers, params)

    # -----------------------------------------------------------------
    # Themes
    # -----------------------------------------------------------------
    def create_theme(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/themes", payload, headers)

    def get_theme(self, theme_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/themes/{theme_id}", None, headers)

    def list_themes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/themes", None, headers, params)

    # -----------------------------------------------------------------
    # Findings and evidence links
    # -----------------------------------------------------------------
    def create_finding(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/findings", payload, headers)

    def create_evidence_link(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/findings/{finding_id}/evidence-links", payload, headers
        )

    def delete_evidence_link(
        self, link_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("DELETE", f"/evidence-links/{link_id}", None, headers)

    def lock_finding(
        self,
        finding_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/findings/{finding_id}/lock", payload or {}, headers
        )

    def publish_finding(
        self,
        finding_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/findings/{finding_id}/publish", payload or {}, headers
        )

    def get_finding(
        self, finding_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/findings/{finding_id}", None, headers)

    def list_findings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/findings", None, headers, params)

    def list_finding_evidence_links(
        self,
        finding_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/findings/{finding_id}/evidence-links", None, headers, params
        )

    # -----------------------------------------------------------------
    # Readouts and follow-ups
    # -----------------------------------------------------------------
    def deliver_readout(
        self,
        readout_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/readouts/{readout_id}/deliver", payload or {}, headers
        )

    def respond_to_readout(
        self, readout_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/readouts/{readout_id}/respond", payload, headers
        )

    def create_follow_up(
        self, readout_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/readouts/{readout_id}/follow-ups", payload, headers
        )

    def complete_follow_up(
        self,
        follow_up_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/follow-ups/{follow_up_id}/complete", payload or {}, headers
        )

    def get_readout(
        self, readout_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/readouts/{readout_id}", None, headers)

    def list_readouts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/readouts", None, headers, params)

    def list_readout_follow_ups(
        self,
        readout_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/readouts/{readout_id}/follow-ups", None, headers, params
        )

    # -----------------------------------------------------------------
    # Raw escape hatches for header-level and query-level negative tests
    # -----------------------------------------------------------------
    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
    ) -> requests.Response:
        return self._request("POST", path, payload, headers)

    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", path, None, headers, params)


api_client = ApiClient()
