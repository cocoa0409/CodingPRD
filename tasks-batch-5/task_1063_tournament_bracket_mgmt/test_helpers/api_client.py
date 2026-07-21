"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Venues & Stations ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def create_station(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/stations", payload, headers)

    def list_venue_stations(self, venue_id, headers, params=None):
        return self._request("GET", f"/venues/{venue_id}/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    # --- Stream channels ---
    def create_stream_channel(self, payload, headers):
        return self._request("POST", "/stream-channels", payload, headers)

    def get_stream_channel(self, channel_id, headers):
        return self._request("GET", f"/stream-channels/{channel_id}", headers=headers)

    # --- Players ---
    def create_player(self, payload, headers):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    # --- Tournaments ---
    def create_tournament(self, payload, headers):
        return self._request("POST", "/tournaments", payload, headers)

    def list_tournaments(self, headers, params=None):
        return self._request("GET", "/tournaments", headers=headers, params=params)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/tournaments/{tournament_id}", headers=headers)

    def open_registration(self, tournament_id, payload, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/open-registration", payload, headers)

    def close_registration(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/close-registration", {}, headers)

    def generate_bracket(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/generate-bracket", {}, headers)

    def start_tournament(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/start", {}, headers)

    def complete_tournament(self, tournament_id, payload, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/complete", payload, headers)

    def cancel_tournament(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/cancel", {}, headers)

    def get_standings(self, tournament_id, headers):
        return self._request("GET", f"/tournaments/{tournament_id}/standings", headers=headers)

    def list_tournament_matches(self, tournament_id, headers, params=None):
        return self._request("GET", f"/tournaments/{tournament_id}/matches", headers=headers, params=params)

    def list_tournament_registrations(self, tournament_id, headers, params=None):
        return self._request("GET", f"/tournaments/{tournament_id}/registrations", headers=headers, params=params)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def check_in(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/check-in", {}, headers)

    def withdraw(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/withdraw", {}, headers)

    # --- Matches ---
    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def schedule_match(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/schedule", payload, headers)

    def report_match(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/report", payload, headers)

    def confirm_match(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/confirm", payload, headers)

    def replay_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/replay", {}, headers)

    # --- Stream assignments ---
    def create_stream_assignment(self, payload, headers):
        return self._request("POST", "/stream-assignments", payload, headers)

    def get_stream_assignment(self, assignment_id, headers):
        return self._request("GET", f"/stream-assignments/{assignment_id}", headers=headers)

    def list_stream_assignments(self, headers, params=None):
        return self._request("GET", "/stream-assignments", headers=headers, params=params)

    # --- Disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # --- Payouts ---
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def pay_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/pay", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
