"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Contractor accounts (PRD §3.1) ---
    def create_contractor_account(self, payload, headers):
        return self._request("POST", "/contractor-accounts", payload, headers)

    def get_contractor_account(self, account_id, headers):
        return self._request("GET", f"/contractor-accounts/{account_id}", headers=headers)

    def patch_contractor_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/contractor-accounts/{account_id}", payload, headers)

    def suspend_contractor_account(self, account_id, headers):
        return self._request("POST", f"/contractor-accounts/{account_id}/suspend", {}, headers)

    def reinstate_contractor_account(self, account_id, headers):
        return self._request("POST", f"/contractor-accounts/{account_id}/reinstate", {}, headers)

    def evaluate_tier(self, account_id, headers):
        return self._request("POST", f"/contractor-accounts/{account_id}/evaluate-tier", {}, headers)

    # --- Job accounts (PRD §3.2) ---
    def create_job_account(self, payload, headers):
        return self._request("POST", "/job-accounts", payload, headers)

    def get_job_account(self, job_id, headers):
        return self._request("GET", f"/job-accounts/{job_id}", headers=headers)

    def list_job_accounts(self, headers, params=None):
        return self._request("GET", "/job-accounts", headers=headers, params=params)

    def place_job_on_hold(self, job_id, headers):
        return self._request("POST", f"/job-accounts/{job_id}/place-on-hold", {}, headers)

    def resume_job(self, job_id, headers):
        return self._request("POST", f"/job-accounts/{job_id}/resume", {}, headers)

    def complete_job(self, job_id, headers):
        return self._request("POST", f"/job-accounts/{job_id}/complete", {}, headers)

    # --- Jurisdictions and VOC rules (PRD §3.3) ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def create_voc_rule(self, payload, headers):
        return self._request("POST", "/voc-rules", payload, headers)

    def list_voc_rules(self, headers, params=None):
        return self._request("GET", "/voc-rules", headers=headers, params=params)

    def get_voc_rule(self, rule_id, headers):
        return self._request("GET", f"/voc-rules/{rule_id}", headers=headers)

    # --- Products (PRD §3.3) ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    # --- Tint formulas (PRD §3.4) ---
    def create_tint_formula(self, payload, headers):
        return self._request("POST", "/tint-formulas", payload, headers)

    def list_tint_formulas(self, headers, params=None):
        return self._request("GET", "/tint-formulas", headers=headers, params=params)

    def get_tint_formula(self, formula_id, headers):
        return self._request("GET", f"/tint-formulas/{formula_id}", headers=headers)

    def retire_tint_formula(self, formula_id, headers):
        return self._request("POST", f"/tint-formulas/{formula_id}/retire", {}, headers)

    # --- Product bulletins (PRD §3.3) ---
    def create_product_bulletin(self, payload, headers):
        return self._request("POST", "/product-bulletins", payload, headers)

    def list_product_bulletins(self, headers, params=None):
        return self._request("GET", "/product-bulletins", headers=headers, params=params)

    def get_product_bulletin(self, bulletin_id, headers):
        return self._request("GET", f"/product-bulletins/{bulletin_id}", headers=headers)

    def publish_product_bulletin(self, bulletin_id, headers):
        return self._request("POST", f"/product-bulletins/{bulletin_id}/publish", {}, headers)

    def take_effect_product_bulletin(self, bulletin_id, headers):
        return self._request("POST", f"/product-bulletins/{bulletin_id}/take-effect", {}, headers)

    # --- Color match requests (PRD §3.4) ---
    def create_color_match_request(self, payload, headers):
        return self._request("POST", "/color-match-requests", payload, headers)

    def get_color_match_request(self, request_id, headers):
        return self._request("GET", f"/color-match-requests/{request_id}", headers=headers)

    def list_color_match_requests(self, headers, params=None):
        return self._request("GET", "/color-match-requests", headers=headers, params=params)

    def create_match_proposal(self, request_id, payload, headers):
        return self._request("POST", f"/color-match-requests/{request_id}/proposals", payload, headers)

    def approve_match_request(self, request_id, headers):
        return self._request("POST", f"/color-match-requests/{request_id}/approve", {}, headers)

    def request_match_revision(self, request_id, headers):
        return self._request("POST", f"/color-match-requests/{request_id}/request-revision", {}, headers)

    def abandon_match_request(self, request_id, headers):
        return self._request("POST", f"/color-match-requests/{request_id}/abandon", {}, headers)

    # --- Orders (PRD §3.6) ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # --- Order lines and returns (PRD §3.7) ---
    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def return_order_line(self, line_id, payload, headers):
        return self._request("POST", f"/order-lines/{line_id}/return", payload, headers)

    def list_return_records(self, headers, params=None):
        return self._request("GET", "/return-records", headers=headers, params=params)

    def get_return_record(self, record_id, headers):
        return self._request("GET", f"/return-records/{record_id}", headers=headers)

    # --- Deliveries (PRD §3.8) ---
    def create_delivery(self, payload, headers):
        return self._request("POST", "/deliveries", payload, headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def dispatch_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/dispatch", {}, headers)

    def mark_delivery_delivered(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/mark-delivered", {}, headers)

    def mark_delivery_failed(self, delivery_id, payload, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/mark-failed", payload, headers)

    # --- Spec sheets (PRD §3.5) ---
    def create_spec_sheet(self, payload, headers):
        return self._request("POST", "/spec-sheets", payload, headers)

    def get_spec_sheet(self, sheet_id, headers):
        return self._request("GET", f"/spec-sheets/{sheet_id}", headers=headers)

    def list_spec_sheets(self, headers, params=None):
        return self._request("GET", "/spec-sheets", headers=headers, params=params)

    def submit_spec_sheet(self, sheet_id, headers):
        return self._request("POST", f"/spec-sheets/{sheet_id}/submit", {}, headers)

    def approve_spec_sheet(self, sheet_id, headers):
        return self._request("POST", f"/spec-sheets/{sheet_id}/approve", {}, headers)

    def reject_spec_sheet(self, sheet_id, payload, headers):
        return self._request("POST", f"/spec-sheets/{sheet_id}/reject", payload, headers)

    def revise_spec_sheet(self, sheet_id, payload, headers):
        return self._request("POST", f"/spec-sheets/{sheet_id}/revise", payload, headers)

    def list_spec_lines(self, headers, params=None):
        return self._request("GET", "/spec-lines", headers=headers, params=params)

    def get_spec_line(self, line_id, headers):
        return self._request("GET", f"/spec-lines/{line_id}", headers=headers)

    # --- Rebate statements (PRD §3.9) ---
    def create_rebate_statement(self, payload, headers):
        return self._request("POST", "/rebate-statements", payload, headers)

    def list_rebate_statements(self, headers, params=None):
        return self._request("GET", "/rebate-statements", headers=headers, params=params)

    def get_rebate_statement(self, statement_id, headers):
        return self._request("GET", f"/rebate-statements/{statement_id}", headers=headers)

    def finalize_rebate_statement(self, statement_id, headers):
        return self._request("POST", f"/rebate-statements/{statement_id}/finalize", {}, headers)

    def dispute_rebate_statement(self, statement_id, headers):
        return self._request("POST", f"/rebate-statements/{statement_id}/dispute", {}, headers)

    def resolve_rebate_dispute(self, statement_id, payload, headers):
        return self._request("POST", f"/rebate-statements/{statement_id}/resolve-dispute", payload, headers)

    def pay_rebate_statement(self, statement_id, headers):
        return self._request("POST", f"/rebate-statements/{statement_id}/pay", {}, headers)

    # --- Loyalty (PRD §3.7) ---
    def create_loyalty_redemption(self, payload, headers):
        return self._request("POST", "/loyalty-redemptions", payload, headers)

    def list_loyalty_transactions(self, headers, params=None):
        return self._request("GET", "/loyalty-transactions", headers=headers, params=params)

    def get_loyalty_transaction(self, txn_id, headers):
        return self._request("GET", f"/loyalty-transactions/{txn_id}", headers=headers)

    # --- Mistint listings (PRD §3.9) ---
    def create_mistint_listing(self, payload, headers):
        return self._request("POST", "/mistint-listings", payload, headers)

    def list_mistint_listings(self, headers, params=None):
        return self._request("GET", "/mistint-listings", headers=headers, params=params)

    def get_mistint_listing(self, listing_id, headers):
        return self._request("GET", f"/mistint-listings/{listing_id}", headers=headers)

    def mark_mistint_sold(self, listing_id, payload, headers):
        return self._request("POST", f"/mistint-listings/{listing_id}/mark-sold", payload, headers)

    def write_off_mistint(self, listing_id, headers):
        return self._request("POST", f"/mistint-listings/{listing_id}/write-off", {}, headers)


api_client = ApiClient()
