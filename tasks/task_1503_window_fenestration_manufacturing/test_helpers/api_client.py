"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- dealers ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/fenestration/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/fenestration/dealers/{dealer_id}", headers=headers)

    def credit_hold_dealer(self, dealer_id, headers):
        return self._request("POST", f"/fenestration/dealers/{dealer_id}/credit-hold", {}, headers)

    def credit_release_dealer(self, dealer_id, headers):
        return self._request("POST", f"/fenestration/dealers/{dealer_id}/credit-release", {}, headers)

    # --- catalog series ---
    def create_catalog_series(self, payload, headers):
        return self._request("POST", "/fenestration/catalog-series", payload, headers)

    def get_catalog_series(self, series_id, headers):
        return self._request("GET", f"/fenestration/catalog-series/{series_id}", headers=headers)

    def discontinue_catalog_series(self, series_id, headers):
        return self._request(
            "POST", f"/fenestration/catalog-series/{series_id}/discontinue", {}, headers
        )

    # --- glass packages ---
    def create_glass_package(self, payload, headers):
        return self._request("POST", "/fenestration/glass-packages", payload, headers)

    def get_glass_package(self, glass_package_id, headers):
        return self._request("GET", f"/fenestration/glass-packages/{glass_package_id}", headers=headers)

    # --- energy code rules ---
    def create_energy_code_rule(self, payload, headers):
        return self._request("POST", "/fenestration/energy-code-rules", payload, headers)

    def get_energy_code_rule(self, rule_id, headers):
        return self._request("GET", f"/fenestration/energy-code-rules/{rule_id}", headers=headers)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/fenestration/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/fenestration/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/fenestration/orders", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/fenestration/orders/{order_id}/confirm", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/fenestration/orders/{order_id}/cancel", {}, headers)

    def confirm_delivery(self, order_id, headers):
        return self._request(
            "POST", f"/fenestration/orders/{order_id}/confirm-delivery", {}, headers
        )

    # --- order lines ---
    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/fenestration/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/fenestration/orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/fenestration/order-lines/{line_id}", headers=headers)

    def list_all_order_lines(self, headers, params=None):
        return self._request("GET", "/fenestration/order-lines", headers=headers, params=params)

    def patch_order_line(self, order_id, line_id, payload, headers):
        return self._request(
            "PATCH", f"/fenestration/orders/{order_id}/lines/{line_id}", payload, headers
        )

    def resume_line_production(self, line_id, headers):
        return self._request(
            "POST", f"/fenestration/order-lines/{line_id}/resume-production", {}, headers
        )

    # --- energy labels ---
    def get_line_energy_label(self, line_id, headers):
        return self._request("GET", f"/fenestration/order-lines/{line_id}/energy-label", headers=headers)

    def get_energy_label(self, label_id, headers):
        return self._request("GET", f"/fenestration/energy-labels/{label_id}", headers=headers)

    def list_energy_labels(self, headers, params=None):
        return self._request("GET", "/fenestration/energy-labels", headers=headers, params=params)

    # --- production waves ---
    def create_wave(self, payload, headers):
        return self._request("POST", "/fenestration/production-waves", payload, headers)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/fenestration/production-waves/{wave_id}", headers=headers)

    def open_wave(self, wave_id, headers):
        return self._request("POST", f"/fenestration/production-waves/{wave_id}/open", {}, headers)

    def assign_order_to_wave(self, wave_id, payload, headers):
        return self._request(
            "POST", f"/fenestration/production-waves/{wave_id}/assignments", payload, headers
        )

    def unassign_order_from_wave(self, wave_id, payload, headers):
        return self._request(
            "POST", f"/fenestration/production-waves/{wave_id}/unassign", payload, headers
        )

    def lock_wave(self, wave_id, headers):
        return self._request("POST", f"/fenestration/production-waves/{wave_id}/lock", {}, headers)

    def release_wave(self, wave_id, headers):
        return self._request("POST", f"/fenestration/production-waves/{wave_id}/release", {}, headers)

    def close_wave(self, wave_id, headers):
        return self._request("POST", f"/fenestration/production-waves/{wave_id}/close", {}, headers)

    def cancel_wave(self, wave_id, headers):
        return self._request("POST", f"/fenestration/production-waves/{wave_id}/cancel", {}, headers)

    # --- IG units ---
    def list_line_ig_units(self, line_id, headers, params=None):
        return self._request("GET", f"/fenestration/order-lines/{line_id}/ig-units", headers=headers, params=params)

    def get_ig_unit(self, ig_unit_id, headers):
        return self._request("GET", f"/fenestration/ig-units/{ig_unit_id}", headers=headers)

    def list_ig_units(self, headers, params=None):
        return self._request("GET", "/fenestration/ig-units", headers=headers, params=params)

    def advance_ig_unit(self, ig_unit_id, headers):
        return self._request("POST", f"/fenestration/ig-units/{ig_unit_id}/advance", {}, headers)

    def qc_check_ig_unit(self, ig_unit_id, payload, headers):
        return self._request("POST", f"/fenestration/ig-units/{ig_unit_id}/qc-check", payload, headers)

    def report_ig_breakage(self, ig_unit_id, payload, headers):
        return self._request(
            "POST", f"/fenestration/ig-units/{ig_unit_id}/report-breakage", payload, headers
        )

    # --- shipping racks and reservations ---
    def create_rack(self, payload, headers):
        return self._request("POST", "/fenestration/shipping-racks", payload, headers)

    def get_rack(self, rack_id, headers):
        return self._request("GET", f"/fenestration/shipping-racks/{rack_id}", headers=headers)

    def list_racks(self, headers, params=None):
        return self._request("GET", "/fenestration/shipping-racks", headers=headers, params=params)

    def create_rack_reservation(self, rack_id, payload, headers):
        return self._request(
            "POST", f"/fenestration/shipping-racks/{rack_id}/reservations", payload, headers
        )

    def list_rack_reservations(self, rack_id, headers, params=None):
        return self._request(
            "GET", f"/fenestration/shipping-racks/{rack_id}/reservations", headers=headers, params=params
        )

    def get_rack_reservation(self, reservation_id, headers):
        return self._request("GET", f"/fenestration/rack-reservations/{reservation_id}", headers=headers)

    def list_all_rack_reservations(self, headers, params=None):
        return self._request("GET", "/fenestration/rack-reservations", headers=headers, params=params)

    def load_rack_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/fenestration/rack-reservations/{reservation_id}/load", payload, headers
        )

    def ship_rack_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/fenestration/rack-reservations/{reservation_id}/ship", {}, headers
        )

    def cancel_rack_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/fenestration/rack-reservations/{reservation_id}/cancel", {}, headers
        )

    # --- warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/fenestration/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/fenestration/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/fenestration/warranty-claims", headers=headers, params=params)

    def list_order_warranty_claims(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/fenestration/orders/{order_id}/warranty-claims", headers=headers, params=params
        )

    def take_review_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/fenestration/warranty-claims/{claim_id}/take-review", {}, headers
        )

    def request_info_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/fenestration/warranty-claims/{claim_id}/request-info", {}, headers
        )

    def provide_info_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/fenestration/warranty-claims/{claim_id}/provide-info", {}, headers
        )

    def approve_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/fenestration/warranty-claims/{claim_id}/approve", payload, headers
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fenestration/warranty-claims/{claim_id}/deny", payload, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/fenestration/warranty-claims/{claim_id}/appeal", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/fenestration/warranty-claims/{claim_id}/close", {}, headers)

    # --- service part shipments ---
    def list_claim_shipments(self, claim_id, headers, params=None):
        return self._request(
            "GET",
            f"/fenestration/warranty-claims/{claim_id}/service-part-shipments",
            headers=headers,
            params=params,
        )

    def get_shipment(self, shipment_id, headers):
        return self._request(
            "GET", f"/fenestration/service-part-shipments/{shipment_id}", headers=headers
        )

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/fenestration/service-part-shipments", headers=headers, params=params)

    def ship_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/fenestration/service-part-shipments/{shipment_id}/ship", {}, headers
        )

    def deliver_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/fenestration/service-part-shipments/{shipment_id}/deliver", {}, headers
        )


api_client = ApiClient()
