"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Facilities ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    # ---- Sources ----
    def create_source(self, payload, headers):
        return self._request("POST", "/sources", payload, headers)

    def get_source(self, source_id, headers):
        return self._request("GET", f"/sources/{source_id}", headers=headers)

    def list_facility_sources(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/sources", headers=headers, params=params)

    def permit_source(self, source_id, headers):
        return self._request("POST", f"/sources/{source_id}/permit", {}, headers)

    def start_operating_source(self, source_id, headers):
        return self._request("POST", f"/sources/{source_id}/start-operating", {}, headers)

    def shutdown_source(self, source_id, headers):
        return self._request("POST", f"/sources/{source_id}/shutdown", {}, headers)

    def create_cem_data(self, source_id, payload, headers):
        return self._request("POST", f"/sources/{source_id}/cem-data", payload, headers)

    def list_cem_data(self, source_id, headers, params=None):
        return self._request("GET", f"/sources/{source_id}/cem-data", headers=headers, params=params)

    def list_source_exceedances(self, source_id, headers, params=None):
        return self._request("GET", f"/sources/{source_id}/exceedances", headers=headers, params=params)

    def list_source_stack_tests(self, source_id, headers, params=None):
        return self._request("GET", f"/sources/{source_id}/stack-tests", headers=headers, params=params)

    # ---- Permits ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_facility_permits(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/submit", {}, headers)

    def begin_review_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/begin-review", {}, headers)

    def return_permit_for_revision(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/return-for-revision", {}, headers)

    def open_public_notice_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/open-public-notice", {}, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    def start_renewal_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/start-renewal", {}, headers)

    def complete_renewal_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/complete-renewal", {}, headers)

    # ---- Public notices ----
    def create_public_notice(self, payload, headers):
        return self._request("POST", "/public-notices", payload, headers)

    def get_public_notice(self, notice_id, headers):
        return self._request("GET", f"/public-notices/{notice_id}", headers=headers)

    def list_permit_public_notices(self, permit_id, headers, params=None):
        return self._request("GET", f"/permits/{permit_id}/public-notices", headers=headers, params=params)

    def comment_public_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/public-notices/{notice_id}/comment", payload, headers)

    def close_public_notice(self, notice_id, headers):
        return self._request("POST", f"/public-notices/{notice_id}/close", {}, headers)

    # ---- Inventories & line items ----
    def create_inventory(self, payload, headers):
        return self._request("POST", "/inventories", payload, headers)

    def get_inventory(self, inventory_id, headers):
        return self._request("GET", f"/inventories/{inventory_id}", headers=headers)

    def list_facility_inventories(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/inventories", headers=headers, params=params)

    def create_line_item(self, payload, headers):
        return self._request("POST", "/line-items", payload, headers)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    def submit_inventory(self, inventory_id, headers):
        return self._request("POST", f"/inventories/{inventory_id}/submit", {}, headers)

    def reject_inventory(self, inventory_id, headers):
        return self._request("POST", f"/inventories/{inventory_id}/reject", {}, headers)

    def certify_inventory(self, inventory_id, payload, headers):
        return self._request("POST", f"/inventories/{inventory_id}/certify", payload, headers)

    def amend_inventory(self, inventory_id, headers):
        return self._request("POST", f"/inventories/{inventory_id}/amend", {}, headers)

    # ---- Stack tests ----
    def create_stack_test(self, payload, headers):
        return self._request("POST", "/stack-tests", payload, headers)

    def get_stack_test(self, stack_test_id, headers):
        return self._request("GET", f"/stack-tests/{stack_test_id}", headers=headers)

    def conduct_stack_test(self, stack_test_id, payload, headers):
        return self._request("POST", f"/stack-tests/{stack_test_id}/conduct", payload, headers)

    # ---- Exceedances ----
    def create_exceedance(self, payload, headers):
        return self._request("POST", "/exceedances", payload, headers)

    def get_exceedance(self, exceedance_id, headers):
        return self._request("GET", f"/exceedances/{exceedance_id}", headers=headers)

    def report_exceedance(self, exceedance_id, headers):
        return self._request("POST", f"/exceedances/{exceedance_id}/report", {}, headers)

    def resolve_exceedance(self, exceedance_id, headers):
        return self._request("POST", f"/exceedances/{exceedance_id}/resolve", {}, headers)

    # ---- Complaints & inspections ----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_facility_complaints(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/complaints", headers=headers, params=params)

    def dismiss_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/dismiss", {}, headers)

    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_facility_inspections(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/inspections", headers=headers, params=params)

    def list_complaint_inspections(self, complaint_id, headers, params=None):
        return self._request("GET", f"/complaints/{complaint_id}/inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/complete", payload, headers)

    # ---- Enforcement ----
    def create_enforcement_action(self, payload, headers):
        return self._request("POST", "/enforcement-actions", payload, headers)

    def get_enforcement_action(self, action_id, headers):
        return self._request("GET", f"/enforcement-actions/{action_id}", headers=headers)

    def list_facility_enforcement_actions(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/enforcement-actions", headers=headers, params=params)

    def assess_penalty(self, action_id, headers):
        return self._request("POST", f"/enforcement-actions/{action_id}/assess-penalty", {}, headers)

    def grant_variance(self, action_id, payload, headers):
        return self._request("POST", f"/enforcement-actions/{action_id}/grant-variance", payload, headers)

    def dismiss_enforcement_action(self, action_id, headers):
        return self._request("POST", f"/enforcement-actions/{action_id}/dismiss", {}, headers)

    def pay_enforcement_action(self, action_id, headers):
        return self._request("POST", f"/enforcement-actions/{action_id}/pay", {}, headers)

    def close_enforcement_action(self, action_id, headers):
        return self._request("POST", f"/enforcement-actions/{action_id}/close", {}, headers)

    # ---- Test-driving logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
