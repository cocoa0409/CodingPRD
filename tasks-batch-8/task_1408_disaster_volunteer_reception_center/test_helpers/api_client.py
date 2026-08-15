"""API client: one method per endpoint defined in the PRD (all under /vrc)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/vrc/_clock/set_current_utc", payload, headers)

    # --- Incident ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/vrc/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/vrc/incidents/{incident_id}", headers=headers)

    def activate_incident(self, incident_id, headers):
        return self._request("POST", f"/vrc/incidents/{incident_id}/activate", None, headers)

    def begin_demobilization(self, incident_id, headers):
        return self._request("POST", f"/vrc/incidents/{incident_id}/begin-demobilization", None, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/vrc/incidents/{incident_id}/close", None, headers)

    def list_incident_volunteers(self, incident_id, headers, params=None):
        return self._request("GET", f"/vrc/incidents/{incident_id}/volunteers", headers=headers, params=params)

    def list_incident_support_requests(self, incident_id, headers, params=None):
        return self._request("GET", f"/vrc/incidents/{incident_id}/support-requests", headers=headers, params=params)

    def list_incident_shifts(self, incident_id, headers, params=None):
        return self._request("GET", f"/vrc/incidents/{incident_id}/shifts", headers=headers, params=params)

    # --- Volunteer ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/vrc/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/vrc/volunteers/{volunteer_id}", headers=headers)

    def patch_volunteer(self, volunteer_id, payload, headers):
        return self._request("PATCH", f"/vrc/volunteers/{volunteer_id}", payload, headers)

    def submit_for_vetting(self, volunteer_id, headers):
        return self._request("POST", f"/vrc/volunteers/{volunteer_id}/submit-for-vetting", None, headers)

    def mark_ready(self, volunteer_id, headers):
        return self._request("POST", f"/vrc/volunteers/{volunteer_id}/mark-ready", None, headers)

    def suspend_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/vrc/volunteers/{volunteer_id}/suspend", None, headers)

    def reinstate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/vrc/volunteers/{volunteer_id}/reinstate", None, headers)

    def withdraw_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/vrc/volunteers/{volunteer_id}/withdraw", None, headers)

    def demobilize_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/vrc/volunteers/{volunteer_id}/demobilize", None, headers)

    def list_volunteer_credentials(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/vrc/volunteers/{volunteer_id}/credentials", headers=headers, params=params)

    def list_volunteer_background_checks(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/vrc/volunteers/{volunteer_id}/background-checks", headers=headers, params=params)

    def list_volunteer_clearances(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/vrc/volunteers/{volunteer_id}/clearances", headers=headers, params=params)

    def list_volunteer_ppe_issuances(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/vrc/volunteers/{volunteer_id}/ppe-issuances", headers=headers, params=params)

    def list_volunteer_risk_reports(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/vrc/volunteers/{volunteer_id}/risk-reports", headers=headers, params=params)

    # --- SkillCredential ---
    def create_credential(self, payload, headers):
        return self._request("POST", "/vrc/credentials", payload, headers)

    def verify_credential(self, credential_id, headers):
        return self._request("POST", f"/vrc/credentials/{credential_id}/verify", None, headers)

    def reject_credential(self, credential_id, headers):
        return self._request("POST", f"/vrc/credentials/{credential_id}/reject", None, headers)

    # --- BackgroundCheck ---
    def create_background_check(self, payload, headers):
        return self._request("POST", "/vrc/background-checks", payload, headers)

    def clear_background_check(self, check_id, headers):
        return self._request("POST", f"/vrc/background-checks/{check_id}/clear", None, headers)

    def flag_background_check(self, check_id, headers):
        return self._request("POST", f"/vrc/background-checks/{check_id}/flag", None, headers)

    # --- Clearance ---
    def create_clearance(self, payload, headers):
        return self._request("POST", "/vrc/clearances", payload, headers)

    def revoke_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"/vrc/clearances/{clearance_id}/revoke", payload, headers)

    # --- SupportRequest ---
    def create_support_request(self, payload, headers):
        return self._request("POST", "/vrc/support-requests", payload, headers)

    def get_support_request(self, request_id, headers):
        return self._request("GET", f"/vrc/support-requests/{request_id}", headers=headers)

    def update_support_request(self, request_id, payload, headers):
        return self._request("PUT", f"/vrc/support-requests/{request_id}", payload, headers)

    def publish_support_request(self, request_id, headers):
        return self._request("POST", f"/vrc/support-requests/{request_id}/publish", None, headers)

    def auto_match(self, request_id, headers):
        return self._request("POST", f"/vrc/support-requests/{request_id}/auto-match", None, headers)

    def cancel_support_request(self, request_id, headers):
        return self._request("POST", f"/vrc/support-requests/{request_id}/cancel", None, headers)

    def complete_support_request(self, request_id, headers):
        return self._request("POST", f"/vrc/support-requests/{request_id}/complete", None, headers)

    # --- SiteShift ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/vrc/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/vrc/shifts/{shift_id}", headers=headers)

    def open_roster(self, shift_id, headers):
        return self._request("POST", f"/vrc/shifts/{shift_id}/open-roster", None, headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/vrc/shifts/{shift_id}/cancel", None, headers)

    # --- DeploymentAssignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/vrc/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/vrc/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/vrc/assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vrc/assignments/{assignment_id}/accept", None, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vrc/assignments/{assignment_id}/decline", None, headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vrc/assignments/{assignment_id}/confirm", None, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vrc/assignments/{assignment_id}/cancel", None, headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vrc/assignments/{assignment_id}/check-in", None, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vrc/assignments/{assignment_id}/complete", None, headers)

    def no_show_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vrc/assignments/{assignment_id}/no-show", None, headers)

    def recall_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vrc/assignments/{assignment_id}/recall", None, headers)

    # --- TransportTrip ---
    def create_trip(self, payload, headers):
        return self._request("POST", "/vrc/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/vrc/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/vrc/trips", headers=headers, params=params)

    def depart_trip(self, trip_id, headers):
        return self._request("POST", f"/vrc/trips/{trip_id}/depart", None, headers)

    def arrive_trip(self, trip_id, headers):
        return self._request("POST", f"/vrc/trips/{trip_id}/arrive", None, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/vrc/trips/{trip_id}/cancel", None, headers)

    # --- SeatBooking ---
    def create_seat_booking(self, payload, headers):
        return self._request("POST", "/vrc/seat-bookings", payload, headers)

    def get_seat_booking(self, booking_id, headers):
        return self._request("GET", f"/vrc/seat-bookings/{booking_id}", headers=headers)

    def list_seat_bookings(self, headers, params=None):
        return self._request("GET", "/vrc/seat-bookings", headers=headers, params=params)

    def board_seat_booking(self, booking_id, headers):
        return self._request("POST", f"/vrc/seat-bookings/{booking_id}/board", None, headers)

    def cancel_seat_booking(self, booking_id, headers):
        return self._request("POST", f"/vrc/seat-bookings/{booking_id}/cancel", None, headers)

    def mark_seat_no_show(self, booking_id, headers):
        return self._request("POST", f"/vrc/seat-bookings/{booking_id}/mark-no-show", None, headers)

    # --- PPEIssuance ---
    def create_ppe_issuance(self, payload, headers):
        return self._request("POST", "/vrc/ppe-issuances", payload, headers)

    def close_ppe_issuance(self, issuance_id, payload, headers):
        return self._request("POST", f"/vrc/ppe-issuances/{issuance_id}/close", payload, headers)

    # --- HourEntry ---
    def create_hour_entry(self, payload, headers):
        return self._request("POST", "/vrc/hour-entries", payload, headers)

    def verify_hour_entry(self, entry_id, headers):
        return self._request("POST", f"/vrc/hour-entries/{entry_id}/verify", None, headers)

    def dispute_hour_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/vrc/hour-entries/{entry_id}/dispute", payload, headers)

    def resubmit_hour_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/vrc/hour-entries/{entry_id}/resubmit", payload, headers)

    def list_assignment_hour_entries(self, assignment_id, headers, params=None):
        return self._request("GET", f"/vrc/assignments/{assignment_id}/hour-entries", headers=headers, params=params)

    # --- RiskReport ---
    def create_risk_report(self, payload, headers):
        return self._request("POST", "/vrc/risk-reports", payload, headers)

    def substantiate_risk_report(self, report_id, headers):
        return self._request("POST", f"/vrc/risk-reports/{report_id}/substantiate", None, headers)

    def dismiss_risk_report(self, report_id, headers):
        return self._request("POST", f"/vrc/risk-reports/{report_id}/dismiss", None, headers)


api_client = ApiClient()
