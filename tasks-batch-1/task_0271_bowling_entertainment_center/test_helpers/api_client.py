"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- RateCard ----
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/rate-cards", headers=headers, params=params)

    # ---- Lane ----
    def create_lane(self, payload, headers):
        return self._request("POST", "/lanes", payload, headers)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/lanes/{lane_id}", headers=headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/lanes", headers=headers, params=params)

    def set_lane_status(self, lane_id, payload, headers):
        return self._request("POST", f"/lanes/{lane_id}/set-status", payload, headers)

    # ---- Bay ----
    def create_bay(self, payload, headers):
        return self._request("POST", "/bays", payload, headers)

    def get_bay(self, bay_id, headers):
        return self._request("GET", f"/bays/{bay_id}", headers=headers)

    def list_bays(self, headers, params=None):
        return self._request("GET", "/bays", headers=headers, params=params)

    def set_bay_status(self, bay_id, payload, headers):
        return self._request("POST", f"/bays/{bay_id}/set-status", payload, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/reinstate", {}, headers)

    # ---- PartyPackage ----
    def create_party_package(self, payload, headers):
        return self._request("POST", "/party-packages", payload, headers)

    def get_party_package(self, party_package_id, headers):
        return self._request("GET", f"/party-packages/{party_package_id}", headers=headers)

    def list_party_packages(self, headers, params=None):
        return self._request("GET", "/party-packages", headers=headers, params=params)

    # ---- FoodItem ----
    def create_food_item(self, payload, headers):
        return self._request("POST", "/food-items", payload, headers)

    def get_food_item(self, food_item_id, headers):
        return self._request("GET", f"/food-items/{food_item_id}", headers=headers)

    def list_food_items(self, headers, params=None):
        return self._request("GET", "/food-items", headers=headers, params=params)

    # ---- RentalItem ----
    def create_rental_item(self, payload, headers):
        return self._request("POST", "/rental-items", payload, headers)

    def get_rental_item(self, rental_item_id, headers):
        return self._request("GET", f"/rental-items/{rental_item_id}", headers=headers)

    def list_rental_items(self, headers, params=None):
        return self._request("GET", "/rental-items", headers=headers, params=params)

    # ---- Reservation core ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def hold_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/hold", {}, headers)

    def confirm_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", payload, headers)

    def revise_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/revise", payload, headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", {}, headers)

    def complete_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/complete", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/no-show", {}, headers)

    def waitlist_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/waitlist", {}, headers)

    # ---- Food order lines ----
    def create_food_line(self, payload, headers):
        return self._request("POST", "/food-lines", payload, headers)

    def get_food_line(self, food_line_id, headers):
        return self._request("GET", f"/food-lines/{food_line_id}", headers=headers)

    def list_food_lines(self, headers, params=None):
        return self._request("GET", "/food-lines", headers=headers, params=params)

    def delete_food_line(self, food_line_id, headers):
        return self._request("DELETE", f"/food-lines/{food_line_id}", headers=headers)

    # ---- Rental lines ----
    def create_rental_line(self, payload, headers):
        return self._request("POST", "/rental-lines", payload, headers)

    def get_rental_line(self, rental_line_id, headers):
        return self._request("GET", f"/rental-lines/{rental_line_id}", headers=headers)

    def list_rental_lines(self, headers, params=None):
        return self._request("GET", "/rental-lines", headers=headers, params=params)

    def return_rental_line(self, rental_line_id, headers):
        return self._request("POST", f"/rental-lines/{rental_line_id}/return", {}, headers)

    # ---- League ----
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_leagues(self, headers, params=None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    def activate_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/activate", {}, headers)

    def close_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/close", {}, headers)

    # ---- LeagueNight ----
    def create_league_night(self, payload, headers):
        return self._request("POST", "/league-nights", payload, headers)

    def get_league_night(self, league_night_id, headers):
        return self._request("GET", f"/league-nights/{league_night_id}", headers=headers)

    def list_league_nights(self, headers, params=None):
        return self._request("GET", "/league-nights", headers=headers, params=params)

    def mark_played_league_night(self, league_night_id, headers):
        return self._request("POST", f"/league-nights/{league_night_id}/mark-played", {}, headers)

    def forfeit_league_night(self, league_night_id, headers):
        return self._request("POST", f"/league-nights/{league_night_id}/forfeit", {}, headers)

    def rain_out_league_night(self, league_night_id, headers):
        return self._request("POST", f"/league-nights/{league_night_id}/rain-out", {}, headers)

    # ---- Test-driving clock ----
    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
