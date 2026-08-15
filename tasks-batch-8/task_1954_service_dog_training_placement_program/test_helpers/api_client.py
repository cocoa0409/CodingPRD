"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Applicant lifecycle ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/api/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/api/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/api/applicants", headers=headers, params=params)

    def begin_review(self, applicant_id, headers):
        return self._request("POST", f"/api/applicants/{applicant_id}/begin-review", {}, headers)

    def request_info(self, applicant_id, payload, headers):
        return self._request("POST", f"/api/applicants/{applicant_id}/request-info", payload, headers)

    def resubmit_applicant(self, applicant_id, headers):
        return self._request("POST", f"/api/applicants/{applicant_id}/resubmit", {}, headers)

    def approve_applicant(self, applicant_id, headers):
        return self._request("POST", f"/api/applicants/{applicant_id}/approve", {}, headers)

    def deny_applicant(self, applicant_id, payload, headers):
        return self._request("POST", f"/api/applicants/{applicant_id}/deny", payload, headers)

    def withdraw_applicant(self, applicant_id, headers):
        return self._request("POST", f"/api/applicants/{applicant_id}/withdraw", {}, headers)

    def list_applicant_assessments(self, applicant_id, headers):
        return self._request("GET", f"/api/applicants/{applicant_id}/assessments", headers=headers)

    def list_applicant_waitlist_entries(self, applicant_id, headers):
        return self._request("GET", f"/api/applicants/{applicant_id}/waitlist-entries", headers=headers)

    def list_applicant_contributions(self, applicant_id, headers):
        return self._request("GET", f"/api/applicants/{applicant_id}/contributions", headers=headers)

    def list_applicant_partnerships(self, applicant_id, headers):
        return self._request("GET", f"/api/applicants/{applicant_id}/partnerships", headers=headers)

    # --- TaskAssessment ---
    def create_assessment(self, applicant_id, payload, headers):
        return self._request("POST", f"/api/applicants/{applicant_id}/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/assessments/{assessment_id}", headers=headers)

    def finalize_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/api/assessments/{assessment_id}/finalize", payload, headers)

    # --- WaitlistEntry ---
    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/api/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/api/waitlist-entries", headers=headers, params=params)

    def recalculate_waitlist_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/api/waitlist-entries/{entry_id}/recalculate", payload, headers)

    def suspend_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/api/waitlist-entries/{entry_id}/suspend", {}, headers)

    def reinstate_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/api/waitlist-entries/{entry_id}/reinstate", {}, headers)

    def list_entry_matches(self, entry_id, headers):
        return self._request("GET", f"/api/waitlist-entries/{entry_id}/matches", headers=headers)

    # --- Contribution ---
    def create_contribution(self, applicant_id, payload, headers):
        return self._request("POST", f"/api/applicants/{applicant_id}/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/api/contributions/{contribution_id}", headers=headers)

    def receive_contribution(self, contribution_id, headers):
        return self._request("POST", f"/api/contributions/{contribution_id}/receive", {}, headers)

    def refund_contribution(self, contribution_id, headers):
        return self._request("POST", f"/api/contributions/{contribution_id}/refund", {}, headers)

    # --- PuppyRaiser ---
    def create_puppy_raiser(self, payload, headers):
        return self._request("POST", "/api/puppy-raisers", payload, headers)

    def get_puppy_raiser(self, raiser_id, headers):
        return self._request("GET", f"/api/puppy-raisers/{raiser_id}", headers=headers)

    def list_puppy_raisers(self, headers, params=None):
        return self._request("GET", "/api/puppy-raisers", headers=headers, params=params)

    def vet_raiser(self, raiser_id, headers):
        return self._request("POST", f"/api/puppy-raisers/{raiser_id}/vet", {}, headers)

    def approve_raiser(self, raiser_id, headers):
        return self._request("POST", f"/api/puppy-raisers/{raiser_id}/approve", {}, headers)

    def hiatus_raiser(self, raiser_id, headers):
        return self._request("POST", f"/api/puppy-raisers/{raiser_id}/hiatus", {}, headers)

    def resume_raiser(self, raiser_id, headers):
        return self._request("POST", f"/api/puppy-raisers/{raiser_id}/resume", {}, headers)

    def deactivate_raiser(self, raiser_id, headers):
        return self._request("POST", f"/api/puppy-raisers/{raiser_id}/deactivate", {}, headers)

    def list_raiser_placements_for_raiser(self, raiser_id, headers):
        return self._request("GET", f"/api/puppy-raisers/{raiser_id}/placements", headers=headers)

    # --- Trainer ---
    def create_trainer(self, payload, headers):
        return self._request("POST", "/api/trainers", payload, headers)

    def get_trainer(self, trainer_id, headers):
        return self._request("GET", f"/api/trainers/{trainer_id}", headers=headers)

    def certify_trainer(self, trainer_id, headers):
        return self._request("POST", f"/api/trainers/{trainer_id}/certify", {}, headers)

    def suspend_trainer(self, trainer_id, headers):
        return self._request("POST", f"/api/trainers/{trainer_id}/suspend", {}, headers)

    def reinstate_trainer(self, trainer_id, headers):
        return self._request("POST", f"/api/trainers/{trainer_id}/reinstate", {}, headers)

    def deactivate_trainer(self, trainer_id, headers):
        return self._request("POST", f"/api/trainers/{trainer_id}/deactivate", {}, headers)

    def list_trainer_dogs(self, trainer_id, headers):
        return self._request("GET", f"/api/trainers/{trainer_id}/dogs", headers=headers)

    def list_trainer_classes(self, trainer_id, headers):
        return self._request("GET", f"/api/trainers/{trainer_id}/classes", headers=headers)

    def list_trainer_evaluations(self, trainer_id, headers):
        return self._request("GET", f"/api/trainers/{trainer_id}/evaluations", headers=headers)

    def list_trainer_milestones(self, trainer_id, headers):
        return self._request("GET", f"/api/trainers/{trainer_id}/milestones", headers=headers)

    # --- Dog ---
    def create_dog(self, payload, headers):
        return self._request("POST", "/api/dogs", payload, headers)

    def get_dog(self, dog_id, headers):
        return self._request("GET", f"/api/dogs/{dog_id}", headers=headers)

    def list_dogs(self, headers, params=None):
        return self._request("GET", "/api/dogs", headers=headers, params=params)

    def list_dog_offspring(self, dog_id, headers):
        return self._request("GET", f"/api/dogs/{dog_id}/offspring", headers=headers)

    def begin_screening(self, dog_id, headers):
        return self._request("POST", f"/api/dogs/{dog_id}/begin-screening", {}, headers)

    def career_change_dog(self, dog_id, payload, headers):
        return self._request("POST", f"/api/dogs/{dog_id}/career-change", payload, headers)

    def list_dog_screenings(self, dog_id, headers):
        return self._request("GET", f"/api/dogs/{dog_id}/screenings", headers=headers)

    def list_dog_milestones(self, dog_id, headers):
        return self._request("GET", f"/api/dogs/{dog_id}/milestones", headers=headers)

    def list_dog_raiser_placements(self, dog_id, headers):
        return self._request("GET", f"/api/dogs/{dog_id}/raiser-placements", headers=headers)

    def list_dog_matches(self, dog_id, headers):
        return self._request("GET", f"/api/dogs/{dog_id}/matches", headers=headers)

    def list_dog_partnerships(self, dog_id, headers):
        return self._request("GET", f"/api/dogs/{dog_id}/partnerships", headers=headers)

    # --- HealthScreening ---
    def create_screening(self, dog_id, payload, headers):
        return self._request("POST", f"/api/dogs/{dog_id}/screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/api/screenings/{screening_id}", headers=headers)

    def submit_screening(self, screening_id, headers):
        return self._request("POST", f"/api/screenings/{screening_id}/submit", {}, headers)

    # --- RaiserPlacement ---
    def create_raiser_placement(self, dog_id, payload, headers):
        return self._request("POST", f"/api/dogs/{dog_id}/raiser-placements", payload, headers)

    def get_raiser_placement(self, placement_id, headers):
        return self._request("GET", f"/api/raiser-placements/{placement_id}", headers=headers)

    def complete_raiser_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/api/raiser-placements/{placement_id}/complete", payload, headers)

    def early_return_raiser_placement(self, placement_id, headers, payload=None):
        return self._request("POST", f"/api/raiser-placements/{placement_id}/early-return", payload or {}, headers)

    # --- TrainingMilestone ---
    def create_milestone(self, dog_id, payload, headers):
        return self._request("POST", f"/api/dogs/{dog_id}/milestones", payload, headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/api/milestones/{milestone_id}", headers=headers)

    # --- MatchRecord ---
    def create_match_proposal(self, dog_id, payload, headers):
        return self._request("POST", f"/api/dogs/{dog_id}/match-proposals", payload, headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/api/matches/{match_id}", headers=headers)

    def accept_match(self, match_id, headers):
        return self._request("POST", f"/api/matches/{match_id}/accept", {}, headers)

    def reject_match(self, match_id, headers):
        return self._request("POST", f"/api/matches/{match_id}/reject", {}, headers)

    def dissolve_match(self, match_id, headers):
        return self._request("POST", f"/api/matches/{match_id}/dissolve", {}, headers)

    def list_match_enrollments(self, match_id, headers):
        return self._request("GET", f"/api/matches/{match_id}/enrollments", headers=headers)

    # --- TeamTrainingClass ---
    def create_class(self, payload, headers):
        return self._request("POST", "/api/classes", payload, headers)

    def get_class(self, class_id, headers):
        return self._request("GET", f"/api/classes/{class_id}", headers=headers)

    def list_classes(self, headers, params=None):
        return self._request("GET", "/api/classes", headers=headers, params=params)

    def open_enrollment(self, class_id, headers):
        return self._request("POST", f"/api/classes/{class_id}/open-enrollment", {}, headers)

    def start_class(self, class_id, headers):
        return self._request("POST", f"/api/classes/{class_id}/start", {}, headers)

    def begin_graduation_review(self, class_id, headers):
        return self._request("POST", f"/api/classes/{class_id}/begin-graduation-review", {}, headers)

    def complete_class(self, class_id, headers):
        return self._request("POST", f"/api/classes/{class_id}/complete", {}, headers)

    def cancel_class(self, class_id, headers):
        return self._request("POST", f"/api/classes/{class_id}/cancel", {}, headers)

    def list_class_enrollments(self, class_id, headers):
        return self._request("GET", f"/api/classes/{class_id}/enrollments", headers=headers)

    # --- Enrollment ---
    def create_enrollment(self, class_id, payload, headers):
        return self._request("POST", f"/api/classes/{class_id}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/api/enrollments/{enrollment_id}", headers=headers)

    def record_attendance(self, enrollment_id, payload, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/record-attendance", payload, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/withdraw", {}, headers)

    def graduate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/graduate", {}, headers)

    def list_enrollment_pats(self, enrollment_id, headers):
        return self._request("GET", f"/api/enrollments/{enrollment_id}/public-access-tests", headers=headers)

    def list_enrollment_partnerships(self, enrollment_id, headers):
        return self._request("GET", f"/api/enrollments/{enrollment_id}/partnerships", headers=headers)

    # --- PublicAccessTest ---
    def create_pat(self, enrollment_id, payload, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/public-access-tests", payload, headers)

    def get_pat(self, pat_id, headers):
        return self._request("GET", f"/api/public-access-tests/{pat_id}", headers=headers)

    def score_pat(self, pat_id, payload, headers):
        return self._request("POST", f"/api/public-access-tests/{pat_id}/score", payload, headers)

    def invalidate_pat(self, pat_id, payload, headers):
        return self._request("POST", f"/api/public-access-tests/{pat_id}/invalidate", payload, headers)

    # --- Partnership ---
    def get_partnership(self, partnership_id, headers):
        return self._request("GET", f"/api/partnerships/{partnership_id}", headers=headers)

    def list_partnerships(self, headers, params=None):
        return self._request("GET", "/api/partnerships", headers=headers, params=params)

    def suspend_partnership(self, partnership_id, payload, headers):
        return self._request("POST", f"/api/partnerships/{partnership_id}/suspend", payload, headers)

    def reinstate_partnership(self, partnership_id, headers):
        return self._request("POST", f"/api/partnerships/{partnership_id}/reinstate", {}, headers)

    def retire_partnership(self, partnership_id, headers):
        return self._request("POST", f"/api/partnerships/{partnership_id}/retire", {}, headers)

    def dissolve_partnership(self, partnership_id, payload, headers):
        return self._request("POST", f"/api/partnerships/{partnership_id}/dissolve", payload, headers)

    def list_partnership_followups(self, partnership_id, headers):
        return self._request("GET", f"/api/partnerships/{partnership_id}/follow-ups", headers=headers)

    def list_partnership_recertifications(self, partnership_id, headers):
        return self._request("GET", f"/api/partnerships/{partnership_id}/recertifications", headers=headers)

    def list_partnership_support_requests(self, partnership_id, headers):
        return self._request("GET", f"/api/partnerships/{partnership_id}/support-requests", headers=headers)

    # --- FollowUp ---
    def create_followup(self, partnership_id, payload, headers):
        return self._request("POST", f"/api/partnerships/{partnership_id}/follow-ups", payload, headers)

    def get_followup(self, followup_id, headers):
        return self._request("GET", f"/api/follow-ups/{followup_id}", headers=headers)

    def complete_followup(self, followup_id, payload, headers):
        return self._request("POST", f"/api/follow-ups/{followup_id}/complete", payload, headers)

    def waive_followup(self, followup_id, headers):
        return self._request("POST", f"/api/follow-ups/{followup_id}/waive", {}, headers)

    # --- Recertification ---
    def create_recertification(self, partnership_id, payload, headers):
        return self._request("POST", f"/api/partnerships/{partnership_id}/recertifications", payload, headers)

    def get_recertification(self, recert_id, headers):
        return self._request("GET", f"/api/recertifications/{recert_id}", headers=headers)

    def record_recert_result(self, recert_id, payload, headers):
        return self._request("POST", f"/api/recertifications/{recert_id}/record-result", payload, headers)

    # --- SupportRequest ---
    def create_support_request(self, partnership_id, payload, headers):
        return self._request("POST", f"/api/partnerships/{partnership_id}/support-requests", payload, headers)

    def list_support_requests(self, headers, params=None):
        return self._request("GET", "/api/support-requests", headers=headers, params=params)

    def get_support_request(self, request_id, headers):
        return self._request("GET", f"/api/support-requests/{request_id}", headers=headers)

    def triage_support_request(self, request_id, payload, headers):
        return self._request("POST", f"/api/support-requests/{request_id}/triage", payload, headers)

    def start_support_request(self, request_id, payload, headers):
        return self._request("POST", f"/api/support-requests/{request_id}/start", payload, headers)

    def resolve_support_request(self, request_id, payload, headers):
        return self._request("POST", f"/api/support-requests/{request_id}/resolve", payload, headers)

    def reopen_support_request(self, request_id, headers):
        return self._request("POST", f"/api/support-requests/{request_id}/reopen", {}, headers)

    def close_support_request(self, request_id, headers):
        return self._request("POST", f"/api/support-requests/{request_id}/close", {}, headers)


api_client = ApiClient()
