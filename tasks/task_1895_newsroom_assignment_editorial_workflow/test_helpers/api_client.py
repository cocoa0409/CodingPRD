"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Staff administration
    # ------------------------------------------------------------------
    def create_staff(self, payload, headers):
        return self._request("POST", "/newsroom/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/newsroom/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/newsroom/staff/{staff_id}", headers=headers)

    def patch_staff(self, staff_id, payload, headers):
        return self._request("PATCH", f"/newsroom/staff/{staff_id}", payload, headers)

    def get_staff_assignments(self, staff_id, headers, params=None):
        return self._request("GET", f"/newsroom/staff/{staff_id}/assignments",
                             headers=headers, params=params)

    def get_staff_payroll(self, staff_id, headers, params=None):
        return self._request("GET", f"/newsroom/staff/{staff_id}/payroll",
                             headers=headers, params=params)

    def get_staff_reviews(self, staff_id, headers, params=None):
        return self._request("GET", f"/newsroom/staff/{staff_id}/reviews",
                             headers=headers, params=params)

    def get_staff_corrections(self, staff_id, headers, params=None):
        return self._request("GET", f"/newsroom/staff/{staff_id}/corrections",
                             headers=headers, params=params)

    def get_staff_call_ins(self, staff_id, headers, params=None):
        return self._request("GET", f"/newsroom/staff/{staff_id}/call-ins",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Pitch intake & desk review
    # ------------------------------------------------------------------
    def create_pitch(self, payload, headers):
        return self._request("POST", "/newsroom/pitches", payload, headers)

    def list_pitches(self, headers, params=None):
        return self._request("GET", "/newsroom/pitches", headers=headers, params=params)

    def get_pitch(self, pitch_id, headers):
        return self._request("GET", f"/newsroom/pitches/{pitch_id}", headers=headers)

    def get_pitch_stories(self, pitch_id, headers):
        return self._request("GET", f"/newsroom/pitches/{pitch_id}/stories",
                             headers=headers)

    def start_pitch_review(self, pitch_id, headers):
        return self._request("POST", f"/newsroom/pitches/{pitch_id}/start-review",
                             {}, headers)

    def return_pitch(self, pitch_id, headers):
        return self._request("POST", f"/newsroom/pitches/{pitch_id}/return",
                             {}, headers)

    def greenlight_pitch(self, pitch_id, payload, headers):
        return self._request("POST", f"/newsroom/pitches/{pitch_id}/greenlight",
                             payload, headers)

    def reject_pitch(self, pitch_id, headers):
        return self._request("POST", f"/newsroom/pitches/{pitch_id}/reject",
                             {}, headers)

    def withdraw_pitch(self, pitch_id, headers):
        return self._request("POST", f"/newsroom/pitches/{pitch_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Story workflow
    # ------------------------------------------------------------------
    def list_stories(self, headers, params=None):
        return self._request("GET", "/newsroom/stories", headers=headers, params=params)

    def get_story(self, story_id, headers):
        return self._request("GET", f"/newsroom/stories/{story_id}", headers=headers)

    def patch_story(self, story_id, payload, headers):
        return self._request("PATCH", f"/newsroom/stories/{story_id}", payload, headers)

    def submit_story_edit(self, story_id, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/submit-edit",
                             {}, headers)

    def complete_story_edit(self, story_id, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/complete-edit",
                             {}, headers)

    def create_story_review(self, story_id, payload, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/reviews",
                             payload, headers)

    def schedule_story(self, story_id, payload, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/schedule",
                             payload, headers)

    def unschedule_story(self, story_id, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/unschedule",
                             {}, headers)

    def reopen_story(self, story_id, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/reopen",
                             {}, headers)

    def kill_story(self, story_id, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/kill",
                             {}, headers)

    def supersede_story(self, story_id, payload, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/supersede",
                             payload, headers)

    def get_story_priority_score(self, story_id, headers, params=None):
        return self._request("GET", f"/newsroom/stories/{story_id}/priority-score",
                             headers=headers, params=params)

    def get_story_assignments(self, story_id, headers, params=None):
        return self._request("GET", f"/newsroom/stories/{story_id}/assignments",
                             headers=headers, params=params)

    def get_story_reviews(self, story_id, headers, params=None):
        return self._request("GET", f"/newsroom/stories/{story_id}/reviews",
                             headers=headers, params=params)

    def get_story_corrections(self, story_id, headers, params=None):
        return self._request("GET", f"/newsroom/stories/{story_id}/corrections",
                             headers=headers, params=params)

    def get_story_analytics_reports(self, story_id, headers, params=None):
        return self._request("GET", f"/newsroom/stories/{story_id}/analytics-reports",
                             headers=headers, params=params)

    def create_story_correction(self, story_id, payload, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/corrections",
                             payload, headers)

    def create_story_analytics_report(self, story_id, payload, headers):
        return self._request("POST", f"/newsroom/stories/{story_id}/analytics-reports",
                             payload, headers)

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/newsroom/assignments", payload, headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/newsroom/assignments/{assignment_id}/accept",
                             {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/newsroom/assignments/{assignment_id}/decline",
                             {}, headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/newsroom/assignments/{assignment_id}/complete",
                             payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/newsroom/assignments/{assignment_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Publication slots
    # ------------------------------------------------------------------
    def create_slot(self, payload, headers):
        return self._request("POST", "/newsroom/slots", payload, headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/newsroom/slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/newsroom/slots/{slot_id}", headers=headers)

    def get_slot_stories(self, slot_id, headers, params=None):
        return self._request("GET", f"/newsroom/slots/{slot_id}/stories",
                             headers=headers, params=params)

    def cancel_slot(self, slot_id, headers):
        return self._request("POST", f"/newsroom/slots/{slot_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Corrections governance
    # ------------------------------------------------------------------
    def approve_correction(self, correction_id, headers):
        return self._request("POST", f"/newsroom/corrections/{correction_id}/approve",
                             {}, headers)

    def reject_correction(self, correction_id, headers):
        return self._request("POST", f"/newsroom/corrections/{correction_id}/reject",
                             {}, headers)

    def issue_correction(self, correction_id, headers):
        return self._request("POST", f"/newsroom/corrections/{correction_id}/issue",
                             {}, headers)

    # ------------------------------------------------------------------
    # Breaking news
    # ------------------------------------------------------------------
    def create_breaking_event(self, payload, headers):
        return self._request("POST", "/newsroom/breaking-events", payload, headers)

    def list_breaking_events(self, headers, params=None):
        return self._request("GET", "/newsroom/breaking-events",
                             headers=headers, params=params)

    def get_breaking_event(self, event_id, headers):
        return self._request("GET", f"/newsroom/breaking-events/{event_id}",
                             headers=headers)

    def activate_breaking_event(self, event_id, headers):
        return self._request("POST", f"/newsroom/breaking-events/{event_id}/activate",
                             {}, headers)

    def resolve_breaking_event(self, event_id, headers):
        return self._request("POST", f"/newsroom/breaking-events/{event_id}/resolve",
                             {}, headers)

    def get_event_call_ins(self, event_id, headers, params=None):
        return self._request("GET", f"/newsroom/breaking-events/{event_id}/call-ins",
                             headers=headers, params=params)

    def get_event_assignments(self, event_id, headers, params=None):
        return self._request("GET",
                             f"/newsroom/breaking-events/{event_id}/assignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Staffing call-ins
    # ------------------------------------------------------------------
    def confirm_call_in(self, call_in_id, headers):
        return self._request("POST", f"/newsroom/call-ins/{call_in_id}/confirm",
                             {}, headers)

    def decline_call_in(self, call_in_id, headers):
        return self._request("POST", f"/newsroom/call-ins/{call_in_id}/decline",
                             {}, headers)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def run_publication_scheduler(self, headers):
        return self._request("POST", "/newsroom/ops/run-publication-scheduler",
                             {}, headers)


api_client = ApiClient()
