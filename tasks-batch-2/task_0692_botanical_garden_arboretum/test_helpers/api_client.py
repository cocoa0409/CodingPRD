"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Garden ----
    def create_garden(self, payload, headers):
        return self._request("POST", "/v1/gardens", payload, headers)

    def get_garden(self, garden_id, headers):
        return self._request("GET", f"/v1/gardens/{garden_id}", headers=headers)

    # ---- MembershipPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/v1/membership-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/membership-plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/v1/membership-plans", headers=headers, params=params)

    # ---- Membership ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/v1/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/v1/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/v1/memberships", headers=headers, params=params)

    def activate_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/activate", {}, headers)

    def renew_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/renew", {}, headers)

    def reinstate_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/reinstate", {}, headers)

    def lapse_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/lapse", {}, headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/cancel", {}, headers)

    # ---- TimeSlot ----
    def create_time_slot(self, payload, headers):
        return self._request("POST", "/v1/time-slots", payload, headers)

    def get_time_slot(self, slot_id, headers):
        return self._request("GET", f"/v1/time-slots/{slot_id}", headers=headers)

    def list_time_slots(self, headers, params=None):
        return self._request("GET", "/v1/time-slots", headers=headers, params=params)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/v1/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/v1/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/v1/reservations", headers=headers, params=params)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/v1/reservations/{reservation_id}/check-in", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/v1/reservations/{reservation_id}/cancel", {}, headers)

    # ---- EventTicket ----
    def create_event_ticket(self, payload, headers):
        return self._request("POST", "/v1/event-tickets", payload, headers)

    def get_event_ticket(self, ticket_id, headers):
        return self._request("GET", f"/v1/event-tickets/{ticket_id}", headers=headers)

    def list_event_tickets(self, headers, params=None):
        return self._request("GET", "/v1/event-tickets", headers=headers, params=params)

    def refund_event_ticket(self, ticket_id, headers):
        return self._request("POST", f"/v1/event-tickets/{ticket_id}/refund", {}, headers)

    # ---- ProgramSession ----
    def create_program_session(self, payload, headers):
        return self._request("POST", "/v1/program-sessions", payload, headers)

    def get_program_session(self, session_id, headers):
        return self._request("GET", f"/v1/program-sessions/{session_id}", headers=headers)

    def list_program_sessions(self, headers, params=None):
        return self._request("GET", "/v1/program-sessions", headers=headers, params=params)

    def close_program_session(self, session_id, headers):
        return self._request("POST", f"/v1/program-sessions/{session_id}/close", {}, headers)

    # ---- Registration ----
    def create_registration(self, payload, headers):
        return self._request("POST", "/v1/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/v1/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/v1/registrations", headers=headers, params=params)

    def withdraw_registration(self, registration_id, headers):
        return self._request("POST", f"/v1/registrations/{registration_id}/withdraw", {}, headers)

    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/v1/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/v1/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/v1/venues", headers=headers, params=params)

    # ---- Rental ----
    def create_rental(self, payload, headers):
        return self._request("POST", "/v1/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/v1/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/v1/rentals", headers=headers, params=params)

    def confirm_rental(self, rental_id, headers):
        return self._request("POST", f"/v1/rentals/{rental_id}/confirm", {}, headers)

    def reject_rental(self, rental_id, headers):
        return self._request("POST", f"/v1/rentals/{rental_id}/reject", {}, headers)

    def cancel_rental(self, rental_id, headers):
        return self._request("POST", f"/v1/rentals/{rental_id}/cancel", {}, headers)

    # ---- Donation ----
    def create_donation(self, payload, headers):
        return self._request("POST", "/v1/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/v1/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/v1/donations", headers=headers, params=params)

    def void_donation(self, donation_id, headers):
        return self._request("POST", f"/v1/donations/{donation_id}/void", {}, headers)

    # ---- ConservancyFund ----
    def create_conservancy_fund(self, payload, headers):
        return self._request("POST", "/v1/conservancy-funds", payload, headers)

    def get_conservancy_fund(self, fund_id, headers):
        return self._request("GET", f"/v1/conservancy-funds/{fund_id}", headers=headers)

    def list_conservancy_funds(self, headers, params=None):
        return self._request("GET", "/v1/conservancy-funds", headers=headers, params=params)

    def close_campaign(self, fund_id, headers):
        return self._request("POST", f"/v1/conservancy-funds/{fund_id}/close-campaign", {}, headers)


api_client = ApiClient()
