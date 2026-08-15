"""API client: one method per endpoint defined in the PRD (section 4)."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def get_sla_report(self, property_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/properties/{property_id}/sla-report", headers=headers, params=params
        )

    # --- Resident ---
    def create_resident(self, payload, headers):
        return self._request("POST", "/residents", payload, headers)

    def list_residents(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/residents", headers=headers, params=params)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    # --- Technician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def vendor_event(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/events", payload, headers)

    # --- Part ---
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def list_parts(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def patch_work_order(self, work_order_id, payload, headers):
        return self._request("PATCH", f"/work-orders/{work_order_id}", payload, headers)

    def dispatch_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/dispatch", payload, headers)

    def start_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", payload, headers)

    def sign_off_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/sign-off", payload, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def reopen_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/reopen", payload, headers)

    def close_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/close", payload, headers)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", payload, headers)

    # --- WorkOrderPart ---
    def reserve_part(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/parts", payload, headers)

    def release_part(self, work_order_id, work_order_part_id, payload, headers):
        return self._request(
            "POST",
            f"/work-orders/{work_order_id}/parts/{work_order_part_id}/release",
            payload,
            headers,
        )

    def list_work_order_parts(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/work-order-parts", headers=headers, params=params)

    def get_work_order_part(self, work_order_part_id, headers):
        return self._request("GET", f"/work-order-parts/{work_order_part_id}", headers=headers)

    # --- PurchaseRequest ---
    def create_purchase_request(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/purchase-requests", payload, headers
        )

    def list_purchase_requests(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/purchase-requests", headers=headers, params=params)

    def get_purchase_request(self, purchase_request_id, headers):
        return self._request(
            "GET", f"/purchase-requests/{purchase_request_id}", headers=headers
        )

    def purchase_request_event(self, purchase_request_id, payload, headers):
        return self._request(
            "POST", f"/purchase-requests/{purchase_request_id}/events", payload, headers
        )

    # --- Chargeback ---
    def list_chargebacks(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/chargebacks", headers=headers, params=params)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/chargebacks/{chargeback_id}", headers=headers)

    def chargeback_event(self, chargeback_id, payload, headers):
        return self._request("POST", f"/chargebacks/{chargeback_id}/events", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
