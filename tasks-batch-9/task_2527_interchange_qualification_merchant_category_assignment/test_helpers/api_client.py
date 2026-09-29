"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Interchange Qualification API."""

    # ── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Processing platforms ─────────────────────────────────────────────
    def create_processing_platform(self, payload, headers):
        return self._request("POST", "/processing-platforms", payload, headers)

    def get_processing_platform(self, platform_id, headers):
        return self._request(
            "GET", f"/processing-platforms/{platform_id}", headers=headers
        )

    def list_processing_platforms(self, headers, params=None):
        return self._request(
            "GET", "/processing-platforms", headers=headers, params=params
        )

    # ── Acquirers ────────────────────────────────────────────────────────
    def create_acquirer(self, payload, headers):
        return self._request("POST", "/acquirers", payload, headers)

    def get_acquirer(self, acquirer_id, headers):
        return self._request("GET", f"/acquirers/{acquirer_id}", headers=headers)

    def list_acquirers(self, headers, params=None):
        return self._request("GET", "/acquirers", headers=headers, params=params)

    # ── MCC definitions ──────────────────────────────────────────────────
    def create_mcc_definition(self, payload, headers):
        return self._request("POST", "/mcc-definitions", payload, headers)

    def get_mcc_definition(self, mcc_definition_id, headers):
        return self._request(
            "GET", f"/mcc-definitions/{mcc_definition_id}", headers=headers
        )

    def list_mcc_definitions(self, headers, params=None):
        return self._request("GET", "/mcc-definitions", headers=headers, params=params)

    # ── Rate programs ────────────────────────────────────────────────────
    def create_rate_program(self, payload, headers):
        return self._request("POST", "/rate-programs", payload, headers)

    def get_rate_program(self, rate_program_id, headers):
        return self._request("GET", f"/rate-programs/{rate_program_id}", headers=headers)

    def list_rate_programs(self, headers, params=None):
        return self._request("GET", "/rate-programs", headers=headers, params=params)

    # ── Rate program versions ────────────────────────────────────────────
    def create_rate_program_version(self, rate_program_id, payload, headers):
        return self._request(
            "POST", f"/rate-programs/{rate_program_id}/versions", payload, headers
        )

    def publish_rate_program_version(self, version_id, headers):
        return self._request(
            "POST", f"/rate-program-versions/{version_id}/publish", {}, headers
        )

    def get_rate_program_version(self, version_id, headers):
        return self._request(
            "GET", f"/rate-program-versions/{version_id}", headers=headers
        )

    def list_rate_program_versions(self, headers, params=None):
        return self._request(
            "GET", "/rate-program-versions", headers=headers, params=params
        )

    # ── Implementation windows ───────────────────────────────────────────
    def create_implementation_window(self, payload, headers):
        return self._request("POST", "/implementation-windows", payload, headers)

    def start_implementation_window(self, window_id, headers):
        return self._request(
            "POST", f"/implementation-windows/{window_id}/start", {}, headers
        )

    def complete_implementation_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/implementation-windows/{window_id}/complete", payload, headers
        )

    def get_implementation_window(self, window_id, headers):
        return self._request(
            "GET", f"/implementation-windows/{window_id}", headers=headers
        )

    def list_implementation_windows(self, headers, params=None):
        return self._request(
            "GET", "/implementation-windows", headers=headers, params=params
        )

    # ── Merchants ────────────────────────────────────────────────────────
    def create_merchant(self, payload, headers):
        return self._request("POST", "/merchants", payload, headers)

    def verify_merchant_category(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/merchants/{merchant_id}/verify-category", payload, headers
        )

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/merchants", headers=headers, params=params)

    # ── Reclassification requests ────────────────────────────────────────
    def create_reclassification_request(self, payload, headers):
        return self._request("POST", "/reclassification-requests", payload, headers)

    def review_reclassification_request(self, request_id, headers):
        return self._request(
            "POST", f"/reclassification-requests/{request_id}/review", {}, headers
        )

    def request_info_reclassification_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/reclassification-requests/{request_id}/request-info",
            payload,
            headers,
        )

    def resubmit_reclassification_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/reclassification-requests/{request_id}/resubmit", payload, headers
        )

    def decide_reclassification_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/reclassification-requests/{request_id}/decide", payload, headers
        )

    def get_reclassification_request(self, request_id, headers):
        return self._request(
            "GET", f"/reclassification-requests/{request_id}", headers=headers
        )

    def list_reclassification_requests(self, headers, params=None):
        return self._request(
            "GET", "/reclassification-requests", headers=headers, params=params
        )

    # ── Currency-conversion rows ─────────────────────────────────────────
    def create_fx_rate(self, payload, headers):
        return self._request("POST", "/fx-rates", payload, headers)

    def get_fx_rate(self, fx_rate_id, headers):
        return self._request("GET", f"/fx-rates/{fx_rate_id}", headers=headers)

    def list_fx_rates(self, headers, params=None):
        return self._request("GET", "/fx-rates", headers=headers, params=params)

    # ── Settlement batches and clearing records ──────────────────────────
    def create_settlement_batch(self, payload, headers):
        return self._request("POST", "/settlement-batches", payload, headers)

    def add_transaction_record(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/settlement-batches/{batch_id}/transaction-records", payload,
            headers,
        )

    def submit_settlement_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/settlement-batches/{batch_id}/submit", {}, headers
        )

    def finalize_settlement_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/settlement-batches/{batch_id}/finalize", {}, headers
        )

    def reverse_transaction_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/transaction-records/{record_id}/reverse", payload, headers
        )

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"/settlement-batches/{batch_id}", headers=headers)

    def list_settlement_batches(self, headers, params=None):
        return self._request(
            "GET", "/settlement-batches", headers=headers, params=params
        )

    def get_transaction_record(self, record_id, headers):
        return self._request("GET", f"/transaction-records/{record_id}", headers=headers)

    def list_transaction_records(self, headers, params=None):
        return self._request(
            "GET", "/transaction-records", headers=headers, params=params
        )

    # ── Incentive programs and enrollments ───────────────────────────────
    def create_incentive_program(self, payload, headers):
        return self._request("POST", "/incentive-programs", payload, headers)

    def get_incentive_program(self, program_id, headers):
        return self._request(
            "GET", f"/incentive-programs/{program_id}", headers=headers
        )

    def list_incentive_programs(self, headers, params=None):
        return self._request(
            "GET", "/incentive-programs", headers=headers, params=params
        )

    def create_incentive_enrollment(self, payload, headers):
        return self._request("POST", "/incentive-enrollments", payload, headers)

    def evaluate_enrollment_performance(self, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/incentive-enrollments/{enrollment_id}/evaluate-performance",
            payload,
            headers,
        )

    def withdraw_incentive_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/incentive-enrollments/{enrollment_id}/withdraw", payload, headers
        )

    def get_incentive_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/incentive-enrollments/{enrollment_id}", headers=headers
        )

    def list_incentive_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/incentive-enrollments", headers=headers, params=params
        )

    # ── Merchant category audits ─────────────────────────────────────────
    def create_merchant_category_audit(self, payload, headers):
        return self._request("POST", "/merchant-category-audits", payload, headers)

    def start_audit_fieldwork(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/merchant-category-audits/{audit_id}/start-fieldwork", payload,
            headers,
        )

    def sustain_audit_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/merchant-category-audits/{audit_id}/sustain-findings", payload,
            headers,
        )

    def clear_audit_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/merchant-category-audits/{audit_id}/clear-findings", payload,
            headers,
        )

    def close_merchant_category_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/merchant-category-audits/{audit_id}/close", {}, headers
        )

    def get_merchant_category_audit(self, audit_id, headers):
        return self._request(
            "GET", f"/merchant-category-audits/{audit_id}", headers=headers
        )

    def list_merchant_category_audits(self, headers, params=None):
        return self._request(
            "GET", "/merchant-category-audits", headers=headers, params=params
        )


api_client = ApiClient()
