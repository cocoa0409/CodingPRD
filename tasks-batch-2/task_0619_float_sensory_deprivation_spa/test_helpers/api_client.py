"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- logical clock ----------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------- MembershipPlan ----------
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    # ---------- Member ----------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    # ---------- Membership ----------
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def activate_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/activate", {}, headers
        )

    def renew_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/renew", payload, headers
        )

    def mark_past_due_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/mark-past-due", {}, headers
        )

    def cancel_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/cancel", {}, headers
        )

    # ---------- CreditLedger ----------
    def get_credit_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/credit-ledger/{entry_id}", headers=headers)

    def list_credit_ledger(self, headers, params=None):
        return self._request("GET", "/credit-ledger", headers=headers, params=params)

    # ---------- Tank ----------
    def create_tank(self, payload, headers):
        return self._request("POST", "/tanks", payload, headers)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/tanks/{tank_id}", headers=headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/tanks", headers=headers, params=params)

    def tank_maintenance(self, tank_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/maintenance", {}, headers)

    def tank_return_to_service(self, tank_id, headers):
        return self._request(
            "POST", f"/tanks/{tank_id}/return-to-service", {}, headers
        )

    def tank_retire(self, tank_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/retire", {}, headers)

    # ---------- SanitationCycle ----------
    def create_sanitation_cycle(self, payload, headers):
        return self._request("POST", "/sanitation-cycles", payload, headers)

    def get_sanitation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/sanitation-cycles/{cycle_id}", headers=headers)

    def list_sanitation_cycles(self, headers, params=None):
        return self._request(
            "GET", "/sanitation-cycles", headers=headers, params=params
        )

    def complete_sanitation_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/sanitation-cycles/{cycle_id}/complete", {}, headers
        )

    # ---------- Attendant ----------
    def create_attendant(self, payload, headers):
        return self._request("POST", "/attendants", payload, headers)

    def get_attendant(self, attendant_id, headers):
        return self._request("GET", f"/attendants/{attendant_id}", headers=headers)

    def list_attendants(self, headers, params=None):
        return self._request("GET", "/attendants", headers=headers, params=params)

    # ---------- Orientation ----------
    def create_orientation(self, payload, headers):
        return self._request("POST", "/orientations", payload, headers)

    def get_orientation(self, orientation_id, headers):
        return self._request("GET", f"/orientations/{orientation_id}", headers=headers)

    def list_orientations(self, headers, params=None):
        return self._request("GET", "/orientations", headers=headers, params=params)

    def complete_orientation(self, orientation_id, headers):
        return self._request(
            "POST", f"/orientations/{orientation_id}/complete", {}, headers
        )

    def cancel_orientation(self, orientation_id, headers):
        return self._request(
            "POST", f"/orientations/{orientation_id}/cancel", {}, headers
        )

    # ---------- Booking ----------
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/bookings/{booking_id}/reschedule", payload, headers
        )

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def no_show_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/no-show", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    # ---------- Payment ----------
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ---------- GiftCard ----------
    def create_gift_card(self, payload, headers):
        return self._request("POST", "/gift-cards", payload, headers)

    def get_gift_card(self, gift_card_id, headers):
        return self._request("GET", f"/gift-cards/{gift_card_id}", headers=headers)

    def list_gift_cards(self, headers, params=None):
        return self._request("GET", "/gift-cards", headers=headers, params=params)

    def void_gift_card(self, gift_card_id, headers):
        return self._request("POST", f"/gift-cards/{gift_card_id}/void", {}, headers)


api_client = ApiClient()
