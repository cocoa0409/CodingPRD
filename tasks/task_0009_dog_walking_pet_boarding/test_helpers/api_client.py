"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Owners ----
    def register_owner(self, payload, headers):
        return self._request("POST", "/api/v1/owners/register", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/api/v1/owners/{owner_id}", headers=headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/api/v1/owners", headers=headers, params=params)

    # ---- Sitters ----
    def register_sitter(self, payload, headers):
        return self._request("POST", "/api/v1/sitters/register", payload, headers)

    def get_sitter(self, sitter_id, headers):
        return self._request("GET", f"/api/v1/sitters/{sitter_id}", headers=headers)

    def list_sitters(self, headers, params=None):
        return self._request("GET", "/api/v1/sitters", headers=headers, params=params)

    def reinstate_sitter(self, sitter_id, headers, payload=None):
        return self._request("POST", f"/api/v1/sitters/{sitter_id}/reinstate", payload or {}, headers)

    def deactivate_sitter(self, sitter_id, headers, payload=None):
        return self._request("POST", f"/api/v1/sitters/{sitter_id}/deactivate", payload or {}, headers)

    def recompute_tier(self, sitter_id, headers, payload=None):
        return self._request("POST", f"/api/v1/sitters/{sitter_id}/recompute-tier", payload or {}, headers)

    # ---- Background Checks ----
    def create_background_check(self, payload, headers):
        return self._request("POST", "/api/v1/background-checks", payload, headers)

    def get_background_check(self, bg_id, headers):
        return self._request("GET", f"/api/v1/background-checks/{bg_id}", headers=headers)

    def list_background_checks(self, headers, params=None):
        return self._request("GET", "/api/v1/background-checks", headers=headers, params=params)

    def clear_background_check(self, bg_id, headers, payload=None):
        return self._request("POST", f"/api/v1/background-checks/{bg_id}/clear", payload or {}, headers)

    def flag_background_check(self, bg_id, payload, headers):
        return self._request("POST", f"/api/v1/background-checks/{bg_id}/flag", payload, headers)

    # ---- Pets ----
    def create_pet(self, payload, headers):
        return self._request("POST", "/api/v1/pets", payload, headers)

    def get_pet(self, pet_id, headers):
        return self._request("GET", f"/api/v1/pets/{pet_id}", headers=headers)

    def list_pets(self, headers, params=None):
        return self._request("GET", "/api/v1/pets", headers=headers, params=params)

    # ---- Emergency Contacts ----
    def create_emergency_contact(self, payload, headers):
        return self._request("POST", "/api/v1/emergency-contacts", payload, headers)

    def get_emergency_contact(self, ec_id, headers):
        return self._request("GET", f"/api/v1/emergency-contacts/{ec_id}", headers=headers)

    def list_emergency_contacts(self, headers, params=None):
        return self._request("GET", "/api/v1/emergency-contacts", headers=headers, params=params)

    # ---- Meet and Greets ----
    def create_meet_and_greet(self, payload, headers):
        return self._request("POST", "/api/v1/meet-and-greets", payload, headers)

    def get_meet_and_greet(self, mg_id, headers):
        return self._request("GET", f"/api/v1/meet-and-greets/{mg_id}", headers=headers)

    def list_meet_and_greets(self, headers, params=None):
        return self._request("GET", "/api/v1/meet-and-greets", headers=headers, params=params)

    def approve_meet_and_greet(self, mg_id, headers, payload=None):
        return self._request("POST", f"/api/v1/meet-and-greets/{mg_id}/approve", payload or {}, headers)

    def decline_meet_and_greet(self, mg_id, headers, payload=None):
        return self._request("POST", f"/api/v1/meet-and-greets/{mg_id}/decline", payload or {}, headers)

    def mark_no_show_meet_and_greet(self, mg_id, headers, payload=None):
        return self._request("POST", f"/api/v1/meet-and-greets/{mg_id}/mark-no-show", payload or {}, headers)

    def cancel_meet_and_greet(self, mg_id, headers, payload=None):
        return self._request("POST", f"/api/v1/meet-and-greets/{mg_id}/cancel", payload or {}, headers)

    # ---- Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/api/v1/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/api/v1/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/api/v1/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/api/v1/bookings/{booking_id}/confirm", payload or {}, headers)

    def reject_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/api/v1/bookings/{booking_id}/reject", payload, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/api/v1/bookings/{booking_id}/cancel", payload, headers)

    def start_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/api/v1/bookings/{booking_id}/start", payload or {}, headers)

    def complete_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/api/v1/bookings/{booking_id}/complete", payload, headers)

    def emergency_terminate_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/api/v1/bookings/{booking_id}/emergency-terminate", payload, headers)

    # ---- Key Handoffs ----
    def create_key_handoff(self, payload, headers):
        return self._request("POST", "/api/v1/key-handoffs", payload, headers)

    def get_key_handoff(self, kh_id, headers):
        return self._request("GET", f"/api/v1/key-handoffs/{kh_id}", headers=headers)

    def list_key_handoffs(self, headers, params=None):
        return self._request("GET", "/api/v1/key-handoffs", headers=headers, params=params)

    def receive_key_handoff(self, kh_id, headers, payload=None):
        return self._request("POST", f"/api/v1/key-handoffs/{kh_id}/receive", payload or {}, headers)

    # ---- GPS Tracks ----
    def create_gps_track(self, payload, headers):
        return self._request("POST", "/api/v1/gps-tracks", payload, headers)

    def get_gps_track(self, gt_id, headers):
        return self._request("GET", f"/api/v1/gps-tracks/{gt_id}", headers=headers)

    def list_gps_tracks(self, headers, params=None):
        return self._request("GET", "/api/v1/gps-tracks", headers=headers, params=params)

    # ---- Insurance Claims ----
    def create_insurance_claim(self, payload, headers):
        return self._request("POST", "/api/v1/insurance-claims", payload, headers)

    def get_insurance_claim(self, ic_id, headers):
        return self._request("GET", f"/api/v1/insurance-claims/{ic_id}", headers=headers)

    def list_insurance_claims(self, headers, params=None):
        return self._request("GET", "/api/v1/insurance-claims", headers=headers, params=params)

    def start_review_insurance_claim(self, ic_id, headers, payload=None):
        return self._request("POST", f"/api/v1/insurance-claims/{ic_id}/start-review", payload or {}, headers)

    def approve_insurance_claim(self, ic_id, payload, headers):
        return self._request("POST", f"/api/v1/insurance-claims/{ic_id}/approve", payload, headers)

    def revert_insurance_claim(self, ic_id, headers, payload=None):
        return self._request("POST", f"/api/v1/insurance-claims/{ic_id}/revert", payload or {}, headers)

    def pay_insurance_claim(self, ic_id, headers, payload=None):
        return self._request("POST", f"/api/v1/insurance-claims/{ic_id}/pay", payload or {}, headers)

    def deny_insurance_claim(self, ic_id, payload, headers):
        return self._request("POST", f"/api/v1/insurance-claims/{ic_id}/deny", payload, headers)

    def withdraw_insurance_claim(self, ic_id, headers, payload=None):
        return self._request("POST", f"/api/v1/insurance-claims/{ic_id}/withdraw", payload or {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/api/v1/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )


api_client = ApiClient()
