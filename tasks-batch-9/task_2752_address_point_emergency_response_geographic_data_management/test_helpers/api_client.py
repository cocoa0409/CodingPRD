"""Typed HTTP client: one method per endpoint of the GIS API.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies. All paths are mounted under ``/gis``.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint methods for the County Address and Emergency Response GIS API."""

    BASE = "/gis"

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Headers = None):
        return self._request(
            "POST",
            f"{self.BASE}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock_raw(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.BASE}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.BASE}/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/jurisdictions/{jurisdiction_id}", None, headers
        )

    def list_jurisdictions(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{self.BASE}/jurisdictions", params, headers)

    # ------------------------------------------------------------------
    # Agencies
    # ------------------------------------------------------------------
    def create_agency(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.BASE}/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: Headers = None):
        return self._request("GET", f"{self.BASE}/agencies/{agency_id}", None, headers)

    def list_agencies(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{self.BASE}/agencies", params, headers)

    def suspend_agency(
        self, agency_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"{self.BASE}/agencies/{agency_id}/suspend", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Coverage cells
    # ------------------------------------------------------------------
    def create_coverage_cell(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.BASE}/coverage-cells", payload, headers)

    def get_coverage_cell(self, cell_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/coverage-cells/{cell_id}", None, headers
        )

    def list_coverage_cells(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{self.BASE}/coverage-cells", params, headers)

    def get_coverage_status(self, cell_id: str, headers: Headers = None):
        return self._request(
            "GET",
            f"{self.BASE}/coverage-cells/{cell_id}/coverage-status",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Road centerlines
    # ------------------------------------------------------------------
    def create_road_centerline(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.BASE}/road-centerlines", payload, headers)

    def get_road_centerline(self, road_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/road-centerlines/{road_id}", None, headers
        )

    def list_road_centerlines(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{self.BASE}/road-centerlines", params, headers)

    def patch_road_centerline(
        self, road_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "PATCH", f"{self.BASE}/road-centerlines/{road_id}", payload, headers
        )

    def validate_road_centerline(
        self, road_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/road-centerlines/{road_id}/validate",
            payload or {},
            headers,
        )

    def publish_road_centerline(
        self, road_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/road-centerlines/{road_id}/publish",
            payload or {},
            headers,
        )

    def retire_road_centerline(
        self, road_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/road-centerlines/{road_id}/retire",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Address points
    # ------------------------------------------------------------------
    def create_address_point(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.BASE}/address-points", payload, headers)

    def get_address_point(self, point_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/address-points/{point_id}", None, headers
        )

    def list_address_points(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{self.BASE}/address-points", params, headers)

    def activate_address_point(
        self, point_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/address-points/{point_id}/activate",
            payload or {},
            headers,
        )

    def retire_address_point(
        self, point_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/address-points/{point_id}/retire",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Address assignment requests
    # ------------------------------------------------------------------
    def create_assignment_request(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.BASE}/address-assignment-requests", payload, headers
        )

    def get_assignment_request(self, request_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/address-assignment-requests/{request_id}", None, headers
        )

    def list_assignment_requests(self, params: Payload = None, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/address-assignment-requests", params, headers
        )

    def gis_review_assignment_request(
        self, request_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/address-assignment-requests/{request_id}/gis-review",
            payload,
            headers,
        )

    def utility_clearance_assignment_request(
        self, request_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/address-assignment-requests/{request_id}/utility-clearance",
            payload,
            headers,
        )

    def assign_assignment_request(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/address-assignment-requests/{request_id}/assign",
            payload or {},
            headers,
        )

    def void_assignment_request(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/address-assignment-requests/{request_id}/void",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Emergency service boundaries
    # ------------------------------------------------------------------
    def create_boundary(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.BASE}/emergency-service-boundaries", payload, headers
        )

    def get_boundary(self, boundary_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/emergency-service-boundaries/{boundary_id}", None, headers
        )

    def list_boundaries(self, params: Payload = None, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/emergency-service-boundaries", params, headers
        )

    def create_cell_assignment(
        self, boundary_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/emergency-service-boundaries/{boundary_id}/cell-assignments",
            payload,
            headers,
        )

    def list_boundary_cell_assignments_of(
        self, boundary_id: str, params: Payload = None, headers: Headers = None
    ):
        return self._request(
            "GET",
            f"{self.BASE}/emergency-service-boundaries/{boundary_id}/cell-assignments",
            params,
            headers,
        )

    def propose_boundary(
        self, boundary_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/emergency-service-boundaries/{boundary_id}/propose",
            payload or {},
            headers,
        )

    def activate_boundary(
        self, boundary_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/emergency-service-boundaries/{boundary_id}/activate",
            payload or {},
            headers,
        )

    def retire_boundary(
        self, boundary_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/emergency-service-boundaries/{boundary_id}/retire",
            payload or {},
            headers,
        )

    def get_cell_assignment(self, assignment_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/boundary-cell-assignments/{assignment_id}", None, headers
        )

    def list_cell_assignments(self, params: Payload = None, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/boundary-cell-assignments", params, headers
        )

    # ------------------------------------------------------------------
    # QC validation reports and defects
    # ------------------------------------------------------------------
    def create_qc_report(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.BASE}/qc-validation-reports", payload, headers
        )

    def get_qc_report(self, report_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/qc-validation-reports/{report_id}", None, headers
        )

    def list_qc_reports(self, params: Payload = None, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/qc-validation-reports", params, headers
        )

    def list_qc_report_defects(
        self, report_id: str, params: Payload = None, headers: Headers = None
    ):
        return self._request(
            "GET",
            f"{self.BASE}/qc-validation-reports/{report_id}/defects",
            params,
            headers,
        )

    def get_qc_defect(self, defect_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/qc-defects/{defect_id}", None, headers
        )

    def waive_qc_defect(
        self, defect_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"{self.BASE}/qc-defects/{defect_id}/waive", payload or {}, headers
        )

    def certify_qc_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/qc-validation-reports/{report_id}/certify",
            payload or {},
            headers,
        )

    def reject_qc_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/qc-validation-reports/{report_id}/reject",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Provisioning packages
    # ------------------------------------------------------------------
    def create_package(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.BASE}/provisioning-packages", payload, headers
        )

    def get_package(self, package_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/provisioning-packages/{package_id}", None, headers
        )

    def list_packages(self, params: Payload = None, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/provisioning-packages", params, headers
        )

    def list_package_records(
        self, package_id: str, params: Payload = None, headers: Headers = None
    ):
        return self._request(
            "GET",
            f"{self.BASE}/provisioning-packages/{package_id}/records",
            params,
            headers,
        )

    def seal_package(
        self, package_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/provisioning-packages/{package_id}/seal",
            payload or {},
            headers,
        )

    def publish_package(
        self, package_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/provisioning-packages/{package_id}/publish",
            payload or {},
            headers,
        )

    def rollback_package(
        self, package_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/provisioning-packages/{package_id}/rollback",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Discrepancy cases and proposals
    # ------------------------------------------------------------------
    def create_discrepancy_case(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.BASE}/discrepancy-cases", payload, headers)

    def get_discrepancy_case(self, case_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.BASE}/discrepancy-cases/{case_id}", None, headers
        )

    def list_discrepancy_cases(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{self.BASE}/discrepancy-cases", params, headers)

    def create_proposal(self, case_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.BASE}/discrepancy-cases/{case_id}/proposals", payload, headers
        )

    def list_proposals(
        self, case_id: str, params: Payload = None, headers: Headers = None
    ):
        return self._request(
            "GET", f"{self.BASE}/discrepancy-cases/{case_id}/proposals", params, headers
        )

    def concur_discrepancy_case(
        self, case_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{self.BASE}/discrepancy-cases/{case_id}/concur", payload, headers
        )

    def adopt_discrepancy_case(
        self, case_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/discrepancy-cases/{case_id}/adopt",
            payload or {},
            headers,
        )

    def arbitrate_discrepancy_case(
        self, case_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.BASE}/discrepancy-cases/{case_id}/arbitrate",
            payload,
            headers,
        )


# Module-level singleton used by the pytest ``api`` fixture.
api_client = ApiClient()
