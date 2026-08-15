"""API client: one method per endpoint defined in the PRD section 4 table."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/spirit-store"


class ApiClient(GenericApiClient):
    # --- MerchProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", f"{BASE}/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", f"{BASE}/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{BASE}/programs/{program_id}", headers=headers)

    def program_lifecycle(self, program_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/lifecycle", payload, headers
        )

    def create_profit_adjustment(self, program_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/programs/{program_id}/profit-adjustments",
            payload,
            headers,
        )

    def get_valuation(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/programs/{program_id}/valuation",
            headers=headers,
            params=params,
        )

    def run_ops(self, program_id, headers):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/run-ops", {}, headers
        )

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{BASE}/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", f"{BASE}/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{BASE}/vendors/{vendor_id}", headers=headers)

    def update_vendor(self, vendor_id, payload, headers):
        return self._request("PATCH", f"{BASE}/vendors/{vendor_id}", payload, headers)

    # --- Design ---
    def create_design(self, payload, headers):
        return self._request("POST", f"{BASE}/designs", payload, headers)

    def list_designs(self, headers, params=None):
        return self._request("GET", f"{BASE}/designs", headers=headers, params=params)

    def get_design(self, design_id, headers):
        return self._request("GET", f"{BASE}/designs/{design_id}", headers=headers)

    def design_licensing_transition(self, design_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/designs/{design_id}/licensing-transition",
            payload,
            headers,
        )

    # --- ProductVariant ---
    def create_product_variant(self, payload, headers):
        return self._request("POST", f"{BASE}/product-variants", payload, headers)

    def list_product_variants(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/product-variants", headers=headers, params=params
        )

    def get_product_variant(self, variant_id, headers):
        return self._request(
            "GET", f"{BASE}/product-variants/{variant_id}", headers=headers
        )

    # --- SeasonalDrop ---
    def create_seasonal_drop(self, payload, headers):
        return self._request("POST", f"{BASE}/seasonal-drops", payload, headers)

    def list_seasonal_drops(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/seasonal-drops", headers=headers, params=params
        )

    def get_seasonal_drop(self, drop_id, headers):
        return self._request(
            "GET", f"{BASE}/seasonal-drops/{drop_id}", headers=headers
        )

    def seasonal_drop_transition(self, drop_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/seasonal-drops/{drop_id}/transition",
            payload,
            headers,
        )

    # --- PurchaseOrder ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", f"{BASE}/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/purchase-orders", headers=headers, params=params
        )

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"{BASE}/purchase-orders/{po_id}", headers=headers)

    def submit_purchase_order(self, po_id, headers):
        return self._request(
            "POST", f"{BASE}/purchase-orders/{po_id}/submit", {}, headers
        )

    def receive_purchase_order(self, po_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/purchase-orders/{po_id}/receive", payload, headers
        )

    def cancel_purchase_order(self, po_id, headers):
        return self._request(
            "POST", f"{BASE}/purchase-orders/{po_id}/cancel", {}, headers
        )

    # --- PreOrderCampaign ---
    def create_preorder_campaign(self, payload, headers):
        return self._request("POST", f"{BASE}/preorder-campaigns", payload, headers)

    def list_preorder_campaigns(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/preorder-campaigns", headers=headers, params=params
        )

    def get_preorder_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"{BASE}/preorder-campaigns/{campaign_id}", headers=headers
        )

    def open_preorder_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"{BASE}/preorder-campaigns/{campaign_id}/open", {}, headers
        )

    def lock_preorder_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"{BASE}/preorder-campaigns/{campaign_id}/lock", {}, headers
        )

    def cancel_preorder_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"{BASE}/preorder-campaigns/{campaign_id}/cancel", {}, headers
        )

    # --- PreOrder ---
    def create_preorder(self, payload, headers):
        return self._request("POST", f"{BASE}/preorders", payload, headers)

    def list_preorders(self, headers, params=None):
        return self._request("GET", f"{BASE}/preorders", headers=headers, params=params)

    def get_preorder(self, preorder_id, headers):
        return self._request("GET", f"{BASE}/preorders/{preorder_id}", headers=headers)

    def pay_preorder(self, preorder_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/preorders/{preorder_id}/pay", payload, headers
        )

    def fulfill_preorder(self, preorder_id, headers):
        return self._request(
            "POST", f"{BASE}/preorders/{preorder_id}/fulfill", {}, headers
        )

    def cancel_preorder(self, preorder_id, headers):
        return self._request(
            "POST", f"{BASE}/preorders/{preorder_id}/cancel", {}, headers
        )

    # --- EventSale ---
    def create_event_sale(self, payload, headers):
        return self._request("POST", f"{BASE}/event-sales", payload, headers)

    def list_event_sales(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/event-sales", headers=headers, params=params
        )

    def get_event_sale(self, event_id, headers):
        return self._request("GET", f"{BASE}/event-sales/{event_id}", headers=headers)

    def open_drawer(self, event_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/event-sales/{event_id}/open-drawer", payload, headers
        )

    def close_count(self, event_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/event-sales/{event_id}/close-count", payload, headers
        )

    def reconcile_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/event-sales/{event_id}/reconcile", payload, headers
        )

    def cancel_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/event-sales/{event_id}/cancel", {}, headers
        )

    # --- Order ---
    def create_order(self, payload, headers):
        return self._request("POST", f"{BASE}/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{BASE}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{BASE}/orders/{order_id}", headers=headers)

    def order_fulfillment_transition(self, order_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/orders/{order_id}/fulfillment-transition",
            payload,
            headers,
        )

    def refund_order(self, order_id, payload, headers):
        return self._request("POST", f"{BASE}/orders/{order_id}/refund", payload, headers)

    # --- ExchangeRequest ---
    def create_exchange(self, payload, headers):
        return self._request("POST", f"{BASE}/exchanges", payload, headers)

    def list_exchanges(self, headers, params=None):
        return self._request("GET", f"{BASE}/exchanges", headers=headers, params=params)

    def get_exchange(self, exchange_id, headers):
        return self._request("GET", f"{BASE}/exchanges/{exchange_id}", headers=headers)

    def exchange_decision(self, exchange_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/exchanges/{exchange_id}/decision", payload, headers
        )

    def complete_exchange(self, exchange_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/exchanges/{exchange_id}/complete", payload, headers
        )

    # --- ActivityAccount ---
    def create_activity_account(self, payload, headers):
        return self._request("POST", f"{BASE}/activity-accounts", payload, headers)

    def list_activity_accounts(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/activity-accounts", headers=headers, params=params
        )

    def get_activity_account(self, account_id, headers):
        return self._request(
            "GET", f"{BASE}/activity-accounts/{account_id}", headers=headers
        )

    # --- AllocationRun ---
    def create_allocation_run(self, payload, headers):
        return self._request("POST", f"{BASE}/allocation-runs", payload, headers)

    def list_allocation_runs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/allocation-runs", headers=headers, params=params
        )

    def get_allocation_run(self, run_id, headers):
        return self._request("GET", f"{BASE}/allocation-runs/{run_id}", headers=headers)

    def post_allocation_run(self, run_id, headers):
        return self._request(
            "POST", f"{BASE}/allocation-runs/{run_id}/post", {}, headers
        )

    def reverse_allocation_run(self, run_id, headers):
        return self._request(
            "POST", f"{BASE}/allocation-runs/{run_id}/reverse", {}, headers
        )

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
