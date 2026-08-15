"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- BranchOffice ---
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    # --- RegisteredRepresentative ---
    def create_representative(self, payload, headers):
        return self._request("POST", "/representatives", payload, headers)

    def list_representatives(self, headers, params=None):
        return self._request("GET", "/representatives", headers=headers, params=params)

    def get_representative(self, rep_id, headers):
        return self._request("GET", f"/representatives/{rep_id}", headers=headers)

    def terminate_representative(self, rep_id, headers):
        return self._request(
            "POST", f"/representatives/{rep_id}/terminate", None, headers
        )

    # --- BranchInspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def start_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/start", None, headers
        )

    def close_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/close", payload, headers
        )

    # --- InspectionFinding ---
    def create_finding(self, payload, headers):
        return self._request("POST", "/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/findings/{finding_id}", headers=headers)

    def remediate_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/findings/{finding_id}/remediate", payload, headers
        )

    def adjudicate_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/findings/{finding_id}/adjudicate", payload, headers
        )

    # --- CorrespondenceItem ---
    def create_correspondence_item(self, payload, headers):
        return self._request("POST", "/correspondence-items", payload, headers)

    def list_correspondence_items(self, headers, params=None):
        return self._request(
            "GET", "/correspondence-items", headers=headers, params=params
        )

    def get_correspondence_item(self, item_id, headers):
        return self._request(
            "GET", f"/correspondence-items/{item_id}", headers=headers
        )

    def review_correspondence_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/correspondence-items/{item_id}/review", payload, headers
        )

    def resolve_escalation(self, item_id, payload, headers):
        return self._request(
            "POST", f"/correspondence-items/{item_id}/resolve-escalation",
            payload, headers,
        )

    # --- OutsideActivityRequest ---
    def create_outside_activity(self, payload, headers):
        return self._request("POST", "/outside-activities", payload, headers)

    def list_outside_activities(self, headers, params=None):
        return self._request(
            "GET", "/outside-activities", headers=headers, params=params
        )

    def get_outside_activity(self, activity_id, headers):
        return self._request("GET", f"/outside-activities/{activity_id}", headers=headers)

    def decide_outside_activity(self, activity_id, payload, headers):
        return self._request(
            "POST", f"/outside-activities/{activity_id}/decide", payload, headers
        )

    def withdraw_outside_activity(self, activity_id, headers):
        return self._request(
            "POST", f"/outside-activities/{activity_id}/withdraw", None, headers
        )

    def revoke_outside_activity(self, activity_id, payload, headers):
        return self._request(
            "POST", f"/outside-activities/{activity_id}/revoke", payload, headers
        )

    def resume_outside_activity(self, activity_id, headers):
        return self._request(
            "POST", f"/outside-activities/{activity_id}/resume", None, headers
        )

    # --- CustomerComplaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def patch_complaint(self, complaint_id, payload, headers):
        return self._request("PATCH", f"/complaints/{complaint_id}", payload, headers)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/resolve", payload, headers
        )

    def report_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/report", None, headers
        )

    # --- DisclosureEvent ---
    def create_disclosure_event(self, payload, headers):
        return self._request("POST", "/disclosure-events", payload, headers)

    def list_disclosure_events(self, headers, params=None):
        return self._request("GET", "/disclosure-events", headers=headers, params=params)

    def get_disclosure_event(self, event_id, headers):
        return self._request("GET", f"/disclosure-events/{event_id}", headers=headers)

    def file_disclosure_event(self, event_id, headers):
        return self._request(
            "POST", f"/disclosure-events/{event_id}/file", None, headers
        )

    def acknowledge_disclosure_event(self, event_id, headers):
        return self._request(
            "POST", f"/disclosure-events/{event_id}/acknowledge", None, headers
        )

    # --- HeightenedSupervisionPlan ---
    def create_supervision_plan(self, payload, headers):
        return self._request("POST", "/supervision-plans", payload, headers)

    def list_supervision_plans(self, headers, params=None):
        return self._request("GET", "/supervision-plans", headers=headers, params=params)

    def get_supervision_plan(self, plan_id, headers):
        return self._request("GET", f"/supervision-plans/{plan_id}", headers=headers)

    def activate_supervision_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/supervision-plans/{plan_id}/activate", None, headers
        )

    def terminate_supervision_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/supervision-plans/{plan_id}/terminate", None, headers
        )

    # --- ComplianceMeeting / Attestation ---
    def create_meeting(self, payload, headers):
        return self._request("POST", "/meetings", payload, headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", "/meetings", headers=headers, params=params)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/meetings/{meeting_id}", headers=headers)

    def hold_meeting(self, meeting_id, headers):
        return self._request("POST", f"/meetings/{meeting_id}/hold", None, headers)

    def close_meeting(self, meeting_id, headers):
        return self._request("POST", f"/meetings/{meeting_id}/close", None, headers)

    def list_attestations(self, headers, params=None):
        return self._request("GET", "/attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"/attestations/{attestation_id}", headers=headers)

    def attest(self, attestation_id, headers):
        return self._request(
            "POST", f"/attestations/{attestation_id}/attest", None, headers
        )

    # --- WSPDocument ---
    def create_wsp_document(self, payload, headers):
        return self._request("POST", "/wsp-documents", payload, headers)

    def list_wsp_documents(self, headers, params=None):
        return self._request("GET", "/wsp-documents", headers=headers, params=params)

    def get_wsp_document(self, document_id, headers):
        return self._request("GET", f"/wsp-documents/{document_id}", headers=headers)

    def publish_wsp_document(self, document_id, headers):
        return self._request(
            "POST", f"/wsp-documents/{document_id}/publish", None, headers
        )

    # --- ExamDocumentRequest ---
    def create_exam_request(self, payload, headers):
        return self._request("POST", "/exam-requests", payload, headers)

    def list_exam_requests(self, headers, params=None):
        return self._request("GET", "/exam-requests", headers=headers, params=params)

    def get_exam_request(self, request_id, headers):
        return self._request("GET", f"/exam-requests/{request_id}", headers=headers)

    def fulfill_exam_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/exam-requests/{request_id}/fulfill", payload, headers
        )


api_client = ApiClient()
