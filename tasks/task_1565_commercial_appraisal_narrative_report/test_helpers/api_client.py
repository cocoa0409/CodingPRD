"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # --- Appraisers ---
    def create_appraiser(self, payload, headers):
        return self._request("POST", "/appraisers", payload, headers)

    def get_appraiser(self, appraiser_id, headers):
        return self._request("GET", f"/appraisers/{appraiser_id}", headers=headers)

    def set_license_status(self, appraiser_id, payload, headers):
        return self._request(
            "POST", f"/appraisers/{appraiser_id}/license_status", payload, headers
        )

    # --- Engagements ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def submit_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/submit", {}, headers
        )

    def accept_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/accept", {}, headers
        )

    def decline_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/decline", payload, headers
        )

    def cancel_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/cancel", payload, headers
        )

    def write_off_fee(self, engagement_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/write_off_fee", {}, headers
        )

    def place_litigation_hold(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/litigation-hold", payload, headers
        )

    def release_litigation_hold(self, engagement_id, headers):
        return self._request(
            "DELETE", f"/engagements/{engagement_id}/litigation-hold", headers=headers
        )

    # --- Data submissions ---
    def create_data_submission(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/data-submissions", payload, headers
        )

    def get_data_submission(self, submission_id, headers):
        return self._request(
            "GET", f"/data-submissions/{submission_id}", headers=headers
        )

    def list_data_submissions(self, headers, params=None):
        return self._request("GET", "/data-submissions", headers=headers, params=params)

    def accept_data_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/data-submissions/{submission_id}/accept", {}, headers
        )

    def reject_data_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/data-submissions/{submission_id}/reject", payload, headers
        )

    # --- Valuation approaches ---
    def create_approach(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/approaches", payload, headers
        )

    def get_approach(self, approach_id, headers):
        return self._request("GET", f"/approaches/{approach_id}", headers=headers)

    def list_approaches(self, headers, params=None):
        return self._request("GET", "/approaches", headers=headers, params=params)

    def complete_approach(self, approach_id, headers):
        return self._request("POST", f"/approaches/{approach_id}/complete", {}, headers)

    def exclude_approach(self, approach_id, headers):
        return self._request("POST", f"/approaches/{approach_id}/exclude", {}, headers)

    def include_approach(self, approach_id, headers):
        return self._request("POST", f"/approaches/{approach_id}/include", {}, headers)

    # --- Comparable sales ---
    def create_comparable(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/comparables", payload, headers
        )

    def get_comparable(self, comparable_id, headers):
        return self._request("GET", f"/comparables/{comparable_id}", headers=headers)

    def list_comparables(self, headers, params=None):
        return self._request("GET", "/comparables", headers=headers, params=params)

    # --- Reports ---
    def create_report(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/reports", payload, headers
        )

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def submit_review(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/submit_review", {}, headers)

    def review_approve(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/review_approve", {}, headers)

    def review_return(self, report_id, payload, headers):
        return self._request(
            "POST", f"/reports/{report_id}/review_return", payload, headers
        )

    def issue_to_client(self, report_id, headers):
        return self._request(
            "POST", f"/reports/{report_id}/issue_to_client", {}, headers
        )

    def reissue_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/reissue", {}, headers)

    def finalize_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/finalize", {}, headers)

    def sign_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/sign", {}, headers)

    def deliver_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/deliver", {}, headers)

    # --- Revision requests ---
    def create_revision_request(self, report_id, payload, headers):
        return self._request(
            "POST", f"/reports/{report_id}/revision-requests", payload, headers
        )

    def get_revision_request(self, request_id, headers):
        return self._request("GET", f"/revision-requests/{request_id}", headers=headers)

    def list_revision_requests(self, headers, params=None):
        return self._request("GET", "/revision-requests", headers=headers, params=params)

    def accept_revision_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/revision-requests/{request_id}/accept", payload, headers
        )

    def decline_revision_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/revision-requests/{request_id}/decline", payload, headers
        )

    def escalate_revision_request(self, request_id, headers):
        return self._request(
            "POST", f"/revision-requests/{request_id}/escalate", {}, headers
        )

    def withdraw_revision_request(self, request_id, headers):
        return self._request(
            "POST", f"/revision-requests/{request_id}/withdraw", {}, headers
        )

    # --- Retention records ---
    def get_retention_record(self, record_id, headers):
        return self._request("GET", f"/retention-records/{record_id}", headers=headers)

    def list_retention_records(self, headers, params=None):
        return self._request("GET", "/retention-records", headers=headers, params=params)

    def authorize_destruction(self, record_id, headers):
        return self._request(
            "POST", f"/retention-records/{record_id}/authorize_destruction", {}, headers
        )

    def confirm_destruction(self, record_id, headers):
        return self._request(
            "POST", f"/retention-records/{record_id}/confirm_destruction", {}, headers
        )


api_client = ApiClient()
