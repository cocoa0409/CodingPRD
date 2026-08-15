"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Borrowers
    # ------------------------------------------------------------------
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    # ------------------------------------------------------------------
    # Loans
    # ------------------------------------------------------------------
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def terminate_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/terminate", {}, headers)

    def run_interest_accrual(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/interest-accruals",
                             payload, headers)

    def list_interest_ledger(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/interest-ledger",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Budget lines
    # ------------------------------------------------------------------
    def create_budget_line(self, payload, headers):
        return self._request("POST", "/budget-lines", payload, headers)

    def get_budget_line(self, line_id, headers):
        return self._request("GET", f"/budget-lines/{line_id}", headers=headers)

    def list_budget_lines(self, headers, params=None):
        return self._request("GET", "/budget-lines", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Draw requests
    # ------------------------------------------------------------------
    def create_draw(self, payload, headers):
        return self._request("POST", "/draws", payload, headers)

    def get_draw(self, draw_id, headers):
        return self._request("GET", f"/draws/{draw_id}", headers=headers)

    def list_draws(self, headers, params=None):
        return self._request("GET", "/draws", headers=headers, params=params)

    def submit_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/submit", {}, headers)

    def start_review_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/start-review", {}, headers)

    def request_revision_draw(self, draw_id, payload, headers):
        return self._request("POST", f"/draws/{draw_id}/request-revision",
                             payload, headers)

    def reject_draw(self, draw_id, payload, headers):
        return self._request("POST", f"/draws/{draw_id}/reject", payload, headers)

    def withdraw_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/withdraw", {}, headers)

    def approve_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/approve", {}, headers)

    def fund_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/fund", {}, headers)

    # ------------------------------------------------------------------
    # Draw line items
    # ------------------------------------------------------------------
    def create_draw_line_item(self, payload, headers):
        return self._request("POST", "/draw-line-items", payload, headers)

    def get_draw_line_item(self, item_id, headers):
        return self._request("GET", f"/draw-line-items/{item_id}", headers=headers)

    def list_draw_line_items(self, headers, params=None):
        return self._request("GET", "/draw-line-items", headers=headers, params=params)

    def mark_installed(self, item_id, payload, headers):
        return self._request("POST", f"/draw-line-items/{item_id}/mark-installed",
                             payload, headers)

    # ------------------------------------------------------------------
    # Draw documents
    # ------------------------------------------------------------------
    def create_draw_document(self, payload, headers):
        return self._request("POST", "/draw-documents", payload, headers)

    def get_draw_document(self, doc_id, headers):
        return self._request("GET", f"/draw-documents/{doc_id}", headers=headers)

    def list_draw_documents(self, headers, params=None):
        return self._request("GET", "/draw-documents", headers=headers, params=params)

    def review_draw_document(self, doc_id, payload, headers):
        return self._request("POST", f"/draw-documents/{doc_id}/review",
                             payload, headers)

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/complete",
                             payload, headers)

    def review_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/review",
                             payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Reallocation requests
    # ------------------------------------------------------------------
    def create_reallocation_request(self, payload, headers):
        return self._request("POST", "/reallocation-requests", payload, headers)

    def get_reallocation_request(self, request_id, headers):
        return self._request("GET", f"/reallocation-requests/{request_id}",
                             headers=headers)

    def list_reallocation_requests(self, headers, params=None):
        return self._request("GET", "/reallocation-requests",
                             headers=headers, params=params)

    def review_reallocation_request(self, request_id, payload, headers):
        return self._request("POST", f"/reallocation-requests/{request_id}/review",
                             payload, headers)

    def apply_reallocation_request(self, request_id, headers):
        return self._request("POST", f"/reallocation-requests/{request_id}/apply",
                             {}, headers)

    def cancel_reallocation_request(self, request_id, headers):
        return self._request("POST", f"/reallocation-requests/{request_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Retainage releases
    # ------------------------------------------------------------------
    def create_retainage_release(self, payload, headers):
        return self._request("POST", "/retainage-releases", payload, headers)

    def get_retainage_release(self, release_id, headers):
        return self._request("GET", f"/retainage-releases/{release_id}",
                             headers=headers)

    def list_retainage_releases(self, headers, params=None):
        return self._request("GET", "/retainage-releases",
                             headers=headers, params=params)

    def review_retainage_release(self, release_id, payload, headers):
        return self._request("POST", f"/retainage-releases/{release_id}/review",
                             payload, headers)

    def pay_retainage_release(self, release_id, headers):
        return self._request("POST", f"/retainage-releases/{release_id}/pay",
                             {}, headers)

    # ------------------------------------------------------------------
    # Conversion reviews
    # ------------------------------------------------------------------
    def create_conversion_review(self, payload, headers):
        return self._request("POST", "/conversion-reviews", payload, headers)

    def get_conversion_review(self, review_id, headers):
        return self._request("GET", f"/conversion-reviews/{review_id}",
                             headers=headers)

    def list_conversion_reviews(self, headers, params=None):
        return self._request("GET", "/conversion-reviews",
                             headers=headers, params=params)

    def review_conversion_review(self, review_id, payload, headers):
        return self._request("POST", f"/conversion-reviews/{review_id}/review",
                             payload, headers)

    def convert_conversion_review(self, review_id, payload, headers):
        return self._request("POST", f"/conversion-reviews/{review_id}/convert",
                             payload, headers)


api_client = ApiClient()
