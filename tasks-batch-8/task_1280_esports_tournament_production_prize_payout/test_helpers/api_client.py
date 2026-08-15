"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under /api. Methods return raw requests.Response
objects so tests can assert on status codes via the framework validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             payload, headers)

    # --- Tournaments ---
    def create_tournament(self, payload, headers):
        return self._request("POST", "/api/tournaments", payload, headers)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/api/tournaments/{tournament_id}",
                             headers=headers)

    def advance_tournament(self, tournament_id, payload, headers):
        return self._request("POST",
                             f"/api/tournaments/{tournament_id}/advance",
                             payload, headers)

    def fund_tournament(self, tournament_id, payload, headers):
        return self._request("POST", f"/api/tournaments/{tournament_id}/fund",
                             payload, headers)

    def generate_bracket(self, tournament_id, payload, headers):
        return self._request(
            "POST", f"/api/tournaments/{tournament_id}/generate-bracket",
            payload, headers)

    def compute_payout_records(self, tournament_id, payload, headers):
        return self._request(
            "POST",
            f"/api/tournaments/{tournament_id}/payout-records/compute",
            payload, headers)

    # --- Players ---
    def create_player(self, payload, headers):
        return self._request("POST", "/api/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/api/players/{player_id}",
                             headers=headers)

    def set_player_eligibility(self, player_id, payload, headers):
        return self._request("POST",
                             f"/api/players/{player_id}/eligibility",
                             payload, headers)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/api/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/api/registrations/{registration_id}",
                             headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/api/registrations", params or {},
                             headers)

    def submit_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/submit", {},
            headers)

    def review_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/review", payload,
            headers)

    def appeal_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/appeal", {},
            headers)

    # --- Roster slots ---
    def create_roster_slot(self, payload, headers):
        return self._request("POST", "/api/roster-slots", payload, headers)

    def remove_roster_slot(self, slot_id, headers):
        return self._request("POST", f"/api/roster-slots/{slot_id}/remove",
                             {}, headers)

    def get_roster_slot(self, slot_id, headers):
        return self._request("GET", f"/api/roster-slots/{slot_id}",
                             headers=headers)

    def list_roster_slots(self, headers, params=None):
        return self._request("GET", "/api/roster-slots", params or {},
                             headers)

    # --- Servers ---
    def create_server(self, payload, headers):
        return self._request("POST", "/api/servers", payload, headers)

    def get_server(self, server_id, headers):
        return self._request("GET", f"/api/servers/{server_id}",
                             headers=headers)

    def list_servers(self, headers, params=None):
        return self._request("GET", "/api/servers", params or {}, headers)

    def server_maintenance(self, server_id, payload, headers):
        return self._request("POST",
                             f"/api/servers/{server_id}/maintenance",
                             payload, headers)

    # --- Matches ---
    def get_match(self, match_id, headers):
        return self._request("GET", f"/api/matches/{match_id}",
                             headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/api/matches", params or {}, headers)

    def schedule_match(self, match_id, payload, headers):
        return self._request("POST", f"/api/matches/{match_id}/schedule",
                             payload, headers)

    def officiate_match(self, match_id, payload, headers):
        return self._request("POST", f"/api/matches/{match_id}/officiate",
                             payload, headers)

    def report_result(self, match_id, payload, headers):
        return self._request("POST", f"/api/matches/{match_id}/report-result",
                             payload, headers)

    def confirm_result(self, match_id, headers):
        return self._request("POST",
                             f"/api/matches/{match_id}/confirm-result", {},
                             headers)

    # --- Disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/api/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/api/disputes/{dispute_id}",
                             headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/api/disputes", params or {}, headers)

    def adjudicate_dispute(self, dispute_id, payload, headers):
        return self._request("POST",
                             f"/api/disputes/{dispute_id}/adjudicate",
                             payload, headers)

    def appeal_dispute(self, dispute_id, headers):
        return self._request("POST", f"/api/disputes/{dispute_id}/appeal",
                             {}, headers)

    # --- Integrity cases ---
    def create_integrity_case(self, payload, headers):
        return self._request("POST", "/api/integrity-cases", payload, headers)

    def get_integrity_case(self, case_id, headers):
        return self._request("GET", f"/api/integrity-cases/{case_id}",
                             headers=headers)

    def list_integrity_cases(self, headers, params=None):
        return self._request("GET", "/api/integrity-cases", params or {},
                             headers)

    def resolve_integrity_case(self, case_id, payload, headers):
        return self._request("POST",
                             f"/api/integrity-cases/{case_id}/resolve",
                             payload, headers)

    # --- Talent and bookings ---
    def create_talent(self, payload, headers):
        return self._request("POST", "/api/talents", payload, headers)

    def create_talent_booking(self, payload, headers):
        return self._request("POST", "/api/talent-bookings", payload, headers)

    def get_talent_booking(self, booking_id, headers):
        return self._request("GET", f"/api/talent-bookings/{booking_id}",
                             headers=headers)

    def list_talent_bookings(self, headers, params=None):
        return self._request("GET", "/api/talent-bookings", params or {},
                             headers)

    def transition_talent_booking(self, booking_id, payload, headers):
        return self._request("POST",
                             f"/api/talent-bookings/{booking_id}/transition",
                             payload, headers)

    # --- Payout records ---
    def get_payout_record(self, record_id, headers):
        return self._request("GET", f"/api/payout-records/{record_id}",
                             headers=headers)

    def list_payout_records(self, headers, params=None):
        return self._request("GET", "/api/payout-records", params or {},
                             headers)

    def submit_payout_docs(self, record_id, payload, headers):
        return self._request(
            "POST", f"/api/payout-records/{record_id}/submit-docs", payload,
            headers)

    def verify_payout_docs(self, record_id, payload, headers):
        return self._request(
            "POST", f"/api/payout-records/{record_id}/verify-docs", payload,
            headers)

    def approve_payout(self, record_id, headers):
        return self._request("POST",
                             f"/api/payout-records/{record_id}/approve", {},
                             headers)

    def pay_payout(self, record_id, headers):
        return self._request("POST", f"/api/payout-records/{record_id}/pay",
                             {}, headers)

    # --- Sponsor deals ---
    def create_sponsor_deal(self, payload, headers):
        return self._request("POST", "/api/sponsor-deals", payload, headers)

    def get_sponsor_deal(self, deal_id, headers):
        return self._request("GET", f"/api/sponsor-deals/{deal_id}",
                             headers=headers)

    def list_sponsor_deals(self, headers, params=None):
        return self._request("GET", "/api/sponsor-deals", params or {},
                             headers)

    def transition_sponsor_deal(self, deal_id, payload, headers):
        return self._request("POST",
                             f"/api/sponsor-deals/{deal_id}/transition",
                             payload, headers)


api_client = ApiClient()
