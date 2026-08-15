"""API client: one method per endpoint declared in PRD section 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Corporate Entity Governance API."""

    # --- Test-driving harness (outside the /api mount) ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_system/sweep", {}, headers)

    # --- Jurisdictions ---
    def create_jurisdiction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/api/jurisdictions/{jurisdiction_id}", headers=headers
        )

    # --- Registered agents ---
    def create_registered_agent(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/registered-agents", payload, headers)

    def list_registered_agents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/registered-agents", headers=headers, params=params)

    def get_registered_agent(self, agent_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/registered-agents/{agent_id}", headers=headers)

    # --- Officers ---
    def create_officer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/officers", payload, headers)

    def list_officers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/officers", headers=headers, params=params)

    def get_officer(self, officer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/officers/{officer_id}", headers=headers)

    def deactivate_officer(self, officer_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/officers/{officer_id}/deactivate", {}, headers)

    # --- Legal entities ---
    def create_entity(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/entities", payload, headers)

    def list_entities(self, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None):
        return self._request("GET", "/api/entities", headers=headers, params=params)

    def get_entity(self, entity_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/entities/{entity_id}", headers=headers)

    def patch_entity(self, entity_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/api/entities/{entity_id}", payload, headers)

    def submit_formation(self, entity_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/submit-formation", {}, headers)

    def confirm_formation(self, entity_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/confirm-formation", {}, headers)

    def commence_dissolution(self, entity_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/commence-dissolution", {}, headers)

    def finalize_dissolution(self, entity_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/finalize-dissolution", {}, headers)

    def revoke_dissolution(self, entity_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/revoke-dissolution", {}, headers)

    # --- Agent appointments ---
    def create_agent_appointment(self, entity_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/agent-appointments", payload, headers)

    def list_agent_appointments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/agent-appointments", headers=headers, params=params)

    def get_agent_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/agent-appointments/{appointment_id}", headers=headers)

    def file_resignation_notice(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/agent-appointments/{appointment_id}/file-resignation-notice", {}, headers
        )

    def finalize_resignation(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/agent-appointments/{appointment_id}/finalize-resignation", {}, headers
        )

    # --- Resolutions ---
    def create_resolution(self, entity_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/resolutions", payload, headers)

    def list_resolutions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/resolutions", headers=headers, params=params)

    def get_resolution(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/resolutions/{resolution_id}", headers=headers)

    def submit_resolution(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/resolutions/{resolution_id}/submit", {}, headers)

    def return_resolution(self, resolution_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/resolutions/{resolution_id}/return", payload, headers)

    def adopt_resolution(self, resolution_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/resolutions/{resolution_id}/adopt", payload, headers)

    def withdraw_resolution(self, resolution_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/resolutions/{resolution_id}/withdraw", {}, headers)

    def rescind_resolution(self, resolution_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/resolutions/{resolution_id}/rescind", payload, headers)

    # --- Officer appointments ---
    def list_officer_appointments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/officer-appointments", headers=headers, params=params)

    def get_officer_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/officer-appointments/{appointment_id}", headers=headers)

    def resign_officer_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/officer-appointments/{appointment_id}/resign", {}, headers
        )

    # --- Annual filings ---
    def list_filings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/filings", headers=headers, params=params)

    def get_filing(self, filing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/filings/{filing_id}", headers=headers)

    def prepare_filing(self, filing_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/filings/{filing_id}/prepare", {}, headers)

    def submit_filing(self, filing_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/filings/{filing_id}/submit", {}, headers)

    def accept_filing(self, filing_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/filings/{filing_id}/accept", {}, headers)

    def reject_filing(self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/filings/{filing_id}/reject", payload, headers)

    # --- Foreign qualifications ---
    def create_qualification(self, entity_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/qualifications", payload, headers)

    def list_qualifications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/qualifications", headers=headers, params=params)

    def get_qualification(self, qualification_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/qualifications/{qualification_id}", headers=headers)

    def confirm_qualification(self, qualification_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/qualifications/{qualification_id}/confirm", {}, headers)

    def commence_withdrawal(self, qualification_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/qualifications/{qualification_id}/commence-withdrawal", {}, headers
        )

    def finalize_withdrawal(self, qualification_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/qualifications/{qualification_id}/finalize-withdrawal", {}, headers
        )

    def abort_withdrawal(self, qualification_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/qualifications/{qualification_id}/abort-withdrawal", {}, headers
        )

    # --- Signature authority grants ---
    def create_signature_grant(self, entity_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/entities/{entity_id}/signature-grants", payload, headers)

    def list_signature_grants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/signature-grants", headers=headers, params=params)

    def get_signature_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/signature-grants/{grant_id}", headers=headers)

    def verify_signature(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/signature-grants/verify", payload, headers)

    def suspend_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/signature-grants/{grant_id}/suspend", {}, headers)

    def reinstate_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/signature-grants/{grant_id}/reinstate", {}, headers)

    def revoke_grant(self, grant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/signature-grants/{grant_id}/revoke", payload, headers)

    # --- Good-standing certificates ---
    def create_certificate_request(self, entity_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/entities/{entity_id}/certificate-requests", payload, headers
        )

    def list_certificates(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/certificates/{certificate_id}", headers=headers)

    def issue_certificate(self, certificate_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/certificates/{certificate_id}/issue", {}, headers)

    def deny_certificate(self, certificate_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/certificates/{certificate_id}/deny", payload, headers)

    # --- Ownership records ---
    def create_ownership_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/ownership-records", payload, headers)

    def list_ownership_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/ownership-records", headers=headers, params=params)

    def get_ownership_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/ownership-records/{record_id}", headers=headers)

    def void_ownership_record(self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/ownership-records/{record_id}/void", payload, headers)

    def get_ownership_chart(self, entity_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/entities/{entity_id}/ownership-chart", headers=headers)

    # --- Compliance events ---
    def list_compliance_events(self, entity_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/entities/{entity_id}/compliance-events", headers=headers, params=params
        )


api_client = ApiClient()
