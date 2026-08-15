"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/fca/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/fca/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/fca/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/fca/clients/{client_id}", headers=headers)

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/fca/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/fca/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/fca/facilities/{facility_id}", headers=headers)

    def get_refresh_health(self, facility_id, headers):
        return self._request("GET", f"/fca/facilities/{facility_id}/refresh-health",
                             headers=headers)

    def recompute_facility(self, facility_id, headers):
        return self._request("POST", f"/fca/facilities/{facility_id}/recompute",
                             {}, headers)

    def list_facility_asset_systems(self, facility_id, headers, params=None):
        return self._request("GET", f"/fca/facilities/{facility_id}/asset-systems",
                             headers=headers, params=params)

    def list_facility_capital_plans(self, facility_id, headers, params=None):
        return self._request("GET", f"/fca/facilities/{facility_id}/capital-plans",
                             headers=headers, params=params)

    def list_facility_refresh_cycles(self, facility_id, headers, params=None):
        return self._request("GET", f"/fca/facilities/{facility_id}/refresh-cycles",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Asset systems
    # ------------------------------------------------------------------
    def create_asset_system(self, payload, headers):
        return self._request("POST", "/fca/asset-systems", payload, headers)

    def list_asset_systems(self, headers, params=None):
        return self._request("GET", "/fca/asset-systems", headers=headers, params=params)

    def get_asset_system(self, system_id, headers):
        return self._request("GET", f"/fca/asset-systems/{system_id}", headers=headers)

    def assess_asset_system(self, system_id, payload, headers):
        return self._request("POST", f"/fca/asset-systems/{system_id}/assess",
                             payload, headers)

    def accept_assessment(self, system_id, headers):
        return self._request("POST", f"/fca/asset-systems/{system_id}/accept-assessment",
                             {}, headers)

    def reject_assessment(self, system_id, headers):
        return self._request("POST", f"/fca/asset-systems/{system_id}/reject-assessment",
                             {}, headers)

    def retire_asset_system(self, system_id, headers):
        return self._request("POST", f"/fca/asset-systems/{system_id}/retire",
                             {}, headers)

    def list_system_deficiencies(self, system_id, headers, params=None):
        return self._request("GET", f"/fca/asset-systems/{system_id}/deficiencies",
                             headers=headers, params=params)

    def list_system_snapshots(self, system_id, headers, params=None):
        return self._request("GET",
                             f"/fca/asset-systems/{system_id}/condition-snapshots",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Deficiencies
    # ------------------------------------------------------------------
    def create_deficiency(self, payload, headers):
        return self._request("POST", "/fca/deficiencies", payload, headers)

    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/fca/deficiencies", headers=headers, params=params)

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/fca/deficiencies/{deficiency_id}",
                             headers=headers)

    def start_remediation(self, deficiency_id, headers):
        return self._request("POST",
                             f"/fca/deficiencies/{deficiency_id}/start-remediation",
                             {}, headers)

    def complete_remediation(self, deficiency_id, headers):
        return self._request("POST",
                             f"/fca/deficiencies/{deficiency_id}/complete-remediation",
                             {}, headers)

    def defer_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"/fca/deficiencies/{deficiency_id}/defer",
                             {}, headers)

    def reopen_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"/fca/deficiencies/{deficiency_id}/reopen",
                             {}, headers)

    def verify_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"/fca/deficiencies/{deficiency_id}/verify",
                             {}, headers)

    def reject_verification(self, deficiency_id, headers):
        return self._request("POST",
                             f"/fca/deficiencies/{deficiency_id}/reject-verification",
                             {}, headers)

    # ------------------------------------------------------------------
    # Capital plans
    # ------------------------------------------------------------------
    def create_capital_plan(self, payload, headers):
        return self._request("POST", "/fca/capital-plans", payload, headers)

    def list_capital_plans(self, headers, params=None):
        return self._request("GET", "/fca/capital-plans", headers=headers,
                             params=params)

    def get_capital_plan(self, plan_id, headers):
        return self._request("GET", f"/fca/capital-plans/{plan_id}", headers=headers)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/fca/capital-plans/{plan_id}/submit",
                             {}, headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/fca/capital-plans/{plan_id}/approve",
                             {}, headers)

    def reject_plan(self, plan_id, headers):
        return self._request("POST", f"/fca/capital-plans/{plan_id}/reject",
                             {}, headers)

    def revise_plan(self, plan_id, headers):
        return self._request("POST", f"/fca/capital-plans/{plan_id}/revise",
                             {}, headers)

    def archive_plan(self, plan_id, headers):
        return self._request("POST", f"/fca/capital-plans/{plan_id}/archive",
                             {}, headers)

    def list_plan_scenarios(self, plan_id, headers, params=None):
        return self._request("GET", f"/fca/capital-plans/{plan_id}/funding-scenarios",
                             headers=headers, params=params)

    def list_plan_line_items(self, plan_id, headers, params=None):
        return self._request("GET", f"/fca/capital-plans/{plan_id}/plan-line-items",
                             headers=headers, params=params)

    def list_plan_bundles(self, plan_id, headers, params=None):
        return self._request("GET", f"/fca/capital-plans/{plan_id}/project-bundles",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Funding scenarios
    # ------------------------------------------------------------------
    def create_funding_scenario(self, payload, headers):
        return self._request("POST", "/fca/funding-scenarios", payload, headers)

    def get_funding_scenario(self, scenario_id, headers):
        return self._request("GET", f"/fca/funding-scenarios/{scenario_id}",
                             headers=headers)

    def run_funding_scenario(self, scenario_id, payload, headers):
        return self._request("POST", f"/fca/funding-scenarios/{scenario_id}/run",
                             payload, headers)

    # ------------------------------------------------------------------
    # Plan line items
    # ------------------------------------------------------------------
    def list_line_items(self, headers, params=None):
        return self._request("GET", "/fca/plan-line-items", headers=headers,
                             params=params)

    def get_line_item(self, item_id, headers):
        return self._request("GET", f"/fca/plan-line-items/{item_id}", headers=headers)

    # ------------------------------------------------------------------
    # Project bundles
    # ------------------------------------------------------------------
    def create_project_bundle(self, payload, headers):
        return self._request("POST", "/fca/project-bundles", payload, headers)

    def attach_line_item(self, bundle_id, payload, headers):
        return self._request("POST", f"/fca/project-bundles/{bundle_id}/attach",
                             payload, headers)

    def get_project_bundle(self, bundle_id, headers):
        return self._request("GET", f"/fca/project-bundles/{bundle_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Refresh cycles
    # ------------------------------------------------------------------
    def open_refresh_cycle(self, facility_id, headers):
        return self._request("POST", f"/fca/facilities/{facility_id}/refresh-cycles",
                             {}, headers)

    def close_refresh_cycle(self, cycle_id, headers):
        return self._request("POST", f"/fca/refresh-cycles/{cycle_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Condition snapshots
    # ------------------------------------------------------------------
    def list_condition_snapshots(self, headers, params=None):
        return self._request("GET", "/fca/condition-snapshots", headers=headers,
                             params=params)


api_client = ApiClient()
