"""One method per endpoint of the payment-card security assessment API.

Paths are routed exactly as the PRD gives them: no version segment and no
common prefix, so every route sits at the top level.
"""

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the service's sixty-nine routes."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ------------------------------------------------------------------
    # Assessors
    # ------------------------------------------------------------------
    def create_assessor(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/assessors", payload, headers)

    def get_assessor(
        self, assessor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/assessors/%s" % assessor_id, None, headers)

    def list_assessors(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/assessors", params, headers)

    def update_assessor(
        self, assessor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", "/assessors/%s" % assessor_id, payload, headers)

    # ------------------------------------------------------------------
    # ASV vendors
    # ------------------------------------------------------------------
    def create_asv_vendor(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/asv-vendors", payload, headers)

    def get_asv_vendor(
        self, vendor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/asv-vendors/%s" % vendor_id, None, headers)

    def list_asv_vendors(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/asv-vendors", params, headers)

    def update_asv_vendor(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", "/asv-vendors/%s" % vendor_id, payload, headers)

    # ------------------------------------------------------------------
    # Engagements
    # ------------------------------------------------------------------
    def create_engagement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/engagements", payload, headers)

    def get_engagement(
        self, engagement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/engagements/%s" % engagement_id, None, headers)

    def list_engagements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/engagements", params, headers)

    def get_engagement_summary(
        self, engagement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/engagements/%s/summary" % engagement_id, None, headers
        )

    def update_engagement(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", "/engagements/%s" % engagement_id, payload, headers
        )

    def assign_qa_reviewer(
        self, engagement_id: str, qa_reviewer_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/engagements/%s/qa-reviewer" % engagement_id,
            {"qa_reviewer_id": qa_reviewer_id},
            headers,
        )

    def lock_scope(
        self, engagement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/engagements/%s/scope-lock" % engagement_id, {}, headers
        )

    def record_reassessment_plan(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/engagements/%s/reassessment-plan" % engagement_id,
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Network segments
    # ------------------------------------------------------------------
    def create_network_segment(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/engagements/%s/network-segments" % engagement_id,
            payload,
            headers,
        )

    def get_network_segment(
        self, segment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/network-segments/%s" % segment_id, None, headers)

    def list_network_segments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/network-segments", params, headers)

    def update_network_segment(
        self, segment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", "/network-segments/%s" % segment_id, payload, headers
        )

    def plan_segmentation_test(
        self, segment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/network-segments/%s/segmentation-test-plan" % segment_id,
            payload,
            headers,
        )

    def record_validation_result(
        self, segment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/network-segments/%s/validation-result" % segment_id,
            payload,
            headers,
        )

    def request_remediation_revalidation(
        self, segment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/network-segments/%s/remediation-revalidation" % segment_id,
            payload,
            headers,
        )

    def withdraw_network_segment(
        self, segment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/network-segments/%s/withdraw" % segment_id, payload, headers
        )

    # ------------------------------------------------------------------
    # System components
    # ------------------------------------------------------------------
    def create_system_component(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/engagements/%s/system-components" % engagement_id,
            payload,
            headers,
        )

    def get_system_component(
        self, component_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/system-components/%s" % component_id, None, headers)

    def list_system_components(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/system-components", params, headers)

    # ------------------------------------------------------------------
    # Sampling plans
    # ------------------------------------------------------------------
    def create_sampling_plan(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/engagements/%s/sampling-plans" % engagement_id, payload, headers
        )

    def get_sampling_plan(
        self, plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/sampling-plans/%s" % plan_id, None, headers)

    def list_sampling_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/sampling-plans", params, headers)

    # ------------------------------------------------------------------
    # Requirement assessments
    # ------------------------------------------------------------------
    def create_requirement_assessment(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/engagements/%s/requirement-assessments" % engagement_id,
            payload,
            headers,
        )

    def get_requirement_assessment(
        self, requirement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/requirement-assessments/%s" % requirement_id, None, headers
        )

    def list_requirement_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/requirement-assessments", params, headers)

    def start_testing(
        self, requirement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/requirement-assessments/%s/start-testing" % requirement_id,
            {},
            headers,
        )

    def conclude_requirement(
        self, requirement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/requirement-assessments/%s/conclusion" % requirement_id,
            payload,
            headers,
        )

    def reopen_requirement(
        self, requirement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/requirement-assessments/%s/reopen" % requirement_id,
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Evidence items
    # ------------------------------------------------------------------
    def create_evidence_item(
        self, requirement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/requirement-assessments/%s/evidence-items" % requirement_id,
            payload,
            headers,
        )

    def get_evidence_item(
        self, evidence_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/evidence-items/%s" % evidence_id, None, headers)

    def list_evidence_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/evidence-items", params, headers)

    # ------------------------------------------------------------------
    # Compensating control worksheets
    # ------------------------------------------------------------------
    def create_ccw(
        self, requirement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/requirement-assessments/%s/ccws" % requirement_id,
            payload,
            headers,
        )

    def get_ccw(self, ccw_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/ccws/%s" % ccw_id, None, headers)

    def list_ccws(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/ccws", params, headers)

    def submit_ccw(self, ccw_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/ccws/%s/submit" % ccw_id, {}, headers)

    def decide_ccw(
        self, ccw_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ccws/%s/decision" % ccw_id, payload, headers)

    # ------------------------------------------------------------------
    # Remediation items
    # ------------------------------------------------------------------
    def get_remediation_item(
        self, item_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/remediation-items/%s" % item_id, None, headers)

    def list_remediation_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/remediation-items", params, headers)

    def assign_remediation_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/remediation-items/%s/assign" % item_id, payload, headers
        )

    def retest_remediation_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/remediation-items/%s/retest" % item_id, payload, headers
        )

    # ------------------------------------------------------------------
    # Reports on compliance
    # ------------------------------------------------------------------
    def create_roc(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/engagements/%s/rocs" % engagement_id, payload, headers
        )

    def get_roc(self, roc_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/rocs/%s" % roc_id, None, headers)

    def list_rocs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/rocs", params, headers)

    def qa_submit_roc(self, roc_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/rocs/%s/qa-submit" % roc_id, {}, headers)

    def qa_review_roc(
        self, roc_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/rocs/%s/qa-review" % roc_id, payload, headers)

    def revise_roc(
        self, roc_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/rocs/%s/revise" % roc_id, payload, headers)

    def attest_roc(
        self, roc_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/rocs/%s/attest" % roc_id, payload, headers)

    def submit_roc(
        self, roc_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/rocs/%s/submission" % roc_id, payload, headers)

    # ------------------------------------------------------------------
    # Scan cycles and findings
    # ------------------------------------------------------------------
    def create_scan_cycle(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/engagements/%s/scan-cycles" % engagement_id, payload, headers
        )

    def get_scan_cycle(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/scan-cycles/%s" % cycle_id, None, headers)

    def list_scan_cycles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/scan-cycles", params, headers)

    def complete_scan_cycle(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/scan-cycles/%s/complete" % cycle_id, {}, headers)

    def create_scan_finding(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/scan-cycles/%s/findings" % cycle_id, payload, headers
        )

    def get_scan_finding(
        self, finding_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/scan-findings/%s" % finding_id, None, headers)

    def list_scan_findings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/scan-findings", params, headers)

    def dispute_scan_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/scan-findings/%s/dispute" % finding_id, payload, headers
        )

    def decide_scan_finding_dispute(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/scan-findings/%s/dispute-decision" % finding_id, payload, headers
        )

    # ------------------------------------------------------------------
    # Change-log entries
    # ------------------------------------------------------------------
    def create_change_log_entry(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/engagements/%s/change-log-entries" % engagement_id,
            payload,
            headers,
        )

    def get_change_log_entry(
        self, entry_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/change-log-entries/%s" % entry_id, None, headers)

    def list_change_log_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/change-log-entries", params, headers)

    # ------------------------------------------------------------------
    # Raw escape hatch for probes that must bypass the typed helpers
    # ------------------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers, params)

    def get_by_path(
        self, path: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", path, params, headers)

    def not_found_probe_paths(self, identifier: str) -> List[str]:
        """The fourteen single-resource reads, one per addressable collection."""
        return [
            "/assessors/%s" % identifier,
            "/asv-vendors/%s" % identifier,
            "/engagements/%s" % identifier,
            "/network-segments/%s" % identifier,
            "/system-components/%s" % identifier,
            "/sampling-plans/%s" % identifier,
            "/requirement-assessments/%s" % identifier,
            "/evidence-items/%s" % identifier,
            "/ccws/%s" % identifier,
            "/remediation-items/%s" % identifier,
            "/rocs/%s" % identifier,
            "/scan-cycles/%s" % identifier,
            "/scan-findings/%s" % identifier,
            "/change-log-entries/%s" % identifier,
        ]
