"""One method per endpoint of the biometric privacy consent API."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin transport wrapper: every method returns the raw response so that
    tests can assert on status codes as well as on bodies."""

    # ------------------------------------------------------------------
    # ComplianceProgram
    # ------------------------------------------------------------------
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}", None, headers)

    def run_destruction_sweep(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/destruction-sweeps", {}, headers)

    # ------------------------------------------------------------------
    # Jurisdiction
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/jurisdictions", payload, headers)

    def update_jurisdiction(
        self, jurisdiction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/jurisdictions/{jurisdiction_id}", payload, headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", None, headers)

    def list_jurisdictions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/jurisdictions", params or {}, headers)

    # ------------------------------------------------------------------
    # Vendor
    # ------------------------------------------------------------------
    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/vendors", payload, headers)

    def record_attestation(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/vendors/{vendor_id}/attestations", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/vendors/{vendor_id}", None, headers)

    def list_vendors(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/vendors", params or {}, headers)

    # ------------------------------------------------------------------
    # VendorContract
    # ------------------------------------------------------------------
    def create_vendor_contract(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/vendor-contracts", payload, headers)

    def transition_vendor_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/vendor-contracts/{contract_id}/transitions", payload, headers)

    def get_vendor_contract(self, contract_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/vendor-contracts/{contract_id}", None, headers)

    def list_vendor_contracts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/vendor-contracts", params or {}, headers)

    # ------------------------------------------------------------------
    # BiometricPolicy
    # ------------------------------------------------------------------
    def create_policy(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/policies", payload, headers)

    def transition_policy(
        self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/policies/{policy_id}/transitions", payload, headers)

    def publish_policy(
        self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/policies/{policy_id}/publish", payload, headers)

    def get_policy(self, policy_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/policies/{policy_id}", None, headers)

    def list_policies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/policies", params or {}, headers)

    # ------------------------------------------------------------------
    # NoticePacket
    # ------------------------------------------------------------------
    def create_notice_packet(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/notice-packets", payload, headers)

    def transition_notice_packet(
        self, notice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/notice-packets/{notice_id}/transitions", payload, headers)

    def get_notice_packet(self, notice_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/notice-packets/{notice_id}", None, headers)

    def list_notice_packets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/notice-packets", params or {}, headers)

    # ------------------------------------------------------------------
    # BiometricAsset
    # ------------------------------------------------------------------
    def create_asset(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/biometric-assets", payload, headers)

    def update_asset(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/biometric-assets/{asset_id}", payload, headers)

    def transition_asset(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/biometric-assets/{asset_id}/transitions", payload, headers)

    def get_asset(self, asset_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/biometric-assets/{asset_id}", None, headers)

    def list_assets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/biometric-assets", params or {}, headers)

    # ------------------------------------------------------------------
    # DataSubject
    # ------------------------------------------------------------------
    def create_data_subject(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/data-subjects", payload, headers)

    def get_data_subject(self, subject_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/data-subjects/{subject_id}", None, headers)

    def list_data_subjects(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/data-subjects", params or {}, headers)

    # ------------------------------------------------------------------
    # ConsentRecord
    # ------------------------------------------------------------------
    def create_consent_record(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/consent-records", payload, headers)

    def transition_consent_record(
        self, consent_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/consent-records/{consent_id}/transitions", payload, headers)

    def get_consent_record(self, consent_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/consent-records/{consent_id}", None, headers)

    def list_consent_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/consent-records", params or {}, headers)

    # ------------------------------------------------------------------
    # AlternativeAccommodation
    # ------------------------------------------------------------------
    def create_accommodation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/accommodations", payload, headers)

    def transition_accommodation(
        self, accommodation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/accommodations/{accommodation_id}/transitions", payload, headers)

    def get_accommodation(self, accommodation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/accommodations/{accommodation_id}", None, headers)

    def list_accommodations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/accommodations", params or {}, headers)

    # ------------------------------------------------------------------
    # IncidentCase
    # ------------------------------------------------------------------
    def create_incident(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/incidents", payload, headers)

    def transition_incident_containment(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/incidents/{incident_id}/containment-transitions", payload, headers)

    def transition_incident_notification(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/incidents/{incident_id}/notification-transitions", payload, headers)

    def get_incident(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/incidents/{incident_id}", None, headers)

    def list_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/incidents", params or {}, headers)

    # ------------------------------------------------------------------
    # ExposureAssessment
    # ------------------------------------------------------------------
    def create_exposure_assessment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/exposure-assessments", payload, headers)

    def transition_exposure_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/exposure-assessments/{assessment_id}/transitions", payload, headers)

    def get_exposure_assessment(self, assessment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/exposure-assessments/{assessment_id}", None, headers)

    def list_exposure_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/exposure-assessments", params or {}, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Raw escape hatch for unknown-id / malformed-path probes
    # ------------------------------------------------------------------
    def raw_get(
        self, path: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", path, params or {}, headers)

    def raw_post(
        self, path: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", path, payload, headers)
