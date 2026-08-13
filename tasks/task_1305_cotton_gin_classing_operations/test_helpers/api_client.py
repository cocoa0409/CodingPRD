"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Growers / settlements / ledger
    # ------------------------------------------------------------------
    def create_grower(self, payload, headers):
        return self._request("POST", "/gin-ops/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/gin-ops/growers/{grower_id}", headers=headers)

    def list_grower_settlements(self, grower_id, headers, params=None):
        return self._request("GET", f"/gin-ops/growers/{grower_id}/settlements",
                             headers=headers, params=params)

    def create_settlement(self, grower_id, payload, headers):
        return self._request("POST", f"/gin-ops/growers/{grower_id}/settlements",
                             payload, headers)

    def create_ledger_adjustment(self, grower_id, payload, headers):
        return self._request("POST", f"/gin-ops/growers/{grower_id}/ledger-adjustments",
                             payload, headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/gin-ops/ledger-entries", headers=headers,
                             params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/gin-ops/ledger-entries/{entry_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Grade schedules
    # ------------------------------------------------------------------
    def create_grade_schedule(self, payload, headers):
        return self._request("POST", "/gin-ops/grade-schedules", payload, headers)

    def get_grade_schedule(self, schedule_id, headers):
        return self._request("GET", f"/gin-ops/grade-schedules/{schedule_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Warehouses
    # ------------------------------------------------------------------
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/gin-ops/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/gin-ops/warehouses/{warehouse_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Gin shifts
    # ------------------------------------------------------------------
    def create_gin_shift(self, payload, headers):
        return self._request("POST", "/gin-ops/gin-shifts", payload, headers)

    def get_gin_shift(self, shift_id, headers):
        return self._request("GET", f"/gin-ops/gin-shifts/{shift_id}", headers=headers)

    def close_gin_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/gin-ops/gin-shifts/{shift_id}/close",
                             payload, headers)

    def reconcile_gin_shift(self, shift_id, headers):
        return self._request("POST", f"/gin-ops/gin-shifts/{shift_id}/reconcile",
                             {}, headers)

    def list_shift_seed_sales(self, shift_id, headers, params=None):
        return self._request("GET", f"/gin-ops/gin-shifts/{shift_id}/seed-sales",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Module receipts
    # ------------------------------------------------------------------
    def create_module(self, payload, headers):
        return self._request("POST", "/gin-ops/modules", payload, headers)

    def get_module(self, module_id, headers):
        return self._request("GET", f"/gin-ops/modules/{module_id}", headers=headers)

    def list_modules(self, headers, params=None):
        return self._request("GET", "/gin-ops/modules", headers=headers, params=params)

    def condition_module(self, module_id, payload, headers):
        return self._request("POST", f"/gin-ops/modules/{module_id}/condition",
                             payload, headers)

    def queue_module(self, module_id, payload, headers):
        return self._request("POST", f"/gin-ops/modules/{module_id}/queue",
                             payload, headers)

    def start_ginning(self, module_id, headers):
        return self._request("POST", f"/gin-ops/modules/{module_id}/start-ginning",
                             {}, headers)

    def complete_ginning(self, module_id, payload, headers):
        return self._request("POST", f"/gin-ops/modules/{module_id}/complete-ginning",
                             payload, headers)

    def reject_module(self, module_id, payload, headers):
        return self._request("POST", f"/gin-ops/modules/{module_id}/reject",
                             payload, headers)

    def list_module_bales(self, module_id, headers, params=None):
        return self._request("GET", f"/gin-ops/modules/{module_id}/bales",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Bales / classing results
    # ------------------------------------------------------------------
    def get_bale(self, bale_id, headers):
        return self._request("GET", f"/gin-ops/bales/{bale_id}", headers=headers)

    def create_classing_result(self, bale_id, payload, headers):
        return self._request("POST", f"/gin-ops/bales/{bale_id}/classing-results",
                             payload, headers)

    def list_classing_results(self, bale_id, headers, params=None):
        return self._request("GET", f"/gin-ops/bales/{bale_id}/classing-results",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Warehouse receipts
    # ------------------------------------------------------------------
    def create_warehouse_receipt(self, payload, headers):
        return self._request("POST", "/gin-ops/warehouse-receipts", payload, headers)

    def get_warehouse_receipt(self, receipt_id, headers):
        return self._request("GET", f"/gin-ops/warehouse-receipts/{receipt_id}",
                             headers=headers)

    def list_warehouse_receipts(self, headers, params=None):
        return self._request("GET", "/gin-ops/warehouse-receipts", headers=headers,
                             params=params)

    def cancel_warehouse_receipt(self, receipt_id, headers):
        return self._request("POST", f"/gin-ops/warehouse-receipts/{receipt_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Loan pledges
    # ------------------------------------------------------------------
    def create_loan_pledge(self, payload, headers):
        return self._request("POST", "/gin-ops/loan-pledges", payload, headers)

    def get_loan_pledge(self, pledge_id, headers):
        return self._request("GET", f"/gin-ops/loan-pledges/{pledge_id}",
                             headers=headers)

    def list_receipt_loan_pledges(self, receipt_id, headers, params=None):
        return self._request("GET",
                             f"/gin-ops/warehouse-receipts/{receipt_id}/loan-pledges",
                             headers=headers, params=params)

    def redeem_loan_pledge(self, pledge_id, headers):
        return self._request("POST", f"/gin-ops/loan-pledges/{pledge_id}/redeem",
                             {}, headers)

    def forfeit_loan_pledge(self, pledge_id, headers):
        return self._request("POST", f"/gin-ops/loan-pledges/{pledge_id}/forfeit",
                             {}, headers)

    # ------------------------------------------------------------------
    # Seed sales
    # ------------------------------------------------------------------
    def create_seed_sale(self, payload, headers):
        return self._request("POST", "/gin-ops/seed-sales", payload, headers)

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/gin-ops/settlements/{settlement_id}",
                             headers=headers)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/gin-ops/settlements/{settlement_id}/finalize",
                             {}, headers)

    def pay_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/gin-ops/settlements/{settlement_id}/pay",
                             payload, headers)

    # ------------------------------------------------------------------
    # Shipping orders
    # ------------------------------------------------------------------
    def create_shipping_order(self, payload, headers):
        return self._request("POST", "/gin-ops/shipping-orders", payload, headers)

    def get_shipping_order(self, order_id, headers):
        return self._request("GET", f"/gin-ops/shipping-orders/{order_id}",
                             headers=headers)

    def list_shipping_orders(self, headers, params=None):
        return self._request("GET", "/gin-ops/shipping-orders", headers=headers,
                             params=params)

    def confirm_shipping_order(self, order_id, headers):
        return self._request("POST", f"/gin-ops/shipping-orders/{order_id}/confirm",
                             {}, headers)

    def ship_shipping_order(self, order_id, headers):
        return self._request("POST", f"/gin-ops/shipping-orders/{order_id}/ship",
                             {}, headers)

    def cancel_shipping_order(self, order_id, headers):
        return self._request("POST", f"/gin-ops/shipping-orders/{order_id}/cancel",
                             {}, headers)

    def list_shipping_order_bales(self, order_id, headers, params=None):
        return self._request("GET", f"/gin-ops/shipping-orders/{order_id}/bales",
                             headers=headers, params=params)


api_client = ApiClient()
