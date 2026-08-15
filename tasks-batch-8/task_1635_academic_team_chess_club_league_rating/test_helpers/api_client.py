"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock (PRD §2.5) ──
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ── Seasons (PRD §3.1, §3.9) ──
    def create_season(self, payload, headers):
        return self._request("POST", "/api/seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/api/seasons", headers=headers, params=params)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/api/seasons/{season_id}", headers=headers)

    def activate_season(self, season_id, headers):
        return self._request("POST", f"/api/seasons/{season_id}/activate", {}, headers)

    def finalize_season(self, season_id, headers):
        return self._request("POST", f"/api/seasons/{season_id}/finalize", {}, headers)

    def reopen_season(self, season_id, headers):
        return self._request("POST", f"/api/seasons/{season_id}/reopen", {}, headers)

    def complete_season(self, season_id, headers):
        return self._request("POST", f"/api/seasons/{season_id}/complete", {}, headers)

    def get_standings(self, season_id, headers):
        return self._request("GET", f"/api/seasons/{season_id}/standings", headers=headers)

    def finalize_standings(self, season_id, payload, headers):
        return self._request("POST", f"/api/seasons/{season_id}/standings/finalize", payload, headers)

    def generate_bids(self, season_id, headers):
        return self._request("POST", f"/api/seasons/{season_id}/bids/generate", {}, headers)

    # ── Clubs (PRD §3.1) ──
    def create_club(self, payload, headers):
        return self._request("POST", "/api/clubs", payload, headers)

    def list_clubs(self, headers, params=None):
        return self._request("GET", "/api/clubs", headers=headers, params=params)

    def get_club(self, club_id, headers):
        return self._request("GET", f"/api/clubs/{club_id}", headers=headers)

    def suspend_club(self, club_id, headers):
        return self._request("POST", f"/api/clubs/{club_id}/suspend", {}, headers)

    def reinstate_club(self, club_id, headers):
        return self._request("POST", f"/api/clubs/{club_id}/reinstate", {}, headers)

    def get_season_invoice(self, club_id, headers, params=None):
        return self._request("GET", f"/api/clubs/{club_id}/season-invoice", headers=headers, params=params)

    # ── Coaches (PRD §3.1) ──
    def create_coach(self, payload, headers):
        return self._request("POST", "/api/coaches", payload, headers)

    def list_coaches(self, headers, params=None):
        return self._request("GET", "/api/coaches", headers=headers, params=params)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/api/coaches/{coach_id}", headers=headers)

    def deactivate_coach(self, coach_id, headers):
        return self._request("POST", f"/api/coaches/{coach_id}/deactivate", {}, headers)

    def reactivate_coach(self, coach_id, headers):
        return self._request("POST", f"/api/coaches/{coach_id}/reactivate", {}, headers)

    # ── Players (PRD §3.1) ──
    def create_player(self, payload, headers):
        return self._request("POST", "/api/players", payload, headers)

    def list_players(self, headers, params=None):
        return self._request("GET", "/api/players", headers=headers, params=params)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/api/players/{player_id}", headers=headers)

    def deactivate_player(self, player_id, headers):
        return self._request("POST", f"/api/players/{player_id}/deactivate", {}, headers)

    def reactivate_player(self, player_id, headers):
        return self._request("POST", f"/api/players/{player_id}/reactivate", {}, headers)

    def suspend_player(self, player_id, headers):
        return self._request("POST", f"/api/players/{player_id}/suspend", {}, headers)

    # ── Memberships (PRD §3.2) ──
    def create_membership(self, payload, headers):
        return self._request("POST", "/api/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/api/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/api/memberships/{membership_id}", headers=headers)

    def pay_membership(self, membership_id, headers):
        return self._request("POST", f"/api/memberships/{membership_id}/pay", {}, headers)

    def waive_membership(self, membership_id, headers):
        return self._request("POST", f"/api/memberships/{membership_id}/waive", {}, headers)

    def refund_membership(self, membership_id, headers):
        return self._request("POST", f"/api/memberships/{membership_id}/refund", {}, headers)

    # ── Ledger (PRD §2.8, §3.2) ──
    def post_ledger_entry(self, club_id, payload, headers):
        return self._request("POST", f"/api/clubs/{club_id}/ledger-entries", payload, headers)

    def list_club_ledger_entries(self, club_id, headers, params=None):
        return self._request("GET", f"/api/clubs/{club_id}/ledger-entries", headers=headers, params=params)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/api/ledger-entries/{ledger_entry_id}", headers=headers)

    def reverse_ledger_entry(self, ledger_entry_id, payload, headers):
        return self._request("POST", f"/api/ledger-entries/{ledger_entry_id}/reverse", payload, headers)

    # ── Meets (PRD §3.3, §3.4) ──
    def create_meet(self, payload, headers):
        return self._request("POST", "/api/meets", payload, headers)

    def list_meets(self, headers, params=None):
        return self._request("GET", "/api/meets", headers=headers, params=params)

    def get_meet(self, meet_id, headers):
        return self._request("GET", f"/api/meets/{meet_id}", headers=headers)

    def schedule_meet(self, meet_id, headers):
        return self._request("POST", f"/api/meets/{meet_id}/schedule", {}, headers)

    def postpone_meet(self, meet_id, headers):
        return self._request("POST", f"/api/meets/{meet_id}/postpone", {}, headers)

    def reschedule_meet(self, meet_id, payload, headers):
        return self._request("POST", f"/api/meets/{meet_id}/reschedule", payload, headers)

    def cancel_meet(self, meet_id, headers):
        return self._request("POST", f"/api/meets/{meet_id}/cancel", {}, headers)

    def create_pairing(self, meet_id, payload, headers):
        return self._request("POST", f"/api/meets/{meet_id}/pairings", payload, headers)

    def list_meet_pairings(self, meet_id, headers, params=None):
        return self._request("GET", f"/api/meets/{meet_id}/pairings", headers=headers, params=params)

    def publish_pairings(self, meet_id, headers):
        return self._request("POST", f"/api/meets/{meet_id}/publish-pairings", {}, headers)

    def start_meet(self, meet_id, headers):
        return self._request("POST", f"/api/meets/{meet_id}/start", {}, headers)

    def complete_meet(self, meet_id, headers):
        return self._request("POST", f"/api/meets/{meet_id}/complete", {}, headers)

    # ── Pairings (PRD §3.4) ──
    def list_pairings(self, headers, params=None):
        return self._request("GET", "/api/pairings", headers=headers, params=params)

    def get_pairing(self, pairing_id, headers):
        return self._request("GET", f"/api/pairings/{pairing_id}", headers=headers)

    def report_result(self, pairing_id, payload, headers):
        return self._request("POST", f"/api/pairings/{pairing_id}/report-result", payload, headers)

    def confirm_pairing(self, pairing_id, headers):
        return self._request("POST", f"/api/pairings/{pairing_id}/confirm", {}, headers)

    def dispute_pairing(self, pairing_id, payload, headers):
        return self._request("POST", f"/api/pairings/{pairing_id}/dispute", payload, headers)

    # ── Disputes (PRD §3.6) ──
    def list_disputes(self, headers, params=None):
        return self._request("GET", "/api/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/api/disputes/{dispute_id}", headers=headers)

    def open_dispute_review(self, dispute_id, headers):
        return self._request("POST", f"/api/disputes/{dispute_id}/open-review", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/api/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/api/disputes/{dispute_id}/withdraw", {}, headers)

    # ── Tournaments & sections (PRD §3.7) ──
    def create_tournament(self, payload, headers):
        return self._request("POST", "/api/tournaments", payload, headers)

    def list_tournaments(self, headers, params=None):
        return self._request("GET", "/api/tournaments", headers=headers, params=params)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/api/tournaments/{tournament_id}", headers=headers)

    def open_registration(self, tournament_id, headers):
        return self._request("POST", f"/api/tournaments/{tournament_id}/open-registration", {}, headers)

    def close_registration(self, tournament_id, headers):
        return self._request("POST", f"/api/tournaments/{tournament_id}/close-registration", {}, headers)

    def reopen_registration(self, tournament_id, headers):
        return self._request("POST", f"/api/tournaments/{tournament_id}/reopen-registration", {}, headers)

    def start_tournament(self, tournament_id, headers):
        return self._request("POST", f"/api/tournaments/{tournament_id}/start", {}, headers)

    def complete_tournament(self, tournament_id, headers):
        return self._request("POST", f"/api/tournaments/{tournament_id}/complete", {}, headers)

    def cancel_tournament(self, tournament_id, headers):
        return self._request("POST", f"/api/tournaments/{tournament_id}/cancel", {}, headers)

    def create_section(self, tournament_id, payload, headers):
        return self._request("POST", f"/api/tournaments/{tournament_id}/sections", payload, headers)

    def list_tournament_sections(self, tournament_id, headers, params=None):
        return self._request("GET", f"/api/tournaments/{tournament_id}/sections", headers=headers, params=params)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/api/sections", headers=headers, params=params)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/api/sections/{section_id}", headers=headers)

    def lock_section(self, section_id, headers):
        return self._request("POST", f"/api/sections/{section_id}/lock", {}, headers)

    def unlock_section(self, section_id, headers):
        return self._request("POST", f"/api/sections/{section_id}/unlock", {}, headers)

    # ── Entries (PRD §3.7) ──
    def create_entry(self, section_id, payload, headers):
        return self._request("POST", f"/api/sections/{section_id}/entries", payload, headers)

    def list_section_entries(self, section_id, headers, params=None):
        return self._request("GET", f"/api/sections/{section_id}/entries", headers=headers, params=params)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/api/entries", headers=headers, params=params)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/api/entries/{entry_id}", headers=headers)

    def withdraw_entry(self, entry_id, headers):
        return self._request("POST", f"/api/entries/{entry_id}/withdraw", {}, headers)

    def check_in_entry(self, entry_id, headers):
        return self._request("POST", f"/api/entries/{entry_id}/check-in", {}, headers)

    # ── Proctor assignments (PRD §3.8) ──
    def create_proctor_assignment(self, payload, headers):
        return self._request("POST", "/api/proctor-assignments", payload, headers)

    def list_proctor_assignments(self, headers, params=None):
        return self._request("GET", "/api/proctor-assignments", headers=headers, params=params)

    def get_proctor_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/proctor-assignments/{assignment_id}", headers=headers)

    def confirm_proctor_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/proctor-assignments/{assignment_id}/confirm", {}, headers)

    def release_proctor_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/proctor-assignments/{assignment_id}/release", {}, headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request("POST", f"/api/proctor-assignments/{assignment_id}/mark-no-show", {}, headers)

    # ── Qualification bids (PRD §3.9) ──
    def list_bids(self, headers, params=None):
        return self._request("GET", "/api/qualification-bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/api/qualification-bids/{bid_id}", headers=headers)

    def accept_bid(self, bid_id, headers):
        return self._request("POST", f"/api/qualification-bids/{bid_id}/accept", {}, headers)

    def decline_bid(self, bid_id, headers):
        return self._request("POST", f"/api/qualification-bids/{bid_id}/decline", {}, headers)

    # ── Rating events (PRD §3.5) ──
    def list_rating_events(self, headers, params=None):
        return self._request("GET", "/api/rating-events", headers=headers, params=params)

    def get_rating_event(self, rating_event_id, headers):
        return self._request("GET", f"/api/rating-events/{rating_event_id}", headers=headers)

    # ── Standing snapshots (PRD §3.9) ──
    def list_standings_snapshots(self, headers, params=None):
        return self._request("GET", "/api/standings-snapshots", headers=headers, params=params)

    def get_standings_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/api/standings-snapshots/{snapshot_id}", headers=headers)

    # ── Travel stipends (PRD §3.9) ──
    def create_travel_stipend(self, payload, headers):
        return self._request("POST", "/api/travel-stipends", payload, headers)

    def list_travel_stipends(self, headers, params=None):
        return self._request("GET", "/api/travel-stipends", headers=headers, params=params)

    def get_travel_stipend(self, stipend_id, headers):
        return self._request("GET", f"/api/travel-stipends/{stipend_id}", headers=headers)


api_client = ApiClient()
