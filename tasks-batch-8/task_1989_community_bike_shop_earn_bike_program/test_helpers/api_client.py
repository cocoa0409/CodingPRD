"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock / ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/ops/run-sweep", headers=headers)

    # --- donors ---
    def create_donor(self, payload, headers):
        return self._request("POST", "/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/donors", headers=headers, params=params)

    def get_donor_receipt(self, donor_id, headers, params=None):
        return self._request("GET", f"/donors/{donor_id}/receipt", headers=headers, params=params)

    # --- bikes ---
    def create_bike(self, payload, headers):
        return self._request("POST", "/bikes", payload, headers)

    def get_bike(self, bike_id, headers):
        return self._request("GET", f"/bikes/{bike_id}", headers=headers)

    def list_bikes(self, headers, params=None):
        return self._request("GET", "/bikes", headers=headers, params=params)

    def triage_bike(self, bike_id, payload, headers):
        return self._request("POST", f"/bikes/{bike_id}/triage", payload, headers)

    def route_bike(self, bike_id, payload, headers):
        return self._request("POST", f"/bikes/{bike_id}/route", payload, headers)

    def submit_safety(self, bike_id, headers):
        return self._request("POST", f"/bikes/{bike_id}/submit-safety", headers=headers)

    def create_safety_inspection(self, bike_id, payload, headers):
        return self._request("POST", f"/bikes/{bike_id}/safety-inspections", payload, headers)

    def get_safety_inspection(self, inspection_id, headers):
        return self._request("GET", f"/safety-inspections/{inspection_id}", headers=headers)

    def list_safety_inspections(self, headers, params=None):
        return self._request("GET", "/safety-inspections", headers=headers, params=params)

    def create_harvest_log(self, bike_id, payload, headers):
        return self._request("POST", f"/bikes/{bike_id}/harvest-logs", payload, headers)

    def get_harvest_log(self, harvest_id, headers):
        return self._request("GET", f"/harvest-logs/{harvest_id}", headers=headers)

    def list_harvest_logs(self, headers, params=None):
        return self._request("GET", "/harvest-logs", headers=headers, params=params)

    def harvest_complete(self, bike_id, headers):
        return self._request("POST", f"/bikes/{bike_id}/harvest-complete", headers=headers)

    def create_usage_log(self, bike_id, payload, headers):
        return self._request("POST", f"/bikes/{bike_id}/usage-logs", payload, headers)

    def get_usage_log(self, usage_id, headers):
        return self._request("GET", f"/usage-logs/{usage_id}", headers=headers)

    def list_usage_logs(self, headers, params=None):
        return self._request("GET", "/usage-logs", headers=headers, params=params)

    def void_usage_log(self, usage_id, payload, headers):
        return self._request("POST", f"/usage-logs/{usage_id}/void", payload, headers)

    def create_scrap_ticket(self, bike_id, payload, headers):
        return self._request("POST", f"/bikes/{bike_id}/scrap-tickets", payload, headers)

    def get_scrap_ticket(self, ticket_id, headers):
        return self._request("GET", f"/scrap-tickets/{ticket_id}", headers=headers)

    def list_scrap_tickets(self, headers, params=None):
        return self._request("GET", "/scrap-tickets", headers=headers, params=params)

    def get_scrap_statement(self, headers, params=None):
        return self._request("GET", "/scrap-tickets/statement", headers=headers, params=params)

    def pickup_scrap_ticket(self, ticket_id, headers):
        return self._request("POST", f"/scrap-tickets/{ticket_id}/pick-up", headers=headers)

    # --- parts ---
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def restock_part(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/restock", payload, headers)

    # --- volunteers ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    def promote_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/volunteers/{volunteer_id}/promote", headers=headers)

    def suspend_volunteer(self, volunteer_id, payload, headers):
        return self._request("POST", f"/volunteers/{volunteer_id}/suspend", payload, headers)

    def reinstate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/volunteers/{volunteer_id}/reinstate", headers=headers)

    # --- training ---
    def create_training_session(self, payload, headers):
        return self._request("POST", "/training-sessions", payload, headers)

    def get_training_session(self, session_id, headers):
        return self._request("GET", f"/training-sessions/{session_id}", headers=headers)

    def list_training_sessions(self, headers, params=None):
        return self._request("GET", "/training-sessions", headers=headers, params=params)

    def enroll_in_session(self, session_id, payload, headers):
        return self._request("POST", f"/training-sessions/{session_id}/enroll", payload, headers)

    def complete_training_session(self, session_id, payload, headers):
        return self._request("POST", f"/training-sessions/{session_id}/complete", payload, headers)

    def cancel_training_session(self, session_id, headers):
        return self._request("POST", f"/training-sessions/{session_id}/cancel", headers=headers)

    def get_attendance(self, attendance_id, headers):
        return self._request("GET", f"/attendances/{attendance_id}", headers=headers)

    def list_attendances(self, headers, params=None):
        return self._request("GET", "/attendances", headers=headers, params=params)

    # --- shifts ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def check_in_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/check-in", headers=headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/complete", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/cancel", headers=headers)

    # --- participants & hour logs ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def record_quiz(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/record-quiz", payload, headers)

    def create_hour_log(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/hour-logs", payload, headers)

    def get_hour_log(self, log_id, headers):
        return self._request("GET", f"/hour-logs/{log_id}", headers=headers)

    def list_hour_logs(self, headers, params=None):
        return self._request("GET", "/hour-logs", headers=headers, params=params)

    def approve_hour_log(self, log_id, payload, headers):
        return self._request("POST", f"/hour-logs/{log_id}/approve", payload, headers)

    def reject_hour_log(self, log_id, payload, headers):
        return self._request("POST", f"/hour-logs/{log_id}/reject", payload, headers)

    def void_hour_log(self, log_id, payload, headers):
        return self._request("POST", f"/hour-logs/{log_id}/void", payload, headers)

    def reserve_bike(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/reserve-bike", payload, headers)

    def release_bike(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/release-bike", headers=headers)

    def graduate_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/graduate", headers=headers)

    def withdraw_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/withdraw", headers=headers)

    # --- sales ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def complete_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/complete", payload, headers)

    def void_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/void", payload, headers)

    # --- giveaways ---
    def create_giveaway(self, payload, headers):
        return self._request("POST", "/giveaways", payload, headers)

    def get_giveaway(self, award_id, headers):
        return self._request("GET", f"/giveaways/{award_id}", headers=headers)

    def list_giveaways(self, headers, params=None):
        return self._request("GET", "/giveaways", headers=headers, params=params)

    def approve_giveaway(self, award_id, headers):
        return self._request("POST", f"/giveaways/{award_id}/approve", headers=headers)

    def deny_giveaway(self, award_id, payload, headers):
        return self._request("POST", f"/giveaways/{award_id}/deny", payload, headers)

    def fulfill_giveaway(self, award_id, headers):
        return self._request("POST", f"/giveaways/{award_id}/fulfill", headers=headers)

    def cancel_giveaway(self, award_id, payload, headers):
        return self._request("POST", f"/giveaways/{award_id}/cancel", payload, headers)

    # --- memberships & sessions ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def suspend_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/suspend", payload, headers)

    def reinstate_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/reinstate", headers=headers)

    def get_membership_billing(self, membership_id, headers, params=None):
        return self._request("GET", f"/memberships/{membership_id}/billing", headers=headers, params=params)

    def book_session(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def start_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/start", headers=headers)

    def close_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/close", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", headers=headers)

    # --- helmet distributions ---
    def create_helmet_distribution(self, payload, headers):
        return self._request("POST", "/helmet-distributions", payload, headers)

    def get_helmet_distribution(self, distribution_id, headers):
        return self._request("GET", f"/helmet-distributions/{distribution_id}", headers=headers)

    def list_helmet_distributions(self, headers, params=None):
        return self._request("GET", "/helmet-distributions", headers=headers, params=params)


api_client = ApiClient()
