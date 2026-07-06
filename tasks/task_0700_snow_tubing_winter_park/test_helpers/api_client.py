"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- patrons ----
    def create_patron(self, payload, headers=None):
        return self._request("POST", "/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/patrons/{patron_id}", headers=headers)

    # ---- parks ----
    def create_park(self, payload, headers=None):
        return self._request("POST", "/parks", payload, headers)

    def get_park(self, park_id, headers):
        return self._request("GET", f"/parks/{park_id}", headers=headers)

    def list_parks(self, headers, params=None):
        return self._request("GET", "/parks", headers=headers, params=params)

    # ---- lanes ----
    def create_lane(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/lanes", payload, headers)

    def list_lanes(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/lanes", headers=headers, params=params)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/lanes/{lane_id}", headers=headers)

    def groom_lane(self, lane_id, headers):
        return self._request("POST", f"/lanes/{lane_id}/groom", {}, headers)

    def reopen_lane(self, lane_id, headers):
        return self._request("POST", f"/lanes/{lane_id}/reopen", {}, headers)

    def close_lane(self, lane_id, headers):
        return self._request("POST", f"/lanes/{lane_id}/close", {}, headers)

    # ---- time blocks ----
    def create_time_block(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/time-blocks", payload, headers)

    def list_time_blocks(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/time-blocks", headers=headers, params=params)

    def get_time_block(self, time_block_id, headers):
        return self._request("GET", f"/time-blocks/{time_block_id}", headers=headers)

    def activate_time_block(self, time_block_id, headers):
        return self._request("POST", f"/time-blocks/{time_block_id}/activate", {}, headers)

    def sweep_time_block(self, time_block_id, headers):
        return self._request("POST", f"/time-blocks/{time_block_id}/sweep", {}, headers)

    # ---- weather ----
    def create_weather_log(self, park_id, payload, headers):
        return self._request("POST", f"/parks/{park_id}/weather-logs", payload, headers)

    def list_weather_logs(self, park_id, headers, params=None):
        return self._request("GET", f"/parks/{park_id}/weather-logs", headers=headers, params=params)

    # ---- waivers ----
    def create_waiver(self, payload, headers):
        return self._request("POST", "/waivers", payload, headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def revoke_waiver(self, waiver_id, headers):
        return self._request("POST", f"/waivers/{waiver_id}/revoke", {}, headers)

    # ---- season passes ----
    def create_season_pass(self, payload, headers):
        return self._request("POST", "/season-passes", payload, headers)

    def list_season_passes(self, headers, params=None):
        return self._request("GET", "/season-passes", headers=headers, params=params)

    def get_season_pass(self, pass_id, headers):
        return self._request("GET", f"/season-passes/{pass_id}", headers=headers)

    def suspend_season_pass(self, pass_id, headers):
        return self._request("POST", f"/season-passes/{pass_id}/suspend", {}, headers)

    # ---- tickets ----
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def confirm_ticket(self, ticket_id, expected_time_block_version, headers):
        return self._request("POST", f"/tickets/{ticket_id}/confirm",
                             {"expected_time_block_version": expected_time_block_version}, headers)

    def refund_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/refund", {}, headers)

    def gear_up_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/gear-up", {}, headers)

    def board_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/board", payload, headers)

    def redeem_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/redeem", {}, headers)

    # ---- equipment rentals ----
    def create_equipment_rental(self, payload, headers):
        return self._request("POST", "/equipment-rentals", payload, headers)

    def list_equipment_rentals(self, headers, params=None):
        return self._request("GET", "/equipment-rentals", headers=headers, params=params)

    def get_equipment_rental(self, rental_id, headers):
        return self._request("GET", f"/equipment-rentals/{rental_id}", headers=headers)

    def return_equipment_rental(self, rental_id, headers):
        return self._request("POST", f"/equipment-rentals/{rental_id}/return", {}, headers)

    def report_damage_equipment_rental(self, rental_id, headers):
        return self._request("POST", f"/equipment-rentals/{rental_id}/report-damage", {}, headers)

    # ---- conveyor turns ----
    def list_conveyor_turns(self, headers, params=None):
        return self._request("GET", "/conveyor-turns", headers=headers, params=params)

    def get_conveyor_turn(self, turn_id, headers):
        return self._request("GET", f"/conveyor-turns/{turn_id}", headers=headers)

    def clear_conveyor_turn(self, turn_id, headers):
        return self._request("POST", f"/conveyor-turns/{turn_id}/clear", {}, headers)

    # ---- group reservations ----
    def create_group_reservation(self, payload, headers):
        return self._request("POST", "/group-reservations", payload, headers)

    def list_group_reservations(self, headers, params=None):
        return self._request("GET", "/group-reservations", headers=headers, params=params)

    def get_group_reservation(self, res_id, headers):
        return self._request("GET", f"/group-reservations/{res_id}", headers=headers)

    def hold_group_reservation(self, res_id, expected_time_block_version, headers):
        return self._request("POST", f"/group-reservations/{res_id}/hold",
                             {"expected_time_block_version": expected_time_block_version}, headers)

    def revise_group_reservation(self, res_id, headers):
        return self._request("POST", f"/group-reservations/{res_id}/revise", {}, headers)

    def confirm_group_reservation(self, res_id, headers):
        return self._request("POST", f"/group-reservations/{res_id}/confirm", {}, headers)

    def cancel_group_reservation(self, res_id, headers):
        return self._request("POST", f"/group-reservations/{res_id}/cancel", {}, headers)

    # ---- add-ons ----
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    def fulfill_add_on(self, add_on_id, headers):
        return self._request("POST", f"/add-ons/{add_on_id}/fulfill", {}, headers)

    def void_add_on(self, add_on_id, headers):
        return self._request("POST", f"/add-ons/{add_on_id}/void", {}, headers)

    # ---- refund entries ----
    def list_refund_entries(self, headers, params=None):
        return self._request("GET", "/refund-entries", headers=headers, params=params)

    def get_refund_entry(self, refund_id, headers):
        return self._request("GET", f"/refund-entries/{refund_id}", headers=headers)


api_client = ApiClient()
