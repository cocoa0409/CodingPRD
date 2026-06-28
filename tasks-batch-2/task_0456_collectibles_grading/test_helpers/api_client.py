"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers=None):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- ServiceLevel ----
    def create_service_level(self, payload, headers):
        return self._request("POST", "/service-levels", payload, headers=headers)

    def get_service_level(self, sl_id, headers):
        return self._request("GET", f"/service-levels/{sl_id}", headers=headers)

    def list_service_levels(self, headers, params=None):
        return self._request("GET", "/service-levels", headers=headers, params=params)

    # ---- GradingStandard ----
    def create_grading_standard(self, payload, headers):
        return self._request("POST", "/grading-standards", payload, headers=headers)

    def get_grading_standard(self, gs_id, headers):
        return self._request("GET", f"/grading-standards/{gs_id}", headers=headers)

    # ---- Submissions ----
    def create_submission(self, payload, headers):
        return self._request("POST", "/submissions", payload, headers=headers)

    def get_submission(self, sub_id, headers):
        return self._request("GET", f"/submissions/{sub_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def submit_submission(self, sub_id, headers):
        return self._request("POST", f"/submissions/{sub_id}/submit", {}, headers=headers)

    def close_submission(self, sub_id, headers):
        return self._request("POST", f"/submissions/{sub_id}/close", {}, headers=headers)

    # ---- SubmissionItems ----
    def add_item(self, sub_id, payload, headers):
        return self._request("POST", f"/submissions/{sub_id}/items", payload, headers=headers)

    def list_submission_items_of(self, sub_id, headers, params=None):
        return self._request("GET", f"/submissions/{sub_id}/items", headers=headers, params=params)

    def list_submission_items(self, headers, params=None):
        return self._request("GET", "/submission-items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/submission-items/{item_id}", headers=headers)

    def delete_item(self, item_id, headers):
        return self._request("DELETE", f"/submission-items/{item_id}", headers=headers)

    # ---- Intake ----
    def log_intake(self, item_id, payload, headers):
        return self._request("POST", f"/submission-items/{item_id}/intake", payload, headers=headers)

    def list_intake(self, item_id, headers):
        return self._request("GET", f"/submission-items/{item_id}/intake", headers=headers)

    def reject_item(self, item_id, headers):
        return self._request("POST", f"/submission-items/{item_id}/reject", {}, headers=headers)

    # ---- Grading ----
    def create_grade_assessment(self, item_id, payload, headers):
        return self._request("POST", f"/submission-items/{item_id}/grade-assessments", payload, headers=headers)

    def list_grade_assessments_of(self, item_id, headers, params=None):
        return self._request("GET", f"/submission-items/{item_id}/grade-assessments", headers=headers, params=params)

    def list_grade_assessments(self, headers, params=None):
        return self._request("GET", "/grade-assessments", headers=headers, params=params)

    def get_grade_assessment(self, ga_id, headers):
        return self._request("GET", f"/grade-assessments/{ga_id}", headers=headers)

    def finalize_assessment(self, ga_id, headers):
        return self._request("POST", f"/grade-assessments/{ga_id}/finalize", {}, headers=headers)

    # ---- Authentication ----
    def authenticate_item(self, item_id, payload, headers):
        return self._request("POST", f"/submission-items/{item_id}/authentication", payload, headers=headers)

    def list_authentication(self, item_id, headers):
        return self._request("GET", f"/submission-items/{item_id}/authentication", headers=headers)

    # ---- Encapsulation / Slab ----
    def encapsulate_item(self, item_id, payload, headers):
        return self._request("POST", f"/submission-items/{item_id}/encapsulate", payload, headers=headers)

    def list_slabs_of(self, item_id, headers, params=None):
        return self._request("GET", f"/submission-items/{item_id}/slabs", headers=headers, params=params)

    def list_slabs(self, headers, params=None):
        return self._request("GET", "/slabs", headers=headers, params=params)

    def get_slab(self, slab_id, headers):
        return self._request("GET", f"/slabs/{slab_id}", headers=headers)

    # ---- Labels ----
    def print_label(self, slab_id, payload, headers):
        return self._request("POST", f"/slabs/{slab_id}/label", payload, headers=headers)

    def list_labels_of(self, slab_id, headers):
        return self._request("GET", f"/slabs/{slab_id}/label", headers=headers)

    def list_labels(self, headers, params=None):
        return self._request("GET", "/labels", headers=headers, params=params)

    def get_label(self, label_id, headers):
        return self._request("GET", f"/labels/{label_id}", headers=headers)

    # ---- Population reports ----
    def list_population_reports(self, headers, params=None):
        return self._request("GET", "/population-reports", headers=headers, params=params)

    def get_population_report(self, pop_id, headers):
        return self._request("GET", f"/population-reports/{pop_id}", headers=headers)

    # ---- Insurance ----
    def get_insurance_policy(self, sub_id, headers):
        return self._request("GET", f"/submissions/{sub_id}/insurance-policy", headers=headers)

    # ---- Regrade ----
    def create_regrade_request(self, item_id, payload, headers):
        return self._request("POST", f"/submission-items/{item_id}/regrade-requests", payload, headers=headers)

    def list_regrade_requests_of(self, item_id, headers, params=None):
        return self._request("GET", f"/submission-items/{item_id}/regrade-requests", headers=headers, params=params)

    def list_regrade_requests(self, headers, params=None):
        return self._request("GET", "/regrade-requests", headers=headers, params=params)

    def get_regrade_request(self, rr_id, headers):
        return self._request("GET", f"/regrade-requests/{rr_id}", headers=headers)

    # ---- Shipments ----
    def create_shipment(self, sub_id, payload, headers):
        return self._request("POST", f"/submissions/{sub_id}/shipments", payload, headers=headers)

    def list_shipments_of(self, sub_id, headers, params=None):
        return self._request("GET", f"/submissions/{sub_id}/shipments", headers=headers, params=params)

    def get_shipment(self, ship_id, headers):
        return self._request("GET", f"/shipments/{ship_id}", headers=headers)

    def dispatch_shipment(self, ship_id, headers):
        return self._request("POST", f"/shipments/{ship_id}/dispatch", {}, headers=headers)

    def deliver_shipment(self, ship_id, headers):
        return self._request("POST", f"/shipments/{ship_id}/deliver", {}, headers=headers)

    def report_lost_shipment(self, ship_id, headers):
        return self._request("POST", f"/shipments/{ship_id}/report-lost", {}, headers=headers)

    # ---- Test-driving: logical clock ----
    def set_clock(self, to_iso8601, headers=None):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
