"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, pid, headers):
        return self._request("GET", f"/programs/{pid}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    # --- Rooms ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, rid, headers):
        return self._request("GET", f"/rooms/{rid}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    # --- PeerGroups (nested) ---
    def create_group(self, pid, payload, headers):
        return self._request("POST", f"/programs/{pid}/groups", payload, headers)

    def get_group(self, pid, gid, headers):
        return self._request("GET", f"/programs/{pid}/groups/{gid}", headers=headers)

    def list_groups(self, pid, headers, params=None):
        return self._request("GET", f"/programs/{pid}/groups", headers=headers, params=params)

    def activate_group(self, pid, gid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/activate", {}, headers)

    def pause_group(self, pid, gid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/pause", {}, headers)

    def resume_group(self, pid, gid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/resume", {}, headers)

    def retire_group(self, pid, gid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/retire", {}, headers)

    # --- Facilitators ---
    def create_facilitator(self, payload, headers):
        return self._request("POST", "/facilitators", payload, headers)

    def get_facilitator(self, fid, headers):
        return self._request("GET", f"/facilitators/{fid}", headers=headers)

    def list_facilitators(self, headers, params=None):
        return self._request("GET", "/facilitators", headers=headers, params=params)

    def advance_to_screening(self, fid, headers):
        return self._request("POST", f"/facilitators/{fid}/advance-to-screening", {}, headers)

    def advance_to_training(self, fid, headers):
        return self._request("POST", f"/facilitators/{fid}/advance-to-training", {}, headers)

    def advance_to_practice(self, fid, headers):
        return self._request("POST", f"/facilitators/{fid}/advance-to-practice", {}, headers)

    def certify_facilitator(self, fid, headers):
        return self._request("POST", f"/facilitators/{fid}/certify", {}, headers)

    def suspend_facilitator(self, fid, headers):
        return self._request("POST", f"/facilitators/{fid}/suspend", {}, headers)

    def reinstate_facilitator(self, fid, headers):
        return self._request("POST", f"/facilitators/{fid}/reinstate", {}, headers)

    def withdraw_facilitator(self, fid, headers):
        return self._request("POST", f"/facilitators/{fid}/withdraw", {}, headers)

    def reject_facilitator(self, fid, headers):
        return self._request("POST", f"/facilitators/{fid}/reject", {}, headers)

    # --- Training courses / completions / reviews ---
    def create_training_course(self, payload, headers):
        return self._request("POST", "/training-courses", payload, headers)

    def get_training_course(self, tcid, headers):
        return self._request("GET", f"/training-courses/{tcid}", headers=headers)

    def list_training_courses(self, headers, params=None):
        return self._request("GET", "/training-courses", headers=headers, params=params)

    def create_training_completion(self, fid, payload, headers):
        return self._request("POST", f"/facilitators/{fid}/training-completions", payload, headers)

    def list_training_completions(self, fid, headers, params=None):
        return self._request("GET", f"/facilitators/{fid}/training-completions", headers=headers, params=params)

    def create_supervision_review(self, fid, payload, headers):
        return self._request("POST", f"/facilitators/{fid}/supervision-reviews", payload, headers)

    def list_supervision_reviews(self, fid, headers, params=None):
        return self._request("GET", f"/facilitators/{fid}/supervision-reviews", headers=headers, params=params)

    # --- Participants ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, pid, headers):
        return self._request("GET", f"/participants/{pid}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def activate_participant(self, pid, headers):
        return self._request("POST", f"/participants/{pid}/activate", {}, headers)

    def suspend_participant(self, pid, headers):
        return self._request("POST", f"/participants/{pid}/suspend", {}, headers)

    def reinstate_participant(self, pid, headers):
        return self._request("POST", f"/participants/{pid}/reinstate", {}, headers)

    def deactivate_participant(self, pid, headers):
        return self._request("POST", f"/participants/{pid}/deactivate", {}, headers)

    # --- Confidentiality agreements ---
    def create_agreement(self, pid, payload, headers):
        return self._request("POST", f"/participants/{pid}/agreements", payload, headers)

    def list_agreements(self, pid, headers, params=None):
        return self._request("GET", f"/participants/{pid}/agreements", headers=headers, params=params)

    def get_agreement(self, pid, aid, headers):
        return self._request("GET", f"/participants/{pid}/agreements/{aid}", headers=headers)

    def revoke_agreement(self, pid, aid, headers):
        return self._request("POST", f"/participants/{pid}/agreements/{aid}/revoke", {}, headers)

    # --- Sessions ---
    def create_session(self, pid, gid, payload, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions", payload, headers)

    def get_session(self, pid, gid, sid, headers):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions/{sid}", headers=headers)

    def list_sessions(self, pid, gid, headers, params=None):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions", headers=headers, params=params)

    def schedule_session(self, pid, gid, sid, payload, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/schedule", payload, headers)

    def cancel_session(self, pid, gid, sid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/cancel", {}, headers)

    def complete_session(self, pid, gid, sid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/complete", {}, headers)

    def get_session_summary(self, pid, gid, sid, headers):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions/{sid}/summary", headers=headers)

    # --- Enrollments ---
    def create_enrollment(self, pid, gid, payload, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/enrollments", payload, headers)

    def list_enrollments(self, pid, gid, headers, params=None):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/enrollments", headers=headers, params=params)

    def get_enrollment(self, pid, gid, eid, headers):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/enrollments/{eid}", headers=headers)

    def confirm_enrollment(self, pid, gid, eid, payload, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/enrollments/{eid}/confirm", payload, headers)

    def release_enrollment(self, pid, gid, eid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/enrollments/{eid}/release", {}, headers)

    # --- Attendance ---
    def check_in(self, pid, gid, sid, payload, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/attendance", payload, headers)

    def list_attendance(self, pid, gid, sid, headers, params=None):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions/{sid}/attendance", headers=headers, params=params)

    def get_attendance(self, pid, gid, sid, aid, headers):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions/{sid}/attendance/{aid}", headers=headers)

    def checkout_attendance(self, pid, gid, sid, aid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/attendance/{aid}/checkout", {}, headers)

    def void_attendance(self, pid, gid, sid, aid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/attendance/{aid}/void", {}, headers)

    # --- Incident reports ---
    def create_incident(self, pid, gid, sid, payload, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/incidents", payload, headers)

    def list_incidents(self, pid, gid, sid, headers, params=None):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions/{sid}/incidents", headers=headers, params=params)

    def get_incident(self, pid, gid, sid, iid, headers):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions/{sid}/incidents/{iid}", headers=headers)

    def acknowledge_incident(self, pid, gid, sid, iid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/incidents/{iid}/acknowledge", {}, headers)

    def resolve_incident(self, pid, gid, sid, iid, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/incidents/{iid}/resolve", {}, headers)

    def escalate_incident(self, pid, gid, sid, iid, headers, payload=None):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/incidents/{iid}/escalate", payload or {}, headers)

    # --- Clinical referrals ---
    def list_referrals(self, pid, headers, params=None):
        return self._request("GET", f"/participants/{pid}/referrals", headers=headers, params=params)

    def get_referral(self, pid, rid, headers):
        return self._request("GET", f"/participants/{pid}/referrals/{rid}", headers=headers)

    def accept_referral(self, pid, rid, headers):
        return self._request("POST", f"/participants/{pid}/referrals/{rid}/accept", {}, headers)

    def decline_referral(self, pid, rid, headers):
        return self._request("POST", f"/participants/{pid}/referrals/{rid}/decline", {}, headers)

    def complete_referral(self, pid, rid, headers):
        return self._request("POST", f"/participants/{pid}/referrals/{rid}/complete", {}, headers)

    # --- Evaluation surveys ---
    def create_survey(self, pid, gid, sid, payload, headers):
        return self._request("POST", f"/programs/{pid}/groups/{gid}/sessions/{sid}/surveys", payload, headers)

    def list_surveys(self, pid, gid, sid, headers, params=None):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions/{sid}/surveys", headers=headers, params=params)

    def get_survey(self, pid, gid, sid, svid, headers):
        return self._request("GET", f"/programs/{pid}/groups/{gid}/sessions/{sid}/surveys/{svid}", headers=headers)

    # --- Computed facilitator capacity score ---
    def get_capacity_score(self, fid, headers):
        return self._request("GET", f"/facilitators/{fid}/capacity-score", headers=headers)

    # --- Top-level single-resource aliases ---
    def get_group_by_id(self, gid, headers):
        return self._request("GET", f"/groups/{gid}", headers=headers)

    def get_session_by_id(self, sid, headers):
        return self._request("GET", f"/sessions/{sid}", headers=headers)

    def get_training_completion_by_id(self, tcid, headers):
        return self._request("GET", f"/training-completions/{tcid}", headers=headers)

    def get_supervision_review_by_id(self, srid, headers):
        return self._request("GET", f"/supervision-reviews/{srid}", headers=headers)

    def get_agreement_by_id(self, aid, headers):
        return self._request("GET", f"/agreements/{aid}", headers=headers)

    def get_enrollment_by_id(self, eid, headers):
        return self._request("GET", f"/enrollments/{eid}", headers=headers)

    def get_attendance_record_by_id(self, aid, headers):
        return self._request("GET", f"/attendance-records/{aid}", headers=headers)

    def get_incident_report_by_id(self, iid, headers):
        return self._request("GET", f"/incident-reports/{iid}", headers=headers)

    def get_clinical_referral_by_id(self, rid, headers):
        return self._request("GET", f"/clinical-referrals/{rid}", headers=headers)

    def get_evaluation_survey_by_id(self, svid, headers):
        return self._request("GET", f"/evaluation-surveys/{svid}", headers=headers)

    # --- Top-level filtered collections ---
    def list_all_groups(self, headers, params=None):
        return self._request("GET", "/groups", headers=headers, params=params)

    def list_all_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def list_all_training_completions(self, headers, params=None):
        return self._request("GET", "/training-completions", headers=headers, params=params)

    def list_all_supervision_reviews(self, headers, params=None):
        return self._request("GET", "/supervision-reviews", headers=headers, params=params)

    def list_all_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def list_all_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def list_all_attendance_records(self, headers, params=None):
        return self._request("GET", "/attendance-records", headers=headers, params=params)

    def list_all_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def list_all_clinical_referrals(self, headers, params=None):
        return self._request("GET", "/clinical-referrals", headers=headers, params=params)

    def list_all_evaluation_surveys(self, headers, params=None):
        return self._request("GET", "/evaluation-surveys", headers=headers, params=params)


api_client = ApiClient()
