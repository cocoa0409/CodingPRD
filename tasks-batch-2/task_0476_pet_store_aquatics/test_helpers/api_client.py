"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Stores -----------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    # ---- Products ---------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ---- Inventory lots ---------------------------------------------------
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def adjust_inventory_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/inventory-lots/{lot_id}/adjust", payload, headers
        )

    # ---- Livestock batches ------------------------------------------------
    def create_livestock_batch(self, payload, headers):
        return self._request("POST", "/livestock-batches", payload, headers)

    def get_livestock_batch(self, batch_id, headers):
        return self._request("GET", f"/livestock-batches/{batch_id}", headers=headers)

    def list_livestock_batches(self, headers, params=None):
        return self._request(
            "GET", "/livestock-batches", headers=headers, params=params
        )

    def clear_quarantine(self, batch_id, headers):
        return self._request(
            "POST", f"/livestock-batches/{batch_id}/clear-quarantine", headers=headers
        )

    def record_mortality(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/livestock-batches/{batch_id}/record-mortality", payload, headers
        )

    def list_on_floor(self, batch_id, headers):
        return self._request(
            "POST", f"/livestock-batches/{batch_id}/list-on-floor", headers=headers
        )

    def condemn_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/livestock-batches/{batch_id}/condemn", headers=headers
        )

    # ---- Livestock sales --------------------------------------------------
    def create_livestock_sale(self, payload, headers):
        return self._request("POST", "/livestock-sales", payload, headers)

    # ---- Customers --------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ---- Prescriptions ----------------------------------------------------
    def create_prescription(self, payload, headers):
        return self._request("POST", "/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request(
            "GET", f"/prescriptions/{prescription_id}", headers=headers
        )

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    def revoke_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/revoke", headers=headers
        )

    # ---- Clinic appointments ----------------------------------------------
    def create_clinic_appointment(self, payload, headers):
        return self._request("POST", "/clinic-appointments", payload, headers)

    def get_clinic_appointment(self, appt_id, headers):
        return self._request(
            "GET", f"/clinic-appointments/{appt_id}", headers=headers
        )

    def list_clinic_appointments(self, headers, params=None):
        return self._request(
            "GET", "/clinic-appointments", headers=headers, params=params
        )

    def check_in_appointment(self, appt_id, headers):
        return self._request(
            "POST", f"/clinic-appointments/{appt_id}/check-in", headers=headers
        )

    def complete_appointment(self, appt_id, headers):
        return self._request(
            "POST", f"/clinic-appointments/{appt_id}/complete", headers=headers
        )

    def cancel_appointment(self, appt_id, headers):
        return self._request(
            "POST", f"/clinic-appointments/{appt_id}/cancel", headers=headers
        )

    def no_show_appointment(self, appt_id, headers):
        return self._request(
            "POST", f"/clinic-appointments/{appt_id}/no-show", headers=headers
        )

    # ---- Subscriptions / shipments ----------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def pause_subscription(self, sub_id, headers):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/pause", headers=headers
        )

    def resume_subscription(self, sub_id, headers):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/resume", headers=headers
        )

    def cancel_subscription(self, sub_id, headers):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/cancel", headers=headers
        )

    def run_shipment(self, sub_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/run-shipment", payload, headers
        )

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    # ---- Special orders ---------------------------------------------------
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def allocate_special_order(self, order_id, headers):
        return self._request(
            "POST", f"/special-orders/{order_id}/allocate", headers=headers
        )

    def fulfill_special_order(self, order_id, headers):
        return self._request(
            "POST", f"/special-orders/{order_id}/fulfill", headers=headers
        )

    def cancel_special_order(self, order_id, headers):
        return self._request(
            "POST", f"/special-orders/{order_id}/cancel", headers=headers
        )

    # ---- Point-of-sale ----------------------------------------------------
    def create_product_sale(self, payload, headers):
        return self._request("POST", "/product-sales", payload, headers)

    # ---- Recalls ----------------------------------------------------------
    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/recalls", headers=headers, params=params)

    def resolve_recall(self, recall_id, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/resolve", headers=headers
        )

    # ---- Adoption events --------------------------------------------------
    def create_adoption_event(self, payload, headers):
        return self._request("POST", "/adoption-events", payload, headers)

    def get_adoption_event(self, event_id, headers):
        return self._request("GET", f"/adoption-events/{event_id}", headers=headers)

    def list_adoption_events(self, headers, params=None):
        return self._request("GET", "/adoption-events", headers=headers, params=params)

    def open_adoption_event(self, event_id, headers):
        return self._request(
            "POST", f"/adoption-events/{event_id}/open", headers=headers
        )

    def close_adoption_event(self, event_id, headers):
        return self._request(
            "POST", f"/adoption-events/{event_id}/close", headers=headers
        )

    # ---- Adoption placements ----------------------------------------------
    def create_adoption_placement(self, payload, headers):
        return self._request("POST", "/adoption-placements", payload, headers)

    def get_adoption_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/adoption-placements/{placement_id}", headers=headers
        )

    def list_adoption_placements(self, headers, params=None):
        return self._request(
            "GET", "/adoption-placements", headers=headers, params=params
        )

    def return_adoption_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/adoption-placements/{placement_id}/return", headers=headers
        )


api_client = ApiClient()
