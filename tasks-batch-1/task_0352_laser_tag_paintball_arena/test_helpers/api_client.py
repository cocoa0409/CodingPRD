"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Arena ---
    def create_arena(self, payload, headers):
        return self._request("POST", "/arenas", payload, headers)

    def get_arena(self, arena_id, headers):
        return self._request("GET", f"/arenas/{arena_id}", headers=headers)

    def list_arenas(self, headers, params=None):
        return self._request("GET", "/arenas", headers=headers, params=params)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def close_arena(self, arena_id, headers):
        return self._request("POST", f"/arenas/{arena_id}/close", headers=headers)

    # --- Field ---
    def create_field(self, payload, headers):
        return self._request("POST", "/fields", payload, headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/fields/{field_id}", headers=headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/fields", headers=headers, params=params)

    def close_field(self, field_id, headers):
        return self._request("POST", f"/fields/{field_id}/close", headers=headers)

    # --- PartyPackage ---
    def create_party_package(self, payload, headers):
        return self._request("POST", "/party-packages", payload, headers)

    def get_party_package(self, package_id, headers):
        return self._request("GET", f"/party-packages/{package_id}", headers=headers)

    def list_party_packages(self, headers, params=None):
        return self._request("GET", "/party-packages", headers=headers, params=params)

    # --- Booking ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", payload, headers)

    def check_in_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", payload, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", headers=headers)

    def no_show_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/no-show", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    # --- WaiverProfile ---
    def create_waiver_profile(self, payload, headers):
        return self._request("POST", "/waiver-profiles", payload, headers)

    def get_waiver_profile(self, waiver_id, headers):
        return self._request("GET", f"/waiver-profiles/{waiver_id}", headers=headers)

    def list_waiver_profiles(self, headers, params=None):
        return self._request("GET", "/waiver-profiles", headers=headers, params=params)

    def sign_waiver(self, waiver_id, headers):
        return self._request("POST", f"/waiver-profiles/{waiver_id}/sign", headers=headers)

    def void_waiver(self, waiver_id, headers):
        return self._request("POST", f"/waiver-profiles/{waiver_id}/void", headers=headers)

    # --- EquipmentUnit ---
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/equipment-units", payload, headers)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"/equipment-units/{unit_id}", headers=headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/equipment-units", headers=headers, params=params)

    def restore_equipment_unit(self, unit_id, headers):
        return self._request("POST", f"/equipment-units/{unit_id}/restore", headers=headers)

    # --- Rental ---
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def return_rental(self, rental_id, payload, headers):
        return self._request("POST", f"/rentals/{rental_id}/return", payload, headers)

    def release_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/release", headers=headers)

    # --- AddOnOrder ---
    def create_add_on_order(self, payload, headers):
        return self._request("POST", "/add-on-orders", payload, headers)

    def get_add_on_order(self, order_id, headers):
        return self._request("GET", f"/add-on-orders/{order_id}", headers=headers)

    def list_add_on_orders(self, headers, params=None):
        return self._request("GET", "/add-on-orders", headers=headers, params=params)

    # --- Referee ---
    def create_referee(self, payload, headers):
        return self._request("POST", "/referees", payload, headers)

    def get_referee(self, referee_id, headers):
        return self._request("GET", f"/referees/{referee_id}", headers=headers)

    def list_referees(self, headers, params=None):
        return self._request("GET", "/referees", headers=headers, params=params)

    # --- RefereeAssignment ---
    def create_referee_assignment(self, payload, headers):
        return self._request("POST", "/referee-assignments", payload, headers)

    def get_referee_assignment(self, assignment_id, headers):
        return self._request("GET", f"/referee-assignments/{assignment_id}", headers=headers)

    def list_referee_assignments(self, headers, params=None):
        return self._request("GET", "/referee-assignments", headers=headers, params=params)

    # --- League ---
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_leagues(self, headers, params=None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    def get_standings(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}/standings", headers=headers)

    def open_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/open", headers=headers)

    def lock_round(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/lock-round", payload, headers)

    def advance_round(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/advance-round", payload, headers)

    def finalize_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/finalize", headers=headers)

    # --- LeagueMatch ---
    def create_league_match(self, payload, headers):
        return self._request("POST", "/league-matches", payload, headers)

    def get_league_match(self, match_id, headers):
        return self._request("GET", f"/league-matches/{match_id}", headers=headers)

    def list_league_matches(self, headers, params=None):
        return self._request("GET", "/league-matches", headers=headers, params=params)

    def record_match_result(self, match_id, payload, headers):
        return self._request("POST", f"/league-matches/{match_id}/record-result", payload, headers)

    def void_match(self, match_id, headers):
        return self._request("POST", f"/league-matches/{match_id}/void", headers=headers)


api_client = ApiClient()
