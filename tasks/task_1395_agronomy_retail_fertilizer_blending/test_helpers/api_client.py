"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/agronomy/_clock/set_current_utc", payload, headers)

    # --- GrowerAccount ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/agronomy/growers", payload, headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/agronomy/growers", headers=headers, params=params)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/agronomy/growers/{grower_id}", headers=headers)

    def update_credit_terms(self, grower_id, payload, headers):
        return self._request("PATCH", f"/agronomy/growers/{grower_id}/credit-terms", payload, headers)

    def credit_hold(self, grower_id, headers, payload=None):
        return self._request("POST", f"/agronomy/growers/{grower_id}/credit-hold", payload or {}, headers)

    def suspend_grower(self, grower_id, headers, payload=None):
        return self._request("POST", f"/agronomy/growers/{grower_id}/suspend", payload or {}, headers)

    def credit_release(self, grower_id, headers, payload=None):
        return self._request("POST", f"/agronomy/growers/{grower_id}/credit-release", payload or {}, headers)

    def post_payment(self, grower_id, payload, headers):
        return self._request("POST", f"/agronomy/growers/{grower_id}/payments", payload, headers)

    def list_credit_ledger(self, grower_id, headers, params=None):
        return self._request("GET", f"/agronomy/growers/{grower_id}/credit-ledger", headers=headers, params=params)

    def get_exposure(self, grower_id, headers):
        return self._request("GET", f"/agronomy/growers/{grower_id}/exposure", headers=headers)

    # --- Field ---
    def create_field(self, grower_id, payload, headers):
        return self._request("POST", f"/agronomy/growers/{grower_id}/fields", payload, headers)

    def list_grower_fields(self, grower_id, headers, params=None):
        return self._request("GET", f"/agronomy/growers/{grower_id}/fields", headers=headers, params=params)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/agronomy/fields", headers=headers, params=params)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/agronomy/fields/{field_id}", headers=headers)

    # --- SoilTest ---
    def create_soil_test(self, field_id, payload, headers):
        return self._request("POST", f"/agronomy/fields/{field_id}/soil-tests", payload, headers)

    def list_field_soil_tests(self, field_id, headers, params=None):
        return self._request("GET", f"/agronomy/fields/{field_id}/soil-tests", headers=headers, params=params)

    def get_soil_test(self, soil_test_id, headers):
        return self._request("GET", f"/agronomy/soil-tests/{soil_test_id}", headers=headers)

    def record_sampling(self, soil_test_id, headers, payload=None):
        return self._request("POST", f"/agronomy/soil-tests/{soil_test_id}/record-sampling", payload or {}, headers)

    def post_results(self, soil_test_id, payload, headers):
        return self._request("POST", f"/agronomy/soil-tests/{soil_test_id}/post-results", payload, headers)

    # --- Recommendation ---
    def create_recommendation(self, soil_test_id, payload, headers):
        return self._request("POST", f"/agronomy/soil-tests/{soil_test_id}/recommendations", payload, headers)

    def list_soil_test_recommendations(self, soil_test_id, headers, params=None):
        return self._request("GET", f"/agronomy/soil-tests/{soil_test_id}/recommendations", headers=headers, params=params)

    def list_recommendations(self, headers, params=None):
        return self._request("GET", "/agronomy/recommendations", headers=headers, params=params)

    def get_recommendation(self, recommendation_id, headers):
        return self._request("GET", f"/agronomy/recommendations/{recommendation_id}", headers=headers)

    def submit_recommendation(self, recommendation_id, headers, payload=None):
        return self._request("POST", f"/agronomy/recommendations/{recommendation_id}/submit", payload or {}, headers)

    def return_recommendation(self, recommendation_id, payload, headers):
        return self._request("POST", f"/agronomy/recommendations/{recommendation_id}/return", payload, headers)

    def approve_recommendation(self, recommendation_id, headers, payload=None):
        return self._request("POST", f"/agronomy/recommendations/{recommendation_id}/approve", payload or {}, headers)

    def supersede_recommendation(self, recommendation_id, headers, payload=None):
        return self._request("POST", f"/agronomy/recommendations/{recommendation_id}/supersede", payload or {}, headers)

    def formulation_preview(self, recommendation_id, payload, headers):
        return self._request("POST", f"/agronomy/recommendations/{recommendation_id}/formulation-preview", payload, headers)

    # --- NutrientManagementPlan ---
    def create_nutrient_plan(self, field_id, payload, headers):
        return self._request("POST", f"/agronomy/fields/{field_id}/nutrient-plans", payload, headers)

    def list_field_nutrient_plans(self, field_id, headers, params=None):
        return self._request("GET", f"/agronomy/fields/{field_id}/nutrient-plans", headers=headers, params=params)

    def get_nutrient_plan(self, plan_id, headers):
        return self._request("GET", f"/agronomy/nutrient-plans/{plan_id}", headers=headers)

    def submit_nutrient_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/agronomy/nutrient-plans/{plan_id}/submit", payload or {}, headers)

    def return_nutrient_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/agronomy/nutrient-plans/{plan_id}/return", payload, headers)

    def approve_nutrient_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/agronomy/nutrient-plans/{plan_id}/approve", payload or {}, headers)

    def suspend_nutrient_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/agronomy/nutrient-plans/{plan_id}/suspend", payload or {}, headers)

    def reinstate_nutrient_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/agronomy/nutrient-plans/{plan_id}/reinstate", payload or {}, headers)

    # --- EnvironmentalPermit ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/agronomy/environmental-permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/agronomy/environmental-permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/agronomy/environmental-permits/{permit_id}", headers=headers)

    def begin_inspection(self, permit_id, headers, payload=None):
        return self._request("POST", f"/agronomy/environmental-permits/{permit_id}/begin-inspection", payload or {}, headers)

    def activate_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/agronomy/environmental-permits/{permit_id}/activate", payload, headers)

    def renew_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/agronomy/environmental-permits/{permit_id}/renew", payload or {}, headers)

    def revoke_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/agronomy/environmental-permits/{permit_id}/revoke", payload or {}, headers)

    # --- Product / PriceSheet / Inventory ---
    def create_product(self, payload, headers):
        return self._request("POST", "/agronomy/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/agronomy/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/agronomy/products/{product_id}", headers=headers)

    def create_price_sheet(self, product_id, payload, headers):
        return self._request("POST", f"/agronomy/products/{product_id}/price-sheets", payload, headers)

    def list_product_price_sheets(self, product_id, headers, params=None):
        return self._request("GET", f"/agronomy/products/{product_id}/price-sheets", headers=headers, params=params)

    def get_price_sheet(self, price_sheet_id, headers):
        return self._request("GET", f"/agronomy/price-sheets/{price_sheet_id}", headers=headers)

    def publish_price_sheet(self, price_sheet_id, headers, payload=None):
        return self._request("POST", f"/agronomy/price-sheets/{price_sheet_id}/publish", payload or {}, headers)

    def expire_price_sheet(self, price_sheet_id, headers, payload=None):
        return self._request("POST", f"/agronomy/price-sheets/{price_sheet_id}/expire", payload or {}, headers)

    def get_inventory_position(self, product_id, headers):
        return self._request("GET", f"/agronomy/products/{product_id}/inventory-position", headers=headers)

    def receive_inventory_lot(self, payload, headers):
        return self._request("POST", "/agronomy/inventory-lots", payload, headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/agronomy/inventory-lots", headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/agronomy/inventory-lots/{lot_id}", headers=headers)

    # --- PrepayProgram / PrepayContract ---
    def create_prepay_program(self, payload, headers):
        return self._request("POST", "/agronomy/prepay-programs", payload, headers)

    def list_prepay_programs(self, headers, params=None):
        return self._request("GET", "/agronomy/prepay-programs", headers=headers, params=params)

    def get_prepay_program(self, program_id, headers):
        return self._request("GET", f"/agronomy/prepay-programs/{program_id}", headers=headers)

    def close_enrollment(self, program_id, headers, payload=None):
        return self._request("POST", f"/agronomy/prepay-programs/{program_id}/close-enrollment", payload or {}, headers)

    def settle_prepay_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/agronomy/prepay-programs/{program_id}/settle", payload or {}, headers)

    def create_prepay_contract(self, grower_id, payload, headers):
        return self._request("POST", f"/agronomy/growers/{grower_id}/prepay-contracts", payload, headers)

    def list_grower_prepay_contracts(self, grower_id, headers, params=None):
        return self._request("GET", f"/agronomy/growers/{grower_id}/prepay-contracts", headers=headers, params=params)

    def list_prepay_contracts(self, headers, params=None):
        return self._request("GET", "/agronomy/prepay-contracts", headers=headers, params=params)

    def get_prepay_contract(self, contract_id, headers):
        return self._request("GET", f"/agronomy/prepay-contracts/{contract_id}", headers=headers)

    def fund_prepay_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/agronomy/prepay-contracts/{contract_id}/fund", payload, headers)

    def refund_prepay_contract(self, contract_id, headers, payload=None):
        return self._request("POST", f"/agronomy/prepay-contracts/{contract_id}/refund", payload or {}, headers)

    # --- BlendOrder / BlendLine ---
    def create_blend_order(self, grower_id, payload, headers):
        return self._request("POST", f"/agronomy/growers/{grower_id}/blend-orders", payload, headers)

    def list_grower_blend_orders(self, grower_id, headers, params=None):
        return self._request("GET", f"/agronomy/growers/{grower_id}/blend-orders", headers=headers, params=params)

    def list_blend_orders(self, headers, params=None):
        return self._request("GET", "/agronomy/blend-orders", headers=headers, params=params)

    def get_blend_order(self, order_id, headers):
        return self._request("GET", f"/agronomy/blend-orders/{order_id}", headers=headers)

    def patch_blend_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/agronomy/blend-orders/{order_id}", payload, headers)

    def book_blend_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/agronomy/blend-orders/{order_id}/book", payload or {}, headers)

    def requote_blend_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/agronomy/blend-orders/{order_id}/requote", payload or {}, headers)

    def cancel_blend_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/agronomy/blend-orders/{order_id}/cancel", payload or {}, headers)

    def confirm_application(self, order_id, headers, payload=None):
        return self._request("POST", f"/agronomy/blend-orders/{order_id}/confirm-application", payload or {}, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/agronomy/blend-orders/{order_id}/lines", headers=headers, params=params)

    def get_blend_line(self, line_id, headers):
        return self._request("GET", f"/agronomy/blend-lines/{line_id}", headers=headers)

    def list_blend_lines(self, headers, params=None):
        return self._request("GET", "/agronomy/blend-lines", headers=headers, params=params)

    # --- Blender / BlendBatch ---
    def create_blender(self, payload, headers):
        return self._request("POST", "/agronomy/blenders", payload, headers)

    def list_blenders(self, headers, params=None):
        return self._request("GET", "/agronomy/blenders", headers=headers, params=params)

    def get_blender(self, blender_id, headers):
        return self._request("GET", f"/agronomy/blenders/{blender_id}", headers=headers)

    def blender_out_of_service(self, blender_id, headers, payload=None):
        return self._request("POST", f"/agronomy/blenders/{blender_id}/out-of-service", payload or {}, headers)

    def blender_return_to_service(self, blender_id, headers, payload=None):
        return self._request("POST", f"/agronomy/blenders/{blender_id}/return-to-service", payload or {}, headers)

    def create_batch(self, order_id, payload, headers):
        return self._request("POST", f"/agronomy/blend-orders/{order_id}/batches", payload, headers)

    def list_order_batches(self, order_id, headers, params=None):
        return self._request("GET", f"/agronomy/blend-orders/{order_id}/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/agronomy/blend-batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/agronomy/blend-batches", headers=headers, params=params)

    def start_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/agronomy/blend-batches/{batch_id}/start", payload or {}, headers)

    def complete_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/agronomy/blend-batches/{batch_id}/complete", payload, headers)

    def void_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/agronomy/blend-batches/{batch_id}/void", payload or {}, headers)

    # --- Truck / DeliveryRoute / DeliveryStop ---
    def create_truck(self, payload, headers):
        return self._request("POST", "/agronomy/trucks", payload, headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/agronomy/trucks", headers=headers, params=params)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/agronomy/trucks/{truck_id}", headers=headers)

    def truck_out_of_service(self, truck_id, headers, payload=None):
        return self._request("POST", f"/agronomy/trucks/{truck_id}/out-of-service", payload or {}, headers)

    def truck_return_to_service(self, truck_id, headers, payload=None):
        return self._request("POST", f"/agronomy/trucks/{truck_id}/return-to-service", payload or {}, headers)

    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/agronomy/delivery-routes", payload, headers)

    def list_delivery_routes(self, headers, params=None):
        return self._request("GET", "/agronomy/delivery-routes", headers=headers, params=params)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/agronomy/delivery-routes/{route_id}", headers=headers)

    def add_delivery_stop(self, route_id, payload, headers):
        return self._request("POST", f"/agronomy/delivery-routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/agronomy/delivery-routes/{route_id}/stops", headers=headers, params=params)

    def dispatch_route(self, route_id, headers, payload=None):
        return self._request("POST", f"/agronomy/delivery-routes/{route_id}/dispatch", payload or {}, headers)

    def cancel_route(self, route_id, headers, payload=None):
        return self._request("POST", f"/agronomy/delivery-routes/{route_id}/cancel", payload or {}, headers)

    def get_delivery_stop(self, stop_id, headers):
        return self._request("GET", f"/agronomy/delivery-stops/{stop_id}", headers=headers)

    def list_delivery_stops(self, headers, params=None):
        return self._request("GET", "/agronomy/delivery-stops", headers=headers, params=params)

    def complete_delivery_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"/agronomy/delivery-stops/{stop_id}/complete", payload or {}, headers)


api_client = ApiClient()
