"""One client method per endpoint the PRD declares.

Every method returns the raw response so tests can assert status codes and error
envelopes themselves. All paths are mounted under the /cdp prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cdp"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------- system capabilities
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    def run_retention(self, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/retention-runs", payload or {}, headers)

    # ------------------------------------------------------------ source systems
    def create_source_system(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/source-systems", payload, headers)

    def get_source_system(self, source_system_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/source-systems/{source_system_id}", None, headers
        )

    def list_source_systems(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/source-systems", params, headers)

    def reinstate_source_system(
        self,
        source_system_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"{PREFIX}/source-systems/{source_system_id}/reinstate",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------ ingest batches
    def create_ingest_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/ingest-batches", payload, headers)

    def get_ingest_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/ingest-batches/{batch_id}", None, headers
        )

    def list_ingest_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/ingest-batches", params, headers)

    def validate_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/ingest-batches/{batch_id}/validate", payload or {}, headers
        )

    def requeue_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/ingest-batches/{batch_id}/requeue", payload or {}, headers
        )

    def promote_batch(
        self, batch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/ingest-batches/{batch_id}/promote", payload or {}, headers
        )

    # ------------------------------------------------------------------ profiles
    def get_profile(self, profile_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/profiles/{profile_id}", None, headers)

    def list_profiles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/profiles", params, headers)

    def get_consent_state(self, profile_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/profiles/{profile_id}/consent-state", None, headers
        )

    def assign_household(
        self, profile_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/profiles/{profile_id}/household-assignment",
            payload,
            headers,
        )

    # ---------------------------------------------------------------- households
    def get_household(self, household_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/households/{household_id}", None, headers)

    def list_households(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/households", params, headers)

    # --------------------------------------------------------------- match rules
    def create_match_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/match-rules", payload, headers)

    def get_match_rule(self, match_rule_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/match-rules/{match_rule_id}", None, headers
        )

    def list_match_rules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/match-rules", params, headers)

    # ------------------------------------------------------------ identity links
    def create_identity_link(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/identity-links", payload, headers)

    def get_identity_link(self, link_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/identity-links/{link_id}", None, headers)

    def list_identity_links(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/identity-links", params, headers)

    def decide_identity_link(
        self, link_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/identity-links/{link_id}/decision", payload, headers
        )

    # ----------------------------------------------------------- consent records
    def create_consent_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/consent-records", payload, headers)

    def get_consent_record(self, consent_record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/consent-records/{consent_record_id}", None, headers
        )

    def list_consent_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/consent-records", params, headers)

    # -------------------------------------------------------- suppression entries
    def create_suppression_entry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/suppression-entries", payload, headers)

    def get_suppression_entry(self, suppression_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/suppression-entries/{suppression_id}", None, headers
        )

    def list_suppression_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{PREFIX}/suppression-entries", params, headers)

    def release_suppression_entry(
        self,
        suppression_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"{PREFIX}/suppression-entries/{suppression_id}/release",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------ segments
    def create_segment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/segments", payload, headers)

    def get_segment(self, segment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/segments/{segment_id}", None, headers)

    def list_segments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/segments", params, headers)

    def submit_segment_for_review(
        self, segment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/segments/{segment_id}/submit-for-review",
            payload or {},
            headers,
        )

    def decide_segment_governance(
        self, segment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/segments/{segment_id}/governance-decision",
            payload,
            headers,
        )

    def retire_segment(
        self, segment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/segments/{segment_id}/retire", payload or {}, headers
        )

    def get_segment_performance(
        self, segment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/segments/{segment_id}/performance", params, headers
        )

    def get_segment_overlap(
        self, segment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/segments/{segment_id}/overlap", params, headers
        )

    # -------------------------------------------------------------- destinations
    def create_destination(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/destinations", payload, headers)

    def get_destination(self, destination_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/destinations/{destination_id}", None, headers
        )

    def list_destinations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/destinations", params, headers)

    # --------------------------------------------------------------- activations
    def create_activation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/activations", payload, headers)

    def get_activation(self, activation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/activations/{activation_id}", None, headers
        )

    def list_activations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/activations", params, headers)

    def dispatch_activation(
        self, activation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/activations/{activation_id}/dispatch",
            payload or {},
            headers,
        )

    def report_match(
        self, activation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/activations/{activation_id}/match-report", payload, headers
        )

    def pause_activation(
        self, activation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/activations/{activation_id}/pause", payload or {}, headers
        )

    def resume_activation(
        self, activation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/activations/{activation_id}/resume", payload or {}, headers
        )

    # ---------------------------------------------------------- deletion requests
    def create_deletion_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/deletion-requests", payload, headers)

    def get_deletion_request(self, deletion_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/deletion-requests/{deletion_request_id}", None, headers
        )

    def list_deletion_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{PREFIX}/deletion-requests", params, headers)

    def propagate_deletion_request(
        self, deletion_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/deletion-requests/{deletion_request_id}/propagate",
            payload,
            headers,
        )

    # ------------------------------------------------------ vendor deletion tasks
    def get_vendor_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/vendor-deletion-tasks/{task_id}", None, headers
        )

    def list_vendor_tasks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/vendor-deletion-tasks", params, headers)

    def acknowledge_vendor_task(
        self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/vendor-deletion-tasks/{task_id}/acknowledge",
            payload,
            headers,
        )
