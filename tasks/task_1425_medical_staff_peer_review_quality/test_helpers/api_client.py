"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/peer-review/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/peer-review/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/peer-review/providers/{provider_id}", headers=headers)

    def list_provider_cases(self, provider_id, headers, params=None):
        return self._request("GET", f"/peer-review/providers/{provider_id}/cases",
                             headers=headers, params=params)

    def list_provider_conflict_declarations(self, provider_id, headers, params=None):
        return self._request("GET", f"/peer-review/providers/{provider_id}/conflict-declarations",
                             headers=headers, params=params)

    def list_provider_focused_reviews(self, provider_id, headers, params=None):
        return self._request("GET", f"/peer-review/providers/{provider_id}/focused-reviews",
                             headers=headers, params=params)

    def get_provider_quality_trend(self, provider_id, headers):
        return self._request("GET", f"/peer-review/providers/{provider_id}/quality-trend",
                             headers=headers)

    # --- Committee members ---
    def create_committee_member(self, payload, headers):
        return self._request("POST", "/peer-review/committee-members", payload, headers)

    def list_committee_members(self, headers, params=None):
        return self._request("GET", "/peer-review/committee-members", headers=headers, params=params)

    def get_committee_member(self, member_id, headers):
        return self._request("GET", f"/peer-review/committee-members/{member_id}", headers=headers)

    def deactivate_committee_member(self, member_id, headers):
        return self._request("POST", f"/peer-review/committee-members/{member_id}/deactivate",
                             headers=headers)

    def activate_committee_member(self, member_id, headers):
        return self._request("POST", f"/peer-review/committee-members/{member_id}/activate",
                             headers=headers)

    def create_conflict_declaration(self, member_id, payload, headers):
        return self._request("POST",
                             f"/peer-review/committee-members/{member_id}/conflict-declarations",
                             payload, headers)

    def list_member_conflict_declarations(self, member_id, headers, params=None):
        return self._request("GET",
                             f"/peer-review/committee-members/{member_id}/conflict-declarations",
                             headers=headers, params=params)

    def delete_conflict_declaration(self, conflict_id, headers):
        return self._request("DELETE", f"/peer-review/conflict-declarations/{conflict_id}",
                             headers=headers)

    def list_member_assignments(self, member_id, headers, params=None):
        return self._request("GET", f"/peer-review/committee-members/{member_id}/assignments",
                             headers=headers, params=params)

    def list_member_notes(self, member_id, headers, params=None):
        return self._request("GET", f"/peer-review/committee-members/{member_id}/notes",
                             headers=headers, params=params)

    def list_member_focus_group_memberships(self, member_id, headers, params=None):
        return self._request("GET",
                             f"/peer-review/committee-members/{member_id}/focus-group-memberships",
                             headers=headers, params=params)

    # --- Review cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/peer-review/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/peer-review/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/peer-review/cases/{case_id}", headers=headers)

    def screen_case(self, case_id, payload, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/screen", payload, headers)

    def get_reviewer_candidates(self, case_id, headers, params=None):
        return self._request("GET", f"/peer-review/cases/{case_id}/reviewer-candidates",
                             headers=headers, params=params)

    def create_assignment(self, case_id, payload, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/assignments", payload, headers)

    def list_case_assignments(self, case_id, headers, params=None):
        return self._request("GET", f"/peer-review/cases/{case_id}/assignments",
                             headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/peer-review/assignments/{assignment_id}", headers=headers)

    def submit_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/peer-review/assignments/{assignment_id}/submit",
                             payload, headers)

    def revise_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/peer-review/assignments/{assignment_id}/revise",
                             payload, headers)

    def create_case_note(self, case_id, payload, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/notes", payload, headers)

    def list_case_notes(self, case_id, headers, params=None):
        return self._request("GET", f"/peer-review/cases/{case_id}/notes",
                             headers=headers, params=params)

    def get_case_deliberation(self, case_id, headers):
        return self._request("GET", f"/peer-review/cases/{case_id}/deliberation", headers=headers)

    def finalize_deliberation(self, case_id, payload, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/finalize-deliberation",
                             payload, headers)

    def list_case_notifications(self, case_id, headers):
        return self._request("GET", f"/peer-review/cases/{case_id}/notifications", headers=headers)

    def create_case_response(self, case_id, payload, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/response", payload, headers)

    def get_case_response(self, case_id, headers):
        return self._request("GET", f"/peer-review/cases/{case_id}/response", headers=headers)

    def committee_review(self, case_id, payload, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/committee-review",
                             payload, headers)

    def finalize_after_response(self, case_id, payload, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/finalize-after-response",
                             payload, headers)

    def close_no_response(self, case_id, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/close-no-response",
                             headers=headers)

    def refer_external(self, case_id, payload, headers):
        return self._request("POST", f"/peer-review/cases/{case_id}/refer-external",
                             payload, headers)

    def list_external_referrals(self, case_id, headers):
        return self._request("GET", f"/peer-review/cases/{case_id}/external-referrals",
                             headers=headers)

    # --- Focused reviews & focus groups ---
    def create_focused_review(self, payload, headers):
        return self._request("POST", "/peer-review/focused-reviews", payload, headers)

    def list_focused_reviews(self, headers, params=None):
        return self._request("GET", "/peer-review/focused-reviews", headers=headers, params=params)

    def get_focused_review(self, focus_id, headers):
        return self._request("GET", f"/peer-review/focused-reviews/{focus_id}", headers=headers)

    def close_focused_review(self, focus_id, payload, headers):
        return self._request("POST", f"/peer-review/focused-reviews/{focus_id}/close",
                             payload, headers)

    def create_focus_group(self, focus_id, payload, headers):
        return self._request("POST", f"/peer-review/focused-reviews/{focus_id}/focus-groups",
                             payload, headers)

    def list_focus_groups(self, focus_id, headers, params=None):
        return self._request("GET", f"/peer-review/focused-reviews/{focus_id}/focus-groups",
                             headers=headers, params=params)

    def get_focus_group(self, group_id, headers):
        return self._request("GET", f"/peer-review/focus-groups/{group_id}", headers=headers)

    def list_focus_group_cases(self, group_id, headers, params=None):
        return self._request("GET", f"/peer-review/focus-groups/{group_id}/cases",
                             headers=headers, params=params)

    def add_focus_group_member(self, group_id, payload, headers):
        return self._request("POST", f"/peer-review/focus-groups/{group_id}/members",
                             payload, headers)

    def list_focus_group_members(self, group_id, headers, params=None):
        return self._request("GET", f"/peer-review/focus-groups/{group_id}/members",
                             headers=headers, params=params)

    def remove_focus_group_member(self, group_id, member_id, headers):
        return self._request("DELETE",
                             f"/peer-review/focus-groups/{group_id}/members/{member_id}",
                             headers=headers)

    # --- Test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/peer-review/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
