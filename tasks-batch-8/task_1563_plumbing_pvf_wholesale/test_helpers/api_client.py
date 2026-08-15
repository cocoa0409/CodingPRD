"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Branch / catalog administration ----
    def create_branch(self, payload, headers):
        return self._request("POST", "/pvf/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/pvf/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/pvf/branches/{branch_id}", headers=headers)

    def create_product(self, payload, headers):
        return self._request("POST", "/pvf/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/pvf/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/pvf/products/{product_id}", headers=headers)

    def get_product_inventory(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/products/{product_id}/inventory", headers=headers, params=params
        )

    def get_product_order_lines(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/products/{product_id}/order-lines", headers=headers, params=params
        )

    # ---- Contractor accounts / credit / job costing / payments ----
    def create_account(self, payload, headers):
        return self._request("POST", "/pvf/contractor-accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/pvf/contractor-accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/pvf/contractor-accounts/{account_id}", headers=headers)

    def credit_review(self, account_id, payload, headers):
        return self._request(
            "POST", f"/pvf/contractor-accounts/{account_id}/credit-review", payload, headers
        )

    def get_credit_exposure(self, account_id, headers):
        return self._request(
            "GET", f"/pvf/contractor-accounts/{account_id}/credit-exposure", headers=headers
        )

    def get_job_costing(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/contractor-accounts/{account_id}/job-costing",
            headers=headers, params=params,
        )

    def get_account_quotes(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/contractor-accounts/{account_id}/quotes", headers=headers, params=params
        )

    def get_account_sheets(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/contractor-accounts/{account_id}/selection-sheets",
            headers=headers, params=params,
        )

    def get_account_orders(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/contractor-accounts/{account_id}/orders", headers=headers, params=params
        )

    def get_account_payments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/contractor-accounts/{account_id}/payments", headers=headers, params=params
        )

    def create_payment(self, account_id, payload, headers):
        return self._request(
            "POST", f"/pvf/contractor-accounts/{account_id}/payments", payload, headers
        )

    # ---- Inventory & receiving ----
    def create_stock_record(self, branch_id, payload, headers):
        return self._request("POST", f"/pvf/branches/{branch_id}/inventory", payload, headers)

    def list_branch_inventory(self, branch_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/branches/{branch_id}/inventory", headers=headers, params=params
        )

    def create_stock_receipt(self, branch_id, payload, headers):
        return self._request(
            "POST", f"/pvf/branches/{branch_id}/stock-receipts", payload, headers
        )

    def list_stock_receipts(self, branch_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/branches/{branch_id}/stock-receipts", headers=headers, params=params
        )

    def list_branch_orders(self, branch_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/branches/{branch_id}/orders", headers=headers, params=params
        )

    def list_branch_slots(self, branch_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/branches/{branch_id}/delivery-slots", headers=headers, params=params
        )

    # ---- Quotes ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/pvf/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/pvf/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/pvf/quotes/{quote_id}", headers=headers)

    def submit_quote(self, quote_id, headers):
        return self._request("POST", f"/pvf/quotes/{quote_id}/submit", {}, headers)

    def award_quote(self, quote_id, headers):
        return self._request("POST", f"/pvf/quotes/{quote_id}/award", {}, headers)

    def lose_quote(self, quote_id, headers):
        return self._request("POST", f"/pvf/quotes/{quote_id}/lose", {}, headers)

    def create_quote_revision(self, quote_id, payload, headers):
        return self._request("POST", f"/pvf/quotes/{quote_id}/revisions", payload, headers)

    def convert_quote(self, quote_id, headers):
        return self._request("POST", f"/pvf/quotes/{quote_id}/convert", {}, headers)

    def get_quote_orders(self, quote_id, headers, params=None):
        return self._request("GET", f"/pvf/quotes/{quote_id}/orders", headers=headers, params=params)

    # ---- Selection sheets ----
    def create_sheet(self, payload, headers):
        return self._request("POST", "/pvf/selection-sheets", payload, headers)

    def list_sheets(self, headers, params=None):
        return self._request("GET", "/pvf/selection-sheets", headers=headers, params=params)

    def get_sheet(self, sheet_id, headers):
        return self._request("GET", f"/pvf/selection-sheets/{sheet_id}", headers=headers)

    def present_sheet(self, sheet_id, headers):
        return self._request("POST", f"/pvf/selection-sheets/{sheet_id}/present", {}, headers)

    def approve_sheet(self, sheet_id, headers):
        return self._request("POST", f"/pvf/selection-sheets/{sheet_id}/approve", {}, headers)

    def revise_sheet(self, sheet_id, payload, headers):
        return self._request("POST", f"/pvf/selection-sheets/{sheet_id}/revise", payload, headers)

    def convert_sheet(self, sheet_id, headers):
        return self._request("POST", f"/pvf/selection-sheets/{sheet_id}/convert", {}, headers)

    def get_sheet_orders(self, sheet_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/selection-sheets/{sheet_id}/orders", headers=headers, params=params
        )

    # ---- Orders & lines ----
    def create_order(self, payload, headers):
        return self._request("POST", "/pvf/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/pvf/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/lines", payload, headers)

    def get_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/pvf/orders/{order_id}/lines", headers=headers, params=params)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/submit", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/cancel", {}, headers)

    def mark_staged(self, order_id, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/mark-staged", {}, headers)

    def dispatch_order(self, order_id, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/dispatch", {}, headers)

    def confirm_delivery(self, order_id, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/confirm-delivery", {}, headers)

    def pickup_order(self, order_id, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/pickup", {}, headers)

    def book_delivery(self, order_id, payload, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/delivery-booking", payload, headers)

    def cancel_booking(self, order_id, headers):
        return self._request(
            "POST", f"/pvf/orders/{order_id}/delivery-booking/cancel", {}, headers
        )

    def propose_substitute(self, line_id, payload, headers):
        return self._request(
            "POST", f"/pvf/order-lines/{line_id}/propose-substitute", payload, headers
        )

    def substitute_decision(self, line_id, payload, headers):
        return self._request(
            "POST", f"/pvf/order-lines/{line_id}/substitute-decision", payload, headers
        )

    # ---- Kitting ----
    def create_kit(self, order_id, payload, headers):
        return self._request("POST", f"/pvf/orders/{order_id}/kits", payload, headers)

    def get_order_kits(self, order_id, headers, params=None):
        return self._request("GET", f"/pvf/orders/{order_id}/kits", headers=headers, params=params)

    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/pvf/kits/{kit_id}", headers=headers)

    def get_kit_lines(self, kit_id, headers, params=None):
        return self._request("GET", f"/pvf/kits/{kit_id}/lines", headers=headers, params=params)

    def stage_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/pvf/kits/{kit_id}/stage", payload, headers)

    def unstage_kit(self, kit_id, headers):
        return self._request("POST", f"/pvf/kits/{kit_id}/unstage", {}, headers)

    # ---- Delivery slots ----
    def create_delivery_slot(self, branch_id, payload, headers):
        return self._request("POST", f"/pvf/branches/{branch_id}/delivery-slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/pvf/delivery-slots/{slot_id}", headers=headers)

    def cancel_slot(self, slot_id, headers):
        return self._request("POST", f"/pvf/delivery-slots/{slot_id}/cancel", {}, headers)

    def get_slot_orders(self, slot_id, headers, params=None):
        return self._request(
            "GET", f"/pvf/delivery-slots/{slot_id}/orders", headers=headers, params=params
        )

    # ---- Manufacturer stocking programs ----
    def create_program(self, payload, headers):
        return self._request("POST", "/pvf/manufacturer-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/pvf/manufacturer-programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/pvf/manufacturer-programs/{program_id}", headers=headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/pvf/manufacturer-programs/{program_id}/close", {}, headers)

    def settle_program(self, program_id, headers):
        return self._request("POST", f"/pvf/manufacturer-programs/{program_id}/settle", {}, headers)

    # ---- Returns ----
    def create_return(self, payload, headers):
        return self._request("POST", "/pvf/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/pvf/returns/{return_id}", headers=headers)

    def get_order_returns(self, order_id, headers, params=None):
        return self._request("GET", f"/pvf/orders/{order_id}/returns", headers=headers, params=params)

    def submit_return(self, return_id, headers):
        return self._request("POST", f"/pvf/returns/{return_id}/submit", {}, headers)

    def decide_return(self, return_id, payload, headers):
        return self._request("POST", f"/pvf/returns/{return_id}/decision", payload, headers)

    def receive_return(self, return_id, headers):
        return self._request("POST", f"/pvf/returns/{return_id}/receive", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/pvf/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
