"""API client: one method per endpoint defined in the Trampoline Park PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Park / clock ─────────────────────────────────
    def create_park(self, payload, headers):
        return self._request("POST", "/park", payload, headers)

    def get_park(self, park_id, headers):
        return self._request("GET", f"/park/{park_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/park/_clock/set_current_utc", payload, headers)

    # ─── SessionSlot ──────────────────────────────────
    def create_slot(self, payload, headers):
        return self._request("POST", "/park/slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/park/slots/{slot_id}", headers=headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/park/slots", headers=headers, params=params)

    def close_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"/park/slots/{slot_id}/close", payload or {}, headers)

    def sweep_no_shows(self, slot_id, headers, payload=None):
        return self._request("POST", f"/park/slots/{slot_id}/sweep-no-shows", payload or {}, headers)

    def list_slot_jump_passes(self, slot_id, headers, params=None):
        return self._request("GET", f"/park/slots/{slot_id}/jump-passes", headers=headers, params=params)

    def list_slot_party_bookings(self, slot_id, headers, params=None):
        return self._request("GET", f"/park/slots/{slot_id}/party-bookings", headers=headers, params=params)

    # ─── Participant ──────────────────────────────────
    def create_participant(self, payload, headers):
        return self._request("POST", "/park/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/park/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/park/participants", headers=headers, params=params)

    def list_participant_waivers(self, participant_id, headers, params=None):
        return self._request("GET", f"/park/participants/{participant_id}/waivers", headers=headers, params=params)

    # ─── Waiver ───────────────────────────────────────
    def create_waiver(self, payload, headers):
        return self._request("POST", "/park/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/park/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/park/waivers", headers=headers, params=params)

    # ─── JumpPass ─────────────────────────────────────
    def create_jump_pass(self, payload, headers):
        return self._request("POST", "/park/jump-passes", payload, headers)

    def get_jump_pass(self, pass_id, headers):
        return self._request("GET", f"/park/jump-passes/{pass_id}", headers=headers)

    def list_jump_passes(self, headers, params=None):
        return self._request("GET", "/park/jump-passes", headers=headers, params=params)

    def pay_jump_pass(self, pass_id, headers, payload=None):
        return self._request("POST", f"/park/jump-passes/{pass_id}/pay", payload or {}, headers)

    def check_in_jump_pass(self, pass_id, headers, payload=None):
        return self._request("POST", f"/park/jump-passes/{pass_id}/check-in", payload or {}, headers)

    def complete_jump_pass(self, pass_id, headers, payload=None):
        return self._request("POST", f"/park/jump-passes/{pass_id}/complete", payload or {}, headers)

    def cancel_jump_pass(self, pass_id, headers, payload=None):
        return self._request("POST", f"/park/jump-passes/{pass_id}/cancel", payload or {}, headers)

    def create_add_on(self, pass_id, payload, headers):
        return self._request("POST", f"/park/jump-passes/{pass_id}/add-ons", payload, headers)

    def list_add_ons(self, pass_id, headers, params=None):
        return self._request("GET", f"/park/jump-passes/{pass_id}/add-ons", headers=headers, params=params)

    # ─── Member / Membership ──────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/park/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/park/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/park/members", headers=headers, params=params)

    def list_member_memberships(self, member_id, headers, params=None):
        return self._request("GET", f"/park/members/{member_id}/memberships", headers=headers, params=params)

    def create_membership(self, payload, headers):
        return self._request("POST", "/park/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/park/memberships/{membership_id}", headers=headers)

    def renew_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/park/memberships/{membership_id}/renew", payload, headers)

    def cancel_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/park/memberships/{membership_id}/cancel", payload or {}, headers)

    # ─── PartyRoom / PartyPackage ─────────────────────
    def create_room(self, payload, headers):
        return self._request("POST", "/park/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/park/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/park/rooms", headers=headers, params=params)

    def list_room_party_bookings(self, room_id, headers, params=None):
        return self._request("GET", f"/park/rooms/{room_id}/party-bookings", headers=headers, params=params)

    def create_package(self, payload, headers):
        return self._request("POST", "/park/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/park/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/park/packages", headers=headers, params=params)

    # ─── PartyBooking ─────────────────────────────────
    def create_party_booking(self, payload, headers):
        return self._request("POST", "/park/party-bookings", payload, headers)

    def get_party_booking(self, booking_id, headers):
        return self._request("GET", f"/park/party-bookings/{booking_id}", headers=headers)

    def list_party_bookings(self, headers, params=None):
        return self._request("GET", "/park/party-bookings", headers=headers, params=params)

    def hold_deposit(self, booking_id, payload, headers):
        return self._request("POST", f"/park/party-bookings/{booking_id}/hold-deposit", payload, headers)

    def confirm_party_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/park/party-bookings/{booking_id}/confirm", payload or {}, headers)

    def check_in_party_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/park/party-bookings/{booking_id}/check-in", payload or {}, headers)

    def complete_party_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/park/party-bookings/{booking_id}/complete", payload or {}, headers)

    def cancel_party_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/park/party-bookings/{booking_id}/cancel", payload or {}, headers)

    # ─── IncidentReport ───────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/park/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/park/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/park/incidents", headers=headers, params=params)

    def review_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/park/incidents/{incident_id}/review", payload or {}, headers)

    def sign_off_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/park/incidents/{incident_id}/sign-off", payload or {}, headers)

    def void_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/park/incidents/{incident_id}/void", payload or {}, headers)


api_client = ApiClient()
