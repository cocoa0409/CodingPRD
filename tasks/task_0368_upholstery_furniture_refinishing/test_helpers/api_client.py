"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Customers -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_work_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/work-orders", headers=headers, params=params)

    # ----- Fabric SKUs -----
    def create_fabric_sku(self, payload, headers):
        return self._request("POST", "/fabric-skus", payload, headers)

    def get_fabric_sku(self, fabric_sku_id, headers):
        return self._request("GET", f"/fabric-skus/{fabric_sku_id}", headers=headers)

    def discontinue_fabric_sku(self, fabric_sku_id, headers):
        return self._request("POST", f"/fabric-skus/{fabric_sku_id}/discontinue", headers=headers)

    # ----- Foam Specs -----
    def create_foam_spec(self, payload, headers):
        return self._request("POST", "/foam-specs", payload, headers)

    def get_foam_spec(self, foam_spec_id, headers):
        return self._request("GET", f"/foam-specs/{foam_spec_id}", headers=headers)

    def discontinue_foam_spec(self, foam_spec_id, headers):
        return self._request("POST", f"/foam-specs/{foam_spec_id}/discontinue", headers=headers)

    # ----- Work Orders -----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    # ----- Condition Photos -----
    def create_condition_photo(self, payload, headers):
        return self._request("POST", "/condition-photos", payload, headers)

    def get_condition_photo(self, photo_id, headers):
        return self._request("GET", f"/condition-photos/{photo_id}", headers=headers)

    def list_condition_photos(self, headers, params=None):
        return self._request("GET", "/condition-photos", headers=headers, params=params)

    # ----- Line Items -----
    def create_line_item(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/line-items", payload, headers)

    def list_work_order_line_items(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    # ----- Estimates -----
    def create_estimate(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_work_order_estimates(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/estimates", headers=headers, params=params)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    # ----- Estimate approval loop -----
    def request_revision(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/request-revision", headers=headers)

    def approve_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/approve", payload, headers)

    def decline_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/decline", headers=headers)

    # ----- Material Orders -----
    def create_material_order(self, payload, headers):
        return self._request("POST", "/material-orders", payload, headers)

    def get_material_order(self, material_order_id, headers):
        return self._request("GET", f"/material-orders/{material_order_id}", headers=headers)

    def list_material_orders(self, headers, params=None):
        return self._request("GET", "/material-orders", headers=headers, params=params)

    def receive_material_order(self, material_order_id, payload, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/receive", payload, headers)

    def cancel_material_order(self, material_order_id, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/cancel", headers=headers)

    # ----- Shop Days -----
    def create_shop_day(self, payload, headers):
        return self._request("POST", "/shop-days", payload, headers)

    def get_shop_day(self, shop_day_id, headers):
        return self._request("GET", f"/shop-days/{shop_day_id}", headers=headers)

    def list_shop_days(self, headers, params=None):
        return self._request("GET", "/shop-days", headers=headers, params=params)

    def close_shop_day(self, shop_day_id, headers):
        return self._request("POST", f"/shop-days/{shop_day_id}/close", headers=headers)

    # ----- Fulfillment Legs -----
    def create_fulfillment_leg(self, payload, headers):
        return self._request("POST", "/fulfillment-legs", payload, headers)

    def get_fulfillment_leg(self, leg_id, headers):
        return self._request("GET", f"/fulfillment-legs/{leg_id}", headers=headers)

    def list_fulfillment_legs(self, headers, params=None):
        return self._request("GET", "/fulfillment-legs", headers=headers, params=params)

    def dispatch_fulfillment_leg(self, leg_id, headers):
        return self._request("POST", f"/fulfillment-legs/{leg_id}/dispatch", headers=headers)

    def complete_fulfillment_leg(self, leg_id, headers):
        return self._request("POST", f"/fulfillment-legs/{leg_id}/complete", headers=headers)

    def cancel_fulfillment_leg(self, leg_id, headers):
        return self._request("POST", f"/fulfillment-legs/{leg_id}/cancel", headers=headers)

    # ----- Work Order lifecycle -----
    def finish_production(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/finish-production", headers=headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", payload, headers)

    def list_work_order_payments(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/payments", headers=headers, params=params)

    # ----- Server clock (test-driving) -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----- Warranty Claims -----
    def file_warranty_claim(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_work_order_warranty_claims(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/warranty-claims", headers=headers, params=params)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", headers=headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", headers=headers)

    def resolve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/resolve", headers=headers)


api_client = ApiClient()
