"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock / ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/ops/run-daily-sweep", {}, headers)

    # --- clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def update_client(self, client_id, payload, headers):
        return self._request("PATCH", f"/clients/{client_id}", payload, headers)

    # --- intake applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/intake-applications", payload, headers)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/intake-applications/{app_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/intake-applications", headers=headers, params=params)

    def screen_application(self, app_id, headers):
        return self._request("POST", f"/intake-applications/{app_id}/screen", {}, headers)

    def request_documents(self, app_id, payload, headers):
        return self._request("POST", f"/intake-applications/{app_id}/request-documents", payload, headers)

    def submit_documents(self, app_id, headers):
        return self._request("POST", f"/intake-applications/{app_id}/submit-documents", {}, headers)

    def decide_eligibility(self, app_id, payload, headers):
        return self._request("POST", f"/intake-applications/{app_id}/decide-eligibility", payload, headers)

    def rescreen_application(self, app_id, payload, headers):
        return self._request("POST", f"/intake-applications/{app_id}/rescreen", payload, headers)

    def enqueue_waitlist(self, app_id, headers):
        return self._request("POST", f"/intake-applications/{app_id}/enqueue-waitlist", {}, headers)

    def withdraw_application(self, app_id, payload, headers):
        return self._request("POST", f"/intake-applications/{app_id}/withdraw", payload, headers)

    def open_case(self, app_id, payload, headers):
        return self._request("POST", f"/intake-applications/{app_id}/open-case", payload, headers)

    # --- conflict checks ---
    def create_conflict_check(self, app_id, payload, headers):
        return self._request("POST", f"/intake-applications/{app_id}/conflict-checks", payload, headers)

    def list_conflict_checks(self, app_id, headers, params=None):
        return self._request("GET", f"/intake-applications/{app_id}/conflict-checks", headers=headers, params=params)

    def get_conflict_check(self, check_id, headers):
        return self._request("GET", f"/conflict-checks/{check_id}", headers=headers)

    def resolve_conflict_check(self, check_id, payload, headers):
        return self._request("POST", f"/conflict-checks/{check_id}/resolve", payload, headers)

    # --- cases ---
    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def assign_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/assign", payload, headers)

    def place_hold(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/place-hold", payload, headers)

    def resume_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/resume", {}, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/close", payload, headers)

    # --- time entries ---
    def create_time_entry(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/time-entries", payload, headers)

    def get_time_entry(self, entry_id, headers):
        return self._request("GET", f"/time-entries/{entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    # --- staff members ---
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def update_staff_member(self, staff_id, payload, headers):
        return self._request("PATCH", f"/staff-members/{staff_id}", payload, headers)

    def get_caseload(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}/caseload", headers=headers)

    # --- referral panel members ---
    def create_panel_member(self, payload, headers):
        return self._request("POST", "/referral-panel-members", payload, headers)

    def get_panel_member(self, member_id, headers):
        return self._request("GET", f"/referral-panel-members/{member_id}", headers=headers)

    def list_panel_members(self, headers, params=None):
        return self._request("GET", "/referral-panel-members", headers=headers, params=params)

    def update_panel_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/referral-panel-members/{member_id}", payload, headers)

    # --- referrals ---
    def create_referral(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def respond_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/respond", payload, headers)

    def withdraw_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/withdraw", payload, headers)

    # --- grant programs ---
    def create_grant_program(self, payload, headers):
        return self._request("POST", "/grant-programs", payload, headers)

    def get_grant_program(self, program_id, headers):
        return self._request("GET", f"/grant-programs/{program_id}", headers=headers)

    def list_grant_programs(self, headers, params=None):
        return self._request("GET", "/grant-programs", headers=headers, params=params)

    def suspend_grant_program(self, program_id, headers):
        return self._request("POST", f"/grant-programs/{program_id}/suspend", {}, headers)

    def resume_grant_program(self, program_id, headers):
        return self._request("POST", f"/grant-programs/{program_id}/resume", {}, headers)

    def close_grant_program(self, program_id, headers):
        return self._request("POST", f"/grant-programs/{program_id}/close", {}, headers)

    def get_grant_utilization(self, program_id, headers):
        return self._request("GET", f"/grant-programs/{program_id}/utilization", headers=headers)

    # --- grant reports ---
    def create_grant_report(self, program_id, payload, headers):
        return self._request("POST", f"/grant-programs/{program_id}/reports", payload, headers)

    def get_grant_report(self, report_id, headers):
        return self._request("GET", f"/grant-reports/{report_id}", headers=headers)

    def list_grant_reports(self, program_id, headers, params=None):
        return self._request("GET", f"/grant-programs/{program_id}/reports", headers=headers, params=params)

    def submit_grant_report(self, report_id, headers):
        return self._request("POST", f"/grant-reports/{report_id}/submit", {}, headers)

    def accept_grant_report(self, report_id, headers):
        return self._request("POST", f"/grant-reports/{report_id}/accept", {}, headers)

    def return_grant_report(self, report_id, payload, headers):
        return self._request("POST", f"/grant-reports/{report_id}/return", payload, headers)

    def revise_grant_report(self, report_id, headers):
        return self._request("POST", f"/grant-reports/{report_id}/revise", {}, headers)

    # --- venue rules ---
    def create_venue_rule(self, payload, headers):
        return self._request("POST", "/venue-rules", payload, headers)

    def get_venue_rule(self, rule_id, headers):
        return self._request("GET", f"/venue-rules/{rule_id}", headers=headers)

    def list_venue_rules(self, headers, params=None):
        return self._request("GET", "/venue-rules", headers=headers, params=params)

    # --- satisfaction surveys ---
    def create_survey(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/satisfaction-surveys", payload, headers)

    def list_surveys(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/satisfaction-surveys", headers=headers, params=params)

    # --- unmet need records ---
    def get_unmet_need_record(self, record_id, headers):
        return self._request("GET", f"/unmet-need-records/{record_id}", headers=headers)

    def list_unmet_need_records(self, headers, params=None):
        return self._request("GET", "/unmet-need-records", headers=headers, params=params)

    # --- waitlist entries ---
    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)


api_client = ApiClient()
