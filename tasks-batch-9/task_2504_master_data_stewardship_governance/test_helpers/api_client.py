"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Master data stewardship governance API client."""

    # ---------------- Logical clock ----------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- Domains ----------------

    def create_domain(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdm/domains", payload, headers)

    def list_domains(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mdm/domains", headers=headers, params=params)

    def get_domain(self, domain_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdm/domains/{domain_id}", headers=headers)

    def activate_domain(self, domain_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/mdm/domains/{domain_id}/activate", {}, headers)

    def get_domain_scorecard(
        self, domain_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/mdm/domains/{domain_id}/scorecard", headers=headers, params=params
        )

    def create_scorecard_run(
        self, domain_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdm/domains/{domain_id}/scorecard-runs", payload, headers
        )

    # ---------------- Source systems ----------------

    def create_source_system(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdm/source-systems", payload, headers)

    def list_source_systems(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mdm/source-systems", headers=headers, params=params)

    def get_source_system(self, source_system_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdm/source-systems/{source_system_id}", headers=headers
        )

    def certify_source_system(self, source_system_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mdm/source-systems/{source_system_id}/certify", {}, headers
        )

    def decertify_source_system(
        self, source_system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdm/source-systems/{source_system_id}/decertify", payload, headers
        )

    # ---------------- Stewards ----------------

    def create_steward(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdm/stewards", payload, headers)

    def list_stewards(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mdm/stewards", headers=headers, params=params)

    def get_steward(self, steward_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdm/stewards/{steward_id}", headers=headers)

    # ---------------- Source registrations ----------------

    def create_source_registration(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/mdm/source-registrations", payload, headers)

    def list_source_registrations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/mdm/source-registrations", headers=headers, params=params
        )

    def get_source_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdm/source-registrations/{registration_id}", headers=headers
        )

    # ---------------- Steward assignments ----------------

    def create_steward_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/mdm/steward-assignments", payload, headers)

    def list_steward_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/mdm/steward-assignments", headers=headers, params=params
        )

    def get_steward_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdm/steward-assignments/{assignment_id}", headers=headers
        )

    # ---------------- Quality rules ----------------

    def create_quality_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdm/quality-rules", payload, headers)

    def list_quality_rules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mdm/quality-rules", headers=headers, params=params)

    def get_quality_rule(self, rule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdm/quality-rules/{rule_id}", headers=headers)

    def update_quality_rule(
        self, rule_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/mdm/quality-rules/{rule_id}", payload, headers)

    # ---------------- Scorecard runs ----------------

    def list_scorecard_runs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mdm/scorecard-runs", headers=headers, params=params)

    def get_scorecard_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdm/scorecard-runs/{run_id}", headers=headers)

    # ---------------- Quality findings ----------------

    def list_quality_findings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/mdm/quality-findings", headers=headers, params=params
        )

    def get_quality_finding(self, finding_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdm/quality-findings/{finding_id}", headers=headers
        )

    def plan_finding_remediation(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/mdm/quality-findings/{finding_id}/plan-remediation",
            payload,
            headers,
        )

    def resolve_quality_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdm/quality-findings/{finding_id}/resolve", payload, headers
        )

    def waive_quality_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdm/quality-findings/{finding_id}/waive", payload, headers
        )

    # ---------------- Master records ----------------

    def create_master_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdm/master-records", payload, headers)

    def list_master_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mdm/master-records", headers=headers, params=params)

    def get_master_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdm/master-records/{record_id}", headers=headers)

    def curate_master_record(
        self,
        record_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/mdm/master-records/{record_id}/curate", payload or {}, headers
        )

    def publish_master_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mdm/master-records/{record_id}/publish", {}, headers
        )

    # ---------------- Merge proposals ----------------

    def create_merge_proposal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdm/merge-proposals", payload, headers)

    def list_merge_proposals(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/mdm/merge-proposals", headers=headers, params=params
        )

    def get_merge_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdm/merge-proposals/{proposal_id}", headers=headers
        )

    def review_merge_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mdm/merge-proposals/{proposal_id}/review", {}, headers
        )

    def decide_merge_proposal(
        self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdm/merge-proposals/{proposal_id}/decide", payload, headers
        )

    def rescore_merge_proposal(
        self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdm/merge-proposals/{proposal_id}/rescore", payload, headers
        )

    # ---------------- Change requests ----------------

    def create_change_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdm/change-requests", payload, headers)

    def list_change_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/mdm/change-requests", headers=headers, params=params
        )

    def get_change_request(self, change_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdm/change-requests/{change_request_id}", headers=headers
        )

    def submit_change_request(self, change_request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mdm/change-requests/{change_request_id}/submit", {}, headers
        )

    def review_change_request(self, change_request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mdm/change-requests/{change_request_id}/review", {}, headers
        )

    def decide_change_request(
        self, change_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdm/change-requests/{change_request_id}/decide", payload, headers
        )

    def schedule_change_request(
        self, change_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/mdm/change-requests/{change_request_id}/schedule",
            payload,
            headers,
        )

    def apply_change_request(self, change_request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mdm/change-requests/{change_request_id}/apply", {}, headers
        )

    def withdraw_change_request(
        self, change_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/mdm/change-requests/{change_request_id}/withdraw",
            payload,
            headers,
        )

    # ---------------- Consumer subscriptions ----------------

    def create_consumer_subscription(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/mdm/consumer-subscriptions", payload, headers)

    def list_consumer_subscriptions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/mdm/consumer-subscriptions", headers=headers, params=params
        )

    def get_consumer_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdm/consumer-subscriptions/{subscription_id}", headers=headers
        )

    def document_consumer_lineage(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH",
            f"/mdm/consumer-subscriptions/{subscription_id}/lineage",
            payload,
            headers,
        )

    def acknowledge_consumer_subscription(
        self, subscription_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/mdm/consumer-subscriptions/{subscription_id}/acknowledge",
            {},
            headers,
        )


api_client = ApiClient()
