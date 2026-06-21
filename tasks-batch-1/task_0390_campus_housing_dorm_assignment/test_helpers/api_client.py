"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Buildings ────────────────────────────────────────────────────────────
    def create_building(self, payload, headers):
        return self._request("POST", "/buildings", payload, headers)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/buildings/{building_id}", headers=headers)

    # ─── Rooms ────────────────────────────────────────────────────────────────
    def create_room(self, building_id, payload, headers):
        return self._request("POST", f"/buildings/{building_id}/rooms", payload, headers)

    def list_rooms_in_building(self, building_id, headers, params=None):
        return self._request("GET", f"/buildings/{building_id}/rooms", headers=headers, params=params)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def take_offline_room(self, room_id, payload, headers):
        return self._request("POST", f"/rooms/{room_id}/take-offline", payload, headers)

    def restore_room(self, room_id, payload, headers):
        return self._request("POST", f"/rooms/{room_id}/restore", payload, headers)

    # ─── Students ─────────────────────────────────────────────────────────────
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def place_hold_student(self, student_id, headers):
        return self._request("POST", f"/students/{student_id}/place-hold", {}, headers)

    def release_hold_student(self, student_id, headers):
        return self._request("POST", f"/students/{student_id}/release-hold", {}, headers)

    # ─── Housing cycles ───────────────────────────────────────────────────────
    def create_cycle(self, payload, headers):
        return self._request("POST", "/housing-cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/housing-cycles/{cycle_id}", headers=headers)

    def run_lottery(self, cycle_id, headers):
        return self._request("POST", f"/housing-cycles/{cycle_id}/run-lottery", {}, headers)

    def open_assignment(self, cycle_id, headers):
        return self._request("POST", f"/housing-cycles/{cycle_id}/open-assignment", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/housing-cycles/{cycle_id}/close", {}, headers)

    # ─── Applications ─────────────────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    def accept_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/accept", payload, headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/decline", {}, headers)

    # ─── Roommate groups & memberships ────────────────────────────────────────
    def create_roommate_group(self, payload, headers):
        return self._request("POST", "/roommate-groups", payload, headers)

    def get_roommate_group(self, group_id, headers):
        return self._request("GET", f"/roommate-groups/{group_id}", headers=headers)

    def list_roommate_groups(self, headers, params=None):
        return self._request("GET", "/roommate-groups", headers=headers, params=params)

    def create_membership(self, group_id, payload, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/memberships", payload, headers)

    def list_memberships_in_group(self, group_id, headers, params=None):
        return self._request("GET", f"/roommate-groups/{group_id}/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/roommate-memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/roommate-memberships", headers=headers, params=params)

    def accept_membership(self, group_id, membership_id, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/memberships/{membership_id}/accept", {}, headers)

    def decline_membership(self, group_id, membership_id, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/memberships/{membership_id}/decline", {}, headers)

    def remove_membership(self, group_id, membership_id, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/memberships/{membership_id}/remove", {}, headers)

    def lock_group(self, group_id, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/lock", {}, headers)

    def reopen_group(self, group_id, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/reopen", {}, headers)

    def disband_group(self, group_id, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/disband", {}, headers)

    # ─── Assignments & swaps ──────────────────────────────────────────────────
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def propose_swap(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/propose-swap", payload, headers)

    def confirm_swap(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/confirm-swap", payload, headers)

    def cancel_swap(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/cancel-swap", {}, headers)

    def vacate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/vacate", {}, headers)

    def check_out_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-out", {}, headers)

    # ─── Meal plans ───────────────────────────────────────────────────────────
    def get_meal_plan(self, meal_plan_id, headers):
        return self._request("GET", f"/meal-plans/{meal_plan_id}", headers=headers)

    def list_meal_plans(self, headers, params=None):
        return self._request("GET", "/meal-plans", headers=headers, params=params)

    def change_meal_plan_tier(self, meal_plan_id, payload, headers):
        return self._request("PATCH", f"/meal-plans/{meal_plan_id}", payload, headers)

    # ─── Waitlist entries ─────────────────────────────────────────────────────
    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    # ─── Damage charges ───────────────────────────────────────────────────────
    def create_damage_charge(self, payload, headers):
        return self._request("POST", "/damage-charges", payload, headers)

    def get_damage_charge(self, charge_id, headers):
        return self._request("GET", f"/damage-charges/{charge_id}", headers=headers)

    def list_damage_charges(self, headers, params=None):
        return self._request("GET", "/damage-charges", headers=headers, params=params)

    def bill_damage_charge(self, charge_id, headers):
        return self._request("POST", f"/damage-charges/{charge_id}/bill", {}, headers)

    def waive_damage_charge(self, charge_id, headers):
        return self._request("POST", f"/damage-charges/{charge_id}/waive", {}, headers)

    def pay_damage_charge(self, charge_id, headers):
        return self._request("POST", f"/damage-charges/{charge_id}/pay", {}, headers)

    # ─── Incident reports ─────────────────────────────────────────────────────
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/incident-reports/{incident_id}", headers=headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def escalate_incident(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/escalate", {}, headers)

    def resolve_incident(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/resolve", {}, headers)

    # ─── Break housing requests ───────────────────────────────────────────────
    def create_break_request(self, payload, headers):
        return self._request("POST", "/break-housing-requests", payload, headers)

    def get_break_request(self, request_id, headers):
        return self._request("GET", f"/break-housing-requests/{request_id}", headers=headers)

    def list_break_requests(self, headers, params=None):
        return self._request("GET", "/break-housing-requests", headers=headers, params=params)

    def approve_break_request(self, request_id, headers):
        return self._request("POST", f"/break-housing-requests/{request_id}/approve", {}, headers)

    def deny_break_request(self, request_id, headers):
        return self._request("POST", f"/break-housing-requests/{request_id}/deny", {}, headers)

    def cancel_break_request(self, request_id, headers):
        return self._request("POST", f"/break-housing-requests/{request_id}/cancel", {}, headers)


api_client = ApiClient()
