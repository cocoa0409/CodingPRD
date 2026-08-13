"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- system / ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/dealership/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/dealership/ops/run-daily-sweep", {}, headers)

    # --- CustomerAccount ---
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/dealership/customer-accounts", payload, headers)

    def list_customer_accounts(self, headers, params=None):
        return self._request("GET", "/dealership/customer-accounts", headers=headers, params=params)

    def get_customer_account(self, account_id, headers):
        return self._request("GET", f"/dealership/customer-accounts/{account_id}", headers=headers)

    def patch_customer_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/dealership/customer-accounts/{account_id}", payload, headers)

    # --- FactoryBuildSlot ---
    def create_factory_build_slot(self, payload, headers):
        return self._request("POST", "/dealership/factory-build-slots", payload, headers)

    def list_factory_build_slots(self, headers, params=None):
        return self._request("GET", "/dealership/factory-build-slots", headers=headers, params=params)

    def get_factory_build_slot(self, slot_id, headers):
        return self._request("GET", f"/dealership/factory-build-slots/{slot_id}", headers=headers)

    # --- FactoryOrder ---
    def create_factory_order(self, payload, headers):
        return self._request("POST", "/dealership/factory-orders", payload, headers)

    def list_factory_orders(self, headers, params=None):
        return self._request("GET", "/dealership/factory-orders", headers=headers, params=params)

    def get_factory_order(self, order_id, headers):
        return self._request("GET", f"/dealership/factory-orders/{order_id}", headers=headers)

    def add_upfit_line(self, order_id, payload, headers):
        return self._request("POST", f"/dealership/factory-orders/{order_id}/upfit-lines", payload, headers)

    def commit_factory_order(self, order_id, headers):
        return self._request("POST", f"/dealership/factory-orders/{order_id}/commit", {}, headers)

    def rehold_factory_order(self, order_id, payload, headers):
        return self._request("POST", f"/dealership/factory-orders/{order_id}/re-hold", payload, headers)

    def cancel_factory_order(self, order_id, headers):
        return self._request("POST", f"/dealership/factory-orders/{order_id}/cancel", {}, headers)

    def receive_factory_order(self, order_id, payload, headers):
        return self._request("POST", f"/dealership/factory-orders/{order_id}/receive", payload, headers)

    # --- Unit ---
    def list_units(self, headers, params=None):
        return self._request("GET", "/dealership/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/dealership/units/{unit_id}", headers=headers)

    def inspect_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/dealership/units/{unit_id}/inspect", payload, headers)

    def sell_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/dealership/units/{unit_id}/sell", payload, headers)

    def wholesale_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/dealership/units/{unit_id}/wholesale", payload, headers)

    def create_floor_plan_adjustment(self, unit_id, payload, headers):
        return self._request("POST", f"/dealership/units/{unit_id}/floor-plan-adjustments", payload, headers)

    def list_floor_plan_entries(self, unit_id, headers, params=None):
        return self._request("GET", f"/dealership/units/{unit_id}/floor-plan-entries", headers=headers, params=params)

    def create_floor_plan_curtailment(self, unit_id, payload, headers):
        return self._request("POST", f"/dealership/units/{unit_id}/floor-plan-curtailments", payload, headers)

    def get_payoff_quote(self, unit_id, headers, params=None):
        return self._request("GET", f"/dealership/units/{unit_id}/payoff-quote", headers=headers, params=params)

    # --- TradeAppraisal ---
    def create_trade_appraisal(self, payload, headers):
        return self._request("POST", "/dealership/trade-appraisals", payload, headers)

    def list_trade_appraisals(self, headers, params=None):
        return self._request("GET", "/dealership/trade-appraisals", headers=headers, params=params)

    def get_trade_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/dealership/trade-appraisals/{appraisal_id}", headers=headers)

    def offer_trade_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/dealership/trade-appraisals/{appraisal_id}/offer", payload, headers)

    def counter_trade_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/dealership/trade-appraisals/{appraisal_id}/counter", {}, headers)

    def accept_trade_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/dealership/trade-appraisals/{appraisal_id}/accept", {}, headers)

    def decline_trade_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/dealership/trade-appraisals/{appraisal_id}/decline", {}, headers)

    # --- ServiceBay / MobileServiceUnit ---
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/dealership/service-bays", payload, headers)

    def list_service_bays(self, headers, params=None):
        return self._request("GET", "/dealership/service-bays", headers=headers, params=params)

    def get_service_bay(self, bay_id, headers):
        return self._request("GET", f"/dealership/service-bays/{bay_id}", headers=headers)

    def set_service_bay_status(self, bay_id, payload, headers):
        return self._request("POST", f"/dealership/service-bays/{bay_id}/set-status", payload, headers)

    def create_mobile_service_unit(self, payload, headers):
        return self._request("POST", "/dealership/mobile-service-units", payload, headers)

    def list_mobile_service_units(self, headers, params=None):
        return self._request("GET", "/dealership/mobile-service-units", headers=headers, params=params)

    def get_mobile_service_unit(self, msu_id, headers):
        return self._request("GET", f"/dealership/mobile-service-units/{msu_id}", headers=headers)

    def set_mobile_service_unit_status(self, msu_id, payload, headers):
        return self._request("POST", f"/dealership/mobile-service-units/{msu_id}/set-status", payload, headers)

    # --- RepairOrder ---
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/dealership/repair-orders", payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/dealership/repair-orders", headers=headers, params=params)

    def get_repair_order(self, ro_id, headers):
        return self._request("GET", f"/dealership/repair-orders/{ro_id}", headers=headers)

    def submit_estimate(self, ro_id, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/submit-estimate", {}, headers)

    def approve_estimate(self, ro_id, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/approve-estimate", {}, headers)

    def decline_estimate(self, ro_id, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/decline-estimate", {}, headers)

    def revise_estimate(self, ro_id, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/revise", {}, headers)

    def start_work(self, ro_id, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/start-work", {}, headers)

    def complete_work(self, ro_id, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/complete-work", {}, headers)

    def invoice_repair_order(self, ro_id, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/invoice", {}, headers)

    def post_ro_payment(self, ro_id, payload, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/post-payment", payload, headers)

    def cancel_repair_order(self, ro_id, headers):
        return self._request("POST", f"/dealership/repair-orders/{ro_id}/cancel", {}, headers)

    # --- RepairOrderLine ---
    def create_repair_order_line(self, payload, headers):
        return self._request("POST", "/dealership/repair-order-lines", payload, headers)

    def list_repair_order_lines(self, headers, params=None):
        return self._request("GET", "/dealership/repair-order-lines", headers=headers, params=params)

    def get_repair_order_line(self, line_id, headers):
        return self._request("GET", f"/dealership/repair-order-lines/{line_id}", headers=headers)

    # --- ServiceBooking ---
    def create_service_booking(self, payload, headers):
        return self._request("POST", "/dealership/service-bookings", payload, headers)

    def list_service_bookings(self, headers, params=None):
        return self._request("GET", "/dealership/service-bookings", headers=headers, params=params)

    def get_service_booking(self, booking_id, headers):
        return self._request("GET", f"/dealership/service-bookings/{booking_id}", headers=headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/dealership/service-bookings/{booking_id}/check-in", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/dealership/service-bookings/{booking_id}/cancel", {}, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/dealership/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/dealership/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/dealership/warranty-claims/{claim_id}", headers=headers)

    def submit_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/dealership/warranty-claims/{claim_id}/submit", {}, headers)

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/dealership/warranty-claims/{claim_id}/adjudicate", payload, headers)

    def appeal_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/dealership/warranty-claims/{claim_id}/appeal", payload, headers)

    def close_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/dealership/warranty-claims/{claim_id}/close", {}, headers)

    def post_claim_payment(self, claim_id, payload, headers):
        return self._request("POST", f"/dealership/warranty-claims/{claim_id}/post-payment", payload, headers)

    def write_off_claim(self, claim_id, headers):
        return self._request("POST", f"/dealership/warranty-claims/{claim_id}/write-off", {}, headers)

    # --- Part / PartsSale ---
    def create_part(self, payload, headers):
        return self._request("POST", "/dealership/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/dealership/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/dealership/parts/{part_id}", headers=headers)

    def discontinue_part(self, part_id, headers):
        return self._request("POST", f"/dealership/parts/{part_id}/discontinue", {}, headers)

    def create_parts_sale(self, payload, headers):
        return self._request("POST", "/dealership/parts-sales", payload, headers)

    def list_parts_sales(self, headers, params=None):
        return self._request("GET", "/dealership/parts-sales", headers=headers, params=params)

    def get_parts_sale(self, sale_id, headers):
        return self._request("GET", f"/dealership/parts-sales/{sale_id}", headers=headers)

    def list_parts_sale_lines(self, headers, params=None):
        return self._request("GET", "/dealership/parts-sale-lines", headers=headers, params=params)

    def get_parts_sale_line(self, line_id, headers):
        return self._request("GET", f"/dealership/parts-sale-lines/{line_id}", headers=headers)

    def return_parts_sale_line(self, line_id, payload, headers):
        return self._request("POST", f"/dealership/parts-sale-lines/{line_id}/return", payload, headers)


api_client = ApiClient()
