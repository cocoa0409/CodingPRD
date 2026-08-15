"""API client: one method per endpoint defined in PRD §4 (all under the /cra prefix)."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- assessment areas ---
    def create_assessment_area(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cra/assessment-areas", payload, headers)

    def get_assessment_area(self, area_id: str, headers: Dict):
        return self._request("GET", f"/cra/assessment-areas/{area_id}", headers=headers)

    def patch_assessment_area(self, area_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/cra/assessment-areas/{area_id}", payload, headers)

    def activate_assessment_area(self, area_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/assessment-areas/{area_id}/activate", {}, headers
        )

    def begin_review_assessment_area(self, area_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/assessment-areas/{area_id}/begin-review", {}, headers
        )

    def complete_review_assessment_area(self, area_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/assessment-areas/{area_id}/complete-review", {}, headers
        )

    def retire_assessment_area(self, area_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/assessment-areas/{area_id}/retire", {}, headers
        )

    # --- demographic profiles ---
    def create_demographic_profile(self, area_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/cra/assessment-areas/{area_id}/demographic-profiles",
            payload, headers,
        )

    def list_demographic_profiles(self, area_id: str, headers: Dict,
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"/cra/assessment-areas/{area_id}/demographic-profiles",
            headers=headers, params=params,
        )

    # --- computed reads on areas ---
    def get_access_analysis(self, area_id: str, headers: Dict):
        return self._request(
            "GET", f"/cra/assessment-areas/{area_id}/access-analysis", headers=headers
        )

    def list_area_loan_records(self, area_id: str, headers: Dict,
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"/cra/assessment-areas/{area_id}/loan-records",
            headers=headers, params=params,
        )

    def list_area_cd_activities(self, area_id: str, headers: Dict,
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"/cra/assessment-areas/{area_id}/community-development-activities",
            headers=headers, params=params,
        )

    def list_area_branches(self, area_id: str, headers: Dict,
                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/cra/assessment-areas/{area_id}/branches",
            headers=headers, params=params,
        )

    def list_area_expansion_applications(self, area_id: str, headers: Dict,
                                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/cra/assessment-areas/{area_id}/expansion-applications",
            headers=headers, params=params,
        )

    # --- loan records ---
    def create_loan_record(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cra/loan-records", payload, headers)

    def get_loan_record(self, loan_id: str, headers: Dict):
        return self._request("GET", f"/cra/loan-records/{loan_id}", headers=headers)

    def confirm_loan_record(self, loan_id: str, headers: Dict):
        return self._request("POST", f"/cra/loan-records/{loan_id}/confirm", {}, headers)

    def return_loan_to_draft(self, loan_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/loan-records/{loan_id}/return-to-draft", {}, headers
        )

    def mark_loan_reported(self, loan_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/loan-records/{loan_id}/mark-reported", {}, headers
        )

    # --- community development activities ---
    def create_cd_activity(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cra/community-development-activities", payload, headers)

    def review_cd_activity(self, activity_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"/cra/community-development-activities/{activity_id}/review-decision",
            payload, headers,
        )

    def resubmit_cd_activity(self, activity_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/community-development-activities/{activity_id}/resubmit",
            {}, headers,
        )

    # --- branches ---
    def create_branch(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cra/branches", payload, headers)

    def get_branch(self, branch_id: str, headers: Dict):
        return self._request("GET", f"/cra/branches/{branch_id}", headers=headers)

    def open_branch(self, branch_id: str, headers: Dict):
        return self._request("POST", f"/cra/branches/{branch_id}/open", {}, headers)

    def close_branch(self, branch_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/cra/branches/{branch_id}/close", payload, headers)

    # --- public comments ---
    def create_public_comment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cra/public-comments", payload, headers)

    def publish_public_comment(self, comment_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/public-comments/{comment_id}/publish", {}, headers
        )

    def respond_public_comment(self, comment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/cra/public-comments/{comment_id}/respond", payload, headers
        )

    # --- public file (singleton) ---
    def create_public_file(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cra/public-files", payload, headers)

    def get_public_file(self, file_id: str, headers: Dict):
        return self._request("GET", f"/cra/public-files/{file_id}", headers=headers)

    def refresh_public_file_items(self, file_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/cra/public-files/{file_id}/refresh-items", payload, headers
        )

    # --- exam cycles ---
    def create_exam_cycle(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cra/exam-cycles", payload, headers)

    def get_exam_cycle(self, exam_id: str, headers: Dict):
        return self._request("GET", f"/cra/exam-cycles/{exam_id}", headers=headers)

    def patch_performance_context(self, exam_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PATCH", f"/cra/exam-cycles/{exam_id}/performance-context", payload, headers
        )

    def begin_data_collection(self, exam_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/exam-cycles/{exam_id}/begin-data-collection", {}, headers
        )

    def begin_fieldwork(self, exam_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/exam-cycles/{exam_id}/begin-fieldwork", {}, headers
        )

    def assign_preliminary_rating(self, exam_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/cra/exam-cycles/{exam_id}/assign-preliminary-rating",
            payload, headers,
        )

    def appeal_exam(self, exam_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/cra/exam-cycles/{exam_id}/appeal", payload, headers)

    def reopen_fieldwork(self, exam_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/exam-cycles/{exam_id}/reopen-fieldwork", {}, headers
        )

    def finalize_exam(self, exam_id: str, headers: Dict):
        return self._request("POST", f"/cra/exam-cycles/{exam_id}/finalize", {}, headers)

    def get_lending_metrics(self, exam_id: str, headers: Dict,
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"/cra/exam-cycles/{exam_id}/lending-metrics",
            headers=headers, params=params,
        )

    # --- expansion applications ---
    def create_expansion_application(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cra/expansion-applications", payload, headers)

    def get_expansion_application(self, app_id: str, headers: Dict):
        return self._request(
            "GET", f"/cra/expansion-applications/{app_id}", headers=headers
        )

    def submit_expansion_application(self, app_id: str, headers: Dict):
        return self._request(
            "POST", f"/cra/expansion-applications/{app_id}/submit", {}, headers
        )

    def decide_expansion_application(self, app_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/cra/expansion-applications/{app_id}/decide", payload, headers
        )

    def list_application_branches(self, app_id: str, headers: Dict,
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"/cra/expansion-applications/{app_id}/branches",
            headers=headers, params=params,
        )

    # --- logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/cra/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
