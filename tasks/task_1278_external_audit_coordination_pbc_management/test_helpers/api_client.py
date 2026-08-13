"""API client: one method per endpoint defined in PRD §4.

All resources are mounted under the /api prefix (PRD §1, §4).
"""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/api"


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.8) ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc",
                             payload, headers)

    # --- AuditEngagement ---
    def create_engagement(self, payload, headers):
        return self._request("POST", f"{BASE}/audit-engagements",
                             payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", f"{BASE}/audit-engagements",
                             headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"{BASE}/audit-engagements/{engagement_id}",
                             headers=headers)

    def commence_fieldwork(self, engagement_id, headers):
        return self._request(
            "POST",
            f"{BASE}/audit-engagements/{engagement_id}/commence-fieldwork",
            headers=headers)

    def complete_fieldwork(self, engagement_id, headers):
        return self._request(
            "POST",
            f"{BASE}/audit-engagements/{engagement_id}/complete-fieldwork",
            headers=headers)

    def issue_report(self, engagement_id, headers):
        return self._request(
            "POST", f"{BASE}/audit-engagements/{engagement_id}/issue-report",
            headers=headers)

    def cancel_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"{BASE}/audit-engagements/{engagement_id}/cancel",
            headers=headers)

    # --- Location ---
    def create_location(self, payload, headers):
        return self._request("POST", f"{BASE}/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", f"{BASE}/locations",
                             headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"{BASE}/locations/{location_id}",
                             headers=headers)

    # --- PBCRequest ---
    def create_pbc_request(self, payload, headers):
        return self._request("POST", f"{BASE}/pbc-requests", payload, headers)

    def list_pbc_requests(self, headers, params=None):
        return self._request("GET", f"{BASE}/pbc-requests",
                             headers=headers, params=params)

    def get_pbc_request(self, pbc_request_id, headers):
        return self._request("GET", f"{BASE}/pbc-requests/{pbc_request_id}",
                             headers=headers)

    def submit_pbc_request(self, pbc_request_id, headers):
        return self._request("POST",
                             f"{BASE}/pbc-requests/{pbc_request_id}/submit",
                             headers=headers)

    def review_pbc_request(self, pbc_request_id, payload, headers):
        return self._request("POST",
                             f"{BASE}/pbc-requests/{pbc_request_id}/review",
                             payload, headers)

    # --- EvidenceUpload ---
    def upload_evidence(self, pbc_request_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/pbc-requests/{pbc_request_id}/evidence-uploads",
            payload, headers)

    def list_evidence_uploads(self, headers, params=None):
        return self._request("GET", f"{BASE}/evidence-uploads",
                             headers=headers, params=params)

    def get_evidence_upload(self, evidence_id, headers):
        return self._request("GET", f"{BASE}/evidence-uploads/{evidence_id}",
                             headers=headers)

    # --- AuditorQuery ---
    def create_query(self, payload, headers):
        return self._request("POST", f"{BASE}/queries", payload, headers)

    def list_queries(self, headers, params=None):
        return self._request("GET", f"{BASE}/queries",
                             headers=headers, params=params)

    def get_query(self, query_id, headers):
        return self._request("GET", f"{BASE}/queries/{query_id}",
                             headers=headers)

    def route_query_to_client(self, query_id, headers):
        return self._request("POST",
                             f"{BASE}/queries/{query_id}/route-to-client",
                             headers=headers)

    def respond_to_query(self, query_id, payload, headers):
        return self._request("POST", f"{BASE}/queries/{query_id}/respond",
                             payload, headers)

    def escalate_query(self, query_id, headers):
        return self._request("POST", f"{BASE}/queries/{query_id}/escalate",
                             headers=headers)

    def close_query(self, query_id, headers):
        return self._request("POST", f"{BASE}/queries/{query_id}/close",
                             headers=headers)

    # --- SamplingRequest ---
    def create_sampling_request(self, payload, headers):
        return self._request("POST", f"{BASE}/sampling-requests",
                             payload, headers)

    def list_sampling_requests(self, headers, params=None):
        return self._request("GET", f"{BASE}/sampling-requests",
                             headers=headers, params=params)

    def get_sampling_request(self, sampling_id, headers):
        return self._request("GET", f"{BASE}/sampling-requests/{sampling_id}",
                             headers=headers)

    def dispatch_sampling_request(self, sampling_id, headers):
        return self._request("POST",
                             f"{BASE}/sampling-requests/{sampling_id}/dispatch",
                             headers=headers)

    def start_sampling_request(self, sampling_id, headers):
        return self._request("POST",
                             f"{BASE}/sampling-requests/{sampling_id}/start",
                             headers=headers)

    def complete_sampling_request(self, sampling_id, headers):
        return self._request(
            "POST", f"{BASE}/sampling-requests/{sampling_id}/complete",
            headers=headers)

    def cancel_sampling_request(self, sampling_id, headers):
        return self._request("POST",
                             f"{BASE}/sampling-requests/{sampling_id}/cancel",
                             headers=headers)

    # --- FieldworkVisit ---
    def create_fieldwork_visit(self, payload, headers):
        return self._request("POST", f"{BASE}/fieldwork-visits",
                             payload, headers)

    def list_fieldwork_visits(self, headers, params=None):
        return self._request("GET", f"{BASE}/fieldwork-visits",
                             headers=headers, params=params)

    def get_fieldwork_visit(self, visit_id, headers):
        return self._request("GET", f"{BASE}/fieldwork-visits/{visit_id}",
                             headers=headers)

    def complete_fieldwork_visit(self, visit_id, headers):
        return self._request("POST",
                             f"{BASE}/fieldwork-visits/{visit_id}/complete",
                             headers=headers)

    def cancel_fieldwork_visit(self, visit_id, headers):
        return self._request("POST",
                             f"{BASE}/fieldwork-visits/{visit_id}/cancel",
                             headers=headers)

    # --- AuditAdjustment ---
    def create_adjustment(self, payload, headers):
        return self._request("POST", f"{BASE}/adjustments", payload, headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", f"{BASE}/adjustments",
                             headers=headers, params=params)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"{BASE}/adjustments/{adjustment_id}",
                             headers=headers)

    def disposition_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/adjustments/{adjustment_id}/disposition",
            payload, headers)

    # --- RepresentationLetter ---
    def create_representation_letter(self, payload, headers):
        return self._request("POST", f"{BASE}/representation-letters",
                             payload, headers)

    def list_representation_letters(self, headers, params=None):
        return self._request("GET", f"{BASE}/representation-letters",
                             headers=headers, params=params)

    def get_representation_letter(self, letter_id, headers):
        return self._request("GET",
                             f"{BASE}/representation-letters/{letter_id}",
                             headers=headers)

    def submit_representation_letter(self, letter_id, headers):
        return self._request(
            "POST", f"{BASE}/representation-letters/{letter_id}/submit",
            headers=headers)

    def sign_representation_letter(self, letter_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/representation-letters/{letter_id}/sign",
            payload, headers)

    # --- FeeChangeRequest ---
    def create_fee_change_request(self, payload, headers):
        return self._request("POST", f"{BASE}/fee-change-requests",
                             payload, headers)

    def list_fee_change_requests(self, headers, params=None):
        return self._request("GET", f"{BASE}/fee-change-requests",
                             headers=headers, params=params)

    def get_fee_change_request(self, fee_change_id, headers):
        return self._request("GET",
                             f"{BASE}/fee-change-requests/{fee_change_id}",
                             headers=headers)

    def resolve_fee_change_request(self, fee_change_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/fee-change-requests/{fee_change_id}/resolve",
            payload, headers)

    def withdraw_fee_change_request(self, fee_change_id, headers):
        return self._request(
            "POST", f"{BASE}/fee-change-requests/{fee_change_id}/withdraw",
            headers=headers)


api_client = ApiClient()
