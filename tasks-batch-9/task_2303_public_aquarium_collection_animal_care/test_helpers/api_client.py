"""HTTP client — one method per endpoint published in PRD §4."""
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/aquarium"


class ApiClient(GenericApiClient):
    """Thin wrapper exposing every documented route as a named method."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Life support systems
    # ------------------------------------------------------------------
    def create_life_support_system(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/life-support-systems", payload, headers)

    def list_life_support_systems(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/life-support-systems", None, headers, params)

    def get_life_support_system(self, system_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/life-support-systems/{system_id}", None, headers)

    def create_water_quality_reading(self, system_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/life-support-systems/{system_id}/water-quality-readings", payload, headers
        )

    def list_water_quality_readings(self, system_id, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/life-support-systems/{system_id}/water-quality-readings", None, headers, params
        )

    def create_redundancy_test(self, system_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/life-support-systems/{system_id}/redundancy-tests", payload, headers
        )

    def list_system_exhibits(self, system_id, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/life-support-systems/{system_id}/exhibits", None, headers, params
        )

    # ------------------------------------------------------------------
    # Exhibits
    # ------------------------------------------------------------------
    def create_exhibit(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/exhibits", payload, headers)

    def list_exhibits(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/exhibits", None, headers, params)

    def get_exhibit(self, exhibit_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/exhibits/{exhibit_id}", None, headers)

    def update_exhibit(self, exhibit_id, payload, headers) -> requests.Response:
        return self._request("PATCH", f"{BASE}/exhibits/{exhibit_id}", payload, headers)

    def list_exhibit_interaction_sessions(self, exhibit_id, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/exhibits/{exhibit_id}/interaction-sessions", None, headers, params
        )

    # ------------------------------------------------------------------
    # Species
    # ------------------------------------------------------------------
    def create_species(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/species", payload, headers)

    def list_species(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/species", None, headers, params)

    def get_species(self, species_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/species/{species_id}", None, headers)

    # ------------------------------------------------------------------
    # Institutions
    # ------------------------------------------------------------------
    def create_institution(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/institutions", payload, headers)

    def list_institutions(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/institutions", None, headers, params)

    def get_institution(self, institution_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/institutions/{institution_id}", None, headers)

    def update_institution(self, institution_id, payload, headers) -> requests.Response:
        return self._request("PATCH", f"{BASE}/institutions/{institution_id}", payload, headers)

    # ------------------------------------------------------------------
    # Collection plan entries
    # ------------------------------------------------------------------
    def create_collection_plan_entry(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/collection-plan-entries", payload, headers)

    def list_collection_plan_entries(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/collection-plan-entries", None, headers, params)

    def get_collection_plan_entry(self, entry_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/collection-plan-entries/{entry_id}", None, headers)

    def plan_entry_status_action(self, entry_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/collection-plan-entries/{entry_id}/status-actions", payload, headers
        )

    # ------------------------------------------------------------------
    # Acquisition requests
    # ------------------------------------------------------------------
    def create_acquisition_request(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/acquisition-requests", payload, headers)

    def list_acquisition_requests(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/acquisition-requests", None, headers, params)

    def get_acquisition_request(self, request_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/acquisition-requests/{request_id}", None, headers)

    def submit_acquisition_request(self, request_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/acquisition-requests/{request_id}/submission", payload, headers
        )

    def clear_acquisition_request(self, request_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/acquisition-requests/{request_id}/clearance", payload, headers
        )

    def cancel_acquisition_request(self, request_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/acquisition-requests/{request_id}/cancellation", payload, headers
        )

    def list_acquisition_request_permits(self, request_id, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/acquisition-requests/{request_id}/permits", None, headers, params
        )

    # ------------------------------------------------------------------
    # Permits
    # ------------------------------------------------------------------
    def create_permit(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/permits", payload, headers)

    def get_permit(self, permit_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/permits/{permit_id}", None, headers)

    def submit_permit(self, permit_id, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/permits/{permit_id}/submission", payload, headers)

    def decide_permit(self, permit_id, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/permits/{permit_id}/decisions", payload, headers)

    # ------------------------------------------------------------------
    # Specimens
    # ------------------------------------------------------------------
    def create_specimen(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/specimens", payload, headers)

    def list_specimens(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/specimens", None, headers, params)

    def get_specimen(self, specimen_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/specimens/{specimen_id}", None, headers)

    def place_specimen(self, specimen_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/specimens/{specimen_id}/exhibit-placements", payload, headers
        )

    def remove_specimen(self, specimen_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/specimens/{specimen_id}/exhibit-removals", payload, headers
        )

    def declare_mortality(self, specimen_id, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/specimens/{specimen_id}/mortality", payload, headers)

    def create_husbandry_log(self, specimen_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/specimens/{specimen_id}/husbandry-logs", payload, headers
        )

    def list_husbandry_logs(self, specimen_id, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/specimens/{specimen_id}/husbandry-logs", None, headers, params
        )

    def list_specimen_quarantine_cases(self, specimen_id, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/specimens/{specimen_id}/quarantine-cases", None, headers, params
        )

    def list_specimen_veterinary_cases(self, specimen_id, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/specimens/{specimen_id}/veterinary-cases", None, headers, params
        )

    # ------------------------------------------------------------------
    # Quarantine cases
    # ------------------------------------------------------------------
    def get_quarantine_case(self, case_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/quarantine-cases/{case_id}", None, headers)

    def create_quarantine_review(self, case_id, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/quarantine-cases/{case_id}/reviews", payload, headers)

    # ------------------------------------------------------------------
    # Veterinary cases
    # ------------------------------------------------------------------
    def create_veterinary_case(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/veterinary-cases", payload, headers)

    def get_veterinary_case(self, case_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/veterinary-cases/{case_id}", None, headers)

    def close_veterinary_case(self, case_id, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/veterinary-cases/{case_id}/closure", payload, headers)

    # ------------------------------------------------------------------
    # Transfer requests
    # ------------------------------------------------------------------
    def create_transfer_request(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/transfer-requests", payload, headers)

    def list_transfer_requests(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/transfer-requests", None, headers, params)

    def get_transfer_request(self, transfer_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/transfer-requests/{transfer_id}", None, headers)

    def submit_transfer_request(self, transfer_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/transfer-requests/{transfer_id}/submission", payload, headers
        )

    def decide_transfer_request(self, transfer_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/transfer-requests/{transfer_id}/decisions", payload, headers
        )

    def complete_transfer_request(self, transfer_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/transfer-requests/{transfer_id}/completion", payload, headers
        )

    # ------------------------------------------------------------------
    # Interaction sessions
    # ------------------------------------------------------------------
    def create_interaction_session(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/interaction-sessions", payload, headers)

    def get_interaction_session(self, session_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/interaction-sessions/{session_id}", None, headers)

    def transition_interaction_session(self, session_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/interaction-sessions/{session_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Accreditation audits
    # ------------------------------------------------------------------
    def create_accreditation_audit(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{BASE}/accreditation-audits", payload, headers)

    def list_accreditation_audits(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{BASE}/accreditation-audits", None, headers, params)

    def get_accreditation_audit(self, audit_id, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/accreditation-audits/{audit_id}", None, headers)

    def progress_accreditation_audit(self, audit_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/accreditation-audits/{audit_id}/progressions", payload, headers
        )


# Shared instance used by the helper builders and by tests.
api_client = ApiClient()
