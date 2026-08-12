"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Partner institutions ---
    def create_partner_institution(self, payload, headers):
        return self._request("POST", "/api/partner-institutions", payload, headers)

    def list_partner_institutions(self, headers, params=None):
        return self._request("GET", "/api/partner-institutions", headers=headers, params=params)

    def get_partner_institution(self, partner_id, headers):
        return self._request("GET", f"/api/partner-institutions/{partner_id}", headers=headers)

    # --- Internal courses ---
    def create_internal_course(self, payload, headers):
        return self._request("POST", "/api/internal-courses", payload, headers)

    def list_internal_courses(self, headers, params=None):
        return self._request("GET", "/api/internal-courses", headers=headers, params=params)

    def get_internal_course(self, course_id, headers):
        return self._request("GET", f"/api/internal-courses/{course_id}", headers=headers)

    def deactivate_internal_course(self, course_id, headers):
        return self._request("POST", f"/api/internal-courses/{course_id}/deactivate", headers=headers)

    # --- Articulation agreements ---
    def create_articulation_agreement(self, payload, headers):
        return self._request("POST", "/api/articulation-agreements", payload, headers)

    def list_articulation_agreements(self, headers, params=None):
        return self._request("GET", "/api/articulation-agreements", headers=headers, params=params)

    def get_articulation_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/articulation-agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/articulation-agreements/{agreement_id}/activate", headers=headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/articulation-agreements/{agreement_id}/suspend", headers=headers)

    def reactivate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/articulation-agreements/{agreement_id}/reactivate", headers=headers)

    def create_amendment(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/articulation-agreements/{agreement_id}/amendments", payload, headers)

    # --- Course equivalencies ---
    def create_course_equivalency(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/articulation-agreements/{agreement_id}/course-equivalencies", payload, headers
        )

    def list_agreement_equivalencies(self, agreement_id, headers):
        return self._request(
            "GET", f"/api/articulation-agreements/{agreement_id}/course-equivalencies", headers=headers
        )

    def list_course_equivalencies(self, headers, params=None):
        return self._request("GET", "/api/course-equivalencies", headers=headers, params=params)

    def get_course_equivalency(self, equivalency_id, headers):
        return self._request("GET", f"/api/course-equivalencies/{equivalency_id}", headers=headers)

    # --- Students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/api/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/api/students/{student_id}", headers=headers)

    def patch_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/api/students/{student_id}", payload, headers)

    def get_degree_progress(self, student_id, headers, params=None):
        return self._request("GET", f"/api/students/{student_id}/degree-progress", headers=headers, params=params)

    # --- Transcripts ---
    def create_transcript(self, payload, headers):
        return self._request("POST", "/api/transcripts", payload, headers)

    def list_transcripts(self, headers, params=None):
        return self._request("GET", "/api/transcripts", headers=headers, params=params)

    def get_transcript(self, transcript_id, headers):
        return self._request("GET", f"/api/transcripts/{transcript_id}", headers=headers)

    def verify_transcript(self, transcript_id, headers):
        return self._request("POST", f"/api/transcripts/{transcript_id}/verify", headers=headers)

    def reject_transcript(self, transcript_id, payload, headers):
        return self._request("POST", f"/api/transcripts/{transcript_id}/reject", payload, headers)

    # --- Evaluations ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/api/transfer-credit-evaluations", payload, headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/api/transfer-credit-evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/api/transfer-credit-evaluations/{evaluation_id}", headers=headers)

    def list_evaluation_line_items(self, evaluation_id, headers):
        return self._request("GET", f"/api/transfer-credit-evaluations/{evaluation_id}/line-items", headers=headers)

    def start_evaluation_review(self, evaluation_id, headers):
        return self._request("POST", f"/api/transfer-credit-evaluations/{evaluation_id}/start-review", headers=headers)

    def finalize_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/api/transfer-credit-evaluations/{evaluation_id}/finalize", headers=headers)

    def post_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/api/transfer-credit-evaluations/{evaluation_id}/post", headers=headers)

    def reopen_evaluation(self, evaluation_id, payload, headers):
        return self._request("POST", f"/api/transfer-credit-evaluations/{evaluation_id}/reopen", payload, headers)

    # --- Line items ---
    def list_line_items(self, headers, params=None):
        return self._request("GET", "/api/evaluation-line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/api/evaluation-line-items/{line_item_id}", headers=headers)

    def adopt_line_item(self, line_item_id, payload, headers):
        return self._request("POST", f"/api/evaluation-line-items/{line_item_id}/adopt", payload, headers)

    def deny_line_item(self, line_item_id, payload, headers):
        return self._request("POST", f"/api/evaluation-line-items/{line_item_id}/deny", payload, headers)

    # --- Petitions ---
    def create_petition(self, payload, headers):
        return self._request("POST", "/api/petitions", payload, headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/api/petitions", headers=headers, params=params)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/api/petitions/{petition_id}", headers=headers)

    def start_petition_review(self, petition_id, headers):
        return self._request("POST", f"/api/petitions/{petition_id}/start-review", headers=headers)

    def adjudicate_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/api/petitions/{petition_id}/adjudicate", payload, headers)

    # --- Appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/api/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/api/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/api/appeals/{appeal_id}", headers=headers)

    def start_appeal_review(self, appeal_id, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/start-review", headers=headers)

    def adjudicate_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/adjudicate", payload, headers)

    # --- Prior learning assessments ---
    def create_pla(self, payload, headers):
        return self._request("POST", "/api/prior-learning-assessments", payload, headers)

    def list_plas(self, headers, params=None):
        return self._request("GET", "/api/prior-learning-assessments", headers=headers, params=params)

    def get_pla(self, pla_id, headers):
        return self._request("GET", f"/api/prior-learning-assessments/{pla_id}", headers=headers)

    def verify_pla(self, pla_id, payload, headers):
        return self._request("POST", f"/api/prior-learning-assessments/{pla_id}/verify", payload, headers)

    def credit_pla(self, pla_id, headers):
        return self._request("POST", f"/api/prior-learning-assessments/{pla_id}/credit", headers=headers)

    def reject_pla(self, pla_id, payload, headers):
        return self._request("POST", f"/api/prior-learning-assessments/{pla_id}/reject", payload, headers)

    # --- Requirement applications ---
    def list_requirement_applications(self, headers, params=None):
        return self._request("GET", "/api/requirement-applications", headers=headers, params=params)

    def get_requirement_application(self, application_id, headers):
        return self._request("GET", f"/api/requirement-applications/{application_id}", headers=headers)

    # --- Transfer guides ---
    def create_transfer_guide(self, payload, headers):
        return self._request("POST", "/api/transfer-guides", payload, headers)

    def list_transfer_guides(self, headers, params=None):
        return self._request("GET", "/api/transfer-guides", headers=headers, params=params)

    def get_transfer_guide(self, guide_id, headers):
        return self._request("GET", f"/api/transfer-guides/{guide_id}", headers=headers)

    def publish_transfer_guide(self, guide_id, headers):
        return self._request("POST", f"/api/transfer-guides/{guide_id}/publish", headers=headers)

    def archive_transfer_guide(self, guide_id, headers):
        return self._request("POST", f"/api/transfer-guides/{guide_id}/archive", headers=headers)

    def get_transfer_guide_entries(self, guide_id, headers):
        return self._request("GET", f"/api/transfer-guides/{guide_id}/entries", headers=headers)


api_client = ApiClient()
