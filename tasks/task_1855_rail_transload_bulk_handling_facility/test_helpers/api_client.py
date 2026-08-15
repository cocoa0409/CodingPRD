"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/transload/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request(
            "GET", f"/transload/facilities/{facility_id}", headers=headers
        )

    def patch_facility(self, facility_id, payload, headers):
        return self._request(
            "PATCH", f"/transload/facilities/{facility_id}", payload, headers
        )

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/transload/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request(
            "GET", f"/transload/customers/{customer_id}", headers=headers
        )

    def patch_customer(self, customer_id, payload, headers):
        return self._request(
            "PATCH", f"/transload/customers/{customer_id}", payload, headers
        )

    def create_allocation_adjustment(self, customer_id, payload, headers):
        return self._request(
            "POST",
            f"/transload/customers/{customer_id}/allocation-adjustments",
            payload,
            headers,
        )

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/transload/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request(
            "GET", f"/transload/products/{product_id}", headers=headers
        )

    # --- Track ---
    def create_track(self, payload, headers):
        return self._request("POST", "/transload/tracks", payload, headers)

    def get_track(self, track_id, headers):
        return self._request("GET", f"/transload/tracks/{track_id}", headers=headers)

    def take_track_out_of_service(self, track_id, headers):
        return self._request(
            "POST", f"/transload/tracks/{track_id}/take-out-of-service", {}, headers
        )

    def restore_track_service(self, track_id, headers):
        return self._request(
            "POST", f"/transload/tracks/{track_id}/restore-service", {}, headers
        )

    def engage_derail(self, track_id, headers):
        return self._request(
            "POST", f"/transload/tracks/{track_id}/engage-derail", {}, headers
        )

    def disengage_derail(self, track_id, headers):
        return self._request(
            "POST", f"/transload/tracks/{track_id}/disengage-derail", {}, headers
        )

    # --- Equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/transload/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request(
            "GET", f"/transload/equipment/{equipment_id}", headers=headers
        )

    def list_equipment(self, headers, params=None):
        return self._request(
            "GET", "/transload/equipment", headers=headers, params=params
        )

    def start_equipment_cleaning(self, equipment_id, headers):
        return self._request(
            "POST", f"/transload/equipment/{equipment_id}/start-cleaning", {}, headers
        )

    def finish_equipment_cleaning(self, equipment_id, headers):
        return self._request(
            "POST", f"/transload/equipment/{equipment_id}/finish-cleaning", {}, headers
        )

    # --- SafetyIncident ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/transload/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request(
            "GET", f"/transload/incidents/{incident_id}", headers=headers
        )

    def resolve_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/transload/incidents/{incident_id}/resolve", {}, headers
        )

    # --- Railcar ---
    def create_railcar(self, payload, headers):
        return self._request("POST", "/transload/railcars", payload, headers)

    def get_railcar(self, railcar_id, headers):
        return self._request(
            "GET", f"/transload/railcars/{railcar_id}", headers=headers
        )

    def list_railcars(self, headers, params=None):
        return self._request("GET", "/transload/railcars", headers=headers, params=params)

    def arrive_railcar(self, railcar_id, headers):
        return self._request(
            "POST", f"/transload/railcars/{railcar_id}/arrive", {}, headers
        )

    def depart_railcar(self, railcar_id, headers):
        return self._request(
            "POST", f"/transload/railcars/{railcar_id}/depart", {}, headers
        )

    def place_hold(self, railcar_id, reason, headers):
        return self._request(
            "POST",
            f"/transload/railcars/{railcar_id}/place-hold",
            {"reason": reason},
            headers,
        )

    def lift_hold(self, railcar_id, headers):
        return self._request(
            "POST", f"/transload/railcars/{railcar_id}/lift-hold", {}, headers
        )

    def start_railcar_cleaning(self, railcar_id, wash_type, headers):
        return self._request(
            "POST",
            f"/transload/railcars/{railcar_id}/start-cleaning",
            {"wash_type": wash_type},
            headers,
        )

    def pass_railcar_cleaning(self, railcar_id, headers):
        return self._request(
            "POST", f"/transload/railcars/{railcar_id}/pass-cleaning", {}, headers
        )

    def fail_railcar_cleaning(self, railcar_id, headers):
        return self._request(
            "POST", f"/transload/railcars/{railcar_id}/fail-cleaning", {}, headers
        )

    def release_railcar(self, railcar_id, headers):
        return self._request(
            "POST", f"/transload/railcars/{railcar_id}/release", {}, headers
        )

    # --- InventoryLot ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/transload/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/transload/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/transload/lots", headers=headers, params=params)

    def close_lot(self, lot_id, headers):
        return self._request("POST", f"/transload/lots/{lot_id}/close", {}, headers)

    # --- SpotOrder ---
    def create_spot_order(self, railcar_id, payload, headers):
        return self._request(
            "POST", f"/transload/railcars/{railcar_id}/spot-orders", payload, headers
        )

    def get_spot_order(self, spot_order_id, headers):
        return self._request(
            "GET", f"/transload/spot-orders/{spot_order_id}", headers=headers
        )

    def list_spot_orders(self, headers, params=None):
        return self._request(
            "GET", "/transload/spot-orders", headers=headers, params=params
        )

    def schedule_spot_order(self, spot_order_id, headers):
        return self._request(
            "POST", f"/transload/spot-orders/{spot_order_id}/schedule", {}, headers
        )

    def execute_spot_order(self, spot_order_id, headers):
        return self._request(
            "POST", f"/transload/spot-orders/{spot_order_id}/execute", {}, headers
        )

    def cancel_spot_order(self, spot_order_id, headers):
        return self._request(
            "POST", f"/transload/spot-orders/{spot_order_id}/cancel", {}, headers
        )

    # --- SwitchOrder ---
    def get_switch_order(self, switch_order_id, headers):
        return self._request(
            "GET", f"/transload/switch-orders/{switch_order_id}", headers=headers
        )

    def list_switch_orders(self, headers, params=None):
        return self._request(
            "GET", "/transload/switch-orders", headers=headers, params=params
        )

    # --- TransferOrder ---
    def create_transfer_order(self, payload, headers):
        return self._request("POST", "/transload/transfer-orders", payload, headers)

    def get_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "GET", f"/transload/transfer-orders/{transfer_order_id}", headers=headers
        )

    def list_transfer_orders(self, headers, params=None):
        return self._request(
            "GET", "/transload/transfer-orders", headers=headers, params=params
        )

    def activate_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "POST",
            f"/transload/transfer-orders/{transfer_order_id}/activate",
            {},
            headers,
        )

    def pause_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "POST", f"/transload/transfer-orders/{transfer_order_id}/pause", {}, headers
        )

    def complete_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "POST",
            f"/transload/transfer-orders/{transfer_order_id}/complete",
            {},
            headers,
        )

    def cancel_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "POST", f"/transload/transfer-orders/{transfer_order_id}/cancel", {}, headers
        )

    # --- WeightTicket ---
    def create_weight_ticket(self, transfer_order_id, payload, headers):
        return self._request(
            "POST",
            f"/transload/transfer-orders/{transfer_order_id}/weight-tickets",
            payload,
            headers,
        )

    def get_weight_ticket(self, weight_ticket_id, headers):
        return self._request(
            "GET", f"/transload/weight-tickets/{weight_ticket_id}", headers=headers
        )

    def list_weight_tickets(self, headers, params=None):
        return self._request(
            "GET", "/transload/weight-tickets", headers=headers, params=params
        )

    def certify_weight_ticket(self, weight_ticket_id, headers):
        return self._request(
            "POST", f"/transload/weight-tickets/{weight_ticket_id}/certify", {}, headers
        )

    def void_weight_ticket(self, weight_ticket_id, headers):
        return self._request(
            "POST", f"/transload/weight-tickets/{weight_ticket_id}/void", {}, headers
        )

    # --- ChargeEntry ---
    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/transload/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/transload/charges", headers=headers, params=params)

    def void_charge(self, charge_id, headers):
        return self._request(
            "POST", f"/transload/charges/{charge_id}/void", {}, headers
        )

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/transload/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/transload/invoices/{invoice_id}", headers=headers
        )

    def list_invoices(self, headers, params=None):
        return self._request(
            "GET", "/transload/invoices", headers=headers, params=params
        )

    def issue_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/transload/invoices/{invoice_id}/issue", {}, headers
        )

    def pay_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/transload/invoices/{invoice_id}/pay", {}, headers
        )

    def dispute_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/transload/invoices/{invoice_id}/dispute", {}, headers
        )


api_client = ApiClient()
