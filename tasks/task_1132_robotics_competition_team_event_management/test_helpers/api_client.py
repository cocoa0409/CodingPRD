"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- FrcEvent lifecycle ---
    def create_event(self, payload, headers):
        return self._request("POST", "/frc-events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/frc-events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/frc-events/{event_id}", headers=headers)

    def open_registration(self, event_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/open-registration", {}, headers)

    def lock_registration(self, event_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/lock-registration", {}, headers)

    def open_build_season(self, event_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/open-build-season", {}, headers)

    def open_inspection(self, event_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/open-inspection", {}, headers)

    def start_matches(self, event_id, expected_event_version, headers):
        return self._request(
            "POST", f"/frc-events/{event_id}/start-matches",
            {"expected_event_version": expected_event_version}, headers,
        )

    def open_alliance_selection(self, event_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/open-alliance-selection", {}, headers)

    def close_alliance_selection(self, event_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/close-alliance-selection", {}, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/close-event", {}, headers)

    # --- BuildSeasonMilestone ---
    def create_milestone(self, event_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/milestones", payload, headers)

    def list_milestones(self, event_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/milestones", headers=headers, params=params)

    def get_milestone(self, event_id, milestone_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/milestones/{milestone_id}", headers=headers)

    def mark_milestone_passed(self, event_id, milestone_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/milestones/{milestone_id}/mark-passed", {}, headers)

    # --- Team ---
    def create_team(self, event_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams", payload, headers)

    def list_teams(self, event_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/teams", headers=headers, params=params)

    def get_team(self, event_id, team_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}", headers=headers)

    def mark_payment_cleared(self, event_id, team_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/mark-payment-cleared", {}, headers)

    def submit_roster(self, event_id, team_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/submit-roster", {}, headers)

    def confirm_team(self, event_id, team_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/confirm", {}, headers)

    def withdraw_team(self, event_id, team_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/withdraw", {}, headers)

    def disqualify_team(self, event_id, team_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/disqualify", {}, headers)

    def get_projected_ranking(self, event_id, team_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/projected-ranking", headers=headers)

    # --- Person ---
    def create_person(self, event_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/persons", payload, headers)

    def list_persons(self, event_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/persons", headers=headers, params=params)

    def get_person(self, event_id, person_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/persons/{person_id}", headers=headers)

    # --- ScreeningRecord ---
    def create_screening_record(self, event_id, person_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/persons/{person_id}/screening-records", payload, headers)

    def list_screening_records(self, event_id, person_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/persons/{person_id}/screening-records", headers=headers, params=params)

    def get_screening_record(self, event_id, person_id, record_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/persons/{person_id}/screening-records/{record_id}", headers=headers)

    def approve_screening(self, event_id, person_id, record_id, expected_person_version, headers):
        return self._request(
            "POST",
            f"/frc-events/{event_id}/persons/{person_id}/screening-records/{record_id}/approve",
            {"expected_person_version": expected_person_version}, headers,
        )

    def reject_screening(self, event_id, person_id, record_id, headers):
        return self._request(
            "POST",
            f"/frc-events/{event_id}/persons/{person_id}/screening-records/{record_id}/reject",
            {}, headers,
        )

    # --- PartOrder ---
    def create_part_order(self, event_id, team_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/part-orders", payload, headers)

    def list_part_orders(self, event_id, team_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/part-orders", headers=headers, params=params)

    def get_part_order(self, event_id, team_id, order_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/part-orders/{order_id}", headers=headers)

    def submit_part_order(self, event_id, team_id, order_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/part-orders/{order_id}/submit", {}, headers)

    def approve_part_order(self, event_id, team_id, order_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/part-orders/{order_id}/approve", {}, headers)

    def reject_part_order(self, event_id, team_id, order_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/part-orders/{order_id}/reject", {}, headers)

    def place_part_order_with_vendor(self, event_id, team_id, order_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/part-orders/{order_id}/place-with-vendor", {}, headers)

    def receive_part_order(self, event_id, team_id, order_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/part-orders/{order_id}/receive", {}, headers)

    def cancel_part_order(self, event_id, team_id, order_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/part-orders/{order_id}/cancel", {}, headers)

    # --- RobotInspection ---
    def create_robot_inspection(self, event_id, team_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/robot-inspections", payload, headers)

    def list_robot_inspections(self, event_id, team_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/robot-inspections", headers=headers, params=params)

    def get_robot_inspection(self, event_id, team_id, inspection_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/robot-inspections/{inspection_id}", headers=headers)

    def submit_robot_inspection(self, event_id, team_id, inspection_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/robot-inspections/{inspection_id}/submit", {}, headers)

    def pass_robot_inspection(self, event_id, team_id, inspection_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/robot-inspections/{inspection_id}/pass", {}, headers)

    def fail_robot_inspection(self, event_id, team_id, inspection_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/robot-inspections/{inspection_id}/fail", {}, headers)

    # --- ComplianceViolation ---
    def create_violation(self, event_id, team_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/violations", payload, headers)

    def list_violations(self, event_id, team_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/violations", headers=headers, params=params)

    def get_violation(self, event_id, team_id, violation_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/violations/{violation_id}", headers=headers)

    def ack_violation(self, event_id, team_id, violation_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/violations/{violation_id}/ack", {}, headers)

    def resolve_violation(self, event_id, team_id, violation_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/violations/{violation_id}/resolve", {}, headers)

    def escalate_violation(self, event_id, team_id, violation_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/violations/{violation_id}/escalate", {}, headers)

    # --- Match ---
    def create_match(self, event_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches", payload, headers)

    def list_matches(self, event_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/matches", headers=headers, params=params)

    def get_match(self, event_id, match_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/matches/{match_id}", headers=headers)

    def queue_match(self, event_id, match_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/queue", {}, headers)

    def take_field(self, event_id, match_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/take-field", {}, headers)

    def score_match(self, event_id, match_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/score", {}, headers)

    def finalize_match(self, event_id, match_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/finalize", {}, headers)

    def replay_match(self, event_id, match_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/replay", {}, headers)

    # --- MatchScoreBreakdown ---
    def create_score_breakdown(self, event_id, match_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/score-breakdowns", payload, headers)

    def list_score_breakdowns(self, event_id, match_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/matches/{match_id}/score-breakdowns", headers=headers)

    # --- QueueSlot ---
    def create_queue_slot(self, event_id, match_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/queue-slots", payload, headers)

    def list_queue_slots(self, event_id, match_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/matches/{match_id}/queue-slots", headers=headers, params=params)

    def get_queue_slot(self, event_id, match_id, slot_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/matches/{match_id}/queue-slots/{slot_id}", headers=headers)

    def mark_slot_at_field(self, event_id, match_id, slot_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/queue-slots/{slot_id}/mark-at-field", {}, headers)

    # --- FieldResetLog ---
    def list_field_reset_logs(self, event_id, match_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/matches/{match_id}/field-reset-logs", headers=headers)

    def get_field_reset_log(self, event_id, match_id, log_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/matches/{match_id}/field-reset-logs/{log_id}", headers=headers)

    def complete_field_reset_log(self, event_id, match_id, log_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/field-reset-logs/{log_id}/complete", {}, headers)

    def abort_field_reset_log(self, event_id, match_id, log_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/matches/{match_id}/field-reset-logs/{log_id}/abort", {}, headers)

    # --- Alliance & selection ---
    def create_alliance(self, event_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/alliances", payload, headers)

    def list_alliances(self, event_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/alliances", headers=headers, params=params)

    def get_alliance(self, event_id, alliance_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/alliances/{alliance_id}", headers=headers)

    def list_selection_rounds(self, event_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/alliance-selection-rounds", headers=headers)

    def get_selection_round(self, event_id, round_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/alliance-selection-rounds/{round_id}", headers=headers)

    def submit_pick(self, event_id, round_id, team_id, expected_round_version, headers):
        return self._request(
            "POST", f"/frc-events/{event_id}/alliance-selection-rounds/{round_id}/pick",
            {"team_id": team_id, "expected_round_version": expected_round_version}, headers,
        )

    # --- Award ---
    def create_award(self, event_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/awards", payload, headers)

    def list_awards(self, event_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/awards", headers=headers, params=params)

    def get_award(self, event_id, award_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/awards/{award_id}", headers=headers)

    def begin_judging(self, event_id, award_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/awards/{award_id}/begin-judging", {}, headers)

    def decide_award(self, event_id, award_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/awards/{award_id}/decide", {}, headers)

    def present_award(self, event_id, award_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/awards/{award_id}/present", {}, headers)

    # --- InterviewSlot ---
    def create_interview_slot(self, event_id, award_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/awards/{award_id}/interview-slots", payload, headers)

    def list_interview_slots(self, event_id, award_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/awards/{award_id}/interview-slots", headers=headers, params=params)

    def get_interview_slot(self, event_id, award_id, slot_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/awards/{award_id}/interview-slots/{slot_id}", headers=headers)

    def confirm_interview_slot(self, event_id, award_id, slot_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/awards/{award_id}/interview-slots/{slot_id}/confirm", {}, headers)

    def complete_interview_slot(self, event_id, award_id, slot_id, score, headers):
        return self._request(
            "POST", f"/frc-events/{event_id}/awards/{award_id}/interview-slots/{slot_id}/complete",
            {"score": score}, headers,
        )

    def cancel_interview_slot(self, event_id, award_id, slot_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/awards/{award_id}/interview-slots/{slot_id}/cancel", {}, headers)

    def no_show_interview_slot(self, event_id, award_id, slot_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/awards/{award_id}/interview-slots/{slot_id}/no-show", {}, headers)

    # --- TravelBooking ---
    def create_travel_booking(self, event_id, team_id, payload, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/travel-bookings", payload, headers)

    def list_travel_bookings(self, event_id, team_id, headers, params=None):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/travel-bookings", headers=headers, params=params)

    def get_travel_booking(self, event_id, team_id, booking_id, headers):
        return self._request("GET", f"/frc-events/{event_id}/teams/{team_id}/travel-bookings/{booking_id}", headers=headers)

    def approve_travel_booking(self, event_id, team_id, booking_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/travel-bookings/{booking_id}/approve", {}, headers)

    def mark_travel_booking_paid(self, event_id, team_id, booking_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/travel-bookings/{booking_id}/mark-paid", {}, headers)

    def deny_travel_booking(self, event_id, team_id, booking_id, headers):
        return self._request("POST", f"/frc-events/{event_id}/teams/{team_id}/travel-bookings/{booking_id}/deny", {}, headers)

    # --- Flat filtered-list routes (PRD §2.8) ---
    def list_teams_flat(self, headers, params=None):
        return self._request("GET", "/frc-events/teams", headers=headers, params=params)

    def list_matches_flat(self, headers, params=None):
        return self._request("GET", "/frc-events/matches-flat", headers=headers, params=params)

    def list_alliances_flat(self, headers, params=None):
        return self._request("GET", "/frc-events/alliances-flat", headers=headers, params=params)

    def list_selection_rounds_flat(self, headers, params=None):
        return self._request("GET", "/frc-events/alliance-selection-rounds-flat", headers=headers, params=params)

    # --- Logical clock (PRD §2.9) ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
