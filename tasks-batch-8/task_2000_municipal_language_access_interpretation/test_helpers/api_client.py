"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Departments
    # ------------------------------------------------------------------
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/departments", headers=headers, params=params)

    def patch_department(self, department_id, payload, headers):
        return self._request("PATCH", f"/departments/{department_id}", payload, headers)

    # ------------------------------------------------------------------
    # Language assessments
    # ------------------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/language-assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/language-assessments/{assessment_id}",
                             headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/language-assessments", headers=headers,
                             params=params)

    def review_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/language-assessments/{assessment_id}/review",
                             payload, headers)

    # ------------------------------------------------------------------
    # Vital documents
    # ------------------------------------------------------------------
    def create_document(self, payload, headers):
        return self._request("POST", "/vital-documents", payload, headers)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/vital-documents/{document_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/vital-documents", headers=headers, params=params)

    def retire_document(self, document_id, headers):
        return self._request("POST", f"/vital-documents/{document_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Translation jobs
    # ------------------------------------------------------------------
    def create_translation_job(self, payload, headers):
        return self._request("POST", "/translation-jobs", payload, headers)

    def get_translation_job(self, job_id, headers):
        return self._request("GET", f"/translation-jobs/{job_id}", headers=headers)

    def list_translation_jobs(self, headers, params=None):
        return self._request("GET", "/translation-jobs", headers=headers, params=params)

    def assign_translation_job(self, job_id, payload, headers):
        return self._request("POST", f"/translation-jobs/{job_id}/assign",
                             payload, headers)

    def submit_translation(self, job_id, payload, headers):
        return self._request("POST", f"/translation-jobs/{job_id}/submit-translation",
                             payload, headers)

    def review_translation_job(self, job_id, payload, headers):
        return self._request("POST", f"/translation-jobs/{job_id}/review",
                             payload, headers)

    def cancel_translation_job(self, job_id, headers):
        return self._request("POST", f"/translation-jobs/{job_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Interpreters
    # ------------------------------------------------------------------
    def create_interpreter(self, payload, headers):
        return self._request("POST", "/interpreters", payload, headers)

    def get_interpreter(self, interpreter_id, headers):
        return self._request("GET", f"/interpreters/{interpreter_id}", headers=headers)

    def list_interpreters(self, headers, params=None):
        return self._request("GET", "/interpreters", headers=headers, params=params)

    def patch_interpreter(self, interpreter_id, payload, headers):
        return self._request("PATCH", f"/interpreters/{interpreter_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Interpretation requests
    # ------------------------------------------------------------------
    def create_interpretation_request(self, payload, headers):
        return self._request("POST", "/interpretation-requests", payload, headers)

    def get_interpretation_request(self, request_id, headers):
        return self._request("GET", f"/interpretation-requests/{request_id}",
                             headers=headers)

    def list_interpretation_requests(self, headers, params=None):
        return self._request("GET", "/interpretation-requests", headers=headers,
                             params=params)

    def complete_interpretation_request(self, request_id, payload, headers):
        return self._request("POST", f"/interpretation-requests/{request_id}/complete",
                             payload, headers)

    def cancel_interpretation_request(self, request_id, headers):
        return self._request("POST", f"/interpretation-requests/{request_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def adjudicate_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/adjudicate",
                             payload, headers)

    def close_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/close",
                             payload, headers)

    # ------------------------------------------------------------------
    # Vendor contracts
    # ------------------------------------------------------------------
    def create_vendor_contract(self, payload, headers):
        return self._request("POST", "/vendor-contracts", payload, headers)

    def get_vendor_contract(self, contract_id, headers):
        return self._request("GET", f"/vendor-contracts/{contract_id}", headers=headers)

    def activate_vendor_contract(self, contract_id, headers):
        return self._request("POST", f"/vendor-contracts/{contract_id}/activate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Language access plans
    # ------------------------------------------------------------------
    def create_language_access_plan(self, payload, headers):
        return self._request("POST", "/language-access-plans", payload, headers)

    def get_language_access_plan(self, plan_id, headers):
        return self._request("GET", f"/language-access-plans/{plan_id}", headers=headers)

    def publish_language_access_plan(self, plan_id, headers):
        return self._request("POST", f"/language-access-plans/{plan_id}/publish",
                             {}, headers)


api_client = ApiClient()
