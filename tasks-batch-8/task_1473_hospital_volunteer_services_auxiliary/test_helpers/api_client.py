"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Volunteer applications (PRD §3.1) ---
    def create_application(self, payload, headers):
        return self._request("POST", "/auxiliary/volunteer-applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/auxiliary/volunteer-applications", headers=headers, params=params)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/auxiliary/volunteer-applications/{app_id}", headers=headers)

    def start_review(self, app_id, headers):
        return self._request("POST", f"/auxiliary/volunteer-applications/{app_id}/start-review", headers=headers)

    def request_info(self, app_id, payload, headers):
        return self._request("POST", f"/auxiliary/volunteer-applications/{app_id}/request-info", payload, headers)

    def resubmit_application(self, app_id, payload, headers):
        return self._request("POST", f"/auxiliary/volunteer-applications/{app_id}/resubmit", payload, headers)

    def decide_application(self, app_id, payload, headers):
        return self._request("POST", f"/auxiliary/volunteer-applications/{app_id}/decide", payload, headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"/auxiliary/volunteer-applications/{app_id}/withdraw", headers=headers)

    # --- Volunteers (PRD §3.4) ---
    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/auxiliary/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/auxiliary/volunteers/{volunteer_id}", headers=headers)

    def get_volunteer_summary(self, volunteer_id, headers):
        return self._request("GET", f"/auxiliary/volunteers/{volunteer_id}/summary", headers=headers)

    def update_volunteer(self, volunteer_id, payload, headers):
        return self._request("PUT", f"/auxiliary/volunteers/{volunteer_id}", payload, headers)

    def activate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/auxiliary/volunteers/{volunteer_id}/activate", headers=headers)

    def suspend_volunteer(self, volunteer_id, payload, headers):
        return self._request("POST", f"/auxiliary/volunteers/{volunteer_id}/suspend", payload, headers)

    def reinstate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/auxiliary/volunteers/{volunteer_id}/reinstate", headers=headers)

    def separate_volunteer(self, volunteer_id, payload, headers):
        return self._request("POST", f"/auxiliary/volunteers/{volunteer_id}/separate", payload, headers)

    def reapply_volunteer(self, volunteer_id, payload, headers):
        return self._request("POST", f"/auxiliary/volunteers/{volunteer_id}/reapply", payload, headers)

    # --- Clearances (PRD §3.2) ---
    def create_clearance(self, payload, headers):
        return self._request("POST", "/auxiliary/clearances", payload, headers)

    def list_clearances(self, headers, params=None):
        return self._request("GET", "/auxiliary/clearances", headers=headers, params=params)

    def get_clearance(self, clearance_id, headers):
        return self._request("GET", f"/auxiliary/clearances/{clearance_id}", headers=headers)

    def adjudicate_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"/auxiliary/clearances/{clearance_id}/adjudicate", payload, headers)

    def resubmit_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"/auxiliary/clearances/{clearance_id}/resubmit", payload, headers)

    def revoke_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"/auxiliary/clearances/{clearance_id}/revoke", payload, headers)

    # --- Departments / roles (PRD §3.3) ---
    def create_department(self, payload, headers):
        return self._request("POST", "/auxiliary/departments", payload, headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/auxiliary/departments", headers=headers, params=params)

    def get_department(self, dept_id, headers):
        return self._request("GET", f"/auxiliary/departments/{dept_id}", headers=headers)

    def create_role(self, payload, headers):
        return self._request("POST", "/auxiliary/volunteer-roles", payload, headers)

    def list_roles(self, headers, params=None):
        return self._request("GET", "/auxiliary/volunteer-roles", headers=headers, params=params)

    def get_role(self, role_id, headers):
        return self._request("GET", f"/auxiliary/volunteer-roles/{role_id}", headers=headers)

    # --- Department requests (PRD §3.3) ---
    def create_department_request(self, payload, headers):
        return self._request("POST", "/auxiliary/department-requests", payload, headers)

    def list_department_requests(self, headers, params=None):
        return self._request("GET", "/auxiliary/department-requests", headers=headers, params=params)

    def get_department_request(self, request_id, headers):
        return self._request("GET", f"/auxiliary/department-requests/{request_id}", headers=headers)

    def open_request(self, request_id, headers):
        return self._request("POST", f"/auxiliary/department-requests/{request_id}/open", headers=headers)

    def close_request(self, request_id, headers):
        return self._request("POST", f"/auxiliary/department-requests/{request_id}/close", headers=headers)

    def cancel_request(self, request_id, headers):
        return self._request("POST", f"/auxiliary/department-requests/{request_id}/cancel", headers=headers)

    # --- Placements (PRD §3.3) ---
    def create_placement(self, payload, headers):
        return self._request("POST", "/auxiliary/placements", payload, headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/auxiliary/placements", headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/auxiliary/placements/{placement_id}", headers=headers)

    def accept_placement(self, placement_id, headers):
        return self._request("POST", f"/auxiliary/placements/{placement_id}/accept", headers=headers)

    def decline_placement(self, placement_id, headers):
        return self._request("POST", f"/auxiliary/placements/{placement_id}/decline", headers=headers)

    def counter_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/auxiliary/placements/{placement_id}/counter", payload, headers)

    def reoffer_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/auxiliary/placements/{placement_id}/reoffer", payload, headers)

    def rescind_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/auxiliary/placements/{placement_id}/rescind", payload, headers)

    # --- Training records (PRD §3.4) ---
    def create_training_record(self, payload, headers):
        return self._request("POST", "/auxiliary/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/auxiliary/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/auxiliary/training-records/{record_id}", headers=headers)

    def complete_training_record(self, record_id, headers):
        return self._request("POST", f"/auxiliary/training-records/{record_id}/complete", headers=headers)

    # --- Shifts (PRD §3.5) ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/auxiliary/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/auxiliary/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/auxiliary/shifts/{shift_id}", headers=headers)

    def update_shift(self, shift_id, payload, headers):
        return self._request("PUT", f"/auxiliary/shifts/{shift_id}", payload, headers)

    def publish_shift(self, shift_id, headers):
        return self._request("POST", f"/auxiliary/shifts/{shift_id}/publish", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/auxiliary/shifts/{shift_id}/cancel", headers=headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"/auxiliary/shifts/{shift_id}/complete", headers=headers)

    # --- Shift assignments (PRD §3.5) ---
    def create_shift_assignment(self, payload, headers):
        return self._request("POST", "/auxiliary/shift-assignments", payload, headers)

    def list_shift_assignments(self, headers, params=None):
        return self._request("GET", "/auxiliary/shift-assignments", headers=headers, params=params)

    def get_shift_assignment(self, assignment_id, headers):
        return self._request("GET", f"/auxiliary/shift-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/auxiliary/shift-assignments/{assignment_id}/confirm", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/auxiliary/shift-assignments/{assignment_id}/cancel", headers=headers)

    # --- Hour entries (PRD §3.6) ---
    def create_hour_entry(self, payload, headers):
        return self._request("POST", "/auxiliary/hour-entries", payload, headers)

    def list_hour_entries(self, headers, params=None):
        return self._request("GET", "/auxiliary/hour-entries", headers=headers, params=params)

    def get_hour_entry(self, entry_id, headers):
        return self._request("GET", f"/auxiliary/hour-entries/{entry_id}", headers=headers)

    def approve_hour_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/auxiliary/hour-entries/{entry_id}/approve", payload, headers)

    def reject_hour_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/auxiliary/hour-entries/{entry_id}/reject", payload, headers)

    def reverse_hour_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/auxiliary/hour-entries/{entry_id}/reverse", payload, headers)

    # --- Badges (PRD §3.4) ---
    def list_badges(self, headers, params=None):
        return self._request("GET", "/auxiliary/badges", headers=headers, params=params)

    def get_badge(self, badge_id, headers):
        return self._request("GET", f"/auxiliary/badges/{badge_id}", headers=headers)

    def revoke_badge(self, badge_id, payload, headers):
        return self._request("POST", f"/auxiliary/badges/{badge_id}/revoke", payload, headers)

    def replace_badge(self, badge_id, payload, headers):
        return self._request("POST", f"/auxiliary/badges/{badge_id}/replace", payload, headers)

    # --- Fundraising campaigns (PRD §3.8) ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/auxiliary/fundraising-campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/auxiliary/fundraising-campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/auxiliary/fundraising-campaigns/{campaign_id}", headers=headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/auxiliary/fundraising-campaigns/{campaign_id}/activate", headers=headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/auxiliary/fundraising-campaigns/{campaign_id}/close", headers=headers)

    def reconcile_campaign(self, campaign_id, headers):
        return self._request("POST", f"/auxiliary/fundraising-campaigns/{campaign_id}/reconcile", headers=headers)

    def disburse_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/auxiliary/fundraising-campaigns/{campaign_id}/disburse", payload, headers)

    # --- Gift shop items / sales (PRD §3.7) ---
    def create_item(self, payload, headers):
        return self._request("POST", "/auxiliary/gift-shop-items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/auxiliary/gift-shop-items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/auxiliary/gift-shop-items/{item_id}", headers=headers)

    def update_item(self, item_id, payload, headers):
        return self._request("PUT", f"/auxiliary/gift-shop-items/{item_id}", payload, headers)

    def create_sale(self, payload, headers):
        return self._request("POST", "/auxiliary/gift-shop-sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/auxiliary/gift-shop-sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/auxiliary/gift-shop-sales/{sale_id}", headers=headers)

    def void_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/auxiliary/gift-shop-sales/{sale_id}/void", payload, headers)

    # --- Recognition events (PRD §3.6) ---
    def list_recognition_events(self, headers, params=None):
        return self._request("GET", "/auxiliary/recognition-events", headers=headers, params=params)

    def get_recognition_event(self, event_id, headers):
        return self._request("GET", f"/auxiliary/recognition-events/{event_id}", headers=headers)

    # --- Annual review (PRD §3.6) ---
    def run_annual_review(self, headers):
        return self._request("POST", "/auxiliary/compliance/annual-review", headers=headers)


api_client = ApiClient()
