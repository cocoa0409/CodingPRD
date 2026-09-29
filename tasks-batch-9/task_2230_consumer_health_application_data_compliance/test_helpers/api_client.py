"""Typed HTTP client exposing one method per documented endpoint."""

from __future__ import annotations

from typing import Any

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/health-data"


class ApiClient(GenericApiClient):
    """One method per endpoint; every method returns the raw response."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # App products
    # ------------------------------------------------------------------
    def create_app_product(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/app-products", payload, headers)

    def list_app_products(self, headers: dict[str, str], params: dict[str, Any] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/app-products", None, headers, params)

    def get_app_product(self, app_product_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/app-products/{app_product_id}", None, headers)

    def update_app_product(
        self, app_product_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{BASE}/app-products/{app_product_id}", payload, headers)

    def get_compliance_summary(self, app_product_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/app-products/{app_product_id}/compliance-summary", None, headers
        )

    # ------------------------------------------------------------------
    # Applicability assessments
    # ------------------------------------------------------------------
    def create_applicability_assessment(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/applicability-assessments", payload, headers)

    def list_applicability_assessments(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/applicability-assessments", None, headers, params)

    def get_applicability_assessment(self, assessment_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/applicability-assessments/{assessment_id}", None, headers)

    def submit_applicability_assessment(
        self, assessment_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/applicability-assessments/{assessment_id}/submit", payload, headers
        )

    def approve_applicability_assessment(
        self, assessment_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/applicability-assessments/{assessment_id}/approve", payload, headers
        )

    def return_applicability_assessment(
        self, assessment_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/applicability-assessments/{assessment_id}/return", payload, headers
        )

    def revise_applicability_assessment(
        self, assessment_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/applicability-assessments/{assessment_id}/revise", payload, headers
        )

    # ------------------------------------------------------------------
    # Data elements
    # ------------------------------------------------------------------
    def create_data_element(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/data-elements", payload, headers)

    def list_data_elements(self, headers: dict[str, str], params: dict[str, Any] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/data-elements", None, headers, params)

    def get_data_element(self, element_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/data-elements/{element_id}", None, headers)

    def update_data_element(
        self, element_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{BASE}/data-elements/{element_id}", payload, headers)

    def retire_data_element(
        self, element_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/data-elements/{element_id}/retire", payload, headers)

    def reinstate_data_element(
        self, element_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/data-elements/{element_id}/reinstate", payload, headers)

    # ------------------------------------------------------------------
    # Processing purposes
    # ------------------------------------------------------------------
    def create_processing_purpose(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/processing-purposes", payload, headers)

    def list_processing_purposes(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/processing-purposes", None, headers, params)

    def get_processing_purpose(self, purpose_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/processing-purposes/{purpose_id}", None, headers)

    # ------------------------------------------------------------------
    # Element-purpose mappings
    # ------------------------------------------------------------------
    def create_element_purpose_mapping(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/element-purpose-mappings", payload, headers)

    def list_element_purpose_mappings(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/element-purpose-mappings", None, headers, params)

    def get_element_purpose_mapping(self, mapping_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/element-purpose-mappings/{mapping_id}", None, headers)

    def activate_element_purpose_mapping(
        self, mapping_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/element-purpose-mappings/{mapping_id}/activate", payload, headers
        )

    def suspend_element_purpose_mapping(
        self, mapping_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/element-purpose-mappings/{mapping_id}/suspend", payload, headers
        )

    def retire_element_purpose_mapping(
        self, mapping_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/element-purpose-mappings/{mapping_id}/retire", payload, headers
        )

    # ------------------------------------------------------------------
    # Consumers
    # ------------------------------------------------------------------
    def create_consumer(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/consumers", payload, headers)

    def list_consumers(self, headers: dict[str, str], params: dict[str, Any] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/consumers", None, headers, params)

    def get_consumer(self, consumer_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/consumers/{consumer_id}", None, headers)

    # ------------------------------------------------------------------
    # Consent records
    # ------------------------------------------------------------------
    def create_consent_record(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/consent-records", payload, headers)

    def list_consent_records(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/consent-records", None, headers, params)

    def get_consent_record(self, record_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/consent-records/{record_id}", None, headers)

    def grant_consent(
        self, record_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/consent-records/{record_id}/grants", payload, headers)

    def withdraw_consent(
        self, record_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consent-records/{record_id}/withdrawals", payload, headers
        )

    # ------------------------------------------------------------------
    # Privacy policy versions
    # ------------------------------------------------------------------
    def create_privacy_policy_version(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/privacy-policy-versions", payload, headers)

    def list_privacy_policy_versions(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/privacy-policy-versions", None, headers, params)

    def get_privacy_policy_version(self, policy_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/privacy-policy-versions/{policy_id}", None, headers)

    def submit_policy_review(
        self, policy_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/privacy-policy-versions/{policy_id}/submit-review", payload, headers
        )

    def return_policy_to_draft(
        self, policy_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/privacy-policy-versions/{policy_id}/return-to-draft", payload, headers
        )

    def publish_privacy_policy_version(
        self, policy_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/privacy-policy-versions/{policy_id}/publish", payload, headers
        )

    # ------------------------------------------------------------------
    # Consumer rights requests
    # ------------------------------------------------------------------
    def create_consumer_request(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/consumer-requests", payload, headers)

    def list_consumer_requests(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/consumer-requests", None, headers, params)

    def get_consumer_request(self, request_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/consumer-requests/{request_id}", None, headers)

    def request_more_info(
        self, request_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consumer-requests/{request_id}/request-more-info", payload, headers
        )

    def resubmit_identity(
        self, request_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consumer-requests/{request_id}/resubmit-identity", payload, headers
        )

    def verify_consumer_request(
        self, request_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consumer-requests/{request_id}/verify", payload, headers
        )

    def extend_consumer_request(
        self, request_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consumer-requests/{request_id}/extend", payload, headers
        )

    def fulfill_consumer_request(
        self, request_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consumer-requests/{request_id}/fulfill", payload, headers
        )

    def deny_consumer_request(
        self, request_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/consumer-requests/{request_id}/deny", payload, headers)

    # ------------------------------------------------------------------
    # Deletion tasks
    # ------------------------------------------------------------------
    def list_deletion_tasks(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/deletion-tasks", None, headers, params)

    def get_deletion_task(self, task_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/deletion-tasks/{task_id}", None, headers)

    def notify_deletion_task(
        self, task_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/deletion-tasks/{task_id}/notify", payload, headers)

    def confirm_deletion_task(
        self, task_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/deletion-tasks/{task_id}/confirm", payload, headers)

    def fail_deletion_task(
        self, task_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/deletion-tasks/{task_id}/fail", payload, headers)

    def reissue_deletion_task(
        self, task_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/deletion-tasks/{task_id}/reissue", payload, headers)

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------
    def create_vendor(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/vendors", payload, headers)

    def list_vendors(self, headers: dict[str, str], params: dict[str, Any] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/vendors", None, headers, params)

    def get_vendor(self, vendor_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/vendors/{vendor_id}", None, headers)

    def update_vendor(
        self, vendor_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{BASE}/vendors/{vendor_id}", payload, headers)

    def execute_vendor_agreement(
        self, vendor_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/vendors/{vendor_id}/execute-agreement", payload, headers)

    def terminate_vendor_agreement(
        self, vendor_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/vendors/{vendor_id}/terminate-agreement", payload, headers
        )

    # ------------------------------------------------------------------
    # Geofence zones
    # ------------------------------------------------------------------
    def create_geofence_zone(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/geofence-zones", payload, headers)

    def list_geofence_zones(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/geofence-zones", None, headers, params)

    def get_geofence_zone(self, zone_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/geofence-zones/{zone_id}", None, headers)

    # ------------------------------------------------------------------
    # Geofence campaigns
    # ------------------------------------------------------------------
    def create_geofence_campaign(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/geofence-campaigns", payload, headers)

    def list_geofence_campaigns(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/geofence-campaigns", None, headers, params)

    def get_geofence_campaign(self, campaign_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/geofence-campaigns/{campaign_id}", None, headers)

    def activate_geofence_campaign(
        self, campaign_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/geofence-campaigns/{campaign_id}/activate", payload, headers
        )

    def pause_geofence_campaign(
        self, campaign_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/geofence-campaigns/{campaign_id}/pause", payload, headers
        )

    def end_geofence_campaign(
        self, campaign_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/geofence-campaigns/{campaign_id}/end", payload, headers)

    # ------------------------------------------------------------------
    # Breach incidents
    # ------------------------------------------------------------------
    def create_breach_incident(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/breach-incidents", payload, headers)

    def list_breach_incidents(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/breach-incidents", None, headers, params)

    def get_breach_incident(self, incident_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/breach-incidents/{incident_id}", None, headers)

    def assess_breach_incident(
        self, incident_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/breach-incidents/{incident_id}/assess", payload, headers)

    def notify_breach_incident(
        self, incident_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/breach-incidents/{incident_id}/notify", payload, headers)

    def retract_breach_incident(
        self, incident_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/breach-incidents/{incident_id}/retract", payload, headers
        )

    # ------------------------------------------------------------------
    # Security risk assessments
    # ------------------------------------------------------------------
    def create_security_risk_assessment(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/security-risk-assessments", payload, headers)

    def list_security_risk_assessments(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/security-risk-assessments", None, headers, params)

    def get_security_risk_assessment(self, sra_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/security-risk-assessments/{sra_id}", None, headers)

    def update_security_risk_assessment(
        self, sra_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{BASE}/security-risk-assessments/{sra_id}", payload, headers)

    def finalize_security_risk_assessment(
        self, sra_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/security-risk-assessments/{sra_id}/finalize", payload, headers
        )


api_client = ApiClient()
