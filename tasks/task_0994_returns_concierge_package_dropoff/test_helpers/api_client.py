"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Subscription plans ---
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/v1/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/subscription-plans/{plan_id}", headers=headers)

    def publish_subscription_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/subscription-plans/{plan_id}/publish", {}, headers)

    def retire_subscription_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/subscription-plans/{plan_id}/retire", {}, headers)

    # --- Merchant accounts ---
    def create_merchant_account(self, payload, headers):
        return self._request("POST", "/v1/merchant-accounts", payload, headers)

    def get_merchant_account(self, merchant_id, headers):
        return self._request("GET", f"/v1/merchant-accounts/{merchant_id}", headers=headers)

    def list_merchant_accounts(self, headers, params=None):
        return self._request("GET", "/v1/merchant-accounts", headers=headers, params=params)

    def suspend_merchant(self, merchant_id, headers):
        return self._request("POST", f"/v1/merchant-accounts/{merchant_id}/suspend", {}, headers)

    def reactivate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/v1/merchant-accounts/{merchant_id}/reactivate", {}, headers)

    def close_merchant(self, merchant_id, headers):
        return self._request("POST", f"/v1/merchant-accounts/{merchant_id}/close", {}, headers)

    def list_merchant_billing_cycles(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/v1/merchant-accounts/{merchant_id}/billing-cycles",
            headers=headers, params=params,
        )

    def list_merchant_return_orders(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"/v1/merchant-accounts/{merchant_id}/return-orders",
            headers=headers, params=params,
        )

    # --- Billing cycles ---
    def create_billing_cycle(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/v1/merchant-accounts/{merchant_id}/billing-cycles", payload, headers
        )

    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/v1/billing-cycles/{cycle_id}", headers=headers)

    def get_charge_preview(self, cycle_id, headers):
        return self._request(
            "GET", f"/v1/billing-cycles/{cycle_id}/charge-preview", headers=headers
        )

    def close_billing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/v1/billing-cycles/{cycle_id}/close", {}, headers)

    def settle_billing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/v1/billing-cycles/{cycle_id}/settle", {}, headers)

    def dispute_billing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/v1/billing-cycles/{cycle_id}/dispute", {}, headers)

    def resettle_billing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/v1/billing-cycles/{cycle_id}/resettle", {}, headers)

    # --- Shoppers ---
    def create_shopper(self, payload, headers):
        return self._request("POST", "/v1/shoppers", payload, headers)

    def get_shopper(self, shopper_id, headers):
        return self._request("GET", f"/v1/shoppers/{shopper_id}", headers=headers)

    def list_shopper_return_orders(self, shopper_id, headers, params=None):
        return self._request(
            "GET", f"/v1/shoppers/{shopper_id}/return-orders", headers=headers, params=params
        )

    def unrestrict_shopper(self, shopper_id, headers):
        return self._request("POST", f"/v1/shoppers/{shopper_id}/unrestrict", {}, headers)

    # --- Dropoff locations / locker slots ---
    def create_dropoff_location(self, payload, headers):
        return self._request("POST", "/v1/dropoff-locations", payload, headers)

    def get_dropoff_location(self, location_id, headers):
        return self._request("GET", f"/v1/dropoff-locations/{location_id}", headers=headers)

    def activate_location(self, location_id, headers):
        return self._request(
            "POST", f"/v1/dropoff-locations/{location_id}/activate", {}, headers
        )

    def pause_location(self, location_id, headers):
        return self._request("POST", f"/v1/dropoff-locations/{location_id}/pause", {}, headers)

    def resume_location(self, location_id, headers):
        return self._request("POST", f"/v1/dropoff-locations/{location_id}/resume", {}, headers)

    def decommission_location(self, location_id, headers):
        return self._request(
            "POST", f"/v1/dropoff-locations/{location_id}/decommission", {}, headers
        )

    def list_locker_slots(self, location_id, headers, params=None):
        return self._request(
            "GET", f"/v1/dropoff-locations/{location_id}/locker-slots",
            headers=headers, params=params,
        )

    def list_location_return_orders(self, location_id, headers, params=None):
        return self._request(
            "GET", f"/v1/dropoff-locations/{location_id}/return-orders",
            headers=headers, params=params,
        )

    def create_locker_slot(self, location_id, payload, headers):
        return self._request(
            "POST", f"/v1/dropoff-locations/{location_id}/locker-slots", payload, headers
        )

    def get_locker_slot(self, slot_id, headers):
        return self._request("GET", f"/v1/locker-slots/{slot_id}", headers=headers)

    def out_of_service_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/locker-slots/{slot_id}/out-of-service", {}, headers)

    def restore_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/locker-slots/{slot_id}/restore", {}, headers)

    def sweep_collect_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/locker-slots/{slot_id}/sweep-collect", {}, headers)

    # --- Return orders / items / labels ---
    def create_return_order(self, payload, headers):
        return self._request("POST", "/v1/return-orders", payload, headers)

    def get_return_order(self, order_id, headers):
        return self._request("GET", f"/v1/return-orders/{order_id}", headers=headers)

    def cancel_return_order(self, order_id, headers):
        return self._request("POST", f"/v1/return-orders/{order_id}/cancel", {}, headers)

    def change_return_order_method(self, order_id, payload, headers):
        return self._request("PATCH", f"/v1/return-orders/{order_id}/method", payload, headers)

    def list_return_order_items(self, order_id, headers):
        return self._request("GET", f"/v1/return-orders/{order_id}/items", headers=headers)

    def get_return_item(self, item_id, headers):
        return self._request("GET", f"/v1/return-items/{item_id}", headers=headers)

    def inspect_return_item(self, item_id, payload, headers):
        return self._request("POST", f"/v1/return-items/{item_id}/inspect", payload, headers)

    def issue_label(self, order_id, payload, headers):
        return self._request("POST", f"/v1/return-orders/{order_id}/labels", payload, headers)

    def get_label(self, label_id, headers):
        return self._request("GET", f"/v1/labels/{label_id}", headers=headers)

    def list_labels(self, headers, params=None):
        return self._request("GET", "/v1/labels", headers=headers, params=params)

    def void_label(self, label_id, headers):
        return self._request("POST", f"/v1/labels/{label_id}/void", {}, headers)

    def confirm_dropoff(self, order_id, payload, headers):
        return self._request(
            "POST", f"/v1/return-orders/{order_id}/confirm-dropoff", payload, headers
        )

    def receive_return_order(self, order_id, headers):
        return self._request("POST", f"/v1/return-orders/{order_id}/receive", {}, headers)

    # --- Slot reservations ---
    def create_slot_reservation(self, payload, headers):
        return self._request("POST", "/v1/slot-reservations", payload, headers)

    def get_slot_reservation(self, reservation_id, headers):
        return self._request("GET", f"/v1/slot-reservations/{reservation_id}", headers=headers)

    def list_slot_reservations(self, headers, params=None):
        return self._request("GET", "/v1/slot-reservations", headers=headers, params=params)

    def release_slot_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/v1/slot-reservations/{reservation_id}/release", {}, headers
        )

    def consume_slot_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/v1/slot-reservations/{reservation_id}/consume", {}, headers
        )

    # --- Courier zones / pickup appointments ---
    def create_courier_zone(self, payload, headers):
        return self._request("POST", "/v1/courier-zones", payload, headers)

    def get_courier_zone(self, zone_id, headers):
        return self._request("GET", f"/v1/courier-zones/{zone_id}", headers=headers)

    def create_pickup_appointment(self, payload, headers):
        return self._request("POST", "/v1/pickup-appointments", payload, headers)

    def get_pickup_appointment(self, appointment_id, headers):
        return self._request("GET", f"/v1/pickup-appointments/{appointment_id}", headers=headers)

    def list_pickup_appointments(self, headers, params=None):
        return self._request("GET", "/v1/pickup-appointments", headers=headers, params=params)

    def start_pickup(self, appointment_id, headers):
        return self._request(
            "POST", f"/v1/pickup-appointments/{appointment_id}/start", {}, headers
        )

    def collect_pickup(self, appointment_id, headers):
        return self._request(
            "POST", f"/v1/pickup-appointments/{appointment_id}/collect", {}, headers
        )

    def fail_pickup(self, appointment_id, headers):
        return self._request(
            "POST", f"/v1/pickup-appointments/{appointment_id}/fail", {}, headers
        )

    def reschedule_pickup(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/v1/pickup-appointments/{appointment_id}/reschedule", payload, headers
        )

    def cancel_pickup(self, appointment_id, headers):
        return self._request(
            "POST", f"/v1/pickup-appointments/{appointment_id}/cancel", {}, headers
        )

    # --- Carrier routes / consolidation totes ---
    def create_carrier_route(self, payload, headers):
        return self._request("POST", "/v1/carrier-routes", payload, headers)

    def get_carrier_route(self, route_id, headers):
        return self._request("GET", f"/v1/carrier-routes/{route_id}", headers=headers)

    def list_carrier_routes(self, headers, params=None):
        return self._request("GET", "/v1/carrier-routes", headers=headers, params=params)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/v1/carrier-routes/{route_id}/dispatch", {}, headers)

    def arrive_route(self, route_id, headers):
        return self._request("POST", f"/v1/carrier-routes/{route_id}/arrive", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/v1/carrier-routes/{route_id}/cancel", {}, headers)

    def create_consolidation_tote(self, payload, headers):
        return self._request("POST", "/v1/consolidation-totes", payload, headers)

    def get_consolidation_tote(self, tote_id, headers):
        return self._request("GET", f"/v1/consolidation-totes/{tote_id}", headers=headers)

    def list_consolidation_totes(self, headers, params=None):
        return self._request("GET", "/v1/consolidation-totes", headers=headers, params=params)

    def list_tote_return_orders(self, tote_id, headers):
        return self._request(
            "GET", f"/v1/consolidation-totes/{tote_id}/return-orders", headers=headers
        )

    def add_order_to_tote(self, tote_id, payload, headers):
        return self._request(
            "POST", f"/v1/consolidation-totes/{tote_id}/return-orders", payload, headers
        )

    def remove_order_from_tote(self, tote_id, payload, headers):
        return self._request(
            "POST", f"/v1/consolidation-totes/{tote_id}/return-orders/remove", payload, headers
        )

    def seal_tote(self, tote_id, headers):
        return self._request("POST", f"/v1/consolidation-totes/{tote_id}/seal", {}, headers)

    def unseal_tote(self, tote_id, headers):
        return self._request("POST", f"/v1/consolidation-totes/{tote_id}/unseal", {}, headers)

    def dispatch_tote(self, tote_id, headers):
        return self._request("POST", f"/v1/consolidation-totes/{tote_id}/dispatch", {}, headers)

    def arrive_tote(self, tote_id, headers):
        return self._request("POST", f"/v1/consolidation-totes/{tote_id}/arrive", {}, headers)

    def flag_tote_discrepancy(self, tote_id, payload, headers):
        return self._request(
            "POST", f"/v1/consolidation-totes/{tote_id}/flag-discrepancy", payload, headers
        )

    def reconcile_tote(self, tote_id, headers):
        return self._request(
            "POST", f"/v1/consolidation-totes/{tote_id}/reconcile", {}, headers
        )

    # --- Refund ledger / projection ---
    def list_refund_ledger(self, order_id, headers):
        return self._request(
            "GET", f"/v1/return-orders/{order_id}/refund-ledger", headers=headers
        )

    def append_ledger_entry(self, order_id, payload, headers):
        return self._request(
            "POST", f"/v1/return-orders/{order_id}/refund-ledger/entries", payload, headers
        )

    def get_refund_projection(self, order_id, headers):
        return self._request(
            "GET", f"/v1/return-orders/{order_id}/refund-projection", headers=headers
        )

    # --- Exception cases ---
    def create_exception_case(self, payload, headers):
        return self._request("POST", "/v1/exception-cases", payload, headers)

    def get_exception_case(self, case_id, headers):
        return self._request("GET", f"/v1/exception-cases/{case_id}", headers=headers)

    def list_exception_cases(self, headers, params=None):
        return self._request("GET", "/v1/exception-cases", headers=headers, params=params)

    def list_order_exception_cases(self, order_id, headers):
        return self._request(
            "GET", f"/v1/return-orders/{order_id}/exception-cases", headers=headers
        )

    def start_investigation(self, case_id, headers):
        return self._request(
            "POST", f"/v1/exception-cases/{case_id}/start-investigation", {}, headers
        )

    def request_shopper_info(self, case_id, headers):
        return self._request(
            "POST", f"/v1/exception-cases/{case_id}/request-shopper-info", {}, headers
        )

    def provide_shopper_info(self, case_id, payload, headers):
        return self._request(
            "POST", f"/v1/exception-cases/{case_id}/provide-shopper-info", payload, headers
        )

    def resolve_exception_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/v1/exception-cases/{case_id}/resolve", payload, headers
        )

    def appeal_exception_case(self, case_id, payload, headers):
        return self._request("POST", f"/v1/exception-cases/{case_id}/appeal", payload, headers)

    def close_exception_case(self, case_id, headers):
        return self._request("POST", f"/v1/exception-cases/{case_id}/close", {}, headers)

    # --- Test-driving endpoints (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/v1/_maintenance/run_sweep", {}, headers)


api_client = ApiClient()
