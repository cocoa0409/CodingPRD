"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving capability) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Fund ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/funds", payload, headers)

    def get_trial_balance(self, fund_id, headers, params=None):
        return self._request(
            "GET", f"/funds/{fund_id}/trial-balance", headers=headers, params=params
        )

    def close_fiscal_year(self, fund_id, payload, headers):
        return self._request(
            "POST", f"/funds/{fund_id}/fiscal-year-close", payload, headers
        )

    # --- ShareClass ---
    def create_share_class(self, payload, headers):
        return self._request("POST", "/share-classes", payload, headers)

    def get_share_class(self, share_class_id, headers):
        return self._request(
            "GET", f"/share-classes/{share_class_id}", headers=headers
        )

    def list_share_classes(self, headers, params=None):
        return self._request("GET", "/share-classes", headers=headers, params=params)

    def post_capital_activity(self, share_class_id, payload, headers):
        return self._request(
            "POST",
            f"/share-classes/{share_class_id}/capital-activity",
            payload,
            headers,
        )

    def get_performance(self, share_class_id, headers, params=None):
        return self._request(
            "GET",
            f"/share-classes/{share_class_id}/performance",
            headers=headers,
            params=params,
        )

    # --- Security ---
    def create_security(self, payload, headers):
        return self._request("POST", "/securities", payload, headers)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/securities/{security_id}", headers=headers)

    def list_security_prices(self, security_id, headers, params=None):
        return self._request(
            "GET", f"/securities/{security_id}/prices", headers=headers, params=params
        )

    # --- Position ---
    def create_position(self, payload, headers):
        return self._request("POST", "/positions", payload, headers)

    def get_position(self, position_id, headers):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/positions", headers=headers, params=params)

    # --- PriceObservation ---
    def create_price_observation(self, payload, headers):
        return self._request("POST", "/price-observations", payload, headers)

    def approve_price_observation(self, price_observation_id, headers):
        return self._request(
            "POST",
            f"/price-observations/{price_observation_id}/approve",
            {},
            headers,
        )

    def override_price_observation(self, price_observation_id, payload, headers):
        return self._request(
            "POST",
            f"/price-observations/{price_observation_id}/override",
            payload,
            headers,
        )

    # --- NavRecord ---
    def create_nav_record(self, payload, headers):
        return self._request("POST", "/nav-records", payload, headers)

    def get_nav_record(self, nav_record_id, headers):
        return self._request("GET", f"/nav-records/{nav_record_id}", headers=headers)

    def list_nav_records(self, headers, params=None):
        return self._request("GET", "/nav-records", headers=headers, params=params)

    def finalize_nav_record(self, nav_record_id, payload, headers):
        return self._request(
            "POST", f"/nav-records/{nav_record_id}/finalize", payload, headers
        )

    def reopen_nav_record(self, nav_record_id, headers):
        return self._request(
            "POST", f"/nav-records/{nav_record_id}/reopen", {}, headers
        )

    # --- ExpenseAccrual ---
    def create_expense_accrual(self, payload, headers):
        return self._request("POST", "/expense-accruals", payload, headers)

    def get_expense_accrual(self, expense_accrual_id, headers):
        return self._request(
            "GET", f"/expense-accruals/{expense_accrual_id}", headers=headers
        )

    def list_expense_accruals(self, headers, params=None):
        return self._request("GET", "/expense-accruals", headers=headers, params=params)

    # --- WaiverAgreement / WaiverLedgerEntry ---
    def create_waiver_agreement(self, payload, headers):
        return self._request("POST", "/waiver-agreements", payload, headers)

    def list_waiver_agreements(self, headers, params=None):
        return self._request(
            "GET", "/waiver-agreements", headers=headers, params=params
        )

    def get_waiver_agreement(self, waiver_agreement_id, headers):
        return self._request(
            "GET", f"/waiver-agreements/{waiver_agreement_id}", headers=headers
        )

    def post_recoupment(self, waiver_agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/waiver-agreements/{waiver_agreement_id}/recoupments",
            payload,
            headers,
        )

    def list_waiver_ledger(self, waiver_agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/waiver-agreements/{waiver_agreement_id}/ledger",
            headers=headers,
            params=params,
        )

    # --- Distribution ---
    def create_distribution(self, payload, headers):
        return self._request("POST", "/distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/distributions/{distribution_id}", headers=headers
        )

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/distributions", headers=headers, params=params)

    def pay_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"/distributions/{distribution_id}/pay", payload, headers
        )

    def cancel_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/distributions/{distribution_id}/cancel", {}, headers
        )

    # --- ReconciliationBreak ---
    def create_reconciliation_break(self, payload, headers):
        return self._request("POST", "/reconciliation-breaks", payload, headers)

    def get_reconciliation_break(self, reconciliation_break_id, headers):
        return self._request(
            "GET",
            f"/reconciliation-breaks/{reconciliation_break_id}",
            headers=headers,
        )

    def list_reconciliation_breaks(self, headers, params=None):
        return self._request(
            "GET", "/reconciliation-breaks", headers=headers, params=params
        )

    def resolve_reconciliation_break(self, reconciliation_break_id, payload, headers):
        return self._request(
            "POST",
            f"/reconciliation-breaks/{reconciliation_break_id}/resolve",
            payload,
            headers,
        )

    def reopen_reconciliation_break(self, reconciliation_break_id, headers):
        return self._request(
            "POST",
            f"/reconciliation-breaks/{reconciliation_break_id}/reopen",
            {},
            headers,
        )

    def escalate_overdue_breaks(self, headers):
        return self._request(
            "POST", "/reconciliation-breaks/escalate-overdue", {}, headers
        )

    # --- FeeInvoice ---
    def create_fee_invoice(self, payload, headers):
        return self._request("POST", "/fee-invoices", payload, headers)

    def get_fee_invoice(self, fee_invoice_id, headers):
        return self._request("GET", f"/fee-invoices/{fee_invoice_id}", headers=headers)

    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/fee-invoices", headers=headers, params=params)

    def approve_fee_invoice(self, fee_invoice_id, headers):
        return self._request(
            "POST", f"/fee-invoices/{fee_invoice_id}/approve", {}, headers
        )

    def pay_fee_invoice(self, fee_invoice_id, headers):
        return self._request(
            "POST", f"/fee-invoices/{fee_invoice_id}/pay", {}, headers
        )

    # --- RegulatoryFiling ---
    def create_regulatory_filing(self, payload, headers):
        return self._request("POST", "/regulatory-filings", payload, headers)

    def get_regulatory_filing(self, regulatory_filing_id, headers):
        return self._request(
            "GET", f"/regulatory-filings/{regulatory_filing_id}", headers=headers
        )

    def list_regulatory_filings(self, headers, params=None):
        return self._request(
            "GET", "/regulatory-filings", headers=headers, params=params
        )

    def submit_filing_review(self, regulatory_filing_id, headers):
        return self._request(
            "POST",
            f"/regulatory-filings/{regulatory_filing_id}/submit-review",
            {},
            headers,
        )

    def approve_regulatory_filing(self, regulatory_filing_id, headers):
        return self._request(
            "POST", f"/regulatory-filings/{regulatory_filing_id}/approve", {}, headers
        )

    def file_regulatory_filing(self, regulatory_filing_id, headers):
        return self._request(
            "POST", f"/regulatory-filings/{regulatory_filing_id}/file", {}, headers
        )

    def amend_regulatory_filing(self, regulatory_filing_id, headers):
        return self._request(
            "POST", f"/regulatory-filings/{regulatory_filing_id}/amend", {}, headers
        )


api_client = ApiClient()
