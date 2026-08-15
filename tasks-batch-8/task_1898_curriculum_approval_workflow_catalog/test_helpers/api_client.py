"""API client: one method per endpoint defined in the PRD.

All paths live under the /curriculum prefix. Methods return the raw
requests.Response so tests can assert on status codes via the framework
validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (registrar-only test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/curriculum/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Departments
    # ------------------------------------------------------------------
    def create_department(self, payload, headers):
        return self._request("POST", "/curriculum/departments", payload, headers)

    # ------------------------------------------------------------------
    # Terms
    # ------------------------------------------------------------------
    def create_term(self, payload, headers):
        return self._request("POST", "/curriculum/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/curriculum/terms/{term_id}", headers=headers)

    def patch_term(self, term_id, payload, headers):
        return self._request("PATCH", f"/curriculum/terms/{term_id}", payload, headers)

    def freeze_proposals(self, term_id, headers):
        return self._request("POST", f"/curriculum/terms/{term_id}/freeze-proposals",
                             {}, headers)

    def freeze_catalog(self, term_id, headers):
        return self._request("POST", f"/curriculum/terms/{term_id}/freeze-catalog",
                             {}, headers)

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------
    def create_course(self, payload, headers):
        return self._request("POST", "/curriculum/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/curriculum/courses", headers=headers,
                             params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/curriculum/courses/{course_id}",
                             headers=headers)

    def list_course_requisites(self, course_id, headers, params=None):
        return self._request("GET", f"/curriculum/courses/{course_id}/requisites",
                             headers=headers, params=params)

    def list_course_cross_listings(self, course_id, headers, params=None):
        return self._request("GET",
                             f"/curriculum/courses/{course_id}/cross-listings",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Proposals
    # ------------------------------------------------------------------
    def create_proposal(self, payload, headers):
        return self._request("POST", "/curriculum/proposals", payload, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/curriculum/proposals", headers=headers,
                             params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/curriculum/proposals/{proposal_id}",
                             headers=headers)

    def update_proposal(self, proposal_id, payload, headers):
        return self._request("PUT", f"/curriculum/proposals/{proposal_id}",
                             payload, headers)

    def submit_proposal(self, proposal_id, headers):
        return self._request("POST", f"/curriculum/proposals/{proposal_id}/submit",
                             {}, headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST",
                             f"/curriculum/proposals/{proposal_id}/withdraw",
                             {}, headers)

    def post_decision(self, proposal_id, payload, headers):
        return self._request("POST",
                             f"/curriculum/proposals/{proposal_id}/decisions",
                             payload, headers)

    def list_decisions(self, proposal_id, headers, params=None):
        return self._request("GET",
                             f"/curriculum/proposals/{proposal_id}/decisions",
                             headers=headers, params=params)

    def list_proposal_requisites(self, proposal_id, headers, params=None):
        return self._request("GET",
                             f"/curriculum/proposals/{proposal_id}/requisites",
                             headers=headers, params=params)

    def activate_proposal(self, proposal_id, headers):
        return self._request("POST",
                             f"/curriculum/proposals/{proposal_id}/activate",
                             {}, headers)

    def create_teach_out_plan(self, proposal_id, payload, headers):
        return self._request("POST",
                             f"/curriculum/proposals/{proposal_id}/teach-out-plan",
                             payload, headers)

    # ------------------------------------------------------------------
    # Teach-out plans
    # ------------------------------------------------------------------
    def list_teach_out_plans(self, headers, params=None):
        return self._request("GET", "/curriculum/teach-out-plans", headers=headers,
                             params=params)

    def get_teach_out_plan(self, plan_id, headers):
        return self._request("GET", f"/curriculum/teach-out-plans/{plan_id}",
                             headers=headers)

    def commit_teach_out_plan(self, plan_id, headers):
        return self._request("POST",
                             f"/curriculum/teach-out-plans/{plan_id}/commit",
                             {}, headers)

    def complete_teach_out_plan(self, plan_id, headers):
        return self._request("POST",
                             f"/curriculum/teach-out-plans/{plan_id}/complete",
                             {}, headers)

    # ------------------------------------------------------------------
    # Cross-listings
    # ------------------------------------------------------------------
    def create_cross_listing(self, payload, headers):
        return self._request("POST", "/curriculum/cross-listings", payload, headers)

    def approve_cross_listing(self, listing_id, headers):
        return self._request("POST",
                             f"/curriculum/cross-listings/{listing_id}/approve",
                             {}, headers)

    def reject_cross_listing(self, listing_id, payload, headers):
        return self._request("POST",
                             f"/curriculum/cross-listings/{listing_id}/reject",
                             payload, headers)

    def rescind_cross_listing(self, listing_id, headers):
        return self._request("POST",
                             f"/curriculum/cross-listings/{listing_id}/rescind",
                             {}, headers)

    # ------------------------------------------------------------------
    # Catalog editions and entries
    # ------------------------------------------------------------------
    def create_edition(self, payload, headers):
        return self._request("POST", "/curriculum/editions", payload, headers)

    def freeze_edition(self, edition_id, headers):
        return self._request("POST", f"/curriculum/editions/{edition_id}/freeze",
                             {}, headers)

    def publish_edition(self, edition_id, headers):
        return self._request("POST", f"/curriculum/editions/{edition_id}/publish",
                             {}, headers)

    def list_catalog_entries(self, headers, params=None):
        return self._request("GET", "/curriculum/catalog-entries", headers=headers,
                             params=params)

    def get_catalog_entry(self, entry_id, headers):
        return self._request("GET", f"/curriculum/catalog-entries/{entry_id}",
                             headers=headers)


api_client = ApiClient()
