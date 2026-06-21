"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Matter ----
    def create_matter(self, payload, headers):
        return self._request("POST", "/matters", payload, headers)

    def get_matter(self, matter_id, headers):
        return self._request("GET", f"/matters/{matter_id}", headers=headers)

    def list_matters(self, headers, params=None):
        return self._request("GET", "/matters", headers=headers, params=params)

    def get_matter_risk(self, matter_id, headers):
        return self._request("GET", f"/matters/{matter_id}/risk", headers=headers)

    def get_collection_summary(self, matter_id, headers):
        return self._request(
            "GET", f"/matters/{matter_id}/collection-summary", headers=headers
        )

    def begin_close_matter(self, matter_id, headers):
        return self._request("POST", f"/matters/{matter_id}/begin-close", {}, headers)

    def release_hold(self, matter_id, headers):
        return self._request("POST", f"/matters/{matter_id}/release-hold", {}, headers)

    def close_matter(self, matter_id, headers):
        return self._request("POST", f"/matters/{matter_id}/close", {}, headers)

    # ---- Custodian ----
    def create_custodian(self, payload, headers):
        return self._request("POST", "/custodians", payload, headers)

    def get_custodian(self, custodian_id, headers):
        return self._request("GET", f"/custodians/{custodian_id}", headers=headers)

    def list_custodians(self, headers, params=None):
        return self._request("GET", "/custodians", headers=headers, params=params)

    # ---- LegalHold ----
    def create_legal_hold(self, payload, headers):
        return self._request("POST", "/legal-holds", payload, headers)

    def get_legal_hold(self, hold_id, headers):
        return self._request("GET", f"/legal-holds/{hold_id}", headers=headers)

    def list_legal_holds(self, headers, params=None):
        return self._request("GET", "/legal-holds", headers=headers, params=params)

    def issue_legal_hold(self, hold_id, headers):
        return self._request("POST", f"/legal-holds/{hold_id}/issue", {}, headers)

    # ---- HoldAcknowledgement ----
    def get_hold_acknowledgement(self, ack_id, headers):
        return self._request(
            "GET", f"/hold-acknowledgements/{ack_id}", headers=headers
        )

    def list_hold_acknowledgements(self, headers, params=None):
        return self._request(
            "GET", "/hold-acknowledgements", headers=headers, params=params
        )

    def acknowledge(self, ack_id, headers):
        return self._request(
            "POST", f"/hold-acknowledgements/{ack_id}/acknowledge", {}, headers
        )

    # ---- CollectionScope ----
    def create_collection_scope(self, payload, headers):
        return self._request("POST", "/collection-scopes", payload, headers)

    def get_collection_scope(self, scope_id, headers):
        return self._request(
            "GET", f"/collection-scopes/{scope_id}", headers=headers
        )

    def list_collection_scopes(self, headers, params=None):
        return self._request(
            "GET", "/collection-scopes", headers=headers, params=params
        )

    def start_collection_scope(self, scope_id, headers):
        return self._request(
            "POST", f"/collection-scopes/{scope_id}/start", {}, headers
        )

    def finish_collection_scope(self, scope_id, headers):
        return self._request(
            "POST", f"/collection-scopes/{scope_id}/finish", {}, headers
        )

    # ---- Document ----
    def create_document(self, payload, headers):
        return self._request("POST", "/documents", payload, headers)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/documents/{document_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/documents", headers=headers, params=params)

    # ---- ProcessingJob ----
    def create_processing_job(self, payload, headers):
        return self._request("POST", "/processing-jobs", payload, headers)

    def get_processing_job(self, job_id, headers):
        return self._request("GET", f"/processing-jobs/{job_id}", headers=headers)

    def list_processing_jobs(self, headers, params=None):
        return self._request("GET", "/processing-jobs", headers=headers, params=params)

    def run_processing_job(self, job_id, headers):
        return self._request("POST", f"/processing-jobs/{job_id}/run", {}, headers)

    def complete_processing_job(self, job_id, headers):
        return self._request(
            "POST", f"/processing-jobs/{job_id}/complete", {}, headers
        )

    def fail_processing_job(self, job_id, headers):
        return self._request("POST", f"/processing-jobs/{job_id}/fail", {}, headers)

    # ---- ReviewBatch ----
    def create_review_batch(self, payload, headers):
        return self._request("POST", "/review-batches", payload, headers)

    def get_review_batch(self, batch_id, headers):
        return self._request("GET", f"/review-batches/{batch_id}", headers=headers)

    def list_review_batches(self, headers, params=None):
        return self._request("GET", "/review-batches", headers=headers, params=params)

    def add_review(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/review-batches/{batch_id}/reviews", payload, headers
        )

    def list_reviews(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/review-batches/{batch_id}/reviews", headers=headers, params=params
        )

    def open_review(self, batch_id, headers):
        return self._request(
            "POST", f"/review-batches/{batch_id}/open-review", {}, headers
        )

    def submit_qc(self, batch_id, headers):
        return self._request(
            "POST", f"/review-batches/{batch_id}/submit-qc", {}, headers
        )

    def reopen_review(self, batch_id, headers):
        return self._request(
            "POST", f"/review-batches/{batch_id}/reopen", {}, headers
        )

    def complete_review_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/review-batches/{batch_id}/complete", {}, headers
        )

    # ---- DocumentReview ----
    def get_document_review(self, review_id, headers):
        return self._request(
            "GET", f"/document-reviews/{review_id}", headers=headers
        )

    def list_document_reviews(self, headers, params=None):
        return self._request(
            "GET", "/document-reviews", headers=headers, params=params
        )

    def decide_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/document-reviews/{review_id}/decide", payload, headers
        )

    # ---- ProductionSet ----
    def create_production_set(self, payload, headers):
        return self._request("POST", "/production-sets", payload, headers)

    def get_production_set(self, set_id, headers):
        return self._request("GET", f"/production-sets/{set_id}", headers=headers)

    def list_production_sets(self, headers, params=None):
        return self._request("GET", "/production-sets", headers=headers, params=params)

    def add_production_item(self, set_id, payload, headers):
        return self._request(
            "POST", f"/production-sets/{set_id}/items", payload, headers
        )

    def list_production_items_on_set(self, set_id, headers, params=None):
        return self._request(
            "GET", f"/production-sets/{set_id}/items", headers=headers, params=params
        )

    def validate_production_set(self, set_id, headers):
        return self._request(
            "POST", f"/production-sets/{set_id}/validate", {}, headers
        )

    def revise_production_set(self, set_id, headers):
        return self._request(
            "POST", f"/production-sets/{set_id}/revise", {}, headers
        )

    def produce_production_set(self, set_id, headers):
        return self._request(
            "POST", f"/production-sets/{set_id}/produce", {}, headers
        )

    # ---- ProductionItem ----
    def get_production_item(self, item_id, headers):
        return self._request("GET", f"/production-items/{item_id}", headers=headers)

    def list_production_items(self, headers, params=None):
        return self._request("GET", "/production-items", headers=headers, params=params)

    # ---- Clawback ----
    def create_clawback(self, payload, headers):
        return self._request("POST", "/clawbacks", payload, headers)

    def get_clawback(self, clawback_id, headers):
        return self._request("GET", f"/clawbacks/{clawback_id}", headers=headers)

    def list_clawbacks(self, headers, params=None):
        return self._request("GET", "/clawbacks", headers=headers, params=params)

    def sequester_clawback(self, clawback_id, headers):
        return self._request(
            "POST", f"/clawbacks/{clawback_id}/sequester", {}, headers
        )

    def dispute_clawback(self, clawback_id, headers):
        return self._request(
            "POST", f"/clawbacks/{clawback_id}/dispute", {}, headers
        )

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
