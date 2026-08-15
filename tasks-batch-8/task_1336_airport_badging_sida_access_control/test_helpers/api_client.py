"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sponsors ---
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/badging/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/badging/sponsors/{sponsor_id}", headers=headers)

    def suspend_sponsor(self, sponsor_id, payload, headers):
        return self._request("POST", f"/badging/sponsors/{sponsor_id}/suspend",
                             payload, headers)

    # --- Applicants ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/badging/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/badging/applicants/{applicant_id}", headers=headers)

    def list_sponsor_applicants(self, sponsor_id, headers, params=None):
        return self._request("GET", f"/badging/sponsors/{sponsor_id}/applicants",
                             headers=headers, params=params)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/badging/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/badging/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/badging/applications/{application_id}",
                             headers=headers)

    def record_chrc(self, application_id, payload, headers):
        return self._request("POST", f"/badging/applications/{application_id}/record-chrc",
                             payload, headers)

    def record_sta_result(self, application_id, payload, headers):
        return self._request("POST",
                             f"/badging/applications/{application_id}/record-sta-result",
                             payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/badging/applications/{application_id}/withdraw",
                             {}, headers)

    def issue_badge(self, application_id, payload, headers):
        return self._request("POST", f"/badging/applications/{application_id}/issue-badge",
                             payload, headers)

    # --- Training ---
    def create_training_completion(self, payload, headers):
        return self._request("POST", "/badging/training-completions", payload, headers)

    def list_training_completions(self, applicant_id, headers, params=None):
        return self._request("GET",
                             f"/badging/applicants/{applicant_id}/training-completions",
                             headers=headers, params=params)

    # --- Badges ---
    def list_badges(self, headers, params=None):
        return self._request("GET", "/badging/badges", headers=headers, params=params)

    def get_badge(self, badge_id, headers):
        return self._request("GET", f"/badging/badges/{badge_id}", headers=headers)

    def suspend_badge(self, badge_id, payload, headers):
        return self._request("POST", f"/badging/badges/{badge_id}/suspend",
                             payload, headers)

    def reinstate_badge(self, badge_id, headers):
        return self._request("POST", f"/badging/badges/{badge_id}/reinstate",
                             {}, headers)

    def report_lost(self, badge_id, payload, headers):
        return self._request("POST", f"/badging/badges/{badge_id}/report-lost",
                             payload, headers)

    def mark_returned(self, badge_id, headers):
        return self._request("POST", f"/badging/badges/{badge_id}/mark-returned",
                             {}, headers)

    def revoke_badge(self, badge_id, payload, headers):
        return self._request("POST", f"/badging/badges/{badge_id}/revoke",
                             payload, headers)

    def replace_badge(self, badge_id, payload, headers):
        return self._request("POST", f"/badging/badges/{badge_id}/replace",
                             payload, headers)

    # --- Escort privileges ---
    def grant_escort_privilege(self, badge_id, payload, headers):
        return self._request("POST", f"/badging/badges/{badge_id}/escort-privileges",
                             payload, headers)

    def list_escort_privileges(self, badge_id, headers, params=None):
        return self._request("GET", f"/badging/badges/{badge_id}/escort-privileges",
                             headers=headers, params=params)

    def revoke_escort_privilege(self, privilege_id, headers):
        return self._request("POST", f"/badging/escort-privileges/{privilege_id}/revoke",
                             {}, headers)

    # --- Access checks ---
    def create_access_check(self, payload, headers):
        return self._request("POST", "/badging/access-checks", payload, headers)

    def list_access_events(self, badge_id, headers, params=None):
        return self._request("GET", f"/badging/badges/{badge_id}/access-events",
                             headers=headers, params=params)

    # --- Violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/badging/violations", payload, headers)

    def list_violations(self, badge_id, headers, params=None):
        return self._request("GET", f"/badging/badges/{badge_id}/violations",
                             headers=headers, params=params)

    def sustain_violation(self, violation_id, headers):
        return self._request("POST", f"/badging/violations/{violation_id}/sustain",
                             {}, headers)

    def dismiss_violation(self, violation_id, headers):
        return self._request("POST", f"/badging/violations/{violation_id}/dismiss",
                             {}, headers)

    # --- Audit cycles ---
    def create_audit_cycle(self, payload, headers):
        return self._request("POST", "/badging/audit-cycles", payload, headers)

    def get_audit_cycle(self, audit_cycle_id, headers):
        return self._request("GET", f"/badging/audit-cycles/{audit_cycle_id}",
                             headers=headers)

    def close_audit_cycle(self, audit_cycle_id, headers):
        return self._request("POST", f"/badging/audit-cycles/{audit_cycle_id}/close",
                             {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/badging/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
