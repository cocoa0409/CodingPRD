"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Administrative clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc", payload, headers)

    # --- Meet lifecycle ---
    def create_meet(self, payload, headers):
        return self._request("POST", "/api/v1/meets", payload, headers)

    def list_meets(self, headers, params=None):
        return self._request("GET", "/api/v1/meets", headers=headers, params=params)

    def get_meet(self, meet_id, headers):
        return self._request("GET", f"/api/v1/meets/{meet_id}", headers=headers)

    def publish_meet(self, meet_id, headers):
        return self._request("POST", f"/api/v1/meets/{meet_id}/publish", {}, headers)

    def close_meet_scoring(self, meet_id, headers):
        return self._request("POST", f"/api/v1/meets/{meet_id}/close-scoring", {}, headers)

    def finalize_meet(self, meet_id, headers):
        return self._request("POST", f"/api/v1/meets/{meet_id}/finalize", {}, headers)

    def archive_meet(self, meet_id, headers):
        return self._request("POST", f"/api/v1/meets/{meet_id}/archive", {}, headers)

    # --- Session ---
    def create_session(self, meet_id, payload, headers):
        return self._request("POST", f"/api/v1/meets/{meet_id}/sessions", payload, headers)

    def list_sessions(self, meet_id, headers, params=None):
        return self._request("GET", f"/api/v1/meets/{meet_id}/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/api/v1/sessions/{session_id}", headers=headers)

    def close_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/v1/sessions/{session_id}/close", payload, headers)

    # --- Squad ---
    def create_squad(self, session_id, payload, headers):
        return self._request("POST", f"/api/v1/sessions/{session_id}/squads", payload, headers)

    def list_squads(self, session_id, headers, params=None):
        return self._request("GET", f"/api/v1/sessions/{session_id}/squads", headers=headers, params=params)

    def get_squad(self, squad_id, headers):
        return self._request("GET", f"/api/v1/squads/{squad_id}", headers=headers)

    def list_squad_entries(self, squad_id, headers, params=None):
        return self._request("GET", f"/api/v1/squads/{squad_id}/athlete-entries", headers=headers, params=params)

    def assign_squads(self, session_id, headers):
        return self._request("POST", f"/api/v1/sessions/{session_id}/assign-squads", {}, headers)

    # --- Gymnast ---
    def create_gymnast(self, payload, headers):
        return self._request("POST", "/api/v1/gymnasts", payload, headers)

    def list_gymnasts(self, headers, params=None):
        return self._request("GET", "/api/v1/gymnasts", headers=headers, params=params)

    def get_gymnast(self, gymnast_id, headers):
        return self._request("GET", f"/api/v1/gymnasts/{gymnast_id}", headers=headers)

    # --- AthleteEntry ---
    def create_athlete_entry(self, session_id, payload, headers):
        return self._request("POST", f"/api/v1/sessions/{session_id}/athlete-entries", payload, headers)

    def list_session_entries(self, session_id, headers, params=None):
        return self._request("GET", f"/api/v1/sessions/{session_id}/athlete-entries", headers=headers, params=params)

    def list_gymnast_entries(self, gymnast_id, headers, params=None):
        return self._request("GET", f"/api/v1/gymnasts/{gymnast_id}/athlete-entries", headers=headers, params=params)

    def get_athlete_entry(self, entry_id, headers):
        return self._request("GET", f"/api/v1/athlete-entries/{entry_id}", headers=headers)

    def check_in_entry(self, entry_id, headers):
        return self._request("POST", f"/api/v1/athlete-entries/{entry_id}/check-in", {}, headers)

    def scratch_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/api/v1/athlete-entries/{entry_id}/scratch", payload, headers)

    # --- Coach ---
    def create_coach(self, payload, headers):
        return self._request("POST", "/api/v1/coaches", payload, headers)

    def list_coaches(self, headers, params=None):
        return self._request("GET", "/api/v1/coaches", headers=headers, params=params)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/api/v1/coaches/{coach_id}", headers=headers)

    def verify_coach(self, coach_id, headers):
        return self._request("POST", f"/api/v1/coaches/{coach_id}/verify", {}, headers)

    # --- CoachMeetPass ---
    def issue_coach_pass(self, meet_id, payload, headers):
        return self._request("POST", f"/api/v1/meets/{meet_id}/coach-meet-passes", payload, headers)

    def list_meet_coach_passes(self, meet_id, headers, params=None):
        return self._request("GET", f"/api/v1/meets/{meet_id}/coach-meet-passes", headers=headers, params=params)

    def list_coach_passes(self, coach_id, headers, params=None):
        return self._request("GET", f"/api/v1/coaches/{coach_id}/coach-meet-passes", headers=headers, params=params)

    def get_coach_pass(self, pass_id, headers):
        return self._request("GET", f"/api/v1/coach-meet-passes/{pass_id}", headers=headers)

    def grant_floor_access(self, pass_id, headers):
        return self._request("POST", f"/api/v1/coach-meet-passes/{pass_id}/grant-floor-access", {}, headers)

    def suspend_pass(self, pass_id, payload, headers):
        return self._request("POST", f"/api/v1/coach-meet-passes/{pass_id}/suspend", payload, headers)

    def reinstate_pass(self, pass_id, headers):
        return self._request("POST", f"/api/v1/coach-meet-passes/{pass_id}/reinstate", {}, headers)

    def revoke_pass(self, pass_id, headers):
        return self._request("POST", f"/api/v1/coach-meet-passes/{pass_id}/revoke", {}, headers)

    # --- Judge ---
    def create_judge(self, payload, headers):
        return self._request("POST", "/api/v1/judges", payload, headers)

    def list_judges(self, headers, params=None):
        return self._request("GET", "/api/v1/judges", headers=headers, params=params)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"/api/v1/judges/{judge_id}", headers=headers)

    # --- JudgePanel ---
    def create_judge_panel(self, session_id, payload, headers):
        return self._request("POST", f"/api/v1/sessions/{session_id}/judge-panels", payload, headers)

    def list_session_panels(self, session_id, headers, params=None):
        return self._request("GET", f"/api/v1/sessions/{session_id}/judge-panels", headers=headers, params=params)

    def list_meet_panels(self, meet_id, headers, params=None):
        return self._request("GET", f"/api/v1/meets/{meet_id}/judge-panels", headers=headers, params=params)

    def get_judge_panel(self, panel_id, headers):
        return self._request("GET", f"/api/v1/judge-panels/{panel_id}", headers=headers)

    def auto_assign_panel(self, panel_id, headers):
        return self._request("POST", f"/api/v1/judge-panels/{panel_id}/auto-assign", {}, headers)

    # --- PanelAssignment ---
    def list_panel_assignments(self, panel_id, headers, params=None):
        return self._request("GET", f"/api/v1/judge-panels/{panel_id}/assignments", headers=headers, params=params)

    def list_judge_assignments(self, judge_id, headers, params=None):
        return self._request("GET", f"/api/v1/judges/{judge_id}/panel-assignments", headers=headers, params=params)

    def get_panel_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/v1/panel-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/v1/panel-assignments/{assignment_id}/confirm", {}, headers)

    def recuse_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/v1/panel-assignments/{assignment_id}/recuse", {}, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/v1/panel-assignments/{assignment_id}/release", {}, headers)

    # --- Rotation ---
    def generate_rotations(self, session_id, headers):
        return self._request("POST", f"/api/v1/sessions/{session_id}/rotations/generate", {}, headers)

    def list_rotations(self, session_id, headers, params=None):
        return self._request("GET", f"/api/v1/sessions/{session_id}/rotations", headers=headers, params=params)

    def get_rotation(self, rotation_id, headers):
        return self._request("GET", f"/api/v1/rotations/{rotation_id}", headers=headers)

    def open_rotation_scoring(self, rotation_id, headers):
        return self._request("POST", f"/api/v1/rotations/{rotation_id}/open-scoring", {}, headers)

    def close_rotation_scoring(self, rotation_id, headers):
        return self._request("POST", f"/api/v1/rotations/{rotation_id}/close-scoring", {}, headers)

    # --- WarmupBlock ---
    def create_warmup_block(self, rotation_id, payload, headers):
        return self._request("POST", f"/api/v1/rotations/{rotation_id}/warmup-blocks", payload, headers)

    def generate_warmup_blocks(self, rotation_id, headers):
        return self._request("POST", f"/api/v1/rotations/{rotation_id}/warmup-blocks/generate", {}, headers)

    def list_rotation_warmup_blocks(self, rotation_id, headers, params=None):
        return self._request("GET", f"/api/v1/rotations/{rotation_id}/warmup-blocks", headers=headers, params=params)

    def list_squad_warmup_blocks(self, squad_id, headers, params=None):
        return self._request("GET", f"/api/v1/squads/{squad_id}/warmup-blocks", headers=headers, params=params)

    def get_warmup_block(self, block_id, headers):
        return self._request("GET", f"/api/v1/warmup-blocks/{block_id}", headers=headers)

    # --- Score ---
    def create_score(self, entry_id, payload, headers):
        return self._request("POST", f"/api/v1/athlete-entries/{entry_id}/scores", payload, headers)

    def list_entry_scores(self, entry_id, headers, params=None):
        return self._request("GET", f"/api/v1/athlete-entries/{entry_id}/scores", headers=headers, params=params)

    def list_rotation_scores(self, rotation_id, headers, params=None):
        return self._request("GET", f"/api/v1/rotations/{rotation_id}/scores", headers=headers, params=params)

    def get_score(self, score_id, headers):
        return self._request("GET", f"/api/v1/scores/{score_id}", headers=headers)

    def amend_score(self, score_id, payload, headers):
        return self._request("PUT", f"/api/v1/scores/{score_id}", payload, headers)

    def publish_score(self, score_id, payload, headers):
        return self._request("POST", f"/api/v1/scores/{score_id}/publish", payload, headers)

    def void_score(self, score_id, headers):
        return self._request("POST", f"/api/v1/scores/{score_id}/void", {}, headers)

    def finalize_score(self, score_id, headers):
        return self._request("POST", f"/api/v1/scores/{score_id}/finalize", {}, headers)

    # --- Inquiry ---
    def file_inquiry(self, score_id, payload, headers):
        return self._request("POST", f"/api/v1/scores/{score_id}/inquiries", payload, headers)

    def list_score_inquiries(self, score_id, headers, params=None):
        return self._request("GET", f"/api/v1/scores/{score_id}/inquiries", headers=headers, params=params)

    def list_coach_inquiries(self, coach_id, headers, params=None):
        return self._request("GET", f"/api/v1/coaches/{coach_id}/inquiries", headers=headers, params=params)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/api/v1/inquiries/{inquiry_id}", headers=headers)

    def begin_review(self, inquiry_id, headers):
        return self._request("POST", f"/api/v1/inquiries/{inquiry_id}/begin-review", {}, headers)

    def return_to_queue(self, inquiry_id, headers):
        return self._request("POST", f"/api/v1/inquiries/{inquiry_id}/return-to-queue", {}, headers)

    def resolve_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/api/v1/inquiries/{inquiry_id}/resolve", payload, headers)

    def withdraw_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/api/v1/inquiries/{inquiry_id}/withdraw", {}, headers)

    # --- Award ---
    def list_session_awards(self, session_id, headers, params=None):
        return self._request("GET", f"/api/v1/sessions/{session_id}/awards", headers=headers, params=params)

    def list_entry_awards(self, entry_id, headers, params=None):
        return self._request("GET", f"/api/v1/athlete-entries/{entry_id}/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/api/v1/awards/{award_id}", headers=headers)

    def generate_awards(self, session_id, payload, headers):
        return self._request("POST", f"/api/v1/sessions/{session_id}/awards/generate", payload, headers)

    # --- SpectatorTicket ---
    def issue_ticket(self, meet_id, session_id, payload, headers):
        return self._request("POST", f"/api/v1/meets/{meet_id}/sessions/{session_id}/spectator-tickets", payload, headers)

    def list_meet_tickets(self, meet_id, headers, params=None):
        return self._request("GET", f"/api/v1/meets/{meet_id}/spectator-tickets", headers=headers, params=params)

    def list_session_tickets(self, session_id, headers, params=None):
        return self._request("GET", f"/api/v1/sessions/{session_id}/spectator-tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/api/v1/spectator-tickets/{ticket_id}", headers=headers)

    def scan_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/v1/spectator-tickets/{ticket_id}/scan", {}, headers)

    def redeem_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/v1/spectator-tickets/{ticket_id}/redeem", {}, headers)

    def refund_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/v1/spectator-tickets/{ticket_id}/refund", {}, headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/v1/spectator-tickets/{ticket_id}/void", {}, headers)

    # --- QualificationRecord ---
    def list_entry_qualification_records(self, entry_id, headers, params=None):
        return self._request("GET", f"/api/v1/athlete-entries/{entry_id}/qualification-records", headers=headers, params=params)

    def get_qualification_record(self, record_id, headers):
        return self._request("GET", f"/api/v1/qualification-records/{record_id}", headers=headers)

    def confirm_qualification_record(self, record_id, headers):
        return self._request("POST", f"/api/v1/qualification-records/{record_id}/confirm", {}, headers)

    def decline_qualification_record(self, record_id, headers):
        return self._request("POST", f"/api/v1/qualification-records/{record_id}/decline", {}, headers)

    def revoke_qualification_record(self, record_id, headers):
        return self._request("POST", f"/api/v1/qualification-records/{record_id}/revoke", {}, headers)

    # --- Live scoring read model ---
    def list_live_scores(self, session_id, headers, params=None):
        return self._request("GET", f"/api/v1/sessions/{session_id}/live-scores", headers=headers, params=params)


api_client = ApiClient()
