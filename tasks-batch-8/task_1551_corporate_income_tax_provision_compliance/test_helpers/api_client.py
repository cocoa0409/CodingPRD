"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PlatformAdmin only)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # TaxYear
    # ------------------------------------------------------------------
    def create_tax_year(self, payload, headers):
        return self._request("POST", "/tax/tax-years", payload, headers)

    def get_tax_year(self, tax_year_id, headers):
        return self._request("GET", f"/tax/tax-years/{tax_year_id}",
                             headers=headers)

    def lock_provision(self, tax_year_id, headers):
        return self._request("POST",
                             f"/tax/tax-years/{tax_year_id}/lock-provision",
                             {}, headers)

    def mark_returns_filed(self, tax_year_id, headers):
        return self._request("POST",
                             f"/tax/tax-years/{tax_year_id}/mark-returns-filed",
                             {}, headers)

    def close_tax_year(self, tax_year_id, headers):
        return self._request("POST", f"/tax/tax-years/{tax_year_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Jurisdiction
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/tax/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/tax/jurisdictions/{jurisdiction_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # BookTaxDifference
    # ------------------------------------------------------------------
    def create_book_tax_difference(self, payload, headers):
        return self._request("POST", "/tax/book-tax-differences", payload,
                             headers)

    def list_book_tax_differences(self, headers, params=None):
        return self._request("GET", "/tax/book-tax-differences",
                             headers=headers, params=params)

    def get_book_tax_difference(self, difference_id, headers):
        return self._request("GET",
                             f"/tax/book-tax-differences/{difference_id}",
                             headers=headers)

    def review_difference(self, difference_id, headers):
        return self._request(
            "POST", f"/tax/book-tax-differences/{difference_id}/review",
            {}, headers)

    def return_difference_for_rework(self, difference_id, headers):
        return self._request(
            "POST",
            f"/tax/book-tax-differences/{difference_id}/return-for-rework",
            {}, headers)

    def lock_difference(self, difference_id, headers):
        return self._request(
            "POST", f"/tax/book-tax-differences/{difference_id}/lock",
            {}, headers)

    def reject_difference(self, difference_id, headers):
        return self._request(
            "POST", f"/tax/book-tax-differences/{difference_id}/reject",
            {}, headers)

    # ------------------------------------------------------------------
    # DeferredTaxItem (system-generated, read-only)
    # ------------------------------------------------------------------
    def list_deferred_tax_items(self, headers, params=None):
        return self._request("GET", "/tax/deferred-tax-items",
                             headers=headers, params=params)

    def get_deferred_tax_item(self, deferred_item_id, headers):
        return self._request("GET",
                             f"/tax/deferred-tax-items/{deferred_item_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # ValuationAllowance
    # ------------------------------------------------------------------
    def create_valuation_allowance(self, payload, headers):
        return self._request("POST", "/tax/valuation-allowances", payload,
                             headers)

    def list_valuation_allowances(self, headers, params=None):
        return self._request("GET", "/tax/valuation-allowances",
                             headers=headers, params=params)

    def get_valuation_allowance(self, allowance_id, headers):
        return self._request("GET",
                             f"/tax/valuation-allowances/{allowance_id}",
                             headers=headers)

    def submit_valuation_allowance(self, allowance_id, headers):
        return self._request(
            "POST", f"/tax/valuation-allowances/{allowance_id}/submit",
            {}, headers)

    def approve_valuation_allowance(self, allowance_id, headers):
        return self._request(
            "POST", f"/tax/valuation-allowances/{allowance_id}/approve",
            {}, headers)

    def return_valuation_allowance(self, allowance_id, headers):
        return self._request(
            "POST", f"/tax/valuation-allowances/{allowance_id}/return",
            {}, headers)

    # ------------------------------------------------------------------
    # UncertainTaxPosition
    # ------------------------------------------------------------------
    def create_uncertain_tax_position(self, payload, headers):
        return self._request("POST", "/tax/uncertain-tax-positions", payload,
                             headers)

    def list_uncertain_tax_positions(self, headers, params=None):
        return self._request("GET", "/tax/uncertain-tax-positions",
                             headers=headers, params=params)

    def get_uncertain_tax_position(self, position_id, headers):
        return self._request("GET",
                             f"/tax/uncertain-tax-positions/{position_id}",
                             headers=headers)

    def measure_position(self, position_id, cumulative_probability_bp,
                         headers):
        return self._request(
            "POST", f"/tax/uncertain-tax-positions/{position_id}/measure",
            {"cumulative_probability_bp": cumulative_probability_bp}, headers)

    def disclose_position(self, position_id, headers):
        return self._request(
            "POST", f"/tax/uncertain-tax-positions/{position_id}/disclose",
            {}, headers)

    def settle_position(self, position_id, settled_amount_cents, headers):
        return self._request(
            "POST", f"/tax/uncertain-tax-positions/{position_id}/settle",
            {"settled_amount_cents": settled_amount_cents}, headers)

    # ------------------------------------------------------------------
    # EstimatedPayment
    # ------------------------------------------------------------------
    def generate_payment_schedule(self, payload, headers):
        return self._request("POST", "/tax/estimated-payments/generate-schedule",
                             payload, headers)

    def create_estimated_payment(self, payload, headers):
        return self._request("POST", "/tax/estimated-payments", payload,
                             headers)

    def list_estimated_payments(self, headers, params=None):
        return self._request("GET", "/tax/estimated-payments",
                             headers=headers, params=params)

    def get_estimated_payment(self, payment_id, headers):
        return self._request("GET", f"/tax/estimated-payments/{payment_id}",
                             headers=headers)

    def record_payment(self, payment_id, amount_cents, headers):
        return self._request(
            "POST", f"/tax/estimated-payments/{payment_id}/record-payment",
            {"amount_cents": amount_cents}, headers)

    def reverse_payment(self, payment_id, amount_cents, headers):
        return self._request(
            "POST", f"/tax/estimated-payments/{payment_id}/reverse-payment",
            {"amount_cents": amount_cents}, headers)

    # ------------------------------------------------------------------
    # Filing
    # ------------------------------------------------------------------
    def create_filing(self, payload, headers):
        return self._request("POST", "/tax/filings", payload, headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/tax/filings", headers=headers,
                             params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/tax/filings/{filing_id}",
                             headers=headers)

    def mark_filing_ready(self, filing_id, return_tax_liability_cents,
                          headers):
        return self._request(
            "POST", f"/tax/filings/{filing_id}/mark-ready",
            {"return_tax_liability_cents": return_tax_liability_cents},
            headers)

    def file_filing(self, filing_id, expected_tax_year_version, headers):
        return self._request(
            "POST", f"/tax/filings/{filing_id}/file",
            {"expected_tax_year_version": expected_tax_year_version}, headers)

    def accept_filing(self, filing_id, headers):
        return self._request("POST", f"/tax/filings/{filing_id}/accept",
                             {}, headers)

    def reject_filing(self, filing_id, rejection_reason, headers):
        return self._request("POST", f"/tax/filings/{filing_id}/reject",
                             {"rejection_reason": rejection_reason}, headers)

    def amend_filing(self, filing_id, return_tax_liability_cents, headers):
        return self._request(
            "POST", f"/tax/filings/{filing_id}/amend",
            {"return_tax_liability_cents": return_tax_liability_cents},
            headers)

    def request_extension(self, filing_id, headers):
        return self._request(
            "POST", f"/tax/filings/{filing_id}/request-extension", {}, headers)

    def resolve_extension(self, filing_id, decision, headers):
        return self._request(
            "POST", f"/tax/filings/{filing_id}/resolve-extension",
            {"decision": decision}, headers)

    # ------------------------------------------------------------------
    # TaxNotice
    # ------------------------------------------------------------------
    def create_notice(self, payload, headers):
        return self._request("POST", "/tax/notices", payload, headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/tax/notices", headers=headers,
                             params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/tax/notices/{notice_id}",
                             headers=headers)

    def assign_notice_review(self, notice_id, headers):
        return self._request(
            "POST", f"/tax/notices/{notice_id}/assign-review", {}, headers)

    def respond_to_notice(self, notice_id, response_text, headers):
        return self._request("POST", f"/tax/notices/{notice_id}/respond",
                             {"response_text": response_text}, headers)

    def resolve_notice(self, notice_id, headers):
        return self._request("POST", f"/tax/notices/{notice_id}/resolve",
                             {}, headers)

    # ------------------------------------------------------------------
    # AuditCase
    # ------------------------------------------------------------------
    def create_audit(self, payload, headers):
        return self._request("POST", "/tax/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/tax/audits", headers=headers,
                             params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/tax/audits/{audit_id}", headers=headers)

    def propose_adjustment(self, audit_id, proposed_adjustment_cents, headers):
        return self._request(
            "POST", f"/tax/audits/{audit_id}/propose-adjustment",
            {"proposed_adjustment_cents": proposed_adjustment_cents}, headers)

    def negotiate_audit(self, audit_id, headers):
        return self._request("POST", f"/tax/audits/{audit_id}/negotiate",
                             {}, headers)

    def revise_adjustment(self, audit_id, proposed_adjustment_cents, headers):
        return self._request(
            "POST", f"/tax/audits/{audit_id}/revise-adjustment",
            {"proposed_adjustment_cents": proposed_adjustment_cents}, headers)

    def close_audit(self, audit_id, outcome, headers,
                    agreed_adjustment_cents=None):
        payload = {"outcome": outcome}
        if agreed_adjustment_cents is not None:
            payload["agreed_adjustment_cents"] = agreed_adjustment_cents
        return self._request("POST", f"/tax/audits/{audit_id}/close", payload,
                             headers)


api_client = ApiClient()
