"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Project ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def substantial_completion_project(self, project_id, headers):
        return self._request(
            "POST", f"/projects/{project_id}/substantial-completion", {}, headers
        )

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close", {}, headers)

    # ---- SovLine ----
    def create_sov_line(self, payload, headers):
        return self._request("POST", "/sov-lines", payload, headers)

    def get_sov_line(self, sov_line_id, headers):
        return self._request("GET", f"/sov-lines/{sov_line_id}", headers=headers)

    def list_sov_lines(self, headers, params=None):
        return self._request("GET", "/sov-lines", headers=headers, params=params)

    # ---- ChangeOrder ----
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def submit_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/submit", {}, headers
        )

    def approve_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/approve", payload, headers
        )

    def reject_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/reject", {}, headers
        )

    # ---- PayApplication ----
    def create_pay_application(self, payload, headers):
        return self._request("POST", "/pay-applications", payload, headers)

    def get_pay_application(self, pay_app_id, headers):
        return self._request("GET", f"/pay-applications/{pay_app_id}", headers=headers)

    def list_pay_applications(self, headers, params=None):
        return self._request("GET", "/pay-applications", headers=headers, params=params)

    def submit_pay_application(self, pay_app_id, headers):
        return self._request(
            "POST", f"/pay-applications/{pay_app_id}/submit", {}, headers
        )

    def certify_pay_application(self, pay_app_id, headers):
        return self._request(
            "POST", f"/pay-applications/{pay_app_id}/certify", {}, headers
        )

    def reject_pay_application(self, pay_app_id, headers):
        return self._request(
            "POST", f"/pay-applications/{pay_app_id}/reject", {}, headers
        )

    # ---- PayAppLine ----
    def create_pay_app_line(self, payload, headers):
        return self._request("POST", "/pay-app-lines", payload, headers)

    def get_pay_app_line(self, pay_app_line_id, headers):
        return self._request("GET", f"/pay-app-lines/{pay_app_line_id}", headers=headers)

    def list_pay_app_lines(self, headers, params=None):
        return self._request("GET", "/pay-app-lines", headers=headers, params=params)

    # ---- SubcontractorCommitment ----
    def create_subcontractor_commitment(self, payload, headers):
        return self._request("POST", "/subcontractor-commitments", payload, headers)

    def get_subcontractor_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"/subcontractor-commitments/{commitment_id}", headers=headers
        )

    def list_subcontractor_commitments(self, headers, params=None):
        return self._request(
            "GET", "/subcontractor-commitments", headers=headers, params=params
        )

    def close_subcontractor_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"/subcontractor-commitments/{commitment_id}/close", {}, headers
        )

    # ---- Rfi ----
    def create_rfi(self, payload, headers):
        return self._request("POST", "/rfis", payload, headers)

    def get_rfi(self, rfi_id, headers):
        return self._request("GET", f"/rfis/{rfi_id}", headers=headers)

    def list_rfis(self, headers, params=None):
        return self._request("GET", "/rfis", headers=headers, params=params)

    def answer_rfi(self, rfi_id, payload, headers):
        return self._request("POST", f"/rfis/{rfi_id}/answer", payload, headers)

    def close_rfi(self, rfi_id, headers):
        return self._request("POST", f"/rfis/{rfi_id}/close", {}, headers)

    # ---- Submittal ----
    def create_submittal(self, payload, headers):
        return self._request("POST", "/submittals", payload, headers)

    def get_submittal(self, submittal_id, headers):
        return self._request("GET", f"/submittals/{submittal_id}", headers=headers)

    def list_submittals(self, headers, params=None):
        return self._request("GET", "/submittals", headers=headers, params=params)

    def review_submittal(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/submittals/{submittal_id}/review", payload, headers
        )

    def resubmit_submittal(self, submittal_id, headers):
        return self._request("POST", f"/submittals/{submittal_id}/resubmit", {}, headers)

    def close_submittal(self, submittal_id, headers):
        return self._request("POST", f"/submittals/{submittal_id}/close", {}, headers)

    # ---- LienWaiver ----
    def create_lien_waiver(self, payload, headers):
        return self._request("POST", "/lien-waivers", payload, headers)

    def get_lien_waiver(self, lien_waiver_id, headers):
        return self._request("GET", f"/lien-waivers/{lien_waiver_id}", headers=headers)

    def list_lien_waivers(self, headers, params=None):
        return self._request("GET", "/lien-waivers", headers=headers, params=params)

    def notarize_lien_waiver(self, lien_waiver_id, headers):
        return self._request(
            "POST", f"/lien-waivers/{lien_waiver_id}/notarize", {}, headers
        )

    def void_lien_waiver(self, lien_waiver_id, headers):
        return self._request("POST", f"/lien-waivers/{lien_waiver_id}/void", {}, headers)

    # ---- PunchListItem ----
    def create_punch_item(self, payload, headers):
        return self._request("POST", "/punch-items", payload, headers)

    def get_punch_item(self, punch_item_id, headers):
        return self._request("GET", f"/punch-items/{punch_item_id}", headers=headers)

    def list_punch_items(self, headers, params=None):
        return self._request("GET", "/punch-items", headers=headers, params=params)

    def ready_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/punch-items/{punch_item_id}/ready", {}, headers)

    def verify_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/punch-items/{punch_item_id}/verify", {}, headers)

    def reopen_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/punch-items/{punch_item_id}/reopen", {}, headers)

    # ---- InspectionWindow ----
    def create_inspection_window(self, payload, headers):
        return self._request("POST", "/inspection-windows", payload, headers)

    def get_inspection_window(self, window_id, headers):
        return self._request("GET", f"/inspection-windows/{window_id}", headers=headers)

    def list_inspection_windows(self, headers, params=None):
        return self._request("GET", "/inspection-windows", headers=headers, params=params)

    def complete_inspection_window(self, window_id, headers):
        return self._request(
            "POST", f"/inspection-windows/{window_id}/complete", {}, headers
        )

    def cancel_inspection_window(self, window_id, headers):
        return self._request(
            "POST", f"/inspection-windows/{window_id}/cancel", {}, headers
        )

    # ---- RetentionRelease ----
    def create_retention_release(self, payload, headers):
        return self._request("POST", "/retention-releases", payload, headers)

    def get_retention_release(self, release_id, headers):
        return self._request("GET", f"/retention-releases/{release_id}", headers=headers)

    def list_retention_releases(self, headers, params=None):
        return self._request("GET", "/retention-releases", headers=headers, params=params)

    def approve_retention_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"/retention-releases/{release_id}/approve", payload, headers
        )

    def reject_retention_release(self, release_id, headers):
        return self._request(
            "POST", f"/retention-releases/{release_id}/reject", {}, headers
        )


api_client = ApiClient()
