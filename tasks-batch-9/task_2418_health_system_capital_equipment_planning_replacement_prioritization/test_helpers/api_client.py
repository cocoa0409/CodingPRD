"""API client: one method per endpoint defined in the PRD.

The API is mounted under ``/capital``, with the administrative logical-clock
capability mounted at the root.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Administrative logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/capital/facilities", payload, headers)

    def patch_facility(self, facility_id, payload, headers):
        return self._request("PATCH", f"/capital/facilities/{facility_id}", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/capital/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/capital/facilities", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Departments
    # ------------------------------------------------------------------
    def create_department(self, payload, headers):
        return self._request("POST", "/capital/departments", payload, headers)

    def patch_department(self, department_id, payload, headers):
        return self._request("PATCH", f"/capital/departments/{department_id}", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/capital/departments/{department_id}", headers=headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/capital/departments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Capital cycles
    # ------------------------------------------------------------------
    def create_cycle(self, payload, headers):
        return self._request("POST", "/capital/cycles", payload, headers)

    def patch_cycle(self, cycle_id, payload, headers):
        return self._request("PATCH", f"/capital/cycles/{cycle_id}", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/capital/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/capital/cycles", headers=headers, params=params)

    def open_intake(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/capital/cycles/{cycle_id}/open-intake", payload, headers)

    def close_intake(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/capital/cycles/{cycle_id}/close-intake", payload, headers)

    def score_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/capital/cycles/{cycle_id}/score", payload, headers)

    def allocate_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/capital/cycles/{cycle_id}/allocate", payload, headers)

    def commit_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/capital/cycles/{cycle_id}/commit", payload, headers)

    # ------------------------------------------------------------------
    # Facility allocations
    # ------------------------------------------------------------------
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/capital/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/capital/allocations", headers=headers, params=params)

    def release_contingency(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/capital/allocations/{allocation_id}/release-contingency", payload, headers
        )

    # ------------------------------------------------------------------
    # Equipment assets and service history
    # ------------------------------------------------------------------
    def create_asset(self, payload, headers):
        return self._request("POST", "/capital/assets", payload, headers)

    def patch_asset(self, asset_id, payload, headers):
        return self._request("PATCH", f"/capital/assets/{asset_id}", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/capital/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/capital/assets", headers=headers, params=params)

    def create_service_event(self, asset_id, payload, headers):
        return self._request("POST", f"/capital/assets/{asset_id}/service-events", payload, headers)

    def list_service_events(self, asset_id, headers, params=None):
        return self._request(
            "GET", f"/capital/assets/{asset_id}/service-events", headers=headers, params=params
        )

    def decommission_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/capital/assets/{asset_id}/decommission", payload, headers)

    # ------------------------------------------------------------------
    # Replacement requests
    # ------------------------------------------------------------------
    def create_request(self, payload, headers):
        return self._request("POST", "/capital/requests", payload, headers)

    def patch_request(self, request_id, payload, headers):
        return self._request("PATCH", f"/capital/requests/{request_id}", payload, headers)

    def get_request(self, request_id, headers):
        return self._request("GET", f"/capital/requests/{request_id}", headers=headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", "/capital/requests", headers=headers, params=params)

    def submit_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/capital/requests/{request_id}/submit", payload, headers)

    def screen_request(self, request_id, payload, headers):
        return self._request("POST", f"/capital/requests/{request_id}/screen", payload, headers)

    def withdraw_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/capital/requests/{request_id}/withdraw", payload, headers)

    def list_request_scores(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/capital/requests/{request_id}/scores", headers=headers, params=params
        )

    def create_vote(self, request_id, payload, headers):
        return self._request("POST", f"/capital/requests/{request_id}/votes", payload, headers)

    def list_request_votes(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/capital/requests/{request_id}/votes", headers=headers, params=params
        )

    def committee_decision(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/capital/requests/{request_id}/committee-decision", payload, headers
        )

    def fund_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/capital/requests/{request_id}/fund", payload, headers)

    def withdraw_funding(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/capital/requests/{request_id}/withdraw-funding", payload, headers
        )

    # ------------------------------------------------------------------
    # Committee members
    # ------------------------------------------------------------------
    def create_committee_member(self, payload, headers):
        return self._request("POST", "/capital/committee-members", payload, headers)

    def patch_committee_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/capital/committee-members/{member_id}", payload, headers)

    def get_committee_member(self, member_id, headers):
        return self._request("GET", f"/capital/committee-members/{member_id}", headers=headers)

    def list_committee_members(self, headers, params=None):
        return self._request("GET", "/capital/committee-members", headers=headers, params=params)

    def list_member_votes(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/capital/committee-members/{member_id}/votes", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Group purchasing contracts
    # ------------------------------------------------------------------
    def create_gpo_contract(self, payload, headers):
        return self._request("POST", "/capital/gpo-contracts", payload, headers)

    def patch_gpo_contract(self, contract_id, payload, headers):
        return self._request("PATCH", f"/capital/gpo-contracts/{contract_id}", payload, headers)

    def get_gpo_contract(self, contract_id, headers):
        return self._request("GET", f"/capital/gpo-contracts/{contract_id}", headers=headers)

    def list_gpo_contracts(self, headers, params=None):
        return self._request("GET", "/capital/gpo-contracts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Vendor quotes
    # ------------------------------------------------------------------
    def create_quote(self, request_id, payload, headers):
        return self._request("POST", f"/capital/requests/{request_id}/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/capital/vendor-quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/capital/vendor-quotes", headers=headers, params=params)

    def counter_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/capital/vendor-quotes/{quote_id}/counter", payload, headers)

    def revise_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/capital/vendor-quotes/{quote_id}/revise", payload, headers)

    def accept_quote(self, quote_id, headers, payload=None):
        return self._request("POST", f"/capital/vendor-quotes/{quote_id}/accept", payload, headers)

    def withdraw_quote(self, quote_id, headers, payload=None):
        return self._request("POST", f"/capital/vendor-quotes/{quote_id}/withdraw", payload, headers)

    # ------------------------------------------------------------------
    # Installation projects
    # ------------------------------------------------------------------
    def create_installation_project(self, request_id, payload, headers):
        return self._request(
            "POST", f"/capital/requests/{request_id}/installation-projects", payload, headers
        )

    def patch_installation_project(self, project_id, payload, headers):
        return self._request(
            "PATCH", f"/capital/installation-projects/{project_id}", payload, headers
        )

    def get_installation_project(self, project_id, headers):
        return self._request(
            "GET", f"/capital/installation-projects/{project_id}", headers=headers
        )

    def list_installation_projects(self, headers, params=None):
        return self._request(
            "GET", "/capital/installation-projects", headers=headers, params=params
        )

    def advance_construction(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/capital/installation-projects/{project_id}/advance-construction",
            payload, headers,
        )

    def advance_equipment(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/capital/installation-projects/{project_id}/advance-equipment",
            payload, headers,
        )

    def go_live_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/capital/installation-projects/{project_id}/go-live", payload, headers
        )

    def cancel_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/capital/installation-projects/{project_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Utilization audits
    # ------------------------------------------------------------------
    def create_audit(self, request_id, payload, headers):
        return self._request("POST", f"/capital/requests/{request_id}/audits", payload, headers)

    def collect_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/capital/audits/{audit_id}/collect", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/capital/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/capital/audits", headers=headers, params=params)


api_client = ApiClient()
