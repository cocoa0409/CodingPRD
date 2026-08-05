"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Jurisdiction ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # --- CensusBlock ---
    def create_census_block(self, jurisdiction_id, payload, headers):
        return self._request("POST", f"/jurisdictions/{jurisdiction_id}/census-blocks", payload, headers)

    def get_census_block(self, census_block_id, headers):
        return self._request("GET", f"/census-blocks/{census_block_id}", headers=headers)

    def list_census_blocks(self, headers, params=None):
        return self._request("GET", "/census-blocks", headers=headers, params=params)

    # --- Precinct ---
    def create_precinct(self, jurisdiction_id, payload, headers):
        return self._request("POST", f"/jurisdictions/{jurisdiction_id}/precincts", payload, headers)

    def list_precincts(self, headers, params=None):
        return self._request("GET", "/precincts", headers=headers, params=params)

    def get_precinct(self, precinct_id, headers):
        return self._request("GET", f"/precincts/{precinct_id}", headers=headers)

    def split_precinct(self, precinct_id, payload, headers):
        return self._request("POST", f"/precincts/{precinct_id}/split", payload, headers)

    def merge_precinct(self, precinct_id, payload, headers):
        return self._request("POST", f"/precincts/{precinct_id}/merge", payload, headers)

    def retire_precinct(self, precinct_id, headers):
        return self._request("POST", f"/precincts/{precinct_id}/retire", {}, headers)

    def certify_precinct(self, precinct_id, headers):
        return self._request("POST", f"/precincts/{precinct_id}/certify", {}, headers)

    # --- Venue ---
    def create_venue(self, jurisdiction_id, payload, headers):
        return self._request("POST", f"/jurisdictions/{jurisdiction_id}/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    # --- PollingPlace ---
    def create_polling_place(self, jurisdiction_id, payload, headers):
        return self._request("POST", f"/jurisdictions/{jurisdiction_id}/polling-places", payload, headers)

    def get_polling_place(self, polling_place_id, headers):
        return self._request("GET", f"/polling-places/{polling_place_id}", headers=headers)

    def list_polling_places(self, headers, params=None):
        return self._request("GET", "/polling-places", headers=headers, params=params)

    def close_polling_place(self, polling_place_id, headers):
        return self._request("POST", f"/polling-places/{polling_place_id}/close", {}, headers)

    # --- PollingAssignment ---
    def create_polling_assignment(self, precinct_id, payload, headers):
        return self._request("POST", f"/precincts/{precinct_id}/polling-assignments", payload, headers)

    def get_polling_assignment(self, polling_assignment_id, headers):
        return self._request("GET", f"/polling-assignments/{polling_assignment_id}", headers=headers)

    def list_polling_assignments(self, headers, params=None):
        return self._request("GET", "/polling-assignments", headers=headers, params=params)

    # --- RedistrictingPlan ---
    def create_plan(self, jurisdiction_id, payload, headers):
        return self._request("POST", f"/jurisdictions/{jurisdiction_id}/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def get_comparison(self, plan_id, other_plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}/comparison", headers=headers,
                             params={"other_plan_id": other_plan_id})

    # --- District ---
    def create_district(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/districts", payload, headers)

    def list_districts(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/districts", headers=headers, params=params)

    # --- BlockAssignment ---
    def create_block_assignment(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/block-assignments", payload, headers)

    def get_block_assignment(self, block_assignment_id, headers):
        return self._request("GET", f"/block-assignments/{block_assignment_id}", headers=headers)

    def list_block_assignments(self, headers, params=None):
        return self._request("GET", "/block-assignments", headers=headers, params=params)

    def remove_block_assignment(self, block_assignment_id, headers):
        return self._request("POST", f"/block-assignments/{block_assignment_id}/remove", {}, headers)

    # --- ComplianceCheck ---
    def create_compliance_check(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/compliance-checks", payload, headers)

    def list_compliance_checks(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/compliance-checks", headers=headers, params=params)

    # --- Plan lifecycle ---
    def submit_review(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/submit-review", {}, headers)

    def open_comment(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/open-comment", {}, headers)

    def request_revision(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/request-revision", {}, headers)

    def reject_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/reject", {}, headers)

    def adopt_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/adopt", {}, headers)

    # --- Hearing ---
    def create_hearing(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def hold_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/hold", {}, headers)

    def cancel_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/cancel", {}, headers)

    # --- PublicComment ---
    def create_comment(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/comments", payload, headers)

    def list_comments(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/comments", headers=headers, params=params)

    def disposition_comment(self, comment_id, payload, headers):
        return self._request("POST", f"/comments/{comment_id}/disposition", payload, headers)

    # --- GISExport ---
    def create_export(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/exports", payload, headers)

    def list_exports(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/exports", headers=headers, params=params)


api_client = ApiClient()
