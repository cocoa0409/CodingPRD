"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Part (catalog + inventory) ────────────────────────────────────────
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def receive_stock(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/receive-stock", payload, headers)

    def discontinue_part(self, part_id, headers):
        return self._request("POST", f"/parts/{part_id}/discontinue", headers=headers)

    # ─── Vehicle ───────────────────────────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    # ─── Fitment ───────────────────────────────────────────────────────────
    def create_fitment(self, payload, headers):
        return self._request("POST", "/fitments", payload, headers)

    def list_fitments(self, headers, params=None):
        return self._request("GET", "/fitments", headers=headers, params=params)

    def get_fitment(self, fitment_id, headers):
        return self._request("GET", f"/fitments/{fitment_id}", headers=headers)

    # ─── CrossReference ────────────────────────────────────────────────────
    def create_cross_reference(self, payload, headers):
        return self._request("POST", "/cross-references", payload, headers)

    def list_cross_references(self, headers, params=None):
        return self._request("GET", "/cross-references", headers=headers, params=params)

    def get_cross_reference(self, cross_reference_id, headers):
        return self._request("GET", f"/cross-references/{cross_reference_id}", headers=headers)

    # ─── PriceTier ─────────────────────────────────────────────────────────
    def create_price_tier(self, payload, headers):
        return self._request("POST", "/price-tiers", payload, headers)

    def list_price_tiers(self, headers, params=None):
        return self._request("GET", "/price-tiers", headers=headers, params=params)

    def get_price_tier(self, price_tier_id, headers):
        return self._request("GET", f"/price-tiers/{price_tier_id}", headers=headers)

    # ─── Account ───────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def hold_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/hold", headers=headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/reinstate", headers=headers)

    # ─── SalesOrder ────────────────────────────────────────────────────────
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def allocate_order(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/allocate", payload, headers)

    def ship_order(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/ship", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel", headers=headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/invoice", headers=headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/pay", headers=headers)

    # ─── OrderLine ─────────────────────────────────────────────────────────
    def create_order_line(self, payload, headers):
        return self._request("POST", "/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    # ─── CoreReturn ────────────────────────────────────────────────────────
    def create_core_return(self, payload, headers):
        return self._request("POST", "/core-returns", payload, headers)

    def list_core_returns(self, headers, params=None):
        return self._request("GET", "/core-returns", headers=headers, params=params)

    def get_core_return(self, core_return_id, headers):
        return self._request("GET", f"/core-returns/{core_return_id}", headers=headers)

    def accept_core_return(self, core_return_id, headers):
        return self._request("POST", f"/core-returns/{core_return_id}/accept", headers=headers)

    def reject_core_return(self, core_return_id, headers):
        return self._request("POST", f"/core-returns/{core_return_id}/reject", headers=headers)

    # ─── WarrantyClaim ─────────────────────────────────────────────────────
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def start_review_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/start-review", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", headers=headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", headers=headers)

    # ─── ReorderRequest ────────────────────────────────────────────────────
    def create_reorder_request(self, payload, headers):
        return self._request("POST", "/reorder-requests", payload, headers)

    def list_reorder_requests(self, headers, params=None):
        return self._request("GET", "/reorder-requests", headers=headers, params=params)

    def get_reorder_request(self, reorder_id, headers):
        return self._request("GET", f"/reorder-requests/{reorder_id}", headers=headers)

    def place_reorder_request(self, reorder_id, headers):
        return self._request("POST", f"/reorder-requests/{reorder_id}/place", headers=headers)

    def receive_reorder_request(self, reorder_id, payload, headers):
        return self._request("POST", f"/reorder-requests/{reorder_id}/receive", payload, headers)

    def cancel_reorder_request(self, reorder_id, headers):
        return self._request("POST", f"/reorder-requests/{reorder_id}/cancel", headers=headers)

    # ─── Driver ────────────────────────────────────────────────────────────
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    # ─── Bay ───────────────────────────────────────────────────────────────
    def create_bay(self, payload, headers):
        return self._request("POST", "/bays", payload, headers)

    def list_bays(self, headers, params=None):
        return self._request("GET", "/bays", headers=headers, params=params)

    def get_bay(self, bay_id, headers):
        return self._request("GET", f"/bays/{bay_id}", headers=headers)

    # ─── DeliveryRun ───────────────────────────────────────────────────────
    def create_delivery_run(self, payload, headers):
        return self._request("POST", "/delivery-runs", payload, headers)

    def list_delivery_runs(self, headers, params=None):
        return self._request("GET", "/delivery-runs", headers=headers, params=params)

    def get_delivery_run(self, run_id, headers):
        return self._request("GET", f"/delivery-runs/{run_id}", headers=headers)

    def dispatch_delivery_run(self, run_id, headers):
        return self._request("POST", f"/delivery-runs/{run_id}/dispatch", headers=headers)

    def complete_delivery_run(self, run_id, headers):
        return self._request("POST", f"/delivery-runs/{run_id}/complete", headers=headers)

    def cancel_delivery_run(self, run_id, headers):
        return self._request("POST", f"/delivery-runs/{run_id}/cancel", headers=headers)


api_client = ApiClient()
