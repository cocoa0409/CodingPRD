"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Shop ──────────────────────────────────────────────────────────────
    def create_shop(self, payload, headers):
        return self._request("POST", "/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    # ─── Customer ──────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def archive_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/archive", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ─── DecorationMethod ──────────────────────────────────────────────────
    def create_decoration_method(self, payload, headers):
        return self._request("POST", "/decoration-methods", payload, headers)

    def get_decoration_method(self, method_id, headers):
        return self._request("GET", f"/decoration-methods/{method_id}", headers=headers)

    def list_decoration_methods(self, headers, params=None):
        return self._request("GET", "/decoration-methods", headers=headers, params=params)

    # ─── GarmentStyle ──────────────────────────────────────────────────────
    def create_garment_style(self, payload, headers):
        return self._request("POST", "/garment-styles", payload, headers)

    def get_garment_style(self, style_id, headers):
        return self._request("GET", f"/garment-styles/{style_id}", headers=headers)

    def list_garment_styles(self, headers, params=None):
        return self._request("GET", "/garment-styles", headers=headers, params=params)

    # ─── BlankSku ──────────────────────────────────────────────────────────
    def create_blank_sku(self, style_id, payload, headers):
        return self._request("POST", f"/garment-styles/{style_id}/blank-skus", payload, headers)

    def restock_blank_sku(self, style_id, sku_id, payload, headers):
        return self._request(
            "POST", f"/garment-styles/{style_id}/blank-skus/{sku_id}/restock", payload, headers
        )

    def list_blank_skus(self, style_id, headers, params=None):
        return self._request(
            "GET", f"/garment-styles/{style_id}/blank-skus", headers=headers, params=params
        )

    def get_blank_sku(self, style_id, sku_id, headers):
        return self._request(
            "GET", f"/garment-styles/{style_id}/blank-skus/{sku_id}", headers=headers
        )

    # ─── Press ─────────────────────────────────────────────────────────────
    def create_press(self, payload, headers):
        return self._request("POST", "/presses", payload, headers)

    def get_press(self, press_id, headers):
        return self._request("GET", f"/presses/{press_id}", headers=headers)

    def list_presses(self, headers, params=None):
        return self._request("GET", "/presses", headers=headers, params=params)

    # ─── EmbroideryStation ─────────────────────────────────────────────────
    def create_embroidery_station(self, payload, headers):
        return self._request("POST", "/embroidery-stations", payload, headers)

    def get_embroidery_station(self, station_id, headers):
        return self._request("GET", f"/embroidery-stations/{station_id}", headers=headers)

    def list_embroidery_stations(self, headers, params=None):
        return self._request("GET", "/embroidery-stations", headers=headers, params=params)

    # ─── Order ─────────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def create_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/invoice", headers=headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", headers=headers)

    def get_quote(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/quote", headers=headers)

    # ─── ArtProof ──────────────────────────────────────────────────────────
    def create_art_proof(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/art-proofs", payload, headers)

    def list_art_proofs(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/art-proofs", headers=headers, params=params
        )

    def get_art_proof(self, order_id, proof_id, headers):
        return self._request("GET", f"/orders/{order_id}/art-proofs/{proof_id}", headers=headers)

    def submit_proof(self, order_id, proof_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/art-proofs/{proof_id}/submit", headers=headers
        )

    def request_changes_proof(self, order_id, proof_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/art-proofs/{proof_id}/request-changes", headers=headers
        )

    def approve_proof(self, order_id, proof_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/art-proofs/{proof_id}/approve", payload, headers
        )

    # ─── BlankReservation ──────────────────────────────────────────────────
    def list_reservations(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/reservations", headers=headers, params=params
        )

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/blank-reservations/{reservation_id}", headers=headers)

    def list_blank_reservations(self, headers, params=None):
        return self._request("GET", "/blank-reservations", headers=headers, params=params)

    # ─── ProductionRun ─────────────────────────────────────────────────────
    def create_production_run(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/production-runs", payload, headers)

    def list_production_runs(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/production-runs", headers=headers, params=params
        )

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def list_all_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def start_run(self, order_id, run_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/production-runs/{run_id}/start", headers=headers
        )

    def complete_run(self, order_id, run_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/production-runs/{run_id}/complete", payload, headers
        )

    def abort_run(self, order_id, run_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/production-runs/{run_id}/abort", headers=headers
        )


api_client = ApiClient()
