"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Household ---
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def patch_household(self, household_id, payload, headers):
        return self._request("PATCH", f"/households/{household_id}", payload, headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    def list_household_members(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}/members", headers=headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def patch_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}", payload, headers)

    # --- PledgeCampaign ---
    def create_pledge_campaign(self, payload, headers):
        return self._request("POST", "/pledge-campaigns", payload, headers)

    def activate_pledge_campaign(self, campaign_id, headers):
        return self._request("POST", f"/pledge-campaigns/{campaign_id}/activate", {}, headers)

    def close_pledge_campaign(self, campaign_id, headers):
        return self._request("POST", f"/pledge-campaigns/{campaign_id}/close", {}, headers)

    def get_pledge_campaign(self, campaign_id, headers, params=None):
        return self._request("GET", f"/pledge-campaigns/{campaign_id}", headers=headers, params=params)

    # --- Pledge ---
    def create_pledge(self, payload, headers):
        return self._request("POST", "/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/pledges/{pledge_id}", headers=headers)

    def cancel_pledge(self, pledge_id, headers):
        return self._request("POST", f"/pledges/{pledge_id}/cancel", {}, headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/pledges", headers=headers, params=params)

    # --- Donation ---
    def create_donation(self, payload, headers):
        return self._request("POST", "/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    def post_donation(self, donation_id, headers):
        return self._request("POST", f"/donations/{donation_id}/post", {}, headers)

    def refund_donation(self, donation_id, headers):
        return self._request("POST", f"/donations/{donation_id}/refund", {}, headers)

    def mark_failed_donation(self, donation_id, headers):
        return self._request("POST", f"/donations/{donation_id}/mark-failed", {}, headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/donations", headers=headers, params=params)

    # --- YearEndStatement ---
    def create_year_end_statement(self, payload, headers):
        return self._request("POST", "/year-end-statements", payload, headers)

    def get_year_end_statement(self, statement_id, headers):
        return self._request("GET", f"/year-end-statements/{statement_id}", headers=headers)

    def issue_year_end_statement(self, statement_id, headers):
        return self._request("POST", f"/year-end-statements/{statement_id}/issue", {}, headers)

    def void_year_end_statement(self, statement_id, headers):
        return self._request("POST", f"/year-end-statements/{statement_id}/void", {}, headers)

    def regenerate_year_end_statement(self, statement_id, headers):
        return self._request("POST", f"/year-end-statements/{statement_id}/regenerate", {}, headers)

    def list_year_end_statements(self, headers, params=None):
        return self._request("GET", "/year-end-statements", headers=headers, params=params)

    # --- Facility & Booking ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def create_facility_booking(self, payload, headers):
        return self._request("POST", "/facility-bookings", payload, headers)

    def get_facility_booking(self, booking_id, headers):
        return self._request("GET", f"/facility-bookings/{booking_id}", headers=headers)

    def cancel_facility_booking(self, booking_id, headers):
        return self._request("POST", f"/facility-bookings/{booking_id}/cancel", {}, headers)

    def list_facility_bookings(self, headers, params=None):
        return self._request("GET", "/facility-bookings", headers=headers, params=params)

    # --- Event ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", {}, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    # --- VolunteerAssignment ---
    def create_volunteer_assignment(self, payload, headers):
        return self._request("POST", "/volunteer-assignments", payload, headers)

    def get_volunteer_assignment(self, assignment_id, headers):
        return self._request("GET", f"/volunteer-assignments/{assignment_id}", headers=headers)

    def accept_volunteer_assignment(self, assignment_id, headers):
        return self._request("POST", f"/volunteer-assignments/{assignment_id}/accept", {}, headers)

    def decline_volunteer_assignment(self, assignment_id, headers):
        return self._request("POST", f"/volunteer-assignments/{assignment_id}/decline", {}, headers)

    def cancel_volunteer_assignment(self, assignment_id, headers):
        return self._request("POST", f"/volunteer-assignments/{assignment_id}/cancel", {}, headers)

    def checkin_volunteer_assignment(self, assignment_id, headers):
        return self._request("POST", f"/volunteer-assignments/{assignment_id}/checkin", {}, headers)

    def list_volunteer_assignments(self, headers, params=None):
        return self._request("GET", "/volunteer-assignments", headers=headers, params=params)

    # --- SmallGroup & GroupMembership ---
    def create_small_group(self, payload, headers):
        return self._request("POST", "/small-groups", payload, headers)

    def get_small_group(self, group_id, headers):
        return self._request("GET", f"/small-groups/{group_id}", headers=headers)

    def list_small_groups(self, headers, params=None):
        return self._request("GET", "/small-groups", headers=headers, params=params)

    def create_group_membership(self, payload, headers):
        return self._request("POST", "/group-memberships", payload, headers)

    def get_group_membership(self, membership_id, headers):
        return self._request("GET", f"/group-memberships/{membership_id}", headers=headers)

    def deactivate_group_membership(self, membership_id, headers):
        return self._request("POST", f"/group-memberships/{membership_id}/deactivate", {}, headers)

    def list_group_memberships(self, headers, params=None):
        return self._request("GET", "/group-memberships", headers=headers, params=params)

    # --- ChildCheckIn ---
    def create_child_checkin(self, payload, headers):
        return self._request("POST", "/child-checkins", payload, headers)

    def get_child_checkin(self, checkin_id, headers):
        return self._request("GET", f"/child-checkins/{checkin_id}", headers=headers)

    def checkout_child_checkin(self, checkin_id, payload, headers):
        return self._request("POST", f"/child-checkins/{checkin_id}/checkout", payload, headers)

    def security_hold_child_checkin(self, checkin_id, headers):
        return self._request("POST", f"/child-checkins/{checkin_id}/security-hold", {}, headers)

    def clear_hold_child_checkin(self, checkin_id, headers):
        return self._request("POST", f"/child-checkins/{checkin_id}/clear-hold", {}, headers)

    def list_child_checkins(self, headers, params=None):
        return self._request("GET", "/child-checkins", headers=headers, params=params)

    # --- Test-driving endpoints ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def simulate_payment(self, donation_id, outcome, headers):
        return self._request("POST", "/_payments/simulate",
                             {"donation_id": donation_id, "outcome": outcome}, headers)


api_client = ApiClient()
