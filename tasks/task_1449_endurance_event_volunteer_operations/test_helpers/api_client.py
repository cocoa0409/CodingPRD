"""API client: one method per endpoint defined in the PRD (PRD §4).

All endpoints are mounted under the /volunteer-ops prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/volunteer-ops"


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Event ---
    def create_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/events/{event_id}", headers=headers)

    def patch_event(self, event_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/events/{event_id}", payload, headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/publish", {}, headers)

    def lock_signups(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/lock-signups", {}, headers)

    def start_race_day(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/start-race-day", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/complete", {}, headers)

    def open_debrief(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/open-debrief", {}, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/close", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/cancel", {}, headers)

    def run_epoch_sweep(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/events/{event_id}/run-epoch-sweep", {}, headers)

    # --- CourseSegment ---
    def create_course_segment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/course-segments", payload, headers)

    def list_course_segments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/course-segments", headers=headers, params=params)

    def get_course_segment(self, segment_id, headers):
        return self._request("GET", f"{PREFIX}/course-segments/{segment_id}", headers=headers)

    # --- RoleCatalogEntry ---
    def create_role_catalog_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/role-catalog-entries", payload, headers)

    def list_role_catalog_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/role-catalog-entries", headers=headers, params=params)

    def get_role_catalog_entry(self, role_entry_id, headers):
        return self._request("GET", f"{PREFIX}/role-catalog-entries/{role_entry_id}", headers=headers)

    def suspend_role_entry(self, role_entry_id, headers):
        return self._request("POST", f"{PREFIX}/role-catalog-entries/{role_entry_id}/suspend", {}, headers)

    def reactivate_role_entry(self, role_entry_id, headers):
        return self._request("POST", f"{PREFIX}/role-catalog-entries/{role_entry_id}/reactivate", {}, headers)

    def retire_role_entry(self, role_entry_id, headers):
        return self._request("POST", f"{PREFIX}/role-catalog-entries/{role_entry_id}/retire", {}, headers)

    # --- Shift ---
    def create_shift(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"{PREFIX}/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"{PREFIX}/shifts/{shift_id}/cancel", {}, headers)

    def reconcile_shift(self, shift_id, headers):
        return self._request("POST", f"{PREFIX}/shifts/{shift_id}/reconcile", {}, headers)

    # --- FundraisingGroup ---
    def create_fundraising_group(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fundraising-groups", payload, headers)

    def list_fundraising_groups(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fundraising-groups", headers=headers, params=params)

    def get_fundraising_group(self, group_id, headers):
        return self._request("GET", f"{PREFIX}/fundraising-groups/{group_id}", headers=headers)

    def get_credit_summary(self, group_id, headers):
        return self._request("GET", f"{PREFIX}/fundraising-groups/{group_id}/credit-summary", headers=headers)

    def suspend_group(self, group_id, headers):
        return self._request("POST", f"{PREFIX}/fundraising-groups/{group_id}/suspend", {}, headers)

    def reinstate_group(self, group_id, headers):
        return self._request("POST", f"{PREFIX}/fundraising-groups/{group_id}/reinstate", {}, headers)

    # --- Volunteer ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"{PREFIX}/volunteers/{volunteer_id}", headers=headers)

    def patch_volunteer(self, volunteer_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/volunteers/{volunteer_id}", payload, headers)

    def screen_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"{PREFIX}/volunteers/{volunteer_id}/screen", {}, headers)

    def reinstate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"{PREFIX}/volunteers/{volunteer_id}/reinstate", {}, headers)

    def get_recognition_summary(self, volunteer_id, headers):
        return self._request("GET", f"{PREFIX}/volunteers/{volunteer_id}/recognition-summary", headers=headers)

    # --- TrainingRecord ---
    def create_training_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/training-records", headers=headers, params=params)

    def get_training_record(self, training_record_id, headers):
        return self._request("GET", f"{PREFIX}/training-records/{training_record_id}", headers=headers)

    def pass_training_record(self, training_record_id, headers):
        return self._request("POST", f"{PREFIX}/training-records/{training_record_id}/pass", {}, headers)

    def fail_training_record(self, training_record_id, headers):
        return self._request("POST", f"{PREFIX}/training-records/{training_record_id}/fail", {}, headers)

    def re_enroll_training_record(self, training_record_id, headers):
        return self._request("POST", f"{PREFIX}/training-records/{training_record_id}/re-enroll", {}, headers)

    # --- Signup ---
    def create_signup(self, payload, headers):
        return self._request("POST", f"{PREFIX}/signups", payload, headers)

    def list_signups(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/signups", headers=headers, params=params)

    def get_signup(self, signup_id, headers):
        return self._request("GET", f"{PREFIX}/signups/{signup_id}", headers=headers)

    def approve_signup(self, signup_id, headers):
        return self._request("POST", f"{PREFIX}/signups/{signup_id}/approve", {}, headers)

    def confirm_signup(self, signup_id, headers):
        return self._request("POST", f"{PREFIX}/signups/{signup_id}/confirm", {}, headers)

    def cancel_signup(self, signup_id, headers):
        return self._request("POST", f"{PREFIX}/signups/{signup_id}/cancel", {}, headers)

    def check_in_signup(self, signup_id, headers):
        return self._request("POST", f"{PREFIX}/signups/{signup_id}/check-in", {}, headers)

    def check_out_signup(self, signup_id, headers, break_minutes=None):
        payload = {} if break_minutes is None else {"break_minutes": break_minutes}
        return self._request("POST", f"{PREFIX}/signups/{signup_id}/check-out", payload, headers)

    def mark_no_show(self, signup_id, headers):
        return self._request("POST", f"{PREFIX}/signups/{signup_id}/mark-no-show", {}, headers)

    def assign_captain(self, signup_id, headers):
        return self._request("POST", f"{PREFIX}/signups/{signup_id}/assign-captain", {}, headers)

    def remove_captain(self, signup_id, headers):
        return self._request("POST", f"{PREFIX}/signups/{signup_id}/remove-captain", {}, headers)

    # --- SupplyInventory ---
    def create_supply_inventory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supply-inventories", payload, headers)

    def list_supply_inventories(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/supply-inventories", headers=headers, params=params)

    def get_supply_inventory(self, inventory_id, headers):
        return self._request("GET", f"{PREFIX}/supply-inventories/{inventory_id}", headers=headers)

    # --- DistributionRecord ---
    def create_distribution_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/distribution-records", payload, headers)

    def list_distribution_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/distribution-records", headers=headers, params=params)

    def get_distribution_record(self, distribution_id, headers):
        return self._request("GET", f"{PREFIX}/distribution-records/{distribution_id}", headers=headers)

    def return_distribution_record(self, distribution_id, headers):
        return self._request("POST", f"{PREFIX}/distribution-records/{distribution_id}/return", {}, headers)

    def revoke_distribution_record(self, distribution_id, headers):
        return self._request("POST", f"{PREFIX}/distribution-records/{distribution_id}/revoke", {}, headers)

    # --- HourLog ---
    def list_hour_logs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hour-logs", headers=headers, params=params)

    def get_hour_log(self, hour_log_id, headers):
        return self._request("GET", f"{PREFIX}/hour-logs/{hour_log_id}", headers=headers)

    def verify_hour_log(self, hour_log_id, headers):
        return self._request("POST", f"{PREFIX}/hour-logs/{hour_log_id}/verify", {}, headers)

    def dispute_hour_log(self, hour_log_id, headers):
        return self._request("POST", f"{PREFIX}/hour-logs/{hour_log_id}/dispute", {}, headers)

    def reject_hour_log(self, hour_log_id, headers):
        return self._request("POST", f"{PREFIX}/hour-logs/{hour_log_id}/reject", {}, headers)

    def adjust_hour_log(self, hour_log_id, break_minutes, headers):
        return self._request("POST", f"{PREFIX}/hour-logs/{hour_log_id}/adjust",
                             {"break_minutes": break_minutes}, headers)

    # --- DebriefReport ---
    def create_debrief_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/debrief-reports", payload, headers)

    def list_debrief_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/debrief-reports", headers=headers, params=params)

    def get_debrief_report(self, debrief_id, headers):
        return self._request("GET", f"{PREFIX}/debrief-reports/{debrief_id}", headers=headers)

    def submit_debrief_report(self, debrief_id, headers):
        return self._request("POST", f"{PREFIX}/debrief-reports/{debrief_id}/submit", {}, headers)

    def acknowledge_debrief_report(self, debrief_id, headers):
        return self._request("POST", f"{PREFIX}/debrief-reports/{debrief_id}/acknowledge", {}, headers)

    # --- RoleAdjustment ---
    def create_role_adjustment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/role-adjustments", payload, headers)

    def list_role_adjustments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/role-adjustments", headers=headers, params=params)

    def get_role_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"{PREFIX}/role-adjustments/{adjustment_id}", headers=headers)

    def approve_role_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"{PREFIX}/role-adjustments/{adjustment_id}/approve", {}, headers)

    def reject_role_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"{PREFIX}/role-adjustments/{adjustment_id}/reject", {}, headers)

    def apply_role_adjustment(self, adjustment_id, expected_role_version, headers):
        return self._request("POST", f"{PREFIX}/role-adjustments/{adjustment_id}/apply",
                             {"expected_role_version": expected_role_version}, headers)


api_client = ApiClient()
