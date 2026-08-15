"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Producers
    # ------------------------------------------------------------------
    def create_producer(self, payload, headers):
        return self._request("POST", "/producers", payload, headers)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/producers/{producer_id}", headers=headers)

    def suspend_producer(self, producer_id, headers):
        return self._request("POST", f"/producers/{producer_id}/suspend", {}, headers)

    def reinstate_producer(self, producer_id, headers):
        return self._request("POST", f"/producers/{producer_id}/reinstate", {}, headers)

    def list_producer_activity_events(self, producer_id, headers, params=None):
        return self._request(
            "GET",
            f"/producers/{producer_id}/activity-events",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_client_contracts(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/contracts", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Existing contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    # ------------------------------------------------------------------
    # Exchange cases
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def submit_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/submit", {}, headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/withdraw", {}, headers)

    def start_review(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/start_review", {}, headers)

    def request_info(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/request_info", payload, headers)

    def recommend_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/recommend", payload, headers)

    def reject_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/reject", payload, headers)

    def approve_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/approve", payload, headers)

    def request_funds(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/request_funds", {}, headers)

    def confirm_delivery(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/confirm_delivery", {}, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/complete", {}, headers)

    def rescind_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/rescind", {}, headers)

    # ------------------------------------------------------------------
    # Case documents
    # ------------------------------------------------------------------
    def create_document(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/documents", payload, headers)

    def list_case_documents(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/documents", headers=headers, params=params
        )

    def verify_document(self, document_id, headers):
        return self._request("POST", f"/documents/{document_id}/verify", {}, headers)

    def reject_document(self, document_id, payload, headers):
        return self._request("POST", f"/documents/{document_id}/reject", payload, headers)

    # ------------------------------------------------------------------
    # Comparison analyses
    # ------------------------------------------------------------------
    def create_comparison_analysis(self, case_id, payload, headers):
        return self._request(
            "POST", f"/cases/{case_id}/comparison-analyses", payload, headers
        )

    def list_comparison_analyses(self, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/cases/{case_id}/comparison-analyses",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Funds transfers
    # ------------------------------------------------------------------
    def list_funds_transfers(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/funds-transfers", headers=headers, params=params
        )

    def mark_transfer_received(self, transfer_id, headers):
        return self._request(
            "POST", f"/transfers/{transfer_id}/mark_received", {}, headers
        )

    def mark_transfer_failed(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/mark_failed", {}, headers)

    # ------------------------------------------------------------------
    # Audit reads
    # ------------------------------------------------------------------
    def list_case_activity_events(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/activity-events", headers=headers, params=params
        )

    def list_review_decisions(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/review-decisions", headers=headers, params=params
        )


api_client = ApiClient()
