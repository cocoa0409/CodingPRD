"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def advance_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/advance", {"to_iso8601": to_iso8601}, headers)

    # ---- Department ----
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/departments", headers=headers, params=params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", {}, headers)

    def list_product_price_plans(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/price-plans", headers=headers, params=params)

    def list_product_promotions(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/promotions", headers=headers, params=params)

    # ---- Shipment + ShipmentLine ----
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def add_shipment_line(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/lines", payload, headers)

    def get_shipment_line(self, line_id, headers):
        return self._request("GET", f"/shipment-lines/{line_id}", headers=headers)

    def list_shipment_lines(self, headers, params=None):
        return self._request("GET", "/shipment-lines", headers=headers, params=params)

    def start_receiving(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/start-receiving", {}, headers)

    def receive_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/receive", payload, headers)

    def reject_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/reject", {}, headers)

    # ---- InventoryLot ----
    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/quarantine", {}, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/release", {}, headers)

    def pull_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/pull", {}, headers)

    def expire_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/expire", {}, headers)

    # ---- PricePlan ----
    def create_price_plan(self, payload, headers):
        return self._request("POST", "/price-plans", payload, headers)

    def get_price_plan(self, plan_id, headers):
        return self._request("GET", f"/price-plans/{plan_id}", headers=headers)

    def cancel_price_plan(self, plan_id, headers):
        return self._request("POST", f"/price-plans/{plan_id}/cancel", {}, headers)

    # ---- Promotion ----
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers)

    def get_promotion(self, promo_id, headers):
        return self._request("GET", f"/promotions/{promo_id}", headers=headers)

    def cancel_promotion(self, promo_id, headers):
        return self._request("POST", f"/promotions/{promo_id}/cancel", {}, headers)

    # ---- LoyaltyMember ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers)

    def reactivate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reactivate", {}, headers)

    def close_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/close", {}, headers)

    def clip_coupon(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/clip", payload, headers)

    def list_member_clipped_coupons(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/clipped-coupons", headers=headers, params=params)

    def get_clipped_coupon(self, clip_id, headers):
        return self._request("GET", f"/clipped-coupons/{clip_id}", headers=headers)

    # ---- DigitalCoupon ----
    def create_coupon(self, payload, headers):
        return self._request("POST", "/coupons", payload, headers)

    def list_coupons(self, headers, params=None):
        return self._request("GET", "/coupons", headers=headers, params=params)

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"/coupons/{coupon_id}", headers=headers)

    def list_coupon_clipped_coupons(self, coupon_id, headers, params=None):
        return self._request("GET", f"/coupons/{coupon_id}/clipped-coupons", headers=headers, params=params)

    # ---- SalesTransaction + SaleLineItem ----
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def add_line_item(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/line-items", payload, headers)

    def get_sale_line_item(self, line_id, headers):
        return self._request("GET", f"/sale-line-items/{line_id}", headers=headers)

    def list_sale_line_items(self, headers, params=None):
        return self._request("GET", "/sale-line-items", headers=headers, params=params)

    def finalize_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/finalize", payload, headers)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/void", {}, headers)

    def pay_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/pay", {}, headers)

    def refund_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/refund", {}, headers)

    # ---- CycleCount ----
    def create_cycle_count(self, payload, headers):
        return self._request("POST", "/cycle-counts", payload, headers)

    def get_cycle_count(self, cc_id, headers):
        return self._request("GET", f"/cycle-counts/{cc_id}", headers=headers)

    def list_cycle_counts(self, headers, params=None):
        return self._request("GET", "/cycle-counts", headers=headers, params=params)

    def submit_cycle_count(self, cc_id, payload, headers):
        return self._request("POST", f"/cycle-counts/{cc_id}/submit", payload, headers)

    def reconcile_cycle_count(self, cc_id, headers):
        return self._request("POST", f"/cycle-counts/{cc_id}/reconcile", {}, headers)

    def cancel_cycle_count(self, cc_id, headers):
        return self._request("POST", f"/cycle-counts/{cc_id}/cancel", {}, headers)

    # ---- EndOfDayReconciliation ----
    def create_eod(self, payload, headers):
        return self._request("POST", "/eod-reconciliations", payload, headers)

    def get_eod(self, eod_id, headers):
        return self._request("GET", f"/eod-reconciliations/{eod_id}", headers=headers)

    def list_eod(self, headers, params=None):
        return self._request("GET", "/eod-reconciliations", headers=headers, params=params)

    def close_eod(self, eod_id, headers):
        return self._request("POST", f"/eod-reconciliations/{eod_id}/close", {}, headers)


api_client = ApiClient()
