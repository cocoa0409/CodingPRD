"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Products / recipes / gift-set bill of material
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_product_recipes(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}/recipes",
                             headers=headers)

    def list_product_gift_components(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}/gift-components",
                             headers=headers)

    def create_recipe(self, payload, headers):
        return self._request("POST", "/recipes", payload, headers)

    def create_gift_component(self, payload, headers):
        return self._request("POST", "/gift-components", payload, headers)

    # ------------------------------------------------------------------
    # Packaging components and purchase orders
    # ------------------------------------------------------------------
    def create_packaging_component(self, payload, headers):
        return self._request("POST", "/packaging-components", payload, headers)

    def list_packaging_components(self, headers, params=None):
        return self._request("GET", "/packaging-components",
                             headers=headers, params=params)

    def create_purchase_order(self, component_id, payload, headers):
        return self._request(
            "POST", f"/packaging-components/{component_id}/purchase-orders",
            payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders",
                             headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}",
                             headers=headers)

    def receive_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/receive",
                             {}, headers)

    # ------------------------------------------------------------------
    # Molds, production lines, changeovers
    # ------------------------------------------------------------------
    def create_mold(self, payload, headers):
        return self._request("POST", "/molds", payload, headers)

    def list_molds(self, headers, params=None):
        return self._request("GET", "/molds", headers=headers, params=params)

    def create_production_line(self, payload, headers):
        return self._request("POST", "/production-lines", payload, headers)

    def list_production_lines(self, headers, params=None):
        return self._request("GET", "/production-lines",
                             headers=headers, params=params)

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/production-lines/{line_id}",
                             headers=headers)

    def create_changeover(self, line_id, payload, headers):
        return self._request("POST",
                             f"/production-lines/{line_id}/changeovers",
                             payload, headers)

    def list_line_changeovers(self, line_id, headers):
        return self._request("GET",
                             f"/production-lines/{line_id}/changeovers",
                             headers=headers)

    def list_changeovers(self, headers, params=None):
        return self._request("GET", "/changeovers", headers=headers,
                             params=params)

    def get_changeover(self, changeover_id, headers):
        return self._request("GET", f"/changeovers/{changeover_id}",
                             headers=headers)

    def record_swab(self, changeover_id, payload, headers):
        return self._request("POST", f"/changeovers/{changeover_id}/swab",
                             payload, headers)

    def release_changeover(self, changeover_id, headers):
        return self._request("POST", f"/changeovers/{changeover_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Seasonal windows
    # ------------------------------------------------------------------
    def create_seasonal_window(self, payload, headers):
        return self._request("POST", "/seasonal-windows", payload, headers)

    def list_seasonal_windows(self, headers, params=None):
        return self._request("GET", "/seasonal-windows", headers=headers,
                             params=params)

    def get_seasonal_window(self, window_id, headers):
        return self._request("GET", f"/seasonal-windows/{window_id}",
                             headers=headers)

    def publish_window(self, window_id, headers):
        return self._request("POST", f"/seasonal-windows/{window_id}/publish",
                             {}, headers)

    def close_window(self, window_id, headers):
        return self._request("POST", f"/seasonal-windows/{window_id}/close",
                             {}, headers)

    def apply_markdown(self, window_id, headers):
        return self._request("POST",
                             f"/seasonal-windows/{window_id}/apply-markdown",
                             {}, headers)

    # ------------------------------------------------------------------
    # Production runs
    # ------------------------------------------------------------------
    def create_production_run(self, payload, headers):
        return self._request("POST", "/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers,
                             params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}",
                             headers=headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/start",
                             {}, headers)

    def hold_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/hold",
                             {}, headers)

    def resume_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/resume",
                             {}, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/production-runs/{run_id}/complete",
                             payload, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Lots and quality holds
    # ------------------------------------------------------------------
    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def create_quality_hold(self, payload, headers):
        return self._request("POST", "/quality-holds", payload, headers)

    def list_quality_holds(self, headers, params=None):
        return self._request("GET", "/quality-holds", headers=headers,
                             params=params)

    def get_quality_hold(self, hold_id, headers):
        return self._request("GET", f"/quality-holds/{hold_id}",
                             headers=headers)

    def disposition_quality_hold(self, hold_id, payload, headers):
        return self._request("POST",
                             f"/quality-holds/{hold_id}/disposition",
                             payload, headers)


api_client = ApiClient()
