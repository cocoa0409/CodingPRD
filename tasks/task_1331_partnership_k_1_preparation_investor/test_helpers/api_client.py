"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Fund ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/funds", payload, headers)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    # --- TaxYear ---
    def create_tax_year(self, payload, headers):
        return self._request("POST", "/funds/tax-years", payload, headers)

    def get_tax_year(self, tax_year_id, headers):
        return self._request("GET", f"/funds/tax-years/{tax_year_id}", headers=headers)

    def list_tax_years(self, headers, params=None):
        return self._request("GET", "/funds/tax-years", headers=headers, params=params)

    def close_books(self, tax_year_id, headers):
        return self._request("POST", f"/funds/tax-years/{tax_year_id}/close-books", {}, headers)

    def submit_tax_year_review(self, tax_year_id, headers):
        return self._request("POST", f"/funds/tax-years/{tax_year_id}/submit-review", {}, headers)

    def approve_tax_year(self, tax_year_id, headers):
        return self._request("POST", f"/funds/tax-years/{tax_year_id}/approve", {}, headers)

    def reopen_tax_year(self, tax_year_id, headers):
        return self._request("POST", f"/funds/tax-years/{tax_year_id}/reopen", {}, headers)

    # --- Partner ---
    def create_partner(self, payload, headers):
        return self._request("POST", "/funds/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/funds/partners/{partner_id}", headers=headers)

    def list_partners(self, headers, params=None):
        return self._request("GET", "/funds/partners", headers=headers, params=params)

    def withdraw_partner(self, partner_id, headers):
        return self._request("POST", f"/funds/partners/{partner_id}/withdraw", {}, headers)

    # --- CapitalAccountEvent ---
    def create_capital_event(self, payload, headers):
        return self._request("POST", "/funds/capital-events", payload, headers)

    def get_capital_event(self, event_id, headers):
        return self._request("GET", f"/funds/capital-events/{event_id}", headers=headers)

    def list_capital_events(self, headers, params=None):
        return self._request("GET", "/funds/capital-events", headers=headers, params=params)

    def reverse_capital_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/funds/capital-events/{event_id}/reverse", payload or {}, headers)

    # --- OwnershipTransfer ---
    def create_transfer(self, payload, headers):
        return self._request("POST", "/funds/transfers", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/funds/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/funds/transfers", headers=headers, params=params)

    def confirm_transfer(self, transfer_id, headers):
        return self._request("POST", f"/funds/transfers/{transfer_id}/confirm", {}, headers)

    def settle_transfer(self, transfer_id, headers):
        return self._request("POST", f"/funds/transfers/{transfer_id}/settle", {}, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/funds/transfers/{transfer_id}/cancel", {}, headers)

    # --- AllocationRun / AllocationLine ---
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/funds/allocation-runs", payload, headers)

    def get_allocation_run(self, run_id, headers):
        return self._request("GET", f"/funds/allocation-runs/{run_id}", headers=headers)

    def list_allocation_runs(self, headers, params=None):
        return self._request("GET", "/funds/allocation-runs", headers=headers, params=params)

    def lock_allocation_run(self, run_id, headers):
        return self._request("POST", f"/funds/allocation-runs/{run_id}/lock", {}, headers)

    def list_run_lines(self, run_id, headers, params=None):
        return self._request("GET", f"/funds/allocation-runs/{run_id}/lines", headers=headers, params=params)

    def list_partner_allocation_lines(self, partner_id, headers, params=None):
        return self._request("GET", f"/funds/partners/{partner_id}/allocation-lines", headers=headers, params=params)

    # --- SpecialAllocation ---
    def create_special_allocation(self, payload, headers):
        return self._request("POST", "/funds/special-allocations", payload, headers)

    def get_special_allocation(self, sa_id, headers):
        return self._request("GET", f"/funds/special-allocations/{sa_id}", headers=headers)

    def list_special_allocations(self, headers, params=None):
        return self._request("GET", "/funds/special-allocations", headers=headers, params=params)

    def approve_special_allocation(self, sa_id, headers):
        return self._request("POST", f"/funds/special-allocations/{sa_id}/approve", {}, headers)

    def reject_special_allocation(self, sa_id, headers):
        return self._request("POST", f"/funds/special-allocations/{sa_id}/reject", {}, headers)

    # --- CompositeFiling ---
    def create_composite_filing(self, payload, headers):
        return self._request("POST", "/funds/composite-filings", payload, headers)

    def get_composite_filing(self, cf_id, headers):
        return self._request("GET", f"/funds/composite-filings/{cf_id}", headers=headers)

    def list_composite_filings(self, headers, params=None):
        return self._request("GET", "/funds/composite-filings", headers=headers, params=params)

    def file_composite_filing(self, cf_id, headers):
        return self._request("POST", f"/funds/composite-filings/{cf_id}/file", {}, headers)

    def record_composite_outcome(self, cf_id, payload, headers):
        return self._request("POST", f"/funds/composite-filings/{cf_id}/record-outcome", payload, headers)

    # --- WithholdingRecord ---
    def create_withholding_accruals(self, payload, headers):
        return self._request("POST", "/funds/withholding-accruals", payload, headers)

    def get_withholding_record(self, wr_id, headers):
        return self._request("GET", f"/funds/withholding-records/{wr_id}", headers=headers)

    def list_withholding_records(self, headers, params=None):
        return self._request("GET", "/funds/withholding-records", headers=headers, params=params)

    def remit_withholding(self, wr_id, payload, headers):
        return self._request("POST", f"/funds/withholding-records/{wr_id}/remit", payload, headers)

    def reconcile_withholding(self, wr_id, headers):
        return self._request("POST", f"/funds/withholding-records/{wr_id}/reconcile", {}, headers)

    # --- K1Package ---
    def generate_k1(self, payload, headers):
        return self._request("POST", "/funds/k1-generation", payload, headers)

    def get_k1_package(self, k1_id, headers):
        return self._request("GET", f"/funds/k1-packages/{k1_id}", headers=headers)

    def list_k1_packages(self, headers, params=None):
        return self._request("GET", "/funds/k1-packages", headers=headers, params=params)

    def submit_k1_review(self, k1_id, headers):
        return self._request("POST", f"/funds/k1-packages/{k1_id}/submit-review", {}, headers)

    def approve_k1(self, k1_id, headers):
        return self._request("POST", f"/funds/k1-packages/{k1_id}/approve", {}, headers)

    def deliver_k1(self, k1_id, payload, headers):
        return self._request("POST", f"/funds/k1-packages/{k1_id}/deliver", payload, headers)

    def acknowledge_k1(self, k1_id, headers):
        return self._request("POST", f"/funds/k1-packages/{k1_id}/acknowledge", {}, headers)

    def report_k1_bounced(self, k1_id, headers, payload=None):
        return self._request("POST", f"/funds/k1-packages/{k1_id}/report-bounced", payload or {}, headers)

    def resend_k1(self, k1_id, headers, payload=None):
        return self._request("POST", f"/funds/k1-packages/{k1_id}/resend", payload or {}, headers)

    # --- K1Amendment ---
    def create_k1_amendment(self, payload, headers):
        return self._request("POST", "/funds/k1-amendments", payload, headers)

    def list_k1_amendments(self, k1_id, headers):
        return self._request("GET", f"/funds/k1-packages/{k1_id}/amendments", headers=headers)

    def start_amendment_prep(self, amendment_id, headers):
        return self._request("POST", f"/funds/k1-amendments/{amendment_id}/start-prep", {}, headers)

    def submit_amendment_review(self, amendment_id, headers):
        return self._request("POST", f"/funds/k1-amendments/{amendment_id}/submit-review", {}, headers)

    def return_amendment_to_prep(self, amendment_id, headers):
        return self._request("POST", f"/funds/k1-amendments/{amendment_id}/return-to-prep", {}, headers)

    def issue_amendment(self, amendment_id, headers):
        return self._request("POST", f"/funds/k1-amendments/{amendment_id}/issue", {}, headers)

    # --- InvestorTicket ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/funds/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/funds/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/funds/tickets", headers=headers, params=params)

    def answer_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/funds/tickets/{ticket_id}/answer", payload, headers)

    def reopen_ticket(self, ticket_id, headers, payload=None):
        return self._request("POST", f"/funds/tickets/{ticket_id}/reopen", payload or {}, headers)

    def close_ticket(self, ticket_id, headers):
        return self._request("POST", f"/funds/tickets/{ticket_id}/close", {}, headers)

    # --- Test-driving logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
