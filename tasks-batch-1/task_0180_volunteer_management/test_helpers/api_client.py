"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Organizations ────────────────────────────────
    def create_organization(self, payload, headers):
        return self._request("POST", "/vm/organizations", payload, headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", "/vm/organizations", headers=headers, params=params)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/vm/organizations/{org_id}", headers=headers)

    def archive_organization(self, org_id, payload, headers):
        return self._request("POST", f"/vm/organizations/{org_id}/archive", payload, headers)

    # ─── Volunteers ───────────────────────────────────
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/vm/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/vm/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/vm/volunteers/{volunteer_id}", headers=headers)

    def withdraw_volunteer(self, volunteer_id, payload, headers):
        return self._request("POST", f"/vm/volunteers/{volunteer_id}/withdraw", payload, headers)

    # ─── Background checks ─────────────────────────────
    def create_background_check(self, payload, headers):
        return self._request("POST", "/vm/background-checks", payload, headers)

    def list_background_checks(self, headers, params=None):
        return self._request("GET", "/vm/background-checks", headers=headers, params=params)

    def get_background_check(self, check_id, headers):
        return self._request("GET", f"/vm/background-checks/{check_id}", headers=headers)

    def start_background_check(self, check_id, headers):
        return self._request("POST", f"/vm/background-checks/{check_id}/start", headers=headers)

    def decide_background_check(self, check_id, payload, headers):
        return self._request("POST", f"/vm/background-checks/{check_id}/decide", payload, headers)

    def renew_background_check(self, check_id, payload, headers):
        return self._request("POST", f"/vm/background-checks/{check_id}/renew", payload, headers)

    # ─── Skills + VolunteerSkills ──────────────────────
    def create_skill(self, payload, headers):
        return self._request("POST", "/vm/skills", payload, headers)

    def list_skills(self, headers, params=None):
        return self._request("GET", "/vm/skills", headers=headers, params=params)

    def get_skill(self, skill_id, headers):
        return self._request("GET", f"/vm/skills/{skill_id}", headers=headers)

    def create_volunteer_skill(self, payload, headers):
        return self._request("POST", "/vm/volunteer-skills", payload, headers)

    def list_volunteer_skills(self, headers, params=None):
        return self._request("GET", "/vm/volunteer-skills", headers=headers, params=params)

    def get_volunteer_skill(self, volunteer_skill_id, headers):
        return self._request("GET", f"/vm/volunteer-skills/{volunteer_skill_id}", headers=headers)

    # ─── Waiver templates + acceptances ────────────────
    def create_waiver_template(self, payload, headers):
        return self._request("POST", "/vm/waiver-templates", payload, headers)

    def list_waiver_templates(self, headers, params=None):
        return self._request("GET", "/vm/waiver-templates", headers=headers, params=params)

    def get_waiver_template(self, waiver_template_id, headers):
        return self._request("GET", f"/vm/waiver-templates/{waiver_template_id}", headers=headers)

    def create_waiver_acceptance(self, payload, headers):
        return self._request("POST", "/vm/waiver-acceptances", payload, headers)

    def list_waiver_acceptances(self, headers, params=None):
        return self._request("GET", "/vm/waiver-acceptances", headers=headers, params=params)

    def get_waiver_acceptance(self, waiver_acceptance_id, headers):
        return self._request("GET", f"/vm/waiver-acceptances/{waiver_acceptance_id}", headers=headers)

    # ─── Training modules + completions ────────────────
    def create_training_module(self, payload, headers):
        return self._request("POST", "/vm/training-modules", payload, headers)

    def list_training_modules(self, headers, params=None):
        return self._request("GET", "/vm/training-modules", headers=headers, params=params)

    def get_training_module(self, training_module_id, headers):
        return self._request("GET", f"/vm/training-modules/{training_module_id}", headers=headers)

    def create_training_completion(self, payload, headers):
        return self._request("POST", "/vm/training-completions", payload, headers)

    def list_training_completions(self, headers, params=None):
        return self._request("GET", "/vm/training-completions", headers=headers, params=params)

    def get_training_completion(self, training_completion_id, headers):
        return self._request("GET", f"/vm/training-completions/{training_completion_id}", headers=headers)

    # ─── Opportunities ─────────────────────────────────
    def create_opportunity(self, payload, headers):
        return self._request("POST", "/vm/opportunities", payload, headers)

    def list_opportunities(self, headers, params=None):
        return self._request("GET", "/vm/opportunities", headers=headers, params=params)

    def get_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/vm/opportunities/{opportunity_id}", headers=headers)

    def publish_opportunity(self, opportunity_id, headers):
        return self._request("POST", f"/vm/opportunities/{opportunity_id}/publish", headers=headers)

    def close_opportunity(self, opportunity_id, headers):
        return self._request("POST", f"/vm/opportunities/{opportunity_id}/close", headers=headers)

    # ─── Shifts ────────────────────────────────────────
    def create_shift(self, payload, headers):
        return self._request("POST", "/vm/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/vm/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/vm/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/vm/shifts/{shift_id}/cancel", headers=headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"/vm/shifts/{shift_id}/complete", headers=headers)

    # ─── Signups ───────────────────────────────────────
    def create_signup(self, shift_id, payload, headers):
        return self._request("POST", f"/vm/shifts/{shift_id}/signups", payload, headers)

    def list_signups(self, headers, params=None):
        return self._request("GET", "/vm/signups", headers=headers, params=params)

    def get_signup(self, signup_id, headers):
        return self._request("GET", f"/vm/signups/{signup_id}", headers=headers)

    def confirm_signup(self, signup_id, headers):
        return self._request("POST", f"/vm/signups/{signup_id}/confirm", headers=headers)

    def cancel_signup(self, signup_id, headers):
        return self._request("POST", f"/vm/signups/{signup_id}/cancel", headers=headers)

    def check_in_signup(self, signup_id, headers):
        return self._request("POST", f"/vm/signups/{signup_id}/check-in", headers=headers)

    def mark_no_show_signup(self, signup_id, headers):
        return self._request("POST", f"/vm/signups/{signup_id}/mark-no-show", headers=headers)

    def log_hours_signup(self, signup_id, payload, headers):
        return self._request("POST", f"/vm/signups/{signup_id}/log-hours", payload, headers)

    def verify_hours_signup(self, signup_id, headers):
        return self._request("POST", f"/vm/signups/{signup_id}/verify-hours", headers=headers)

    def reject_hours_signup(self, signup_id, headers):
        return self._request("POST", f"/vm/signups/{signup_id}/reject-hours", headers=headers)

    # ─── Corporate groups ──────────────────────────────
    def create_corporate_group(self, payload, headers):
        return self._request("POST", "/vm/corporate-groups", payload, headers)

    def list_corporate_groups(self, headers, params=None):
        return self._request("GET", "/vm/corporate-groups", headers=headers, params=params)

    def get_corporate_group(self, group_id, headers):
        return self._request("GET", f"/vm/corporate-groups/{group_id}", headers=headers)

    def approve_corporate_group(self, group_id, headers):
        return self._request("POST", f"/vm/corporate-groups/{group_id}/approve", headers=headers)

    def reject_corporate_group(self, group_id, headers):
        return self._request("POST", f"/vm/corporate-groups/{group_id}/reject", headers=headers)

    def allocate_corporate_group(self, group_id, payload, headers):
        return self._request("POST", f"/vm/corporate-groups/{group_id}/allocate", payload, headers)

    def cancel_corporate_group(self, group_id, headers):
        return self._request("POST", f"/vm/corporate-groups/{group_id}/cancel", headers=headers)

    # ─── Test-only clock control ───────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
