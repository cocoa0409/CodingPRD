"""API client: one method per endpoint defined in the PRD (mounted under /api/v1)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc", payload, headers)

    # --- events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/api/v1/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/api/v1/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/v1/events/{event_id}", headers=headers)

    def advance_posture(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/posture", payload, headers)

    def get_event_summary(self, event_id, headers):
        return self._request("GET", f"/api/v1/events/{event_id}/summary", headers=headers)

    # --- bids ---
    def create_bid(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/bids", payload, headers)

    def list_bids(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/api/v1/bids/{bid_id}", headers=headers)

    def patch_bid(self, bid_id, payload, headers):
        return self._request("PATCH", f"/api/v1/bids/{bid_id}", payload, headers)

    def submit_bid(self, bid_id, headers):
        return self._request("POST", f"/api/v1/bids/{bid_id}/submit", {}, headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/api/v1/bids/{bid_id}/withdraw", {}, headers)

    def review_bid(self, bid_id, headers):
        return self._request("POST", f"/api/v1/bids/{bid_id}/review", {}, headers)

    def request_revision(self, bid_id, payload, headers):
        return self._request("POST", f"/api/v1/bids/{bid_id}/request-revision", payload, headers)

    def decide_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/api/v1/bids/{bid_id}/decide", payload, headers)

    # --- bid requirements ---
    def list_requirements(self, bid_id, headers, params=None):
        return self._request("GET", f"/api/v1/bids/{bid_id}/requirements", headers=headers, params=params)

    def create_requirement(self, bid_id, payload, headers):
        return self._request("POST", f"/api/v1/bids/{bid_id}/requirements", payload, headers)

    def get_requirement(self, requirement_id, headers):
        return self._request("GET", f"/api/v1/requirements/{requirement_id}", headers=headers)

    def submit_evidence(self, requirement_id, payload, headers):
        return self._request("POST", f"/api/v1/requirements/{requirement_id}/evidence", payload, headers)

    def verify_requirement(self, requirement_id, payload, headers):
        return self._request("POST", f"/api/v1/requirements/{requirement_id}/verify", payload, headers)

    def waive_requirement(self, requirement_id, payload, headers):
        return self._request("POST", f"/api/v1/requirements/{requirement_id}/waive", payload, headers)

    # --- venues / fields ---
    def create_venue(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/venues", payload, headers)

    def list_venues(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/api/v1/venues/{venue_id}", headers=headers)

    def contract_venue(self, venue_id, payload, headers):
        return self._request("POST", f"/api/v1/venues/{venue_id}/contract", payload, headers)

    def release_venue(self, venue_id, headers):
        return self._request("POST", f"/api/v1/venues/{venue_id}/release", {}, headers)

    def create_field(self, venue_id, payload, headers):
        return self._request("POST", f"/api/v1/venues/{venue_id}/fields", payload, headers)

    def list_fields(self, venue_id, headers, params=None):
        return self._request("GET", f"/api/v1/venues/{venue_id}/fields", headers=headers, params=params)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/api/v1/fields/{field_id}", headers=headers)

    def blackout_field(self, field_id, payload, headers):
        return self._request("POST", f"/api/v1/fields/{field_id}/blackout", payload, headers)

    def unblackout_field(self, field_id, headers):
        return self._request("POST", f"/api/v1/fields/{field_id}/unblackout", {}, headers)

    def list_field_matches(self, field_id, headers, params=None):
        return self._request("GET", f"/api/v1/fields/{field_id}/matches", headers=headers, params=params)

    # --- hotel blocks / room bookings ---
    def create_hotel_block(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/hotel-blocks", payload, headers)

    def list_hotel_blocks(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/hotel-blocks", headers=headers, params=params)

    def get_hotel_block(self, block_id, headers):
        return self._request("GET", f"/api/v1/hotel-blocks/{block_id}", headers=headers)

    def patch_hotel_block(self, block_id, payload, headers):
        return self._request("PATCH", f"/api/v1/hotel-blocks/{block_id}", payload, headers)

    def contract_hotel_block(self, block_id, headers):
        return self._request("POST", f"/api/v1/hotel-blocks/{block_id}/contract", {}, headers)

    def close_cutoff(self, block_id, headers):
        return self._request("POST", f"/api/v1/hotel-blocks/{block_id}/close-cutoff", {}, headers)

    def reconcile_hotel_block(self, block_id, headers):
        return self._request("POST", f"/api/v1/hotel-blocks/{block_id}/reconcile", {}, headers)

    def list_block_bookings(self, block_id, headers, params=None):
        return self._request("GET", f"/api/v1/hotel-blocks/{block_id}/room-bookings", headers=headers, params=params)

    def create_booking(self, block_id, payload, headers):
        return self._request("POST", f"/api/v1/hotel-blocks/{block_id}/room-bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/api/v1/room-bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/api/v1/room-bookings", headers=headers, params=params)

    def transition_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/api/v1/room-bookings/{booking_id}/transition", payload, headers)

    # --- divisions / teams ---
    def create_division(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/divisions", payload, headers)

    def list_divisions(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/divisions", headers=headers, params=params)

    def get_division(self, division_id, headers):
        return self._request("GET", f"/api/v1/divisions/{division_id}", headers=headers)

    def lock_seeding(self, division_id, headers):
        return self._request("POST", f"/api/v1/divisions/{division_id}/lock-seeding", {}, headers)

    def publish_bracket(self, division_id, headers):
        return self._request("POST", f"/api/v1/divisions/{division_id}/publish-bracket", {}, headers)

    def list_division_teams(self, division_id, headers, params=None):
        return self._request("GET", f"/api/v1/divisions/{division_id}/teams", headers=headers, params=params)

    def list_division_matches(self, division_id, headers, params=None):
        return self._request("GET", f"/api/v1/divisions/{division_id}/matches", headers=headers, params=params)

    def create_team(self, division_id, payload, headers):
        return self._request("POST", f"/api/v1/divisions/{division_id}/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/api/v1/teams/{team_id}", headers=headers)

    def submit_roster(self, team_id, payload, headers):
        return self._request("POST", f"/api/v1/teams/{team_id}/roster", payload, headers)

    def verify_eligibility(self, team_id, headers):
        return self._request("POST", f"/api/v1/teams/{team_id}/verify-eligibility", {}, headers)

    def check_in_team(self, team_id, headers):
        return self._request("POST", f"/api/v1/teams/{team_id}/check-in", {}, headers)

    def withdraw_team(self, team_id, headers):
        return self._request("POST", f"/api/v1/teams/{team_id}/withdraw", {}, headers)

    def disqualify_team(self, team_id, payload, headers):
        return self._request("POST", f"/api/v1/teams/{team_id}/disqualify", payload, headers)

    # --- matches ---
    def get_match(self, match_id, headers):
        return self._request("GET", f"/api/v1/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/api/v1/matches", headers=headers, params=params)

    def schedule_match(self, match_id, payload, headers):
        return self._request("POST", f"/api/v1/matches/{match_id}/schedule", payload, headers)

    def reschedule_match(self, match_id, payload, headers):
        return self._request("POST", f"/api/v1/matches/{match_id}/reschedule", payload, headers)

    def start_match(self, match_id, headers):
        return self._request("POST", f"/api/v1/matches/{match_id}/start", {}, headers)

    def finalize_match(self, match_id, payload, headers):
        return self._request("POST", f"/api/v1/matches/{match_id}/finalize", payload, headers)

    def forfeit_match(self, match_id, payload, headers):
        return self._request("POST", f"/api/v1/matches/{match_id}/forfeit", payload, headers)

    def list_match_assignments(self, match_id, headers, params=None):
        return self._request("GET", f"/api/v1/matches/{match_id}/official-assignments", headers=headers, params=params)

    # --- officials / assignments ---
    def create_official(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/officials", payload, headers)

    def list_officials(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/officials", headers=headers, params=params)

    def get_official(self, official_id, headers):
        return self._request("GET", f"/api/v1/officials/{official_id}", headers=headers)

    def transition_official(self, official_id, payload, headers):
        return self._request("POST", f"/api/v1/officials/{official_id}/transition", payload, headers)

    def list_official_assignments(self, official_id, headers, params=None):
        return self._request("GET", f"/api/v1/officials/{official_id}/assignments", headers=headers, params=params)

    def create_assignment(self, match_id, payload, headers):
        return self._request("POST", f"/api/v1/matches/{match_id}/official-assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/v1/official-assignments/{assignment_id}", headers=headers)

    def respond_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/v1/official-assignments/{assignment_id}/respond", payload, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/v1/official-assignments/{assignment_id}/release", {}, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/v1/official-assignments/{assignment_id}/complete", {}, headers)

    # --- volunteers / shifts / signups ---
    def create_volunteer(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/volunteers", payload, headers)

    def list_volunteers(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/api/v1/volunteers/{volunteer_id}", headers=headers)

    def patch_volunteer(self, volunteer_id, payload, headers):
        return self._request("PATCH", f"/api/v1/volunteers/{volunteer_id}", payload, headers)

    def transition_volunteer(self, volunteer_id, payload, headers):
        return self._request("POST", f"/api/v1/volunteers/{volunteer_id}/transition", payload, headers)

    def list_volunteer_signups(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/api/v1/volunteers/{volunteer_id}/signups", headers=headers, params=params)

    def create_shift(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/shifts", payload, headers)

    def list_shifts(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/api/v1/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/api/v1/shifts/{shift_id}/cancel", {}, headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"/api/v1/shifts/{shift_id}/complete", {}, headers)

    def list_shift_signups(self, shift_id, headers, params=None):
        return self._request("GET", f"/api/v1/shifts/{shift_id}/signups", headers=headers, params=params)

    def create_signup(self, shift_id, payload, headers):
        return self._request("POST", f"/api/v1/shifts/{shift_id}/signups", payload, headers)

    def get_signup(self, signup_id, headers):
        return self._request("GET", f"/api/v1/shift-signups/{signup_id}", headers=headers)

    def confirm_signup(self, signup_id, headers):
        return self._request("POST", f"/api/v1/shift-signups/{signup_id}/confirm", {}, headers)

    def cancel_signup(self, signup_id, headers):
        return self._request("POST", f"/api/v1/shift-signups/{signup_id}/cancel", {}, headers)

    def mark_no_show(self, signup_id, headers):
        return self._request("POST", f"/api/v1/shift-signups/{signup_id}/mark-no-show", {}, headers)

    # --- weather alerts ---
    def create_weather_alert(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/weather-alerts", payload, headers)

    def list_event_alerts(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/weather-alerts", headers=headers, params=params)

    def get_weather_alert(self, alert_id, headers):
        return self._request("GET", f"/api/v1/weather-alerts/{alert_id}", headers=headers)

    def list_weather_alerts(self, headers, params=None):
        return self._request("GET", "/api/v1/weather-alerts", headers=headers, params=params)

    def activate_alert(self, alert_id, headers):
        return self._request("POST", f"/api/v1/weather-alerts/{alert_id}/activate", {}, headers)

    def resolve_alert(self, alert_id, headers):
        return self._request("POST", f"/api/v1/weather-alerts/{alert_id}/resolve", {}, headers)

    # --- impact reports ---
    def create_impact_report(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/impact-reports", payload, headers)

    def list_impact_reports(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/impact-reports", headers=headers, params=params)

    def get_impact_report(self, report_id, headers):
        return self._request("GET", f"/api/v1/impact-reports/{report_id}", headers=headers)

    def submit_impact_report(self, report_id, headers):
        return self._request("POST", f"/api/v1/impact-reports/{report_id}/submit", {}, headers)

    def audit_impact_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/v1/impact-reports/{report_id}/audit", payload, headers)

    def audit_decision(self, report_id, payload, headers):
        return self._request("POST", f"/api/v1/impact-reports/{report_id}/audit-decision", payload, headers)

    def revise_impact_report(self, report_id, headers):
        return self._request("POST", f"/api/v1/impact-reports/{report_id}/revise", {}, headers)

    # --- settlements ---
    def create_settlement(self, event_id, payload, headers):
        return self._request("POST", f"/api/v1/events/{event_id}/settlements", payload, headers)

    def list_settlements(self, event_id, headers, params=None):
        return self._request("GET", f"/api/v1/events/{event_id}/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/api/v1/settlements/{settlement_id}", headers=headers)

    def add_expense_line(self, settlement_id, payload, headers):
        return self._request("POST", f"/api/v1/settlements/{settlement_id}/expense-lines", payload, headers)

    def certify_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/v1/settlements/{settlement_id}/certify", {}, headers)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/v1/settlements/{settlement_id}/approve", {}, headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/v1/settlements/{settlement_id}/pay", {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/api/v1/settlements/{settlement_id}/dispute", payload, headers)

    def reopen_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/v1/settlements/{settlement_id}/reopen", {}, headers)


api_client = ApiClient()
