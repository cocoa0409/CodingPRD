"""API client: one method per endpoint defined in the PRD (all under /lab)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Warehouses ---
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/lab/warehouses", payload, headers)

    def list_warehouses(self, headers, params=None):
        return self._request("GET", "/lab/warehouses", headers=headers, params=params)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/lab/warehouses/{warehouse_id}", headers=headers)

    def suspend_warehouse(self, warehouse_id, headers):
        return self._request("POST", f"/lab/warehouses/{warehouse_id}/suspend", {}, headers)

    def resume_warehouse(self, warehouse_id, headers):
        return self._request("POST", f"/lab/warehouses/{warehouse_id}/resume", {}, headers)

    # --- Storage zones ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/lab/storage-zones", payload, headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/lab/storage-zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/lab/storage-zones/{zone_id}", headers=headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/lab/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/lab/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/lab/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/lab/products/{product_id}/discontinue", {}, headers)

    # --- Reagent lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/lab/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lab/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lab/lots/{lot_id}", headers=headers)

    def adjust_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lab/lots/{lot_id}/adjustments", payload, headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/lab/lots/{lot_id}/quarantine", {}, headers)

    def release_lot_quarantine(self, lot_id, headers):
        return self._request("POST", f"/lab/lots/{lot_id}/release-quarantine", {}, headers)

    # --- Customer accounts ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/lab/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/lab/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/lab/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/lab/customers/{customer_id}", payload, headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/lab/customers/{customer_id}/suspend", {}, headers)

    def reactivate_customer(self, customer_id, headers):
        return self._request("POST", f"/lab/customers/{customer_id}/reactivate", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/lab/customers/{customer_id}/close", {}, headers)

    def record_payment(self, customer_id, payload, headers):
        return self._request("POST", f"/lab/customers/{customer_id}/payments", payload, headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/lab/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/lab/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/lab/orders/{order_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/lab/orders/{order_id}/submit", {}, headers)

    def reallocate_order(self, order_id, payload, headers):
        return self._request("POST", f"/lab/orders/{order_id}/reallocate", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/lab/orders/{order_id}/cancel", {}, headers)

    def get_cost_summary(self, order_id, headers):
        return self._request("GET", f"/lab/orders/{order_id}/cost-summary", headers=headers)

    # --- Order lines ---
    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/lab/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/lab/order-lines/{order_line_id}", headers=headers)

    # --- Lot reservations ---
    def list_reservations(self, headers, params=None):
        return self._request("GET", "/lab/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/lab/reservations/{reservation_id}", headers=headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"/lab/reservations/{reservation_id}/release", {}, headers)

    # --- Shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/lab/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/lab/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/lab/shipments/{shipment_id}", headers=headers)

    def pack_shipment(self, shipment_id, headers):
        return self._request("POST", f"/lab/shipments/{shipment_id}/pack", {}, headers)

    def dispatch_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/lab/shipments/{shipment_id}/dispatch", payload, headers)

    def record_temperature(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/lab/shipments/{shipment_id}/record-temperature", payload, headers
        )

    def resume_transit(self, shipment_id, headers):
        return self._request("POST", f"/lab/shipments/{shipment_id}/resume-transit", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/lab/shipments/{shipment_id}/deliver", {}, headers)

    # --- Temperature excursions ---
    def list_excursions(self, headers, params=None):
        return self._request("GET", "/lab/excursions", headers=headers, params=params)

    def get_excursion(self, excursion_id, headers):
        return self._request("GET", f"/lab/excursions/{excursion_id}", headers=headers)

    def disposition_excursion(self, excursion_id, payload, headers):
        return self._request(
            "POST", f"/lab/excursions/{excursion_id}/disposition", payload, headers
        )

    # --- Standing orders ---
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/lab/standing-orders", payload, headers)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/lab/standing-orders", headers=headers, params=params)

    def get_standing_order(self, standing_order_id, headers):
        return self._request(
            "GET", f"/lab/standing-orders/{standing_order_id}", headers=headers
        )

    def pause_standing_order(self, standing_order_id, headers):
        return self._request(
            "POST", f"/lab/standing-orders/{standing_order_id}/pause", {}, headers
        )

    def resume_standing_order(self, standing_order_id, headers):
        return self._request(
            "POST", f"/lab/standing-orders/{standing_order_id}/resume", {}, headers
        )

    def cancel_standing_order(self, standing_order_id, headers):
        return self._request(
            "POST", f"/lab/standing-orders/{standing_order_id}/cancel", {}, headers
        )

    # --- Consignment ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/lab/consignment-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/lab/consignment-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/lab/consignment-agreements/{agreement_id}", headers=headers
        )

    def suspend_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/lab/consignment-agreements/{agreement_id}/suspend", {}, headers
        )

    def reactivate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/lab/consignment-agreements/{agreement_id}/reactivate", {}, headers
        )

    def close_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/lab/consignment-agreements/{agreement_id}/close", {}, headers
        )

    def record_consumption(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/lab/consignment-agreements/{agreement_id}/consumption", payload, headers
        )

    def list_consumption_records(self, headers, params=None):
        return self._request("GET", "/lab/consumption-records", headers=headers, params=params)

    def get_consumption_record(self, record_id, headers):
        return self._request("GET", f"/lab/consumption-records/{record_id}", headers=headers)

    # --- Recalls ---
    def create_recall(self, payload, headers):
        return self._request("POST", "/lab/recalls", payload, headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/lab/recalls", headers=headers, params=params)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/lab/recalls/{recall_id}", headers=headers)

    def issue_recall(self, recall_id, headers):
        return self._request("POST", f"/lab/recalls/{recall_id}/issue", {}, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/lab/recalls/{recall_id}/close", {}, headers)

    # --- Kits ---
    def create_kit(self, payload, headers):
        return self._request("POST", "/lab/kits", payload, headers)

    def list_kits(self, headers, params=None):
        return self._request("GET", "/lab/kits", headers=headers, params=params)

    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/lab/kits/{kit_id}", headers=headers)

    def activate_kit(self, kit_id, headers):
        return self._request("POST", f"/lab/kits/{kit_id}/activate", {}, headers)

    def retire_kit(self, kit_id, headers):
        return self._request("POST", f"/lab/kits/{kit_id}/retire", {}, headers)

    # --- Kit assembly jobs ---
    def create_job(self, payload, headers):
        return self._request("POST", "/lab/kit-assembly-jobs", payload, headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/lab/kit-assembly-jobs", headers=headers, params=params)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/lab/kit-assembly-jobs/{job_id}", headers=headers)

    def execute_job(self, job_id, headers):
        return self._request("POST", f"/lab/kit-assembly-jobs/{job_id}/execute", {}, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/lab/kit-assembly-jobs/{job_id}/cancel", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/lab/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
