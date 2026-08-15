"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under /api (PRD §4: "All endpoints are mounted
under /api").
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving / ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/api/ops/run-daily-sweep", {}, headers)

    # --- salon accounts ---
    def create_salon_account(self, payload, headers):
        return self._request("POST", "/api/salon-accounts", payload, headers)

    def list_salon_accounts(self, headers, params=None):
        return self._request("GET", "/api/salon-accounts", headers=headers, params=params)

    def get_salon_account(self, salon_id, headers):
        return self._request(
            "GET", f"/api/salon-accounts/{salon_id}", headers=headers
        )

    def suspend_salon(self, salon_id, payload, headers):
        return self._request(
            "POST", f"/api/salon-accounts/{salon_id}/suspend", payload, headers
        )

    def reinstate_salon(self, salon_id, headers):
        return self._request(
            "POST", f"/api/salon-accounts/{salon_id}/reinstate", {}, headers
        )

    def deactivate_salon(self, salon_id, headers):
        return self._request(
            "POST", f"/api/salon-accounts/{salon_id}/deactivate", {}, headers
        )

    def tier_override_salon(self, salon_id, payload, headers):
        return self._request(
            "POST", f"/api/salon-accounts/{salon_id}/tier-override", payload, headers
        )

    def evaluate_tier(self, salon_id, headers):
        return self._request(
            "POST", f"/api/salon-accounts/{salon_id}/evaluate-tier", {}, headers
        )

    # --- professional licenses ---
    def create_license(self, salon_id, payload, headers):
        return self._request(
            "POST", f"/api/salon-accounts/{salon_id}/licenses", payload, headers
        )

    def list_licenses(self, salon_id, headers, params=None):
        return self._request(
            "GET", f"/api/salon-accounts/{salon_id}/licenses",
            headers=headers, params=params,
        )

    def get_license(self, license_id, headers):
        return self._request("GET", f"/api/licenses/{license_id}", headers=headers)

    def verify_license(self, license_id, headers):
        return self._request(
            "POST", f"/api/licenses/{license_id}/verify", {}, headers
        )

    def reject_license(self, license_id, headers):
        return self._request(
            "POST", f"/api/licenses/{license_id}/reject", {}, headers
        )

    # --- brands / territory exclusives ---
    def create_brand(self, payload, headers):
        return self._request("POST", "/api/brands", payload, headers)

    def list_brands(self, headers, params=None):
        return self._request("GET", "/api/brands", headers=headers, params=params)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/api/brands/{brand_id}", headers=headers)

    def discontinue_brand(self, brand_id, headers):
        return self._request(
            "POST", f"/api/brands/{brand_id}/discontinue", {}, headers
        )

    def create_territory_exclusive(self, brand_id, payload, headers):
        return self._request(
            "POST", f"/api/brands/{brand_id}/territory-exclusives", payload, headers
        )

    def list_territory_exclusives(self, brand_id, headers, params=None):
        return self._request(
            "GET", f"/api/brands/{brand_id}/territory-exclusives",
            headers=headers, params=params,
        )

    # --- products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/api/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    def transition_product_lifecycle(self, product_id, payload, headers):
        return self._request(
            "POST", f"/api/products/{product_id}/lifecycle", payload, headers
        )

    # --- sales consultants ---
    def create_sales_consultant(self, payload, headers):
        return self._request("POST", "/api/sales-consultants", payload, headers)

    def get_sales_consultant(self, consultant_id, headers):
        return self._request(
            "GET", f"/api/sales-consultants/{consultant_id}", headers=headers
        )

    def update_sales_consultant(self, consultant_id, payload, headers):
        return self._request(
            "PATCH", f"/api/sales-consultants/{consultant_id}", payload, headers
        )

    # --- route plans ---
    def create_route_plan(self, payload, headers):
        return self._request("POST", "/api/route-plans", payload, headers)

    def list_route_plans(self, headers, params=None):
        return self._request("GET", "/api/route-plans", headers=headers, params=params)

    def get_route_plan(self, plan_id, headers):
        return self._request("GET", f"/api/route-plans/{plan_id}", headers=headers)

    def publish_route_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/api/route-plans/{plan_id}/publish", {}, headers
        )

    def unpublish_route_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/api/route-plans/{plan_id}/unpublish", {}, headers
        )

    def add_route_stop(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/api/route-plans/{plan_id}/stops", payload, headers
        )

    # --- route stops ---
    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/api/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/api/route-stops/{stop_id}", headers=headers)

    def complete_route_stop(self, stop_id, headers):
        return self._request(
            "POST", f"/api/route-stops/{stop_id}/complete", {}, headers
        )

    def no_show_route_stop(self, stop_id, headers):
        return self._request(
            "POST", f"/api/route-stops/{stop_id}/no-show", {}, headers
        )

    def reschedule_route_stop(self, stop_id, payload, headers):
        return self._request(
            "POST", f"/api/route-stops/{stop_id}/reschedule", payload, headers
        )

    def cancel_route_stop(self, stop_id, headers):
        return self._request(
            "POST", f"/api/route-stops/{stop_id}/cancel", {}, headers
        )

    # --- orders / order items ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def add_order_item(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/orders/{order_id}/items", payload, headers
        )

    def remove_order_item(self, order_id, item_id, headers):
        return self._request(
            "DELETE", f"/api/orders/{order_id}/items/{item_id}", headers=headers
        )

    def list_order_items(self, headers, params=None):
        return self._request("GET", "/api/order-items", headers=headers, params=params)

    def get_order_item(self, item_id, headers):
        return self._request("GET", f"/api/order-items/{item_id}", headers=headers)

    def redeem_credits(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/orders/{order_id}/redeem-credits", payload, headers
        )

    def redeem_promotion(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/orders/{order_id}/redeem-promotion", payload, headers
        )

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/submit", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    def approve_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/approve", {}, headers)

    def reject_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/orders/{order_id}/reject", payload, headers
        )

    # --- shipments ---
    def create_shipment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/orders/{order_id}/shipments", payload, headers
        )

    def list_shipments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/orders/{order_id}/shipments",
            headers=headers, params=params,
        )

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def create_shipment_label(self, shipment_id, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/create-label", {}, headers
        )

    def ship_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/ship", {}, headers
        )

    def deliver_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/deliver", {}, headers
        )

    def void_shipment_label(self, shipment_id, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/void-label", {}, headers
        )

    # --- promotions / redemptions ---
    def create_promotion(self, payload, headers):
        return self._request("POST", "/api/promotions", payload, headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/api/promotions", headers=headers, params=params)

    def get_promotion(self, promotion_id, headers):
        return self._request(
            "GET", f"/api/promotions/{promotion_id}", headers=headers
        )

    def activate_promotion(self, promotion_id, headers):
        return self._request(
            "POST", f"/api/promotions/{promotion_id}/activate", {}, headers
        )

    def pause_promotion(self, promotion_id, headers):
        return self._request(
            "POST", f"/api/promotions/{promotion_id}/pause", {}, headers
        )

    def resume_promotion(self, promotion_id, headers):
        return self._request(
            "POST", f"/api/promotions/{promotion_id}/resume", {}, headers
        )

    def adjust_promotion_budget(self, promotion_id, payload, headers):
        return self._request(
            "POST", f"/api/promotions/{promotion_id}/budget-adjustments",
            payload, headers,
        )

    def list_promotion_redemptions(self, headers, params=None):
        return self._request(
            "GET", "/api/promotion-redemptions", headers=headers, params=params
        )

    def get_promotion_redemption(self, redemption_id, headers):
        return self._request(
            "GET", f"/api/promotion-redemptions/{redemption_id}", headers=headers
        )

    # --- diversion cases ---
    def create_diversion_case(self, payload, headers):
        return self._request("POST", "/api/diversion-cases", payload, headers)

    def list_diversion_cases(self, headers, params=None):
        return self._request(
            "GET", "/api/diversion-cases", headers=headers, params=params
        )

    def get_diversion_case(self, case_id, headers):
        return self._request(
            "GET", f"/api/diversion-cases/{case_id}", headers=headers
        )

    def start_diversion_review(self, case_id, headers):
        return self._request(
            "POST", f"/api/diversion-cases/{case_id}/start-review", {}, headers
        )

    def request_diversion_evidence(self, case_id, headers):
        return self._request(
            "POST", f"/api/diversion-cases/{case_id}/request-evidence", {}, headers
        )

    def substantiate_diversion_case(self, case_id, headers):
        return self._request(
            "POST", f"/api/diversion-cases/{case_id}/substantiate", {}, headers
        )

    def dismiss_diversion_case(self, case_id, headers):
        return self._request(
            "POST", f"/api/diversion-cases/{case_id}/dismiss", {}, headers
        )

    # --- education-credit ledger ---
    def list_credit_ledger(self, salon_id, headers, params=None):
        return self._request(
            "GET", f"/api/salon-accounts/{salon_id}/credit-ledger",
            headers=headers, params=params,
        )

    def list_order_credit_entries(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/orders/{order_id}/credit-entries",
            headers=headers, params=params,
        )


api_client = ApiClient()
