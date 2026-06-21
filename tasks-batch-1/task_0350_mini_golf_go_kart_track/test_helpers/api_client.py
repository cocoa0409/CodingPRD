"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP envelope. Every method returns the raw Response for the validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Venue ───────────────────────────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def weather_hold_venue(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/weather-hold", payload, headers)

    def resume_venue(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/resume", payload, headers)

    def close_venue(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/close", payload, headers)

    def set_venue_clock(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/_clock/set_current_utc", payload, headers
        )

    # ─── Attraction ──────────────────────────────────────────────────────────
    def create_attraction(self, payload, headers):
        return self._request("POST", "/attractions", payload, headers)

    def get_attraction(self, attraction_id, headers):
        return self._request("GET", f"/attractions/{attraction_id}", headers=headers)

    def list_attractions(self, headers, params=None):
        return self._request("GET", "/attractions", headers=headers, params=params)

    # ─── PricingPlan ─────────────────────────────────────────────────────────
    def create_pricing_plan(self, payload, headers):
        return self._request("POST", "/pricing-plans", payload, headers)

    def get_pricing_plan(self, pricing_plan_id, headers):
        return self._request("GET", f"/pricing-plans/{pricing_plan_id}", headers=headers)

    def list_pricing_plans(self, headers, params=None):
        return self._request("GET", "/pricing-plans", headers=headers, params=params)

    # ─── Heat ────────────────────────────────────────────────────────────────
    def create_heat(self, payload, headers):
        return self._request("POST", "/heats", payload, headers)

    def get_heat(self, heat_id, headers):
        return self._request("GET", f"/heats/{heat_id}", headers=headers)

    def list_heats(self, headers, params=None):
        return self._request("GET", "/heats", headers=headers, params=params)

    def open_heat(self, heat_id, headers):
        return self._request("POST", f"/heats/{heat_id}/open", {}, headers)

    def close_heat(self, heat_id, headers):
        return self._request("POST", f"/heats/{heat_id}/close", {}, headers)

    def cancel_heat(self, heat_id, headers):
        return self._request("POST", f"/heats/{heat_id}/cancel", {}, headers)

    # ─── TeeSession ──────────────────────────────────────────────────────────
    def create_tee_session(self, payload, headers):
        return self._request("POST", "/tee-sessions", payload, headers)

    def get_tee_session(self, tee_session_id, headers):
        return self._request("GET", f"/tee-sessions/{tee_session_id}", headers=headers)

    def list_tee_sessions(self, headers, params=None):
        return self._request("GET", "/tee-sessions", headers=headers, params=params)

    def open_tee_session(self, tee_session_id, headers):
        return self._request("POST", f"/tee-sessions/{tee_session_id}/open", {}, headers)

    def close_tee_session(self, tee_session_id, headers):
        return self._request("POST", f"/tee-sessions/{tee_session_id}/close", {}, headers)

    def cancel_tee_session(self, tee_session_id, headers):
        return self._request("POST", f"/tee-sessions/{tee_session_id}/cancel", {}, headers)

    # ─── Guest / Waiver ──────────────────────────────────────────────────────
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def list_guests(self, headers, params=None):
        return self._request("GET", "/guests", headers=headers, params=params)

    def create_waiver(self, payload, headers):
        return self._request("POST", "/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    # ─── Wallet ──────────────────────────────────────────────────────────────
    def get_wallet(self, wallet_id, headers):
        return self._request("GET", f"/wallets/{wallet_id}", headers=headers)

    def list_wallets(self, headers, params=None):
        return self._request("GET", "/wallets", headers=headers, params=params)

    def top_up_wallet(self, wallet_id, payload, headers):
        return self._request("POST", f"/wallets/{wallet_id}/top-ups", payload, headers)

    def redeem_wallet(self, wallet_id, payload, headers):
        return self._request("POST", f"/wallets/{wallet_id}/redemptions", payload, headers)

    # ─── ComboPass ───────────────────────────────────────────────────────────
    def create_combo_pass(self, payload, headers):
        return self._request("POST", "/combo-passes", payload, headers)

    def get_combo_pass(self, combo_pass_id, headers):
        return self._request("GET", f"/combo-passes/{combo_pass_id}", headers=headers)

    def list_combo_passes(self, headers, params=None):
        return self._request("GET", "/combo-passes", headers=headers, params=params)

    # ─── PartyGroup ──────────────────────────────────────────────────────────
    def create_party_group(self, payload, headers):
        return self._request("POST", "/party-groups", payload, headers)

    def get_party_group(self, group_id, headers):
        return self._request("GET", f"/party-groups/{group_id}", headers=headers)

    def list_party_groups(self, headers, params=None):
        return self._request("GET", "/party-groups", headers=headers, params=params)

    def confirm_party_group(self, group_id, payload, headers):
        return self._request("POST", f"/party-groups/{group_id}/confirm", payload, headers)

    def check_in_party_group(self, group_id, headers):
        return self._request("POST", f"/party-groups/{group_id}/check-in", {}, headers)

    def cancel_party_group(self, group_id, headers):
        return self._request("POST", f"/party-groups/{group_id}/cancel", {}, headers)

    # ─── Booking ─────────────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", payload, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def no_show_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/no-show", {}, headers)


api_client = ApiClient()
