"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Buildings and rooms
    # ------------------------------------------------------------------
    def create_building(self, payload, headers):
        return self._request("POST", "/buildings", payload, headers)

    def list_buildings(self, headers, params=None):
        return self._request("GET", "/buildings", headers=headers, params=params)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/buildings/{building_id}", headers=headers)

    def initiate_release(self, building_id, headers):
        return self._request("POST", f"/buildings/{building_id}/initiate-release", {}, headers)

    def confirm_release(self, building_id, headers):
        return self._request("POST", f"/buildings/{building_id}/confirm-release", {}, headers)

    def abort_release(self, building_id, headers):
        return self._request("POST", f"/buildings/{building_id}/abort-release", {}, headers)

    def begin_turn_season(self, building_id, headers):
        return self._request("POST", f"/buildings/{building_id}/begin-turn-season", {}, headers)

    def begin_fall_prep(self, building_id, headers):
        return self._request("POST", f"/buildings/{building_id}/begin-fall-prep", {}, headers)

    def certify_fall_ready(self, building_id, headers):
        return self._request("POST", f"/buildings/{building_id}/certify-fall-ready", {}, headers)

    def reopen_academic(self, building_id, headers):
        return self._request("POST", f"/buildings/{building_id}/reopen-academic", {}, headers)

    def create_room(self, building_id, payload, headers):
        return self._request("POST", f"/buildings/{building_id}/rooms", payload, headers)

    def list_rooms(self, building_id, headers, params=None):
        return self._request("GET", f"/buildings/{building_id}/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def list_room_turn_tasks(self, room_id, headers, params=None):
        return self._request("GET", f"/rooms/{room_id}/turn-tasks", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Conference groups, participants, rooming-list revisions
    # ------------------------------------------------------------------
    def create_conference_group(self, payload, headers):
        return self._request("POST", "/conference-groups", payload, headers)

    def list_conference_groups(self, headers, params=None):
        return self._request("GET", "/conference-groups", headers=headers, params=params)

    def get_conference_group(self, group_id, headers):
        return self._request("GET", f"/conference-groups/{group_id}", headers=headers)

    def record_deposit(self, group_id, amount_cents, headers):
        return self._request("POST", f"/conference-groups/{group_id}/record-deposit",
                             {"amount_cents": amount_cents}, headers)

    def add_participant(self, group_id, payload, headers):
        return self._request("POST", f"/conference-groups/{group_id}/participants", payload, headers)

    def list_participants(self, group_id, headers, params=None):
        return self._request("GET", f"/conference-groups/{group_id}/participants",
                             headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def create_rooming_list_revision(self, group_id, payload, headers):
        return self._request("POST", f"/conference-groups/{group_id}/rooming-list-revisions",
                             payload, headers)

    def list_rooming_list_revisions(self, group_id, headers, params=None):
        return self._request("GET", f"/conference-groups/{group_id}/rooming-list-revisions",
                             headers=headers, params=params)

    def get_rooming_list_revision(self, revision_id, headers):
        return self._request("GET", f"/rooming-list-revisions/{revision_id}", headers=headers)

    def submit_group(self, group_id, headers):
        return self._request("POST", f"/conference-groups/{group_id}/submit", {}, headers)

    def return_for_revision(self, group_id, headers):
        return self._request("POST", f"/conference-groups/{group_id}/return-for-revision", {}, headers)

    def confirm_group(self, group_id, headers):
        return self._request("POST", f"/conference-groups/{group_id}/confirm", {}, headers)

    def cancel_group(self, group_id, headers):
        return self._request("POST", f"/conference-groups/{group_id}/cancel", {}, headers)

    def close_out_group(self, group_id, headers):
        return self._request("POST", f"/conference-groups/{group_id}/close-out", {}, headers)

    # ------------------------------------------------------------------
    # Stay assignments
    # ------------------------------------------------------------------
    def list_stay_assignments(self, headers, params=None):
        return self._request("GET", "/stay-assignments", headers=headers, params=params)

    def get_stay_assignment(self, assignment_id, headers):
        return self._request("GET", f"/stay-assignments/{assignment_id}", headers=headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/stay-assignments/{assignment_id}/check-in", {}, headers)

    def check_out_assignment(self, assignment_id, headers):
        return self._request("POST", f"/stay-assignments/{assignment_id}/check-out", {}, headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request("POST", f"/stay-assignments/{assignment_id}/mark-no-show", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/stay-assignments/{assignment_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Turn tasks
    # ------------------------------------------------------------------
    def get_turn_task(self, task_id, headers):
        return self._request("GET", f"/turn-tasks/{task_id}", headers=headers)

    def start_turn_task(self, task_id, headers):
        return self._request("POST", f"/turn-tasks/{task_id}/start", {}, headers)

    def submit_turn_task_for_inspection(self, task_id, headers):
        return self._request("POST", f"/turn-tasks/{task_id}/submit-for-inspection", {}, headers)

    def inspect_turn_task(self, task_id, outcome, headers, note=None):
        payload = {"outcome": outcome}
        if note is not None:
            payload["note"] = note
        return self._request("POST", f"/turn-tasks/{task_id}/inspect", payload, headers)

    def cancel_turn_task(self, task_id, headers):
        return self._request("POST", f"/turn-tasks/{task_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Background screenings
    # ------------------------------------------------------------------
    def create_background_screening(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/background-screenings",
                             payload, headers)

    def list_participant_screenings(self, participant_id, headers, params=None):
        return self._request("GET", f"/participants/{participant_id}/background-screenings",
                             headers=headers, params=params)

    def get_background_screening(self, screening_id, headers):
        return self._request("GET", f"/background-screenings/{screening_id}", headers=headers)

    def begin_review_screening(self, screening_id, headers):
        return self._request("POST", f"/background-screenings/{screening_id}/begin-review", {}, headers)

    def decide_screening(self, screening_id, outcome, headers):
        return self._request("POST", f"/background-screenings/{screening_id}/decide",
                             {"outcome": outcome}, headers)

    def appeal_screening(self, screening_id, appeal_reason, headers):
        return self._request("POST", f"/background-screenings/{screening_id}/appeal",
                             {"appeal_reason": appeal_reason}, headers)

    def resolve_appeal(self, screening_id, outcome, headers):
        return self._request("POST", f"/background-screenings/{screening_id}/resolve-appeal",
                             {"outcome": outcome}, headers)

    # ------------------------------------------------------------------
    # Linen issues
    # ------------------------------------------------------------------
    def create_linen_issue(self, group_id, packs_issued, headers):
        return self._request("POST", f"/conference-groups/{group_id}/linen-issues",
                             {"packs_issued": packs_issued}, headers)

    def list_linen_issues(self, headers, params=None):
        return self._request("GET", "/linen-issues", headers=headers, params=params)

    def get_linen_issue(self, issue_id, headers):
        return self._request("GET", f"/linen-issues/{issue_id}", headers=headers)

    def record_linen_return(self, issue_id, packs_returned, packs_damaged, headers):
        return self._request("POST", f"/linen-issues/{issue_id}/record-return",
                             {"packs_returned": packs_returned, "packs_damaged": packs_damaged},
                             headers)

    # ------------------------------------------------------------------
    # Key credentials
    # ------------------------------------------------------------------
    def create_key_credential(self, group_id, participant_id, credential_code, headers):
        return self._request("POST", f"/conference-groups/{group_id}/key-credentials",
                             {"participant_id": participant_id,
                              "credential_code": credential_code}, headers)

    def list_key_credentials(self, headers, params=None):
        return self._request("GET", "/key-credentials", headers=headers, params=params)

    def get_key_credential(self, credential_id, headers):
        return self._request("GET", f"/key-credentials/{credential_id}", headers=headers)

    def activate_key_credential(self, credential_id, headers):
        return self._request("POST", f"/key-credentials/{credential_id}/activate", {}, headers)

    def return_key_credential(self, credential_id, headers):
        return self._request("POST", f"/key-credentials/{credential_id}/return", {}, headers)

    def report_key_lost(self, credential_id, headers):
        return self._request("POST", f"/key-credentials/{credential_id}/report-lost", {}, headers)

    # ------------------------------------------------------------------
    # Damage assessments
    # ------------------------------------------------------------------
    def create_damage_assessment(self, room_id, payload, headers):
        return self._request("POST", f"/rooms/{room_id}/damage-assessments", payload, headers)

    def list_damage_assessments(self, headers, params=None):
        return self._request("GET", "/damage-assessments", headers=headers, params=params)

    def get_damage_assessment(self, assessment_id, headers):
        return self._request("GET", f"/damage-assessments/{assessment_id}", headers=headers)

    def assess_damage(self, assessment_id, headers):
        return self._request("POST", f"/damage-assessments/{assessment_id}/assess", {}, headers)

    def bill_damage(self, assessment_id, headers):
        return self._request("POST", f"/damage-assessments/{assessment_id}/bill", {}, headers)

    def dispute_damage(self, assessment_id, dispute_reason, headers):
        return self._request("POST", f"/damage-assessments/{assessment_id}/dispute",
                             {"dispute_reason": dispute_reason}, headers)

    def resolve_damage(self, assessment_id, outcome, headers, adjusted_line_items=None):
        payload = {"outcome": outcome}
        if adjusted_line_items is not None:
            payload["adjusted_line_items"] = adjusted_line_items
        return self._request("POST", f"/damage-assessments/{assessment_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", {}, headers)

    def record_payment(self, invoice_id, amount_cents, headers):
        return self._request("POST", f"/invoices/{invoice_id}/record-payment",
                             {"amount_cents": amount_cents}, headers)

    # ------------------------------------------------------------------
    # Maintenance windows
    # ------------------------------------------------------------------
    def create_maintenance_window(self, building_id, payload, headers):
        return self._request("POST", f"/buildings/{building_id}/maintenance-windows",
                             payload, headers)

    def list_maintenance_windows(self, building_id, headers, params=None):
        return self._request("GET", f"/buildings/{building_id}/maintenance-windows",
                             headers=headers, params=params)

    def get_maintenance_window(self, window_id, headers):
        return self._request("GET", f"/maintenance-windows/{window_id}", headers=headers)

    def confirm_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/maintenance-windows/{window_id}/confirm", {}, headers)

    def start_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/maintenance-windows/{window_id}/start", {}, headers)

    def complete_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/maintenance-windows/{window_id}/complete", {}, headers)

    def cancel_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/maintenance-windows/{window_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Allocation runs
    # ------------------------------------------------------------------
    def create_allocation_run(self, building_id, payload, headers):
        return self._request("POST", f"/buildings/{building_id}/allocation-runs", payload, headers)

    def list_allocation_runs(self, building_id, headers, params=None):
        return self._request("GET", f"/buildings/{building_id}/allocation-runs",
                             headers=headers, params=params)

    def get_allocation_run(self, run_id, headers):
        return self._request("GET", f"/allocation-runs/{run_id}", headers=headers)

    def lock_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/lock", {}, headers)


api_client = ApiClient()
