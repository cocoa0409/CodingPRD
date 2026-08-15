"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- TransmissionModel ---
    def create_transmission_model(self, payload, headers):
        return self._request("POST", "/api/transmission-models", payload, headers)

    def update_transmission_model(self, model_id, payload, headers):
        return self._request("PUT", f"/api/transmission-models/{model_id}",
                             payload, headers)

    def get_transmission_model(self, model_id, headers):
        return self._request("GET", f"/api/transmission-models/{model_id}",
                             headers=headers)

    # --- HardPart ---
    def create_hard_part(self, payload, headers):
        return self._request("POST", "/api/hard-parts", payload, headers)

    def get_hard_part(self, part_id, headers):
        return self._request("GET", f"/api/hard-parts/{part_id}", headers=headers)

    def create_stock_adjustment(self, part_id, payload, headers):
        return self._request("POST", f"/api/hard-parts/{part_id}/stock-adjustments",
                             payload, headers)

    # --- InterchangeMapping ---
    def create_interchange_mapping(self, payload, headers):
        return self._request("POST", "/api/interchange-mappings", payload, headers)

    def list_interchange_mappings(self, headers, params=None):
        return self._request("GET", "/api/interchange-mappings",
                             headers=headers, params=params)

    def get_interchange_mapping(self, mapping_id, headers):
        return self._request("GET", f"/api/interchange-mappings/{mapping_id}",
                             headers=headers)

    # --- RemanOrder ---
    def create_reman_order(self, payload, headers):
        return self._request("POST", "/api/reman-orders", payload, headers)

    def list_reman_orders(self, headers, params=None):
        return self._request("GET", "/api/reman-orders", headers=headers, params=params)

    def get_reman_order(self, order_id, headers):
        return self._request("GET", f"/api/reman-orders/{order_id}", headers=headers)

    def kit_reserve(self, order_id, headers):
        return self._request("POST", f"/api/reman-orders/{order_id}/kit-reserve",
                             headers=headers)

    def complete_assembly(self, order_id, headers):
        return self._request("POST", f"/api/reman-orders/{order_id}/complete-assembly",
                             headers=headers)

    def put_calibration(self, order_id, payload, headers):
        return self._request("PUT", f"/api/reman-orders/{order_id}/calibration",
                             payload, headers)

    def verify_calibration(self, order_id, headers):
        return self._request("POST", f"/api/reman-orders/{order_id}/verify-calibration",
                             headers=headers)

    def resync_spec(self, order_id, payload, headers):
        return self._request("POST", f"/api/reman-orders/{order_id}/resync-spec",
                             payload, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/api/reman-orders/{order_id}/ship",
                             headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/reman-orders/{order_id}/cancel",
                             headers=headers)

    # --- DynoBooking ---
    def create_dyno_booking(self, payload, headers):
        return self._request("POST", "/api/dyno-bookings", payload, headers)

    def list_dyno_bookings(self, headers, params=None):
        return self._request("GET", "/api/dyno-bookings", headers=headers, params=params)

    def get_dyno_booking(self, booking_id, headers):
        return self._request("GET", f"/api/dyno-bookings/{booking_id}", headers=headers)

    # --- DynoTestRun ---
    def create_dyno_test_run(self, payload, headers):
        return self._request("POST", "/api/dyno-test-runs", payload, headers)

    def list_dyno_test_runs(self, headers, params=None):
        return self._request("GET", "/api/dyno-test-runs", headers=headers, params=params)

    def get_dyno_test_run(self, run_id, headers):
        return self._request("GET", f"/api/dyno-test-runs/{run_id}", headers=headers)

    # --- CoreUnit ---
    def create_core_unit(self, payload, headers):
        return self._request("POST", "/api/core-units", payload, headers)

    def list_core_units(self, headers, params=None):
        return self._request("GET", "/api/core-units", headers=headers, params=params)

    def get_core_unit(self, core_id, headers):
        return self._request("GET", f"/api/core-units/{core_id}", headers=headers)

    def inspect_core_unit(self, core_id, payload, headers):
        return self._request("POST", f"/api/core-units/{core_id}/inspect",
                             payload, headers)

    # --- CoreDepositInvoice ---
    def list_core_deposit_invoices(self, headers, params=None):
        return self._request("GET", "/api/core-deposit-invoices",
                             headers=headers, params=params)

    def get_core_deposit_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/core-deposit-invoices/{invoice_id}",
                             headers=headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST",
                             f"/api/core-deposit-invoices/{invoice_id}/dispute",
                             headers=headers)

    def resolve_dispute(self, invoice_id, payload, headers):
        return self._request("POST",
                             f"/api/core-deposit-invoices/{invoice_id}/resolve-dispute",
                             payload, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/api/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/api/warranty-claims", headers=headers,
                             params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/api/warranty-claims/{claim_id}", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/approve",
                             headers=headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/deny",
                             payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/pay",
                             headers=headers)

    def return_ship_claim(self, claim_id, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/return-ship",
                             headers=headers)

    def return_receive_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/return-receive",
                             payload, headers)

    # --- Logical clock (test-driving endpoint, PRD §2.5) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
