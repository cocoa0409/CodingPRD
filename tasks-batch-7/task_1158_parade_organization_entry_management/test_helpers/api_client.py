"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ParadeEvent ---
    def create_parade(self, payload, headers):
        return self._request("POST", "/parades", payload, headers)

    def list_parades(self, headers, params=None):
        return self._request("GET", "/parades", headers=headers, params=params)

    def get_parade(self, parade_id, headers):
        return self._request("GET", f"/parades/{parade_id}", headers=headers)

    def submit_parade_permit(self, parade_id, headers):
        return self._request("POST", f"/parades/{parade_id}/submit-permit", {}, headers)

    def lock_parade(self, parade_id, headers):
        return self._request("POST", f"/parades/{parade_id}/lock", {}, headers)

    def publish_lineup(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/publish-lineup", payload, headers)

    def complete_parade(self, parade_id, headers):
        return self._request("POST", f"/parades/{parade_id}/complete", {}, headers)

    def cancel_parade(self, parade_id, headers):
        return self._request("POST", f"/parades/{parade_id}/cancel", {}, headers)

    def finalize_script(self, parade_id, headers):
        return self._request("POST", f"/parades/{parade_id}/finalize-script", {}, headers)

    # --- RouteSegment ---
    def create_route_segment(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/route-segments", payload, headers)

    def list_route_segments(self, parade_id, headers, params=None):
        return self._request("GET", f"/parades/{parade_id}/route-segments", headers=headers, params=params)

    def get_route_segment(self, segment_id, headers):
        return self._request("GET", f"/route-segments/{segment_id}", headers=headers)

    # --- PermitApplication ---
    def create_permit(self, parade_id, headers):
        return self._request("POST", f"/parades/{parade_id}/permit", {}, headers)

    def get_parade_permit(self, parade_id, headers):
        return self._request("GET", f"/parades/{parade_id}/permit", headers=headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/submit", {}, headers)

    def grant_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/grant", {}, headers)

    def deny_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/deny", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers)

    def refile_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/refile", {}, headers)

    # --- AgencyEndorsement ---
    def create_endorsement(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/endorsements", payload, headers)

    def list_endorsements(self, permit_id, headers, params=None):
        return self._request("GET", f"/permits/{permit_id}/endorsements", headers=headers, params=params)

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/endorsements/{endorsement_id}", headers=headers)

    def endorse_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/endorsements/{endorsement_id}/endorse", {}, headers)

    def reject_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/endorsements/{endorsement_id}/reject", {}, headers)

    # --- EntryApplication ---
    def create_entry(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/entries", payload, headers)

    def list_entries(self, parade_id, headers, params=None):
        return self._request("GET", f"/parades/{parade_id}/entries", headers=headers, params=params)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/entries/{entry_id}", headers=headers)

    def start_review(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/start-review", {}, headers)

    def approve_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/approve", payload, headers)

    def reject_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/reject", payload, headers)

    def request_revision(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/request-revision", payload, headers)

    def resubmit_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/resubmit", payload, headers)

    def withdraw_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/withdraw", {}, headers)

    def pay_fee(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/pay-fee", {}, headers)

    # --- Float ---
    def create_float(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/floats", payload, headers)

    def list_floats(self, entry_id, headers, params=None):
        return self._request("GET", f"/entries/{entry_id}/floats", headers=headers, params=params)

    def get_float(self, float_id, headers):
        return self._request("GET", f"/floats/{float_id}", headers=headers)

    # --- SafetyInspection ---
    def schedule_inspection(self, float_id, payload, headers):
        return self._request("POST", f"/floats/{float_id}/inspections", payload, headers)

    def list_inspections(self, float_id, headers, params=None):
        return self._request("GET", f"/floats/{float_id}/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def pass_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/pass", payload, headers)

    def fail_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/fail", payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/cancel", {}, headers)

    # --- StagingArea ---
    def create_staging_area(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/staging-areas", payload, headers)

    def list_staging_areas(self, parade_id, headers, params=None):
        return self._request("GET", f"/parades/{parade_id}/staging-areas", headers=headers, params=params)

    def get_staging_area(self, staging_area_id, headers):
        return self._request("GET", f"/staging-areas/{staging_area_id}", headers=headers)

    # --- LineupAssignment ---
    def create_lineup_assignment(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/lineup-assignments", payload, headers)

    def list_lineup_assignments(self, headers, params=None):
        return self._request("GET", "/lineup-assignments", headers=headers, params=params)

    def get_lineup_assignment(self, assignment_id, headers):
        return self._request("GET", f"/lineup-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/lineup-assignments/{assignment_id}/confirm", {}, headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/lineup-assignments/{assignment_id}/check-in", {}, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/lineup-assignments/{assignment_id}/release", {}, headers)

    def no_show_assignment(self, assignment_id, headers):
        return self._request("POST", f"/lineup-assignments/{assignment_id}/no-show", {}, headers)

    def pull_assignment(self, assignment_id, headers):
        return self._request("POST", f"/lineup-assignments/{assignment_id}/pull", {}, headers)

    # --- MarshalAssignment ---
    def create_marshal_assignment(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/marshal-assignments", payload, headers)

    def list_marshal_assignments(self, headers, params=None):
        return self._request("GET", "/marshal-assignments", headers=headers, params=params)

    def get_marshal_assignment(self, assignment_id, headers):
        return self._request("GET", f"/marshal-assignments/{assignment_id}", headers=headers)

    def confirm_marshal_assignment(self, assignment_id, headers):
        return self._request("POST", f"/marshal-assignments/{assignment_id}/confirm", {}, headers)

    def complete_marshal_assignment(self, assignment_id, headers):
        return self._request("POST", f"/marshal-assignments/{assignment_id}/complete", {}, headers)

    def no_show_marshal_assignment(self, assignment_id, headers):
        return self._request("POST", f"/marshal-assignments/{assignment_id}/no-show", {}, headers)

    # --- JudgingScoreSheet ---
    def create_score_sheet(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/score-sheets", payload, headers)

    def list_score_sheets(self, entry_id, headers, params=None):
        return self._request("GET", f"/entries/{entry_id}/score-sheets", headers=headers, params=params)

    def get_score_sheet(self, sheet_id, headers):
        return self._request("GET", f"/score-sheets/{sheet_id}", headers=headers)

    def submit_score_sheet(self, sheet_id, headers):
        return self._request("POST", f"/score-sheets/{sheet_id}/submit", {}, headers)

    def reopen_score_sheet(self, sheet_id, headers):
        return self._request("POST", f"/score-sheets/{sheet_id}/reopen", {}, headers)

    def finalize_score_sheet(self, sheet_id, headers):
        return self._request("POST", f"/score-sheets/{sheet_id}/finalize", {}, headers)

    # --- Award ---
    def create_award(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/awards", payload, headers)

    def list_parade_awards(self, parade_id, headers, params=None):
        return self._request("GET", f"/parades/{parade_id}/awards", headers=headers, params=params)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def announce_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/announce", {}, headers)

    def present_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/present", {}, headers)

    def cancel_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/cancel", {}, headers)

    # --- SponsorPackage ---
    def create_sponsor(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/sponsors", payload, headers)

    def list_sponsors(self, parade_id, headers, params=None):
        return self._request("GET", f"/parades/{parade_id}/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/sponsors/{sponsor_id}", headers=headers)

    def activate_sponsor(self, sponsor_id, headers):
        return self._request("POST", f"/sponsors/{sponsor_id}/activate", {}, headers)

    # --- AnnouncerScriptItem ---
    def create_script_item(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/script-items", payload, headers)

    def list_parade_script_items(self, parade_id, headers, params=None):
        return self._request("GET", f"/parades/{parade_id}/script-items", headers=headers, params=params)

    def list_script_items(self, headers, params=None):
        return self._request("GET", "/script-items", headers=headers, params=params)

    def get_script_item(self, item_id, headers):
        return self._request("GET", f"/script-items/{item_id}", headers=headers)

    def approve_script_item(self, item_id, headers):
        return self._request("POST", f"/script-items/{item_id}/approve", {}, headers)

    def reopen_script_item(self, item_id, headers):
        return self._request("POST", f"/script-items/{item_id}/reopen", {}, headers)

    def cancel_script_item(self, item_id, headers):
        return self._request("POST", f"/script-items/{item_id}/cancel", {}, headers)

    # --- DispersalPlan ---
    def create_dispersal_plan(self, parade_id, payload, headers):
        return self._request("POST", f"/parades/{parade_id}/dispersal-plan", payload, headers)

    def get_parade_dispersal_plan(self, parade_id, headers):
        return self._request("GET", f"/parades/{parade_id}/dispersal-plan", headers=headers)

    def get_dispersal_plan(self, plan_id, headers):
        return self._request("GET", f"/dispersal-plans/{plan_id}", headers=headers)

    def submit_dispersal_plan(self, plan_id, headers):
        return self._request("POST", f"/dispersal-plans/{plan_id}/submit", {}, headers)

    def approve_dispersal_plan(self, plan_id, headers):
        return self._request("POST", f"/dispersal-plans/{plan_id}/approve", {}, headers)

    def reject_dispersal_plan(self, plan_id, headers):
        return self._request("POST", f"/dispersal-plans/{plan_id}/reject", {}, headers)

    def revise_dispersal_plan(self, plan_id, headers):
        return self._request("POST", f"/dispersal-plans/{plan_id}/revise", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
