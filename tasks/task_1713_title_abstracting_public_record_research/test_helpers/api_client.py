"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Abstract orders ---
    def create_abstract_order(self, payload, headers):
        return self._request("POST", "/api/abstract-orders", payload, headers)

    def get_abstract_order(self, order_id, headers):
        return self._request("GET", f"/api/abstract-orders/{order_id}", headers=headers)

    def list_abstract_orders(self, headers, params=None):
        return self._request("GET", "/api/abstract-orders", headers=headers, params=params)

    def patch_abstract_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/api/abstract-orders/{order_id}", payload, headers)

    def cancel_abstract_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/abstract-orders/{order_id}/cancel", payload, headers)

    def deliver_abstract_order(self, order_id, headers):
        return self._request("POST", f"/api/abstract-orders/{order_id}/deliver", {}, headers)

    # --- Search assignments ---
    def create_search_assignment(self, payload, headers):
        return self._request("POST", "/api/search-assignments", payload, headers)

    def get_search_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/search-assignments/{assignment_id}", headers=headers)

    def list_search_assignments(self, headers, params=None):
        return self._request("GET", "/api/search-assignments", headers=headers, params=params)

    def submit_search_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/search-assignments/{assignment_id}/submit", {}, headers)

    def accept_search_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/search-assignments/{assignment_id}/accept", {}, headers)

    def return_search_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/search-assignments/{assignment_id}/return", payload, headers)

    def resume_search_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/search-assignments/{assignment_id}/resume", {}, headers)

    # --- Record documents ---
    def create_record_document(self, payload, headers):
        return self._request("POST", "/api/record-documents", payload, headers)

    def get_record_document(self, document_id, headers):
        return self._request("GET", f"/api/record-documents/{document_id}", headers=headers)

    def list_record_documents(self, headers, params=None):
        return self._request("GET", "/api/record-documents", headers=headers, params=params)

    def verify_record_document(self, document_id, headers):
        return self._request("POST", f"/api/record-documents/{document_id}/verify", {}, headers)

    def flag_record_document(self, document_id, payload, headers):
        return self._request("POST", f"/api/record-documents/{document_id}/flag", payload, headers)

    def void_record_document(self, document_id, payload, headers):
        return self._request("POST", f"/api/record-documents/{document_id}/void", payload, headers)

    # --- Legal description checks ---
    def create_legal_description_check(self, payload, headers):
        return self._request("POST", "/api/legal-description-checks", payload, headers)

    def get_legal_description_check(self, check_id, headers):
        return self._request("GET", f"/api/legal-description-checks/{check_id}", headers=headers)

    def list_legal_description_checks(self, headers, params=None):
        return self._request("GET", "/api/legal-description-checks", headers=headers, params=params)

    def submit_legal_verdict(self, check_id, payload, headers):
        return self._request("POST", f"/api/legal-description-checks/{check_id}/submit-verdict", payload, headers)

    def resolve_legal_description_check(self, check_id, payload, headers):
        return self._request("POST", f"/api/legal-description-checks/{check_id}/resolve", payload, headers)

    # --- Abstract reports ---
    def create_abstract_report(self, payload, headers):
        return self._request("POST", "/api/abstract-reports", payload, headers)

    def get_abstract_report(self, report_id, headers):
        return self._request("GET", f"/api/abstract-reports/{report_id}", headers=headers)

    def list_abstract_reports(self, headers, params=None):
        return self._request("GET", "/api/abstract-reports", headers=headers, params=params)

    def submit_abstract_report(self, report_id, headers):
        return self._request("POST", f"/api/abstract-reports/{report_id}/submit", {}, headers)

    def start_report_review(self, report_id, payload, headers):
        return self._request("POST", f"/api/abstract-reports/{report_id}/start-review", payload, headers)

    def approve_abstract_report(self, report_id, headers):
        return self._request("POST", f"/api/abstract-reports/{report_id}/approve", {}, headers)

    def require_report_revision(self, report_id, payload, headers):
        return self._request("POST", f"/api/abstract-reports/{report_id}/require-revision", payload, headers)

    # --- Curative requirements ---
    def create_curative_requirement(self, payload, headers):
        return self._request("POST", "/api/curative-requirements", payload, headers)

    def get_curative_requirement(self, curative_id, headers):
        return self._request("GET", f"/api/curative-requirements/{curative_id}", headers=headers)

    def list_curative_requirements(self, headers, params=None):
        return self._request("GET", "/api/curative-requirements", headers=headers, params=params)

    def satisfy_curative_requirement(self, curative_id, payload, headers):
        return self._request("POST", f"/api/curative-requirements/{curative_id}/satisfy", payload, headers)

    def waive_curative_requirement(self, curative_id, payload, headers):
        return self._request("POST", f"/api/curative-requirements/{curative_id}/waive", payload, headers)

    # --- County retrievals ---
    def create_county_retrieval(self, payload, headers):
        return self._request("POST", "/api/county-retrievals", payload, headers)

    def get_county_retrieval(self, retrieval_id, headers):
        return self._request("GET", f"/api/county-retrievals/{retrieval_id}", headers=headers)

    def list_county_retrievals(self, headers, params=None):
        return self._request("GET", "/api/county-retrievals", headers=headers, params=params)

    def post_retrieval_fee(self, retrieval_id, headers):
        return self._request("POST", f"/api/county-retrievals/{retrieval_id}/post-fee", {}, headers)

    def reverse_retrieval_fee(self, retrieval_id, payload, headers):
        return self._request("POST", f"/api/county-retrievals/{retrieval_id}/reverse-fee", payload, headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
