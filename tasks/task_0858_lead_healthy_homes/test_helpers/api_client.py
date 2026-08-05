"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Child ----
    def create_child(self, payload, headers):
        return self._request("POST", "/api/v1/children", payload, headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/api/v1/children", headers=headers, params=params)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/api/v1/children/{child_id}", headers=headers)

    def list_child_blood_lead_tests(self, child_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/children/{child_id}/blood-lead-tests",
            headers=headers, params=params,
        )

    # ---- BloodLeadTest ----
    def create_blood_lead_test(self, payload, headers):
        return self._request("POST", "/api/v1/blood-lead-tests", payload, headers)

    # ---- Dwelling ----
    def create_dwelling(self, payload, headers):
        return self._request("POST", "/api/v1/dwellings", payload, headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/api/v1/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/v1/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/v1/cases", headers=headers, params=params)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/api/v1/cases/{case_id}/withdraw", {}, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/api/v1/cases/{case_id}/close", {}, headers)

    # ---- Inspector ----
    def create_inspector(self, payload, headers):
        return self._request("POST", "/api/v1/inspectors", payload, headers)

    # ---- EnvironmentalInvestigation ----
    def create_investigation(self, payload, headers):
        return self._request("POST", "/api/v1/investigations", payload, headers)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET", f"/api/v1/investigations/{investigation_id}", headers=headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", "/api/v1/investigations", headers=headers, params=params)

    def list_investigation_hazard_findings(self, investigation_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/investigations/{investigation_id}/hazard-findings",
            headers=headers, params=params,
        )

    def create_finding(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/investigations/{investigation_id}/findings", payload, headers,
        )

    def complete_investigation(self, investigation_id, headers):
        return self._request(
            "POST", f"/api/v1/investigations/{investigation_id}/complete", {}, headers,
        )

    # ---- HazardControlOrder ----
    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/v1/hazard-control-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/v1/hazard-control-orders", headers=headers, params=params)

    def list_order_clearance_tests(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/v1/hazard-control-orders/{order_id}/clearance-tests",
            headers=headers, params=params,
        )

    def request_clearance(self, order_id, headers):
        return self._request(
            "POST", f"/api/v1/hazard-control-orders/{order_id}/request-clearance", {}, headers,
        )

    def void_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/v1/hazard-control-orders/{order_id}/void", {}, headers,
        )

    # ---- ClearanceTest ----
    def create_clearance_test(self, payload, headers):
        return self._request("POST", "/api/v1/clearance-tests", payload, headers)

    # ---- RelocationUnit ----
    def create_relocation_unit(self, payload, headers):
        return self._request("POST", "/api/v1/relocation-units", payload, headers)

    # ---- RelocationPlacement ----
    def create_relocation_placement(self, payload, headers):
        return self._request("POST", "/api/v1/relocation-placements", payload, headers)

    def get_relocation_placement(self, placement_id, headers):
        return self._request("GET", f"/api/v1/relocation-placements/{placement_id}", headers=headers)

    def list_relocation_placements(self, headers, params=None):
        return self._request("GET", "/api/v1/relocation-placements", headers=headers, params=params)

    def end_relocation_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/relocation-placements/{placement_id}/end", payload, headers,
        )

    # ---- Contractor ----
    def create_contractor(self, payload, headers):
        return self._request("POST", "/api/v1/contractors", payload, headers)

    def contractor_certification(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/contractors/{contractor_id}/certification", payload, headers,
        )

    # ---- GrantFund ----
    def create_grant_fund(self, payload, headers):
        return self._request("POST", "/api/v1/grant-funds", payload, headers)

    def get_grant_fund(self, grant_fund_id, headers):
        return self._request("GET", f"/api/v1/grant-funds/{grant_fund_id}", headers=headers)

    # ---- RemediationProject ----
    def create_remediation_project(self, payload, headers):
        return self._request("POST", "/api/v1/remediation-projects", payload, headers)

    def get_remediation_project(self, project_id, headers):
        return self._request("GET", f"/api/v1/remediation-projects/{project_id}", headers=headers)

    def list_remediation_projects(self, headers, params=None):
        return self._request("GET", "/api/v1/remediation-projects", headers=headers, params=params)

    def approve_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/remediation-projects/{project_id}/approve", payload, headers,
        )

    def start_project(self, project_id, headers):
        return self._request(
            "POST", f"/api/v1/remediation-projects/{project_id}/start", {}, headers,
        )

    def complete_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/remediation-projects/{project_id}/complete", payload, headers,
        )

    def cancel_project(self, project_id, headers):
        return self._request(
            "POST", f"/api/v1/remediation-projects/{project_id}/cancel", {}, headers,
        )

    # ---- Reporting ----
    def surveillance_report(self, headers, params=None):
        return self._request("GET", "/api/v1/reports/surveillance", headers=headers, params=params)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
