"""API client: one method per endpoint defined in the Quick Lube & Oil Change PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ───────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ─── Shop ─────────────────────────────────────────
    def create_shop(self, payload, headers):
        return self._request("POST", "/shops", payload, headers)

    def list_shops(self, headers, params=None):
        return self._request("GET", "/shops", headers=headers, params=params)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    # ─── ServicePackage ───────────────────────────────
    def create_service_package(self, payload, headers):
        return self._request("POST", "/service-packages", payload, headers)

    def list_service_packages(self, headers, params=None):
        return self._request("GET", "/service-packages", headers=headers, params=params)

    def get_service_package(self, package_id, headers):
        return self._request("GET", f"/service-packages/{package_id}", headers=headers)

    def retire_service_package(self, package_id, headers):
        return self._request("POST", f"/service-packages/{package_id}/retire", headers=headers)

    # ─── InspectionItem ───────────────────────────────
    def create_inspection_item(self, payload, headers):
        return self._request("POST", "/inspection-items", payload, headers)

    def list_inspection_items(self, headers, params=None):
        return self._request("GET", "/inspection-items", headers=headers, params=params)

    def get_inspection_item(self, item_id, headers):
        return self._request("GET", f"/inspection-items/{item_id}", headers=headers)

    # ─── Coupon ───────────────────────────────────────
    def create_coupon(self, payload, headers):
        return self._request("POST", "/coupons", payload, headers)

    def list_coupons(self, headers, params=None):
        return self._request("GET", "/coupons", headers=headers, params=params)

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"/coupons/{coupon_id}", headers=headers)

    def expire_coupon(self, coupon_id, headers):
        return self._request("POST", f"/coupons/{coupon_id}/expire", headers=headers)

    # ─── FleetAccount ─────────────────────────────────
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/fleet-accounts", payload, headers)

    def list_fleet_accounts(self, headers, params=None):
        return self._request("GET", "/fleet-accounts", headers=headers, params=params)

    def get_fleet_account(self, account_id, headers):
        return self._request("GET", f"/fleet-accounts/{account_id}", headers=headers)

    def list_fleet_account_vehicles(self, account_id, headers, params=None):
        return self._request("GET", f"/fleet-accounts/{account_id}/vehicles", headers=headers, params=params)

    def suspend_fleet_account(self, account_id, headers):
        return self._request("POST", f"/fleet-accounts/{account_id}/suspend", headers=headers)

    def reactivate_fleet_account(self, account_id, headers):
        return self._request("POST", f"/fleet-accounts/{account_id}/reactivate", headers=headers)

    def close_fleet_account(self, account_id, headers):
        return self._request("POST", f"/fleet-accounts/{account_id}/close", headers=headers)

    # ─── Vehicle ──────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_work_orders(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/work-orders", headers=headers, params=params)

    # ─── Bay ──────────────────────────────────────────
    def create_bay(self, payload, headers):
        return self._request("POST", "/bays", payload, headers)

    def list_bays(self, headers, params=None):
        return self._request("GET", "/bays", headers=headers, params=params)

    def get_bay(self, bay_id, headers):
        return self._request("GET", f"/bays/{bay_id}", headers=headers)

    def close_bay(self, bay_id, headers):
        return self._request("POST", f"/bays/{bay_id}/close", headers=headers)

    def reopen_bay(self, bay_id, headers):
        return self._request("POST", f"/bays/{bay_id}/reopen", headers=headers)

    # ─── Technician ───────────────────────────────────
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # ─── QueueTicket ──────────────────────────────────
    def create_queue_ticket(self, payload, headers):
        return self._request("POST", "/queue-tickets", payload, headers)

    def list_queue_tickets(self, headers, params=None):
        return self._request("GET", "/queue-tickets", headers=headers, params=params)

    def get_queue_ticket(self, ticket_id, headers):
        return self._request("GET", f"/queue-tickets/{ticket_id}", headers=headers)

    def assign_queue_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/queue-tickets/{ticket_id}/assign", payload, headers)

    def requeue_queue_ticket(self, ticket_id, headers):
        return self._request("POST", f"/queue-tickets/{ticket_id}/requeue", headers=headers)

    def cancel_queue_ticket(self, ticket_id, headers):
        return self._request("POST", f"/queue-tickets/{ticket_id}/cancel", headers=headers)

    # ─── WorkOrder ────────────────────────────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def claim_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/claim", payload, headers)

    def apply_coupon(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/apply-coupon", payload, headers)

    def add_line(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/lines", payload, headers)

    def list_lines(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/lines", headers=headers, params=params)

    def remove_line(self, work_order_id, line_id, headers):
        return self._request("DELETE", f"/work-orders/{work_order_id}/lines/{line_id}", headers=headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", headers=headers)

    def begin_inspection(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/begin-inspection", headers=headers)

    def finish_inspection(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/finish-inspection", headers=headers)

    def mark_ready(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/mark-ready", headers=headers)

    def authorize_payment(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/authorize", payload, headers)

    def capture_payment(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/capture-payment", headers=headers)

    def void_payment(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/void-payment", headers=headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", headers=headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", headers=headers)

    def get_sticker(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/sticker", headers=headers, params=params)

    def list_payments(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/payments", headers=headers, params=params)


api_client = ApiClient()
