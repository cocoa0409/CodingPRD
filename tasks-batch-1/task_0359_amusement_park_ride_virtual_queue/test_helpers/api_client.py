"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Park ----
    def create_park(self, payload, headers):
        return self._request("POST", "/parks", payload, headers)

    def get_park(self, park_id, headers):
        return self._request("GET", f"/parks/{park_id}", headers=headers)

    def admit(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/admissions", payload, headers)

    def exit_guest(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/exits", payload, headers)

    def advance_windows(self, park_id, headers):
        return self._request("POST", f"/parks/{park_id}/advance-windows", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Ride + ReturnWindow ----
    def create_ride(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/rides", payload, headers)

    def list_rides(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/rides", headers=headers, params=params)

    def get_ride(self, ride_id, headers):
        return self._request("GET", f"/rides/{ride_id}", headers=headers)

    def create_return_window(self, ride_id, payload, headers):
        return self._request("POST", f"/rides/{ride_id}/return-windows", payload, headers)

    def list_return_windows(self, ride_id, headers, params=None):
        return self._request("GET", f"/rides/{ride_id}/return-windows", headers=headers, params=params)

    def get_return_window(self, window_id, headers):
        return self._request("GET", f"/return-windows/{window_id}", headers=headers)

    def declare_down(self, ride_id, headers):
        return self._request("POST", f"/rides/{ride_id}/declare-down", {}, headers)

    def restore_ride(self, ride_id, headers):
        return self._request("POST", f"/rides/{ride_id}/restore", {}, headers)

    def close_ride(self, ride_id, headers):
        return self._request("POST", f"/rides/{ride_id}/close", {}, headers)

    def redistribute(self, ride_id, headers):
        return self._request("POST", f"/rides/{ride_id}/redistribute", {}, headers)

    # ---- Guest + GuestDayTicket ----
    def create_guest(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/guests", payload, headers)

    def list_park_guests(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/guests", headers=headers, params=params)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def list_guests(self, headers, params=None):
        return self._request("GET", "/guests", headers=headers, params=params)

    def create_day_ticket(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/day-tickets", payload, headers)

    def list_park_day_tickets(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/day-tickets", headers=headers, params=params)

    def get_day_ticket(self, ticket_id, headers):
        return self._request("GET", f"/day-tickets/{ticket_id}", headers=headers)

    def list_day_tickets(self, headers, params=None):
        return self._request("GET", "/day-tickets", headers=headers, params=params)

    # ---- Party + PartyMembership ----
    def create_party(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/parties", payload, headers)

    def list_park_parties(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/parties", headers=headers, params=params)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/parties/{party_id}", headers=headers)

    def list_parties(self, headers, params=None):
        return self._request("GET", "/parties", headers=headers, params=params)

    def add_member(self, party_id, payload, headers):
        return self._request("POST", f"/parties/{party_id}/members", payload, headers)

    def list_members(self, party_id, headers, params=None):
        return self._request("GET", f"/parties/{party_id}/members", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/party-memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/party-memberships", headers=headers, params=params)

    def remove_member(self, party_id, guest_id, headers):
        return self._request("DELETE", f"/parties/{party_id}/members/{guest_id}", headers=headers)

    def party_book(self, party_id, payload, headers):
        return self._request("POST", f"/parties/{party_id}/party-book", payload, headers)

    def release_lock(self, party_id, headers):
        return self._request("POST", f"/parties/{party_id}/release-lock", {}, headers)

    def disband(self, party_id, headers):
        return self._request("POST", f"/parties/{party_id}/disband", {}, headers)

    # ---- EntitlementPlan + LightningLanePurchase ----
    def create_entitlement_plan(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/entitlement-plans", payload, headers)

    def list_entitlement_plans(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/entitlement-plans", headers=headers, params=params)

    def create_lightning_lane_purchase(self, payload, headers):
        return self._request("POST", "/lightning-lane-purchases", payload, headers)

    def list_lightning_lane_purchases(self, headers, params=None):
        return self._request("GET", "/lightning-lane-purchases", headers=headers, params=params)

    def get_lightning_lane_purchase(self, purchase_id, headers):
        return self._request("GET", f"/lightning-lane-purchases/{purchase_id}", headers=headers)

    def redeem_lightning_lane_purchase(self, purchase_id, headers):
        return self._request("POST", f"/lightning-lane-purchases/{purchase_id}/redeem", {}, headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", {}, headers)

    def redeem_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/redeem", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)


api_client = ApiClient()
