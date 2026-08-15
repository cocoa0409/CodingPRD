"""API client: one method per endpoint defined in the PRD (all under /pool-supply)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/pool-supply/_clock/set_current_utc", payload, headers)

    # --- Branches ---
    def create_branch(self, payload, headers):
        return self._request("POST", "/pool-supply/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/pool-supply/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/pool-supply/branches/{branch_id}", headers=headers)

    def close_branch_season(self, branch_id, headers):
        return self._request("POST", f"/pool-supply/branches/{branch_id}/close-season", {}, headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/pool-supply/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/pool-supply/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/pool-supply/accounts/{account_id}", headers=headers)

    def patch_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/pool-supply/accounts/{account_id}", payload, headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/pool-supply/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/pool-supply/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/pool-supply/products/{product_id}", headers=headers)

    # --- Stock lots ---
    def create_stock_lot(self, payload, headers):
        return self._request("POST", "/pool-supply/stock-lots", payload, headers)

    def list_stock_lots(self, headers, params=None):
        return self._request("GET", "/pool-supply/stock-lots", headers=headers, params=params)

    def get_stock_lot(self, lot_id, headers):
        return self._request("GET", f"/pool-supply/stock-lots/{lot_id}", headers=headers)

    def replenish_stock_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/pool-supply/stock-lots/{lot_id}/replenish", payload, headers)

    # --- Seasonal programs ---
    def create_seasonal_program(self, payload, headers):
        return self._request("POST", "/pool-supply/seasonal-programs", payload, headers)

    def list_seasonal_programs(self, headers, params=None):
        return self._request("GET", "/pool-supply/seasonal-programs", headers=headers, params=params)

    def get_seasonal_program(self, program_id, headers):
        return self._request("GET", f"/pool-supply/seasonal-programs/{program_id}", headers=headers)

    def open_seasonal_program(self, program_id, headers):
        return self._request("POST", f"/pool-supply/seasonal-programs/{program_id}/open", {}, headers)

    def close_seasonal_program(self, program_id, headers):
        return self._request("POST", f"/pool-supply/seasonal-programs/{program_id}/close", {}, headers)

    # --- Seasonal commitments ---
    def create_seasonal_commitment(self, payload, headers):
        return self._request("POST", "/pool-supply/seasonal-commitments", payload, headers)

    def list_seasonal_commitments(self, headers, params=None):
        return self._request("GET", "/pool-supply/seasonal-commitments", headers=headers, params=params)

    def get_seasonal_commitment(self, commitment_id, headers):
        return self._request("GET", f"/pool-supply/seasonal-commitments/{commitment_id}", headers=headers)

    # --- Sales orders / order lines ---
    def create_order(self, payload, headers):
        return self._request("POST", "/pool-supply/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/pool-supply/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/pool-supply/orders/{order_id}", headers=headers)

    def list_order_lines_flat(self, headers, params=None):
        return self._request("GET", "/pool-supply/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/pool-supply/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/pool-supply/orders/{order_id}/lines", headers=headers, params=params)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/pool-supply/orders/{order_id}/confirm", payload, headers)

    def mark_order_loaded(self, order_id, headers):
        return self._request("POST", f"/pool-supply/orders/{order_id}/mark-loaded", {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/pool-supply/orders/{order_id}/complete", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/pool-supply/orders/{order_id}/cancel", {}, headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/pool-supply/orders/{order_id}/invoice", {}, headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/pool-supply/orders/{order_id}/pay", {}, headers)

    # --- Backorder requests ---
    def list_backorder_requests(self, headers, params=None):
        return self._request("GET", "/pool-supply/backorder-requests", headers=headers, params=params)

    def get_backorder_request(self, backorder_id, headers):
        return self._request("GET", f"/pool-supply/backorder-requests/{backorder_id}", headers=headers)

    def allocate_backorder(self, backorder_id, payload, headers):
        return self._request("POST", f"/pool-supply/backorder-requests/{backorder_id}/allocate", payload, headers)

    def cancel_backorder(self, backorder_id, headers):
        return self._request("POST", f"/pool-supply/backorder-requests/{backorder_id}/cancel", {}, headers)

    # --- Service centers ---
    def create_service_center(self, payload, headers):
        return self._request("POST", "/pool-supply/service-centers", payload, headers)

    def list_service_centers(self, headers, params=None):
        return self._request("GET", "/pool-supply/service-centers", headers=headers, params=params)

    def get_service_center(self, center_id, headers):
        return self._request("GET", f"/pool-supply/service-centers/{center_id}", headers=headers)

    def patch_service_center(self, center_id, payload, headers):
        return self._request("PATCH", f"/pool-supply/service-centers/{center_id}", payload, headers)

    # --- Warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/pool-supply/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/pool-supply/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/pool-supply/warranty-claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/pool-supply/warranty-claims/{claim_id}/start-review", {}, headers)

    def request_claim_info(self, claim_id, headers):
        return self._request("POST", f"/pool-supply/warranty-claims/{claim_id}/request-info", {}, headers)

    def supply_claim_info(self, claim_id, payload, headers):
        return self._request("POST", f"/pool-supply/warranty-claims/{claim_id}/supply-info", payload, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/pool-supply/warranty-claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/pool-supply/warranty-claims/{claim_id}/reject", {}, headers)

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/pool-supply/warranty-claims/{claim_id}/resolve", payload, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/pool-supply/warranty-claims/{claim_id}/close", {}, headers)

    # --- Return authorizations ---
    def create_return_authorization(self, payload, headers):
        return self._request("POST", "/pool-supply/return-authorizations", payload, headers)

    def list_return_authorizations(self, headers, params=None):
        return self._request("GET", "/pool-supply/return-authorizations", headers=headers, params=params)

    def get_return_authorization(self, rma_id, headers):
        return self._request("GET", f"/pool-supply/return-authorizations/{rma_id}", headers=headers)

    def approve_return_authorization(self, rma_id, headers):
        return self._request("POST", f"/pool-supply/return-authorizations/{rma_id}/approve", {}, headers)

    def deny_return_authorization(self, rma_id, headers):
        return self._request("POST", f"/pool-supply/return-authorizations/{rma_id}/deny", {}, headers)

    def receive_return_authorization(self, rma_id, headers):
        return self._request("POST", f"/pool-supply/return-authorizations/{rma_id}/receive", {}, headers)

    def credit_return_authorization(self, rma_id, headers):
        return self._request("POST", f"/pool-supply/return-authorizations/{rma_id}/credit", {}, headers)


api_client = ApiClient()
