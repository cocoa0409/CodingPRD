"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ucc/_clock/set_current_utc", payload, headers)

    # --- students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/ucc/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/ucc/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/ucc/students", headers=headers, params=params)

    def update_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/ucc/students/{student_id}", payload, headers)

    def reset_student_strikes(self, student_id, headers):
        return self._request("POST", f"/ucc/students/{student_id}/strikes/reset",
                             headers=headers)

    # --- counselors ---
    def create_counselor(self, payload, headers):
        return self._request("POST", "/ucc/counselors", payload, headers)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/ucc/counselors/{counselor_id}", headers=headers)

    def list_counselors(self, headers, params=None):
        return self._request("GET", "/ucc/counselors", headers=headers, params=params)

    # --- intake assessments ---
    def create_intake_assessment(self, payload, headers):
        return self._request("POST", "/ucc/intake-assessments", payload, headers)

    def get_intake_assessment(self, assessment_id, headers):
        return self._request("GET", f"/ucc/intake-assessments/{assessment_id}",
                             headers=headers)

    def list_intake_assessments(self, headers, params=None):
        return self._request("GET", "/ucc/intake-assessments",
                             headers=headers, params=params)

    def complete_intake_assessment(self, assessment_id, payload, headers):
        return self._request("POST",
                             f"/ucc/intake-assessments/{assessment_id}/complete",
                             payload, headers)

    # --- care episodes ---
    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/ucc/episodes/{episode_id}", headers=headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/ucc/episodes", headers=headers, params=params)

    def book_session(self, episode_id, payload, headers):
        return self._request("POST", f"/ucc/episodes/{episode_id}/sessions",
                             payload, headers)

    def close_episode(self, episode_id, headers):
        return self._request("POST", f"/ucc/episodes/{episode_id}/close",
                             headers=headers)

    def reopen_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/ucc/episodes/{episode_id}/reopen",
                             payload, headers)

    def grant_episode_exemption(self, episode_id, headers):
        return self._request("POST", f"/ucc/episodes/{episode_id}/exemptions",
                             headers=headers)

    # --- sessions ---
    def get_session(self, session_id, headers):
        return self._request("GET", f"/ucc/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/ucc/sessions", headers=headers, params=params)

    def hold_session(self, session_id, headers):
        return self._request("POST", f"/ucc/sessions/{session_id}/hold",
                             headers=headers)

    def release_session_hold(self, session_id, headers):
        return self._request("POST", f"/ucc/sessions/{session_id}/release-hold",
                             headers=headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/ucc/sessions/{session_id}/complete",
                             headers=headers)

    def cancel_session(self, session_id, payload, headers):
        return self._request("POST", f"/ucc/sessions/{session_id}/cancel",
                             payload, headers)

    def mark_session_no_show(self, session_id, payload, headers):
        return self._request("POST", f"/ucc/sessions/{session_id}/mark-no-show",
                             payload, headers)

    def excuse_session_no_show(self, session_id, headers):
        return self._request("POST", f"/ucc/sessions/{session_id}/excuse",
                             headers=headers)

    # --- clinical notes ---
    def create_clinical_note(self, payload, headers):
        return self._request("POST", "/ucc/clinical-notes", payload, headers)

    def get_clinical_note(self, note_id, headers):
        return self._request("GET", f"/ucc/clinical-notes/{note_id}", headers=headers)

    def list_clinical_notes(self, headers, params=None):
        return self._request("GET", "/ucc/clinical-notes",
                             headers=headers, params=params)

    # --- group programs ---
    def create_group_program(self, payload, headers):
        return self._request("POST", "/ucc/group-programs", payload, headers)

    def get_group_program(self, program_id, headers):
        return self._request("GET", f"/ucc/group-programs/{program_id}",
                             headers=headers)

    def list_group_programs(self, headers, params=None):
        return self._request("GET", "/ucc/group-programs",
                             headers=headers, params=params)

    def publish_group_program(self, program_id, headers):
        return self._request("POST", f"/ucc/group-programs/{program_id}/publish",
                             headers=headers)

    def cancel_group_program(self, program_id, headers):
        return self._request("POST", f"/ucc/group-programs/{program_id}/cancel",
                             headers=headers)

    def enroll_in_group_program(self, program_id, payload, headers):
        return self._request("POST",
                             f"/ucc/group-programs/{program_id}/enrollments",
                             payload, headers)

    # --- group enrollments ---
    def get_group_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/ucc/group-enrollments/{enrollment_id}",
                             headers=headers)

    def list_group_enrollments(self, headers, params=None):
        return self._request("GET", "/ucc/group-enrollments",
                             headers=headers, params=params)

    def drop_group_enrollment(self, enrollment_id, headers):
        return self._request("POST",
                             f"/ucc/group-enrollments/{enrollment_id}/drop",
                             headers=headers)

    # --- crisis shifts ---
    def create_crisis_shift(self, payload, headers):
        return self._request("POST", "/ucc/crisis-shifts", payload, headers)

    def get_crisis_shift(self, shift_id, headers):
        return self._request("GET", f"/ucc/crisis-shifts/{shift_id}", headers=headers)

    def list_crisis_shifts(self, headers, params=None):
        return self._request("GET", "/ucc/crisis-shifts",
                             headers=headers, params=params)

    def claim_crisis_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/ucc/crisis-shifts/{shift_id}/claim",
                             payload, headers)

    def release_crisis_shift(self, shift_id, headers):
        return self._request("POST", f"/ucc/crisis-shifts/{shift_id}/release",
                             headers=headers)

    # --- crisis visits ---
    def create_crisis_visit(self, payload, headers):
        return self._request("POST", "/ucc/crisis-visits", payload, headers)

    def get_crisis_visit(self, visit_id, headers):
        return self._request("GET", f"/ucc/crisis-visits/{visit_id}", headers=headers)

    def list_crisis_visits(self, headers, params=None):
        return self._request("GET", "/ucc/crisis-visits",
                             headers=headers, params=params)

    def room_crisis_visit(self, visit_id, headers):
        return self._request("POST", f"/ucc/crisis-visits/{visit_id}/room",
                             headers=headers)

    def stabilize_crisis_visit(self, visit_id, headers):
        return self._request("POST", f"/ucc/crisis-visits/{visit_id}/stabilize",
                             headers=headers)

    def escalate_crisis_visit(self, visit_id, headers):
        return self._request("POST", f"/ucc/crisis-visits/{visit_id}/escalate",
                             headers=headers)

    def disposition_crisis_visit(self, visit_id, payload, headers):
        return self._request("POST",
                             f"/ucc/crisis-visits/{visit_id}/disposition",
                             payload, headers)

    # --- referrals ---
    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/ucc/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/ucc/referrals", headers=headers, params=params)

    def match_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/ucc/referrals/{referral_id}/match",
                             payload, headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/ucc/referrals/{referral_id}/accept",
                             headers=headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/ucc/referrals/{referral_id}/decline",
                             headers=headers)

    def rematch_referral(self, referral_id, headers):
        return self._request("POST", f"/ucc/referrals/{referral_id}/rematch",
                             headers=headers)

    def confirm_referral_engagement(self, referral_id, headers):
        return self._request("POST",
                             f"/ucc/referrals/{referral_id}/confirm-engagement",
                             headers=headers)

    # --- policies ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/ucc/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/ucc/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/ucc/policies", headers=headers, params=params)

    def publish_policy(self, policy_id, headers):
        return self._request("POST", f"/ucc/policies/{policy_id}/publish",
                             headers=headers)

    def retire_policy(self, policy_id, headers):
        return self._request("POST", f"/ucc/policies/{policy_id}/retire",
                             headers=headers)

    # --- outcome measures ---
    def create_outcome_measure(self, payload, headers):
        return self._request("POST", "/ucc/outcome-measures", payload, headers)

    def get_outcome_measure(self, measure_id, headers):
        return self._request("GET", f"/ucc/outcome-measures/{measure_id}",
                             headers=headers)

    def list_outcome_measures(self, headers, params=None):
        return self._request("GET", "/ucc/outcome-measures",
                             headers=headers, params=params)

    # --- reports ---
    def get_capacity_report(self, headers, params=None):
        return self._request("GET", "/ucc/reports/capacity",
                             headers=headers, params=params)


api_client = ApiClient()
