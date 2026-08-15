"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sites & dashboard ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def get_site_dashboard(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}/dashboard", headers=headers)

    # --- Fuel prices ---
    def create_fuel_price(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/fuel-prices", payload, headers)

    def list_fuel_prices(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/fuel-prices", headers=headers, params=params)

    def get_fuel_price(self, price_id, headers):
        return self._request("GET", f"/fuel-prices/{price_id}", headers=headers)

    # --- Pumps ---
    def create_pump(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/pumps", payload, headers)

    def list_pumps(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/pumps", headers=headers, params=params)

    def get_pump(self, pump_id, headers):
        return self._request("GET", f"/pumps/{pump_id}", headers=headers)

    def pump_out_of_service(self, pump_id, headers):
        return self._request("POST", f"/pumps/{pump_id}/out-of-service", headers=headers)

    def pump_return_to_service(self, pump_id, headers):
        return self._request("POST", f"/pumps/{pump_id}/return-to-service", headers=headers)

    def list_pump_fuel_sales(self, pump_id, headers, params=None):
        return self._request("GET", f"/pumps/{pump_id}/fuel-sales", headers=headers, params=params)

    # --- Fuel sales ---
    def create_fuel_sale(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/fuel-sales", payload, headers)

    def list_fuel_sales(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/fuel-sales", headers=headers, params=params)

    def get_fuel_sale(self, sale_id, headers):
        return self._request("GET", f"/fuel-sales/{sale_id}", headers=headers)

    def fuel_sale_dispensing_start(self, sale_id, headers):
        return self._request("POST", f"/fuel-sales/{sale_id}/dispensing-start", headers=headers)

    def fuel_sale_dispensing_complete(self, sale_id, payload, headers):
        return self._request("POST", f"/fuel-sales/{sale_id}/dispensing-complete", payload, headers)

    def fuel_sale_finalize(self, sale_id, headers):
        return self._request("POST", f"/fuel-sales/{sale_id}/finalize", headers=headers)

    def fuel_sale_pay(self, sale_id, payload, headers):
        return self._request("POST", f"/fuel-sales/{sale_id}/pay", payload, headers)

    def fuel_sale_void(self, sale_id, payload, headers):
        return self._request("POST", f"/fuel-sales/{sale_id}/void", payload, headers)

    # --- Parking spaces ---
    def create_parking_space(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/parking-spaces", payload, headers)

    def list_parking_spaces(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/parking-spaces", headers=headers, params=params)

    def get_parking_space(self, space_id, headers):
        return self._request("GET", f"/parking-spaces/{space_id}", headers=headers)

    def list_parking_space_reservations(self, space_id, headers, params=None):
        return self._request("GET", f"/parking-spaces/{space_id}/reservations", headers=headers, params=params)

    # --- Parking reservations ---
    def create_parking_reservation(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/parking-reservations", payload, headers)

    def list_parking_reservations(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/parking-reservations", headers=headers, params=params)

    def get_parking_reservation(self, reservation_id, headers):
        return self._request("GET", f"/parking-reservations/{reservation_id}", headers=headers)

    def parking_reservation_check_in(self, reservation_id, payload, headers):
        return self._request("POST", f"/parking-reservations/{reservation_id}/check-in", payload, headers)

    def parking_reservation_check_out(self, reservation_id, headers):
        return self._request("POST", f"/parking-reservations/{reservation_id}/check-out", headers=headers)

    def parking_reservation_cancel(self, reservation_id, headers):
        return self._request("POST", f"/parking-reservations/{reservation_id}/cancel", headers=headers)

    def parking_reservation_no_show(self, reservation_id, headers):
        return self._request("POST", f"/parking-reservations/{reservation_id}/no-show", headers=headers)

    # --- Service queue ---
    def create_service_ticket(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/service-tickets", payload, headers)

    def list_service_tickets(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/service-tickets", headers=headers, params=params)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def call_service_queue(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/service-queue/call", payload, headers)

    def service_ticket_start(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/start", headers=headers)

    def service_ticket_complete(self, ticket_id, payload, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/complete", payload, headers)

    def service_ticket_pay(self, ticket_id, payload, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/pay", payload, headers)

    def service_ticket_cancel(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/cancel", headers=headers)

    def service_ticket_no_show(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/no-show", headers=headers)

    def service_ticket_requeue(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/requeue", headers=headers)

    # --- Scale ---
    def create_scale_ticket(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/scale-tickets", payload, headers)

    def list_scale_tickets(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/scale-tickets", headers=headers, params=params)

    def get_scale_ticket(self, ticket_id, headers):
        return self._request("GET", f"/scale-tickets/{ticket_id}", headers=headers)

    def scale_ticket_weigh(self, ticket_id, payload, headers):
        return self._request("POST", f"/scale-tickets/{ticket_id}/weigh", payload, headers)

    def list_scale_weigh_events(self, ticket_id, headers, params=None):
        return self._request("GET", f"/scale-tickets/{ticket_id}/weigh-events", headers=headers, params=params)

    def scale_ticket_settle(self, ticket_id, payload, headers):
        return self._request("POST", f"/scale-tickets/{ticket_id}/settle", payload, headers)

    def scale_ticket_close(self, ticket_id, headers):
        return self._request("POST", f"/scale-tickets/{ticket_id}/close", headers=headers)

    def scale_ticket_cancel(self, ticket_id, headers):
        return self._request("POST", f"/scale-tickets/{ticket_id}/cancel", headers=headers)

    # --- Stock items & vendors ---
    def create_stock_item(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/stock-items", payload, headers)

    def list_stock_items(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/stock-items", headers=headers, params=params)

    def get_stock_item(self, item_id, headers):
        return self._request("GET", f"/stock-items/{item_id}", headers=headers)

    def list_stock_item_work_order_parts(self, item_id, headers, params=None):
        return self._request("GET", f"/stock-items/{item_id}/work-order-parts", headers=headers, params=params)

    def create_vendor(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/vendors", payload, headers)

    def list_vendors(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def create_vendor_price(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/price-list", payload, headers)

    def list_vendor_prices(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/price-list", headers=headers, params=params)

    def list_vendor_stock_items(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/stock-items", headers=headers, params=params)

    def list_vendor_purchase_orders(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/purchase-orders", headers=headers, params=params)

    def list_vendor_deliveries(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/deliveries", headers=headers, params=params)

    # --- Purchase orders ---
    def create_purchase_order(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/purchase-orders", payload, headers)

    def list_purchase_orders(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def purchase_order_approve(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/approve", headers=headers)

    def purchase_order_receive(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/receive", payload, headers)

    def purchase_order_cancel(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", headers=headers)

    # --- Shop bays & technicians ---
    def create_bay(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/bays", payload, headers)

    def list_bays(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/bays", headers=headers, params=params)

    def get_bay(self, bay_id, headers):
        return self._request("GET", f"/bays/{bay_id}", headers=headers)

    def list_bay_work_orders(self, bay_id, headers, params=None):
        return self._request("GET", f"/bays/{bay_id}/work-orders", headers=headers, params=params)

    def bay_maintenance_block(self, bay_id, payload, headers):
        return self._request("POST", f"/bays/{bay_id}/maintenance-block", payload, headers)

    def bay_maintenance_clear(self, bay_id, headers):
        return self._request("POST", f"/bays/{bay_id}/maintenance-clear", headers=headers)

    def create_technician(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/technicians", payload, headers)

    def list_technicians(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/technicians", headers=headers, params=params)

    def get_technician(self, tech_id, headers):
        return self._request("GET", f"/technicians/{tech_id}", headers=headers)

    def list_technician_work_orders(self, tech_id, headers, params=None):
        return self._request("GET", f"/technicians/{tech_id}/work-orders", headers=headers, params=params)

    # --- Work orders ---
    def create_work_order(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/work-orders", payload, headers)

    def list_work_orders(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/work-orders", headers=headers, params=params)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def work_order_estimate(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/estimate", payload, headers)

    def work_order_approve_estimate(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/approve-estimate", headers=headers)

    def work_order_schedule(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/schedule", payload, headers)

    def work_order_check_in(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/check-in", headers=headers)

    def work_order_start_work(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/start-work", headers=headers)

    def work_order_issue_part(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/parts", payload, headers)

    def list_work_order_parts(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/parts", headers=headers, params=params)

    def work_order_part_return(self, part_id, payload, headers):
        return self._request("POST", f"/work-order-parts/{part_id}/return", payload, headers)

    def work_order_dispatch_road(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/dispatch-road", payload, headers)

    def work_order_road_complete(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/road-complete", payload, headers)

    def work_order_send_to_vendor(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/send-to-vendor", payload, headers)

    def work_order_return_from_vendor(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/return-from-vendor", headers=headers)

    def work_order_complete_work(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/complete-work", payload, headers)

    def work_order_close(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/close", payload, headers)

    def work_order_cancel(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/cancel", headers=headers)

    # --- Registers & shifts ---
    def create_register(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/registers", payload, headers)

    def list_registers(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/registers", headers=headers, params=params)

    def get_register(self, register_id, headers):
        return self._request("GET", f"/registers/{register_id}", headers=headers)

    def list_register_shifts(self, register_id, headers, params=None):
        return self._request("GET", f"/registers/{register_id}/shifts", headers=headers, params=params)

    def list_register_cash_drops(self, register_id, headers, params=None):
        return self._request("GET", f"/registers/{register_id}/cash-drops", headers=headers, params=params)

    def list_register_safe_deposits(self, register_id, headers, params=None):
        return self._request("GET", f"/registers/{register_id}/safe-deposits", headers=headers, params=params)

    def create_shift(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/shifts", payload, headers)

    def list_shifts(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def shift_drop(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/drops", payload, headers)

    def shift_payout(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/payouts", payload, headers)

    def shift_close(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/close", payload, headers)

    def shift_reconcile(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/reconcile", headers=headers)

    def shift_lock(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/lock", headers=headers)

    def list_shift_reconciliations(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/reconciliations", headers=headers, params=params)

    def list_shift_cash_drops(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/cash-drops", headers=headers, params=params)

    def list_shift_safe_deposits(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/safe-deposits", headers=headers, params=params)

    def list_shift_fuel_sales(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/fuel-sales", headers=headers, params=params)

    def list_shift_parking_reservations(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/parking-reservations", headers=headers, params=params)

    def list_shift_service_tickets(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/service-tickets", headers=headers, params=params)

    def list_shift_scale_tickets(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/scale-tickets", headers=headers, params=params)

    def list_shift_store_sales(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/store-sales", headers=headers, params=params)

    # --- Fleet accounts ---
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/fleet-accounts", payload, headers)

    def get_fleet_account(self, fleet_id, headers):
        return self._request("GET", f"/fleet-accounts/{fleet_id}", headers=headers)

    def update_fleet_account(self, fleet_id, payload, headers):
        return self._request("PATCH", f"/fleet-accounts/{fleet_id}", payload, headers)

    def fleet_credit_hold(self, fleet_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_id}/credit-hold", headers=headers)

    def fleet_credit_reinstate(self, fleet_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_id}/credit-reinstate", headers=headers)

    def fleet_close(self, fleet_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_id}/close", headers=headers)

    def fleet_tier_recompute(self, fleet_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_id}/tier-recompute", headers=headers)

    def list_fleet_contracts(self, fleet_id, headers, params=None):
        return self._request("GET", f"/fleet-accounts/{fleet_id}/contracts", headers=headers, params=params)

    def list_fleet_loyalty_members(self, fleet_id, headers, params=None):
        return self._request("GET", f"/fleet-accounts/{fleet_id}/loyalty-members", headers=headers, params=params)

    def list_fleet_fuel_sales(self, fleet_id, headers, params=None):
        return self._request("GET", f"/fleet-accounts/{fleet_id}/fuel-sales", headers=headers, params=params)

    def list_fleet_work_orders(self, fleet_id, headers, params=None):
        return self._request("GET", f"/fleet-accounts/{fleet_id}/work-orders", headers=headers, params=params)

    # --- Contracts ---
    def create_contract(self, fleet_id, payload, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_id}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def amend_contract(self, contract_id, payload, headers):
        return self._request("PATCH", f"/contracts/{contract_id}", payload, headers)

    def contract_activate(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", headers=headers)

    def contract_suspend(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/suspend", headers=headers)

    def contract_resume(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/resume", headers=headers)

    def contract_expire(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/expire", headers=headers)

    def contract_terminate(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", headers=headers)

    def list_contract_fuel_sales(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/fuel-sales", headers=headers, params=params)

    # --- Loyalty members, vehicles, enrollments, networks ---
    def create_loyalty_member(self, payload, headers):
        return self._request("POST", "/loyalty-members", payload, headers)

    def get_loyalty_member(self, member_id, headers):
        return self._request("GET", f"/loyalty-members/{member_id}", headers=headers)

    def member_suspend(self, member_id, headers):
        return self._request("POST", f"/loyalty-members/{member_id}/suspend", headers=headers)

    def member_reactivate(self, member_id, headers):
        return self._request("POST", f"/loyalty-members/{member_id}/reactivate", headers=headers)

    def member_close(self, member_id, headers):
        return self._request("POST", f"/loyalty-members/{member_id}/close", headers=headers)

    def member_adjustment(self, member_id, payload, headers):
        return self._request("POST", f"/loyalty-members/{member_id}/adjustments", payload, headers)

    def list_member_points_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/points-ledger", headers=headers, params=params)

    def create_member_vehicle(self, member_id, payload, headers):
        return self._request("POST", f"/loyalty-members/{member_id}/vehicles", payload, headers)

    def list_member_vehicles(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/vehicles", headers=headers, params=params)

    def create_member_enrollment(self, member_id, payload, headers):
        return self._request("POST", f"/loyalty-members/{member_id}/discount-enrollments", payload, headers)

    def list_member_enrollments(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/discount-enrollments", headers=headers, params=params)

    def list_member_fuel_sales(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/fuel-sales", headers=headers, params=params)

    def list_member_parking_reservations(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/parking-reservations", headers=headers, params=params)

    def list_member_service_tickets(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/service-tickets", headers=headers, params=params)

    def list_member_store_sales(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/store-sales", headers=headers, params=params)

    def create_discount_network(self, payload, headers):
        return self._request("POST", "/discount-networks", payload, headers)

    def get_discount_network(self, network_id, headers):
        return self._request("GET", f"/discount-networks/{network_id}", headers=headers)

    def list_network_enrollments(self, network_id, headers, params=None):
        return self._request("GET", f"/discount-networks/{network_id}/enrollments", headers=headers, params=params)

    def network_activate(self, network_id, headers):
        return self._request("POST", f"/discount-networks/{network_id}/activate", headers=headers)

    def network_retire(self, network_id, headers):
        return self._request("POST", f"/discount-networks/{network_id}/retire", headers=headers)

    def enrollment_activate(self, enrollment_id, headers):
        return self._request("POST", f"/discount-enrollments/{enrollment_id}/activate", headers=headers)

    def enrollment_suspend(self, enrollment_id, headers):
        return self._request("POST", f"/discount-enrollments/{enrollment_id}/suspend", headers=headers)

    def enrollment_resume(self, enrollment_id, headers):
        return self._request("POST", f"/discount-enrollments/{enrollment_id}/resume", headers=headers)

    def enrollment_cancel(self, enrollment_id, headers):
        return self._request("POST", f"/discount-enrollments/{enrollment_id}/cancel", headers=headers)

    # --- Store sales ---
    def create_store_sale(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/store-sales", payload, headers)

    def list_store_sales(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/store-sales", headers=headers, params=params)

    def get_store_sale(self, sale_id, headers):
        return self._request("GET", f"/store-sales/{sale_id}", headers=headers)

    def store_sale_refund(self, sale_id, payload, headers):
        return self._request("POST", f"/store-sales/{sale_id}/refund", payload, headers)

    # --- Bulk tanks & deliveries ---
    def create_bulk_tank(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/bulk-tanks", payload, headers)

    def list_bulk_tanks(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/bulk-tanks", headers=headers, params=params)

    def get_bulk_tank(self, tank_id, headers):
        return self._request("GET", f"/bulk-tanks/{tank_id}", headers=headers)

    def tank_stick_reading(self, tank_id, payload, headers):
        return self._request("POST", f"/bulk-tanks/{tank_id}/stick-reading", payload, headers)

    def tank_delivery(self, tank_id, payload, headers):
        return self._request("POST", f"/bulk-tanks/{tank_id}/deliveries", payload, headers)

    def list_tank_deliveries(self, tank_id, headers, params=None):
        return self._request("GET", f"/bulk-tanks/{tank_id}/deliveries", headers=headers, params=params)

    def get_reorder_suggestions(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}/reorder-suggestions", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
