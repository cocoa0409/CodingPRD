"""API client: one method per endpoint defined in the PRD endpoint table.

Every method returns the raw requests.Response; tests validate envelopes via
test_helpers validators. List endpoints accept a `params` dict that is passed
through as query parameters.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -- logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/tax1099/_clock/set_current_utc", payload, headers)

    # -- tax years -----------------------------------------------------------
    def create_tax_year(self, payload, headers):
        return self._request("POST", "/tax1099/tax-years", payload, headers)

    def close_tax_year(self, tax_year_id, headers):
        return self._request("POST", f"/tax1099/tax-years/{tax_year_id}/close", {}, headers)

    # -- vendors -------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/tax1099/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/tax1099/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/tax1099/vendors", headers=headers, params=params)

    def patch_vendor(self, vendor_id, payload, headers):
        return self._request("PATCH", f"/tax1099/vendors/{vendor_id}", payload, headers)

    def deactivate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/tax1099/vendors/{vendor_id}/deactivate", {}, headers)

    # -- W-9 submissions -----------------------------------------------------
    def create_w9_submission(self, vendor_id, payload, headers):
        return self._request("POST", f"/tax1099/vendors/{vendor_id}/w9-submissions", payload, headers)

    def get_w9_submission(self, submission_id, headers):
        return self._request("GET", f"/tax1099/w9-submissions/{submission_id}", headers=headers)

    def list_w9_submissions(self, headers, params=None):
        return self._request("GET", "/tax1099/w9-submissions", headers=headers, params=params)

    def record_match_result(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/tax1099/w9-submissions/{submission_id}/record-match-result", payload, headers
        )

    # -- payments ------------------------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/tax1099/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/tax1099/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/tax1099/payments", headers=headers, params=params)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/tax1099/payments/{payment_id}/void", {}, headers)

    # -- withholding entries -------------------------------------------------
    def get_withholding_entry(self, entry_id, headers):
        return self._request("GET", f"/tax1099/withholding-entries/{entry_id}", headers=headers)

    def list_withholding_entries(self, headers, params=None):
        return self._request("GET", "/tax1099/withholding-entries", headers=headers, params=params)

    def reverse_withholding_entry(self, entry_id, headers):
        return self._request("POST", f"/tax1099/withholding-entries/{entry_id}/reverse", {}, headers)

    # -- remittances ---------------------------------------------------------
    def create_remittance(self, payload, headers):
        return self._request("POST", "/tax1099/remittances", payload, headers)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/tax1099/remittances/{remittance_id}", headers=headers)

    def submit_remittance(self, remittance_id, headers):
        return self._request("POST", f"/tax1099/remittances/{remittance_id}/submit", {}, headers)

    def record_remittance_outcome(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/tax1099/remittances/{remittance_id}/record-outcome", payload, headers
        )

    def reopen_remittance(self, remittance_id, headers):
        return self._request("POST", f"/tax1099/remittances/{remittance_id}/reopen", {}, headers)

    # -- returns -------------------------------------------------------------
    def generate_returns(self, payload, headers):
        return self._request("POST", "/tax1099/returns/generate", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/tax1099/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/tax1099/returns", headers=headers, params=params)

    def validate_return(self, return_id, headers):
        return self._request("POST", f"/tax1099/returns/{return_id}/validate", {}, headers)

    def void_return(self, return_id, headers):
        return self._request("POST", f"/tax1099/returns/{return_id}/void", {}, headers)

    def correct_return(self, return_id, payload, headers):
        return self._request("POST", f"/tax1099/returns/{return_id}/correct", payload, headers)

    def deliver_copy(self, return_id, payload, headers):
        return self._request("POST", f"/tax1099/returns/{return_id}/deliver-copy", payload, headers)

    def record_copy_bounce(self, return_id, headers):
        return self._request("POST", f"/tax1099/returns/{return_id}/record-copy-bounce", {}, headers)

    # -- transmittals --------------------------------------------------------
    def create_transmittal(self, payload, headers):
        return self._request("POST", "/tax1099/transmittals", payload, headers)

    def get_transmittal(self, transmittal_id, headers):
        return self._request("GET", f"/tax1099/transmittals/{transmittal_id}", headers=headers)

    def seal_transmittal(self, transmittal_id, headers):
        return self._request("POST", f"/tax1099/transmittals/{transmittal_id}/seal", {}, headers)

    def submit_transmittal(self, transmittal_id, payload, headers):
        return self._request("POST", f"/tax1099/transmittals/{transmittal_id}/submit", payload, headers)

    def record_transmittal_outcome(self, transmittal_id, payload, headers):
        return self._request(
            "POST", f"/tax1099/transmittals/{transmittal_id}/record-outcome", payload, headers
        )

    def reopen_transmittal(self, transmittal_id, headers):
        return self._request("POST", f"/tax1099/transmittals/{transmittal_id}/reopen", {}, headers)

    # -- state rules / obligations -------------------------------------------
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/tax1099/state-rules", payload, headers)

    def evaluate_state_obligations(self, payload, headers):
        return self._request("POST", "/tax1099/state-obligations/evaluate", payload, headers)

    def get_state_obligation(self, obligation_id, headers):
        return self._request("GET", f"/tax1099/state-obligations/{obligation_id}", headers=headers)

    def list_state_obligations(self, headers, params=None):
        return self._request("GET", "/tax1099/state-obligations", headers=headers, params=params)

    def mark_state_obligation_filed(self, obligation_id, headers):
        return self._request(
            "POST", f"/tax1099/state-obligations/{obligation_id}/mark-filed", {}, headers
        )

    # -- B-notices -----------------------------------------------------------
    def create_b_notice(self, payload, headers):
        return self._request("POST", "/tax1099/b-notices", payload, headers)

    def get_b_notice(self, notice_id, headers):
        return self._request("GET", f"/tax1099/b-notices/{notice_id}", headers=headers)

    def list_b_notices(self, headers, params=None):
        return self._request("GET", "/tax1099/b-notices", headers=headers, params=params)

    def resolve_b_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/tax1099/b-notices/{notice_id}/resolve", payload, headers)

    # -- vendor merge requests ------------------------------------------------
    def create_merge_request(self, payload, headers):
        return self._request("POST", "/tax1099/vendor-merge-requests", payload, headers)

    def approve_merge_request(self, request_id, headers):
        return self._request(
            "POST", f"/tax1099/vendor-merge-requests/{request_id}/approve", {}, headers
        )

    def reject_merge_request(self, request_id, headers):
        return self._request(
            "POST", f"/tax1099/vendor-merge-requests/{request_id}/reject", {}, headers,
        )

    def get_merge_request(self, request_id, headers):
        return self._request("GET", f"/tax1099/vendor-merge-requests/{request_id}", headers=headers)

    def list_merge_requests(self, headers, params=None):
        return self._request("GET", "/tax1099/vendor-merge-requests", headers=headers, params=params)


api_client = ApiClient()
