"""API client: one method per endpoint of the Life Science Conversion API."""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Every endpoint served under the root path."""

    # -- logical clock ------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # -- buildings ----------------------------------------------------------

    def create_building(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/buildings", payload, headers)

    def get_building(self, building_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/buildings/{building_id}", headers=headers)

    def approve_conversion(
        self, building_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/buildings/{building_id}/conversion-approval", payload or {}, headers
        )

    # -- floors -------------------------------------------------------------

    def create_floor(self, building_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/buildings/{building_id}/floors", payload, headers)

    def list_building_floors(
        self, building_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/buildings/{building_id}/floors", headers=headers, params=params
        )

    def get_floor(self, floor_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/floors/{floor_id}", headers=headers)

    def list_floors(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/floors", headers=headers, params=params)

    def get_hazmat_utilization(
        self, floor_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/floors/{floor_id}/hazmat-utilization", headers=headers, params=params
        )

    # -- suitability assessments -------------------------------------------

    def create_assessment(
        self, building_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/buildings/{building_id}/suitability-assessments", payload, headers
        )

    def list_building_assessments(
        self, building_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/buildings/{building_id}/suitability-assessments",
            headers=headers,
            params=params,
        )

    def get_assessment(self, assessment_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/suitability-assessments/{assessment_id}", headers=headers
        )

    def list_assessments(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/suitability-assessments", headers=headers, params=params
        )

    def submit_assessment(
        self, assessment_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/suitability-assessments/{assessment_id}/submit",
            payload or {},
            headers,
        )

    def decide_assessment(
        self, assessment_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/suitability-assessments/{assessment_id}/decision", payload, headers
        )

    # -- conversion scope items --------------------------------------------

    def create_scope_item(
        self, building_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/buildings/{building_id}/conversion-scope-items", payload, headers
        )

    def list_building_scope_items(
        self, building_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/buildings/{building_id}/conversion-scope-items",
            headers=headers,
            params=params,
        )

    def get_scope_item(self, item_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/conversion-scope-items/{item_id}", headers=headers)

    def list_scope_items(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/conversion-scope-items", headers=headers, params=params
        )

    def complete_scope_item(
        self, item_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/conversion-scope-items/{item_id}/complete", payload or {}, headers
        )

    # -- shared amenities ---------------------------------------------------

    def create_amenity(self, building_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/buildings/{building_id}/shared-amenities", payload, headers
        )

    def list_building_amenities(
        self, building_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/buildings/{building_id}/shared-amenities", headers=headers, params=params
        )

    def get_amenity(self, amenity_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/shared-amenities/{amenity_id}", headers=headers)

    def list_amenities(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/shared-amenities", headers=headers, params=params)

    # -- tenants ------------------------------------------------------------

    def create_tenant(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # -- leases -------------------------------------------------------------

    def create_lease(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def create_proposal(self, lease_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/leases/{lease_id}/ti-proposals", payload, headers)

    def list_lease_proposals(
        self, lease_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/leases/{lease_id}/ti-proposals", headers=headers, params=params
        )

    def get_proposal(self, proposal_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/ti-proposals/{proposal_id}", headers=headers)

    def list_proposals(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/ti-proposals", headers=headers, params=params)

    def accept_proposal(
        self, proposal_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/ti-proposals/{proposal_id}/accept", payload or {}, headers
        )

    def create_escrow_deposit(
        self, lease_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/leases/{lease_id}/escrow-deposits", payload, headers)

    def execute_lease(
        self, lease_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request("POST", f"/leases/{lease_id}/execute", payload or {}, headers)

    def create_disbursement(
        self, lease_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/leases/{lease_id}/ti-disbursements", payload, headers
        )

    def issue_expiration_notice(
        self, lease_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/leases/{lease_id}/expiration-notice", payload, headers
        )

    def settle_restoration(
        self, lease_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/leases/{lease_id}/restoration-settlement", payload or {}, headers
        )

    # -- fit-out projects ---------------------------------------------------

    def create_project(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/fit-out-projects", payload, headers)

    def get_project(self, project_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/fit-out-projects/{project_id}", headers=headers)

    def list_projects(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/fit-out-projects", headers=headers, params=params)

    def apply_for_permit(
        self, project_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/fit-out-projects/{project_id}/permit-application", payload or {}, headers
        )

    def decide_permit(self, project_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/fit-out-projects/{project_id}/permit-decision", payload, headers
        )

    def declare_milestone(self, project_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/fit-out-projects/{project_id}/construction-milestone", payload, headers
        )

    # -- phase packages -----------------------------------------------------

    def create_phase(self, project_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/fit-out-projects/{project_id}/phase-packages", payload, headers
        )

    def get_phase(self, phase_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/phase-packages/{phase_id}", headers=headers)

    def list_phases(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/phase-packages", headers=headers, params=params)

    def schedule_phase(self, phase_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/phase-packages/{phase_id}/schedule", payload, headers
        )

    def hold_phase(self, phase_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/phase-packages/{phase_id}/hold", payload, headers)

    def progress_phase(self, phase_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/phase-packages/{phase_id}/progress", payload, headers
        )

    # -- capacity reservations ---------------------------------------------

    def create_reservation(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/capacity-reservations", payload, headers)

    def get_reservation(self, reservation_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/capacity-reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/capacity-reservations", headers=headers, params=params)

    def cancel_reservation(
        self, reservation_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/capacity-reservations/{reservation_id}/cancel", payload or {}, headers
        )

    # -- hazardous material use permits ------------------------------------

    def create_hazmat_permit(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/hazmat-permits", payload, headers)

    def get_hazmat_permit(self, permit_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/hazmat-permits/{permit_id}", headers=headers)

    def list_hazmat_permits(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/hazmat-permits", headers=headers, params=params)

    def decide_hazmat_permit(
        self, permit_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/hazmat-permits/{permit_id}/decision", payload, headers
        )

    # -- amenity allocations ------------------------------------------------

    def create_allocation(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/amenity-allocations", payload, headers)

    def get_allocation(self, allocation_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/amenity-allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/amenity-allocations", headers=headers, params=params)

    def confirm_allocation(
        self, allocation_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/amenity-allocations/{allocation_id}/confirm", payload or {}, headers
        )

    def cancel_allocation(
        self, allocation_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/amenity-allocations/{allocation_id}/cancel", payload or {}, headers
        )

    # -- commissioning records ---------------------------------------------

    def create_commissioning_record(
        self, project_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/fit-out-projects/{project_id}/commissioning-records", payload, headers
        )

    def list_project_commissioning_records(
        self, project_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/fit-out-projects/{project_id}/commissioning-records",
            headers=headers,
            params=params,
        )

    def get_commissioning_record(self, record_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/commissioning-records/{record_id}", headers=headers)

    def list_commissioning_records(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/commissioning-records", headers=headers, params=params)

    def record_commissioning_result(
        self, record_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/commissioning-records/{record_id}/result", payload, headers
        )


api_client = ApiClient()
