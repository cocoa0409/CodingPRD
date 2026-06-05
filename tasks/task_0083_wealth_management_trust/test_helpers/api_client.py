"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Parties: grantors / trustees / beneficiaries ─────────
    def create_grantor(self, payload, headers):
        return self._request("POST", "/grantors", payload, headers)

    def get_grantor(self, grantor_id, headers):
        return self._request("GET", f"/grantors/{grantor_id}", headers=headers)

    def create_trustee(self, payload, headers):
        return self._request("POST", "/trustees", payload, headers)

    def get_trustee(self, trustee_id, headers):
        return self._request("GET", f"/trustees/{trustee_id}", headers=headers)

    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}", headers=headers)

    def list_beneficiaries(self, headers, params=None):
        return self._request("GET", "/beneficiaries", headers=headers, params=params)

    # ─── Trust lifecycle ──────────────────────────────────────
    def create_trust(self, payload, headers):
        return self._request("POST", "/trusts", payload, headers)

    def get_trust(self, trust_id, headers):
        return self._request("GET", f"/trusts/{trust_id}", headers=headers)

    def list_trusts(self, headers, params=None):
        return self._request("GET", "/trusts", headers=headers, params=params)

    def fund_trust(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/fund", {}, headers)

    def activate_trust(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/activate", {}, headers)

    def open_amendment(self, trust_id, payload, headers):
        return self._request("POST", f"/trusts/{trust_id}/amendments", payload, headers)

    def commit_amendment(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/amendments/commit", {}, headers)

    def revoke_trust(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/revoke", {}, headers)

    def terminate_trust(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/terminate", {}, headers)

    def finalize_termination(self, trust_id, headers):
        return self._request("POST", f"/trusts/{trust_id}/terminate/finalize", {}, headers)

    # ─── Trustee appointments ─────────────────────────────────
    def create_trustee_appointment(self, trust_id, payload, headers):
        return self._request("POST", f"/trusts/{trust_id}/trustee-appointments", payload, headers)

    def list_trust_trustee_appointments(self, trust_id, headers, params=None):
        return self._request("GET", f"/trusts/{trust_id}/trustee-appointments", headers=headers, params=params)

    def get_trustee_appointment(self, appointment_id, headers):
        return self._request("GET", f"/trustee-appointments/{appointment_id}", headers=headers)

    def list_trustee_appointments(self, headers, params=None):
        return self._request("GET", "/trustee-appointments", headers=headers, params=params)

    # ─── Accounting periods + ledger ──────────────────────────
    def create_account(self, trust_id, payload, headers):
        return self._request("POST", f"/trusts/{trust_id}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_trust_accounts(self, trust_id, headers, params=None):
        return self._request("GET", f"/trusts/{trust_id}/accounts", headers=headers, params=params)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    def create_receipt(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/receipts", payload, headers)

    def list_receipts(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/receipts", headers=headers, params=params)

    def create_disbursement(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/disbursements", payload, headers)

    def list_disbursements(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/disbursements", headers=headers, params=params)

    # ─── Distributions ────────────────────────────────────────
    def create_distribution(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/distributions/{distribution_id}", headers=headers)

    def list_account_distributions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/distributions", headers=headers, params=params)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/distributions", headers=headers, params=params)

    def approve_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/approve", {}, headers)

    def reject_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/reject", {}, headers)

    def pay_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/pay", {}, headers)

    def reverse_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/reverse", {}, headers)

    # ─── K-1 statements ───────────────────────────────────────
    def list_account_k1s(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/k1s", headers=headers, params=params)

    def get_k1(self, k1_id, headers):
        return self._request("GET", f"/k1s/{k1_id}", headers=headers)

    def list_k1s(self, headers, params=None):
        return self._request("GET", "/k1s", headers=headers, params=params)

    # ─── Tax filings ──────────────────────────────────────────
    def create_filing(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def list_account_filings(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/filings", headers=headers, params=params)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/filings", headers=headers, params=params)

    def file_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/file", {}, headers)

    def amend_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/amend", {}, headers)

    def refile_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/refile", {}, headers)

    # ─── GST exemption ────────────────────────────────────────
    def create_gst_exemption_allocation(self, trust_id, payload, headers):
        return self._request("POST", f"/trusts/{trust_id}/gst-exemption-allocations", payload, headers)

    def list_trust_gst_exemption_allocations(self, trust_id, headers, params=None):
        return self._request("GET", f"/trusts/{trust_id}/gst-exemption-allocations", headers=headers, params=params)

    def get_gst_exemption_allocation(self, allocation_id, headers):
        return self._request("GET", f"/gst-exemption-allocations/{allocation_id}", headers=headers)

    def list_gst_exemption_allocations(self, headers, params=None):
        return self._request("GET", "/gst-exemption-allocations", headers=headers, params=params)

    def release_gst_exemption_allocation(self, trust_id, allocation_id, headers):
        return self._request("DELETE", f"/trusts/{trust_id}/gst-exemption-allocations/{allocation_id}", headers=headers)

    # ─── GST events ───────────────────────────────────────────
    def list_trust_gst_events(self, trust_id, headers, params=None):
        return self._request("GET", f"/trusts/{trust_id}/gst-events", headers=headers, params=params)

    def get_gst_event(self, event_id, headers):
        return self._request("GET", f"/gst-events/{event_id}", headers=headers)

    def list_gst_events(self, headers, params=None):
        return self._request("GET", "/gst-events", headers=headers, params=params)


api_client = ApiClient()
