"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and daily sweep (LibraryAdmin system capabilities)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/library/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/library/_sweep/run_daily", {}, headers)

    # ------------------------------------------------------------------
    # Publishers
    # ------------------------------------------------------------------
    def create_publisher(self, payload, headers):
        return self._request("POST", "/library/publishers", payload, headers)

    def list_publishers(self, headers, params=None):
        return self._request("GET", "/library/publishers", headers=headers, params=params)

    def get_publisher(self, publisher_id, headers):
        return self._request("GET", f"/library/publishers/{publisher_id}", headers=headers)

    def patch_publisher(self, publisher_id, payload, headers):
        return self._request("PATCH", f"/library/publishers/{publisher_id}", payload, headers)

    # ------------------------------------------------------------------
    # Works
    # ------------------------------------------------------------------
    def create_work(self, payload, headers):
        return self._request("POST", "/library/works", payload, headers)

    def list_works(self, headers, params=None):
        return self._request("GET", "/library/works", headers=headers, params=params)

    def get_work(self, work_id, headers):
        return self._request("GET", f"/library/works/{work_id}", headers=headers)

    def get_sourcing_quote(self, work_id, headers):
        return self._request("GET", f"/library/works/{work_id}/sourcing-quote",
                             headers=headers)

    def patch_work(self, work_id, payload, headers):
        return self._request("PATCH", f"/library/works/{work_id}", payload, headers)

    # ------------------------------------------------------------------
    # Rental sets
    # ------------------------------------------------------------------
    def create_rental_set(self, payload, headers):
        return self._request("POST", "/library/rental-sets", payload, headers)

    def list_rental_sets(self, headers, params=None):
        return self._request("GET", "/library/rental-sets", headers=headers, params=params)

    def get_rental_set(self, rental_set_id, headers):
        return self._request("GET", f"/library/rental-sets/{rental_set_id}", headers=headers)

    def patch_rental_set(self, rental_set_id, payload, headers):
        return self._request("PATCH", f"/library/rental-sets/{rental_set_id}", payload, headers)

    # ------------------------------------------------------------------
    # Customer accounts
    # ------------------------------------------------------------------
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/library/customer-accounts", payload, headers)

    def list_customer_accounts(self, headers, params=None):
        return self._request("GET", "/library/customer-accounts", headers=headers, params=params)

    def get_customer_account(self, account_id, headers):
        return self._request("GET", f"/library/customer-accounts/{account_id}",
                             headers=headers)

    def create_credit_adjustment(self, account_id, payload, headers):
        return self._request("POST",
                             f"/library/customer-accounts/{account_id}/credit-adjustments",
                             payload, headers)

    def bar_account(self, account_id, headers):
        return self._request("POST", f"/library/customer-accounts/{account_id}/bar",
                             {}, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/library/customer-accounts/{account_id}/reinstate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Purchase orders
    # ------------------------------------------------------------------
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/library/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/library/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/library/purchase-orders/{po_id}", headers=headers)

    def approve_purchase_order(self, po_id, headers):
        return self._request("POST", f"/library/purchase-orders/{po_id}/approve", {}, headers)

    def reject_purchase_order(self, po_id, headers):
        return self._request("POST", f"/library/purchase-orders/{po_id}/reject", {}, headers)

    def close_purchase_order(self, po_id, headers):
        return self._request("POST", f"/library/purchase-orders/{po_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Rental orders
    # ------------------------------------------------------------------
    def create_rental_order(self, payload, headers):
        return self._request("POST", "/library/rental-orders", payload, headers)

    def list_rental_orders(self, headers, params=None):
        return self._request("GET", "/library/rental-orders", headers=headers, params=params)

    def get_rental_order(self, order_id, headers):
        return self._request("GET", f"/library/rental-orders/{order_id}", headers=headers)

    def get_settlement_preview(self, order_id, headers):
        return self._request("GET", f"/library/rental-orders/{order_id}/settlement-preview",
                             headers=headers)

    def reserve_rental_order(self, order_id, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/reserve", {}, headers)

    def dispatch_rental_order(self, order_id, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/dispatch", {}, headers)

    def confirm_receipt(self, order_id, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/confirm-receipt",
                             {}, headers)

    def renew_rental_order(self, order_id, expected_rental_order_version, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/renew",
                             {"expected_rental_order_version": expected_rental_order_version},
                             headers)

    def check_in_rental_order(self, order_id, line_grades, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/check-in",
                             {"line_grades": line_grades}, headers)

    def dispute_rental_order(self, order_id, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/dispute", {}, headers)

    def resolve_dispute_rental_order(self, order_id, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/resolve-dispute",
                             {}, headers)

    def settle_rental_order(self, order_id, headers, topup_cents=None):
        payload = {}
        if topup_cents is not None:
            payload["topup_cents"] = topup_cents
        return self._request("POST", f"/library/rental-orders/{order_id}/settle",
                             payload, headers)

    def cancel_rental_order(self, order_id, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/cancel", {}, headers)

    def record_prepayment(self, order_id, amount_cents, headers):
        return self._request("POST", f"/library/rental-orders/{order_id}/prepayments",
                             {"amount_cents": amount_cents}, headers)

    # ------------------------------------------------------------------
    # Rental lines
    # ------------------------------------------------------------------
    def list_rental_lines(self, headers, params=None):
        return self._request("GET", "/library/rental-lines", headers=headers, params=params)

    def get_rental_line(self, line_id, headers):
        return self._request("GET", f"/library/rental-lines/{line_id}", headers=headers)

    def report_line_lost(self, line_id, headers):
        return self._request("POST", f"/library/rental-lines/{line_id}/report-lost",
                             {}, headers)

    # ------------------------------------------------------------------
    # Condition reports
    # ------------------------------------------------------------------
    def create_condition_report(self, payload, headers):
        return self._request("POST", "/library/condition-reports", payload, headers)

    def list_condition_reports(self, headers, params=None):
        return self._request("GET", "/library/condition-reports", headers=headers,
                             params=params)

    def get_condition_report(self, report_id, headers):
        return self._request("GET", f"/library/condition-reports/{report_id}", headers=headers)

    # ------------------------------------------------------------------
    # Damage invoices
    # ------------------------------------------------------------------
    def create_damage_invoice(self, payload, headers):
        return self._request("POST", "/library/damage-invoices", payload, headers)

    def list_damage_invoices(self, headers, params=None):
        return self._request("GET", "/library/damage-invoices", headers=headers, params=params)

    def get_damage_invoice(self, invoice_id, headers):
        return self._request("GET", f"/library/damage-invoices/{invoice_id}", headers=headers)

    def issue_damage_invoice(self, invoice_id, headers):
        return self._request("POST", f"/library/damage-invoices/{invoice_id}/issue",
                             {}, headers)

    def record_invoice_payment(self, invoice_id, headers):
        return self._request("POST", f"/library/damage-invoices/{invoice_id}/record-payment",
                             {}, headers)

    def resolve_damage_invoice(self, invoice_id, resolution, headers):
        return self._request("POST", f"/library/damage-invoices/{invoice_id}/resolve",
                             {"resolution": resolution}, headers)

    def reissue_damage_invoice(self, invoice_id, new_condition_report_id, headers):
        return self._request("POST", f"/library/damage-invoices/{invoice_id}/reissue",
                             {"new_condition_report_id": new_condition_report_id}, headers)

    # ------------------------------------------------------------------
    # Perusal requests
    # ------------------------------------------------------------------
    def create_perusal_request(self, payload, headers):
        return self._request("POST", "/library/perusal-requests", payload, headers)

    def list_perusal_requests(self, headers, params=None):
        return self._request("GET", "/library/perusal-requests", headers=headers, params=params)

    def get_perusal_request(self, perusal_id, headers):
        return self._request("GET", f"/library/perusal-requests/{perusal_id}", headers=headers)

    def approve_perusal_request(self, perusal_id, headers):
        return self._request("POST", f"/library/perusal-requests/{perusal_id}/approve",
                             {}, headers)

    def reject_perusal_request(self, perusal_id, headers):
        return self._request("POST", f"/library/perusal-requests/{perusal_id}/reject",
                             {}, headers)

    def ship_perusal_request(self, perusal_id, headers):
        return self._request("POST", f"/library/perusal-requests/{perusal_id}/ship",
                             {}, headers)

    def record_perusal_return(self, perusal_id, headers):
        return self._request("POST", f"/library/perusal-requests/{perusal_id}/record-return",
                             {}, headers)

    def convert_perusal_request(self, perusal_id, payload, headers):
        return self._request("POST", f"/library/perusal-requests/{perusal_id}/convert",
                             payload, headers)

    # ------------------------------------------------------------------
    # Sale records
    # ------------------------------------------------------------------
    def create_sale_record(self, payload, headers):
        return self._request("POST", "/library/sale-records", payload, headers)

    def list_sale_records(self, headers, params=None):
        return self._request("GET", "/library/sale-records", headers=headers, params=params)

    def get_sale_record(self, sale_id, headers):
        return self._request("GET", f"/library/sale-records/{sale_id}", headers=headers)

    def record_sale_payment(self, sale_id, headers):
        return self._request("POST", f"/library/sale-records/{sale_id}/record-payment",
                             {}, headers)

    def write_off_sale(self, sale_id, headers):
        return self._request("POST", f"/library/sale-records/{sale_id}/write-off", {}, headers)

    # ------------------------------------------------------------------
    # Rights advisory cases
    # ------------------------------------------------------------------
    def create_rights_case(self, payload, headers):
        return self._request("POST", "/library/rights-advisory-cases", payload, headers)

    def list_rights_cases(self, headers, params=None):
        return self._request("GET", "/library/rights-advisory-cases", headers=headers,
                             params=params)

    def get_rights_case(self, case_id, headers):
        return self._request("GET", f"/library/rights-advisory-cases/{case_id}",
                             headers=headers)

    def decide_rights_case(self, case_id, determination, headers):
        return self._request("POST", f"/library/rights-advisory-cases/{case_id}/decide",
                             {"determination": determination}, headers)

    def withdraw_rights_case(self, case_id, headers):
        return self._request("POST", f"/library/rights-advisory-cases/{case_id}/withdraw",
                             {}, headers)


api_client = ApiClient()
