"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ScholarshipFund ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/scholarship-funds", payload, headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/scholarship-funds", headers=headers, params=params)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/scholarship-funds/{fund_id}", headers=headers)

    def open_fund(self, fund_id, headers):
        return self._request("POST", f"/scholarship-funds/{fund_id}/open", {}, headers)

    def begin_review_fund(self, fund_id, headers):
        return self._request("POST", f"/scholarship-funds/{fund_id}/begin-review", {}, headers)

    def begin_awarding_fund(self, fund_id, headers):
        return self._request("POST", f"/scholarship-funds/{fund_id}/begin-awarding", {}, headers)

    def close_fund(self, fund_id, headers):
        return self._request("POST", f"/scholarship-funds/{fund_id}/close", {}, headers)

    # --- EligibilityCriteria ---
    def create_criteria(self, payload, headers):
        return self._request("POST", "/eligibility-criteria", payload, headers)

    def list_criteria(self, headers, params=None):
        return self._request("GET", "/eligibility-criteria", headers=headers, params=params)

    def get_criteria(self, criteria_id, headers):
        return self._request("GET", f"/eligibility-criteria/{criteria_id}", headers=headers)

    # --- Applicant ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # --- CommitteeMember ---
    def create_committee_member(self, payload, headers):
        return self._request("POST", "/committee-members", payload, headers)

    def list_committee_members(self, headers, params=None):
        return self._request("GET", "/committee-members", headers=headers, params=params)

    def get_committee_member(self, member_id, headers):
        return self._request("GET", f"/committee-members/{member_id}", headers=headers)

    # --- Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def start_review_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/start-review", {}, headers)

    def request_revision_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/request-revision", {}, headers)

    def finalize_scoring_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/finalize-scoring", {}, headers)

    def award_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/award", payload, headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/reject", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    # --- Recommendation ---
    def create_recommendation(self, payload, headers):
        return self._request("POST", "/recommendations", payload, headers)

    def list_recommendations(self, headers, params=None):
        return self._request("GET", "/recommendations", headers=headers, params=params)

    def get_recommendation(self, recommendation_id, headers):
        return self._request("GET", f"/recommendations/{recommendation_id}", headers=headers)

    # --- Transcript ---
    def create_transcript(self, payload, headers):
        return self._request("POST", "/transcripts", payload, headers)

    def list_transcripts(self, headers, params=None):
        return self._request("GET", "/transcripts", headers=headers, params=params)

    def get_transcript(self, transcript_id, headers):
        return self._request("GET", f"/transcripts/{transcript_id}", headers=headers)

    # --- CommitteeAssignment ---
    def create_committee_assignment(self, payload, headers):
        return self._request("POST", "/committee-assignments", payload, headers)

    def list_committee_assignments(self, headers, params=None):
        return self._request("GET", "/committee-assignments", headers=headers, params=params)

    def get_committee_assignment(self, assignment_id, headers):
        return self._request("GET", f"/committee-assignments/{assignment_id}", headers=headers)

    def decline_committee_assignment(self, assignment_id, headers):
        return self._request("POST", f"/committee-assignments/{assignment_id}/decline", {}, headers)

    # --- RubricScore ---
    def create_rubric_score(self, payload, headers):
        return self._request("POST", "/rubric-scores", payload, headers)

    def list_rubric_scores(self, headers, params=None):
        return self._request("GET", "/rubric-scores", headers=headers, params=params)

    def get_rubric_score(self, score_id, headers):
        return self._request("GET", f"/rubric-scores/{score_id}", headers=headers)

    def submit_rubric_score(self, score_id, headers):
        return self._request("POST", f"/rubric-scores/{score_id}/submit", {}, headers)

    # --- Award ---
    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def disburse_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/disburse", payload, headers)

    def complete_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/complete", {}, headers)

    def revoke_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/revoke", {}, headers)

    # --- Disbursement ---
    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def settle_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/settle", {}, headers)

    def return_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/return", {}, headers)

    # --- RenewalReview ---
    def create_renewal_review(self, payload, headers):
        return self._request("POST", "/renewal-reviews", payload, headers)

    def list_renewal_reviews(self, headers, params=None):
        return self._request("GET", "/renewal-reviews", headers=headers, params=params)

    def get_renewal_review(self, review_id, headers):
        return self._request("GET", f"/renewal-reviews/{review_id}", headers=headers)

    def approve_renewal_review(self, review_id, headers):
        return self._request("POST", f"/renewal-reviews/{review_id}/approve", {}, headers)

    def deny_renewal_review(self, review_id, headers):
        return self._request("POST", f"/renewal-reviews/{review_id}/deny", {}, headers)

    # --- StewardshipRecord ---
    def create_stewardship_record(self, payload, headers):
        return self._request("POST", "/stewardship-records", payload, headers)

    def list_stewardship_records(self, headers, params=None):
        return self._request("GET", "/stewardship-records", headers=headers, params=params)

    def get_stewardship_record(self, stewardship_id, headers):
        return self._request("GET", f"/stewardship-records/{stewardship_id}", headers=headers)

    def acknowledge_stewardship_record(self, stewardship_id, headers):
        return self._request("POST", f"/stewardship-records/{stewardship_id}/acknowledge", {}, headers)


api_client = ApiClient()
