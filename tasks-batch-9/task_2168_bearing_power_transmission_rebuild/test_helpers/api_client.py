"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------ Customer -----------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/shop/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/shop/customers/{customer_id}", headers=headers)

    def create_asset(self, customer_id, payload, headers):
        return self._request("POST", f"/shop/customers/{customer_id}/assets", payload, headers)

    def list_customer_assets(self, customer_id, headers, params=None):
        return self._request("GET", f"/shop/customers/{customer_id}/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/shop/assets/{asset_id}", headers=headers)

    def create_manual_credit_note(self, customer_id, payload, headers):
        return self._request("POST", f"/shop/customers/{customer_id}/credit-notes", payload, headers)

    # -------------------------- ClearanceStandard ------------------------
    def create_clearance_standard(self, payload, headers):
        return self._request("POST", "/shop/clearance-standards", payload, headers)

    def get_clearance_standard(self, standard_id, headers):
        return self._request("GET", f"/shop/clearance-standards/{standard_id}", headers=headers)

    # -------------------------------- Bench ------------------------------
    def create_bench(self, payload, headers):
        return self._request("POST", "/shop/benches", payload, headers)

    def get_bench(self, bench_id, headers):
        return self._request("GET", f"/shop/benches/{bench_id}", headers=headers)

    def list_bench_reservations(self, bench_id, headers, params=None):
        return self._request("GET", f"/shop/benches/{bench_id}/reservations", headers=headers, params=params)

    # ------------------------------ CoreUnit -----------------------------
    def create_core_unit(self, payload, headers):
        return self._request("POST", "/shop/core-units", payload, headers)

    def get_core_unit(self, core_unit_id, headers):
        return self._request("GET", f"/shop/core-units/{core_unit_id}", headers=headers)

    def list_core_units(self, headers, params=None):
        return self._request("GET", "/shop/core-units", headers=headers, params=params)

    def advance_core_unit(self, core_unit_id, payload, headers):
        return self._request("POST", f"/shop/core-units/{core_unit_id}/advance", payload, headers)

    # ---------------------------- RebuildOrder ---------------------------
    def create_rebuild_order(self, payload, headers):
        return self._request("POST", "/shop/rebuild-orders", payload, headers)

    def get_rebuild_order(self, order_id, headers):
        return self._request("GET", f"/shop/rebuild-orders/{order_id}", headers=headers)

    def list_rebuild_orders(self, headers, params=None):
        return self._request("GET", "/shop/rebuild-orders", headers=headers, params=params)

    def get_quote(self, order_id, headers):
        return self._request("GET", f"/shop/rebuild-orders/{order_id}/quote", headers=headers)

    def advance_rebuild_order(self, order_id, payload, headers):
        return self._request("POST", f"/shop/rebuild-orders/{order_id}/advance", payload, headers)

    def cancel_rebuild_order(self, order_id, payload, headers):
        return self._request("POST", f"/shop/rebuild-orders/{order_id}/cancel", payload, headers)

    def expedite_rebuild_order(self, order_id, payload, headers):
        return self._request("POST", f"/shop/rebuild-orders/{order_id}/expedite", payload, headers)

    # ------------------------------ PartLine -----------------------------
    def create_part_line(self, order_id, payload, headers):
        return self._request("POST", f"/shop/rebuild-orders/{order_id}/part-lines", payload, headers)

    def list_part_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/shop/rebuild-orders/{order_id}/part-lines", headers=headers, params=params)

    def advance_part_line(self, part_line_id, payload, headers):
        return self._request("POST", f"/shop/part-lines/{part_line_id}/advance", payload, headers)

    def decide_part_line(self, part_line_id, payload, headers):
        return self._request("POST", f"/shop/part-lines/{part_line_id}/decide", payload, headers)

    # -------------------------- VibrationReading -------------------------
    def create_vibration_reading(self, payload, headers):
        return self._request("POST", "/shop/vibration-readings", payload, headers)

    def list_asset_vibration_readings(self, asset_id, headers, params=None):
        return self._request("GET", f"/shop/assets/{asset_id}/vibration-readings", headers=headers, params=params)

    # ----------------------------- Inspection ----------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/shop/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/shop/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/shop/inspections", headers=headers, params=params)

    def create_measurement(self, inspection_id, payload, headers):
        return self._request("POST", f"/shop/inspections/{inspection_id}/measurements", payload, headers)

    def list_measurements(self, inspection_id, headers, params=None):
        return self._request("GET", f"/shop/inspections/{inspection_id}/measurements", headers=headers, params=params)

    def advance_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/shop/inspections/{inspection_id}/advance", payload, headers)

    # -------------------------- BenchReservation -------------------------
    def create_bench_reservation(self, payload, headers):
        return self._request("POST", "/shop/bench-reservations", payload, headers)

    def list_order_bench_reservations(self, order_id, headers, params=None):
        return self._request("GET", f"/shop/rebuild-orders/{order_id}/bench-reservations", headers=headers, params=params)

    def advance_bench_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/shop/bench-reservations/{reservation_id}/advance", payload, headers)

    # ---------------------------- Installation ---------------------------
    def create_installation(self, payload, headers):
        return self._request("POST", "/shop/installations", payload, headers)

    def get_installation(self, installation_id, headers):
        return self._request("GET", f"/shop/installations/{installation_id}", headers=headers)

    def list_installations(self, headers, params=None):
        return self._request("GET", "/shop/installations", headers=headers, params=params)

    def advance_installation(self, installation_id, payload, headers):
        return self._request("POST", f"/shop/installations/{installation_id}/advance", payload, headers)

    # --------------------------- WarrantyClaim ---------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/shop/warranty-claims", payload, headers)

    def list_installation_warranty_claims(self, installation_id, headers, params=None):
        return self._request("GET", f"/shop/installations/{installation_id}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/shop/warranty-claims/{claim_id}", headers=headers)

    def advance_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/shop/warranty-claims/{claim_id}/advance", payload, headers)

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/shop/warranty-claims/{claim_id}/adjudicate", payload, headers)

    # ----------------------------- CreditNote ----------------------------
    def get_credit_note(self, note_id, headers):
        return self._request("GET", f"/shop/credit-notes/{note_id}", headers=headers)

    def list_credit_notes(self, headers, params=None):
        return self._request("GET", "/shop/credit-notes", headers=headers, params=params)

    def void_credit_note(self, note_id, payload, headers):
        return self._request("POST", f"/shop/credit-notes/{note_id}/void", payload, headers)

    # ------------------------- logical shop clock ------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------- raw path helpers --------------------------
    def get_path(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def post_path(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
