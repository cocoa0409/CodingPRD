"""API client: one method per endpoint defined in the LIHTC Compliance PRD (§4).

The flat topology means every entity is its own top-level collection; foreign keys travel
in request bodies and reverse relationships are discovered via filtered-list GETs.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Project ─────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def certify_set_aside(self, project_id, headers):
        return self._request(
            "POST", f"/projects/{project_id}/certify-set-aside", {}, headers
        )

    def begin_credit_period(self, project_id, headers):
        return self._request(
            "POST", f"/projects/{project_id}/begin-credit-period", {}, headers
        )

    def begin_compliance_period(self, project_id, headers):
        return self._request(
            "POST", f"/projects/{project_id}/begin-compliance-period", {}, headers
        )

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close", {}, headers)

    # ─── Building ────────────────────────────────────
    def create_building(self, payload, headers):
        return self._request("POST", "/buildings", payload, headers)

    def list_buildings(self, headers, params=None):
        return self._request("GET", "/buildings", headers=headers, params=params)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/buildings/{building_id}", headers=headers)

    def issue_form8609(self, building_id, payload, headers):
        return self._request(
            "POST", f"/buildings/{building_id}/form8609", payload, headers
        )

    def list_form8609s(self, headers, params=None):
        return self._request("GET", "/form8609s", headers=headers, params=params)

    def get_form8609(self, form_id, headers):
        return self._request("GET", f"/form8609s/{form_id}", headers=headers)

    def revoke_final(self, building_id, headers):
        return self._request(
            "POST", f"/buildings/{building_id}/revoke-final", {}, headers
        )

    def recapture(self, building_id, payload, headers):
        return self._request(
            "POST", f"/buildings/{building_id}/recapture", payload, headers
        )

    # ─── Unit ────────────────────────────────────────
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def lease_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/lease", payload, headers)

    def disqualify_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/disqualify", payload, headers)

    # ─── Lease ───────────────────────────────────────
    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    # ─── Household ───────────────────────────────────
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    # ─── Certification ───────────────────────────────
    def create_certification(self, payload, headers):
        return self._request("POST", "/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/certifications/{cert_id}", headers=headers)

    def submit_certification(self, cert_id, headers):
        return self._request(
            "POST", f"/certifications/{cert_id}/submit", {}, headers
        )

    def revise_certification(self, cert_id, headers):
        return self._request(
            "POST", f"/certifications/{cert_id}/revise", {}, headers
        )

    def approve_certification(self, cert_id, payload, headers):
        return self._request(
            "POST", f"/certifications/{cert_id}/approve", payload, headers
        )

    # ─── Inspection ──────────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def conduct_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/conduct", {}, headers
        )

    def close_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/close", {}, headers
        )

    # ─── Finding ─────────────────────────────────────
    def list_findings(self, headers, params=None):
        return self._request("GET", "/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/findings/{finding_id}", headers=headers)

    def report_finding(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/report", {}, headers)

    def correct_finding(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/correct", {}, headers)


api_client = ApiClient()
