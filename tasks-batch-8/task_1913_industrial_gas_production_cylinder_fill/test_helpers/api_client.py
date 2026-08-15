"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Plants (PRD §3.1) ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/api/plants", payload, headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/api/plants", headers=headers, params=params)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/api/plants/{plant_id}", headers=headers)

    def set_plant_status(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/set-status", payload, headers)

    # --- Storage tanks (PRD §3.1) ---
    def create_tank(self, payload, headers):
        return self._request("POST", "/api/tanks", payload, headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/api/tanks", headers=headers, params=params)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/api/tanks/{tank_id}", headers=headers)

    def patch_tank(self, tank_id, payload, headers):
        return self._request("PATCH", f"/api/tanks/{tank_id}", payload, headers)

    def set_tank_status(self, tank_id, payload, headers):
        return self._request("POST", f"/api/tanks/{tank_id}/set-status", payload, headers)

    # --- Telemetry readings (PRD §3.1) ---
    def create_telemetry_reading(self, payload, headers):
        return self._request("POST", "/api/telemetry-readings", payload, headers)

    def list_telemetry_readings(self, headers, params=None):
        return self._request("GET", "/api/telemetry-readings", headers=headers, params=params)

    def get_telemetry_reading(self, reading_id, headers):
        return self._request("GET", f"/api/telemetry-readings/{reading_id}", headers=headers)

    # --- Cylinder assets (PRD §3.2) ---
    def create_cylinder(self, payload, headers):
        return self._request("POST", "/api/cylinders", payload, headers)

    def list_cylinders(self, headers, params=None):
        return self._request("GET", "/api/cylinders", headers=headers, params=params)

    def get_cylinder(self, cylinder_id, headers):
        return self._request("GET", f"/api/cylinders/{cylinder_id}", headers=headers)

    def record_hydro_retest(self, cylinder_id, payload, headers):
        return self._request(
            "POST", f"/api/cylinders/{cylinder_id}/hydro-retests", payload, headers
        )

    def release_quarantine(self, cylinder_id, headers):
        return self._request(
            "POST", f"/api/cylinders/{cylinder_id}/release-quarantine", {}, headers
        )

    def decommission_cylinder(self, cylinder_id, payload, headers):
        return self._request(
            "POST", f"/api/cylinders/{cylinder_id}/decommission", payload, headers
        )

    # --- Fill lots (PRD §3.3) ---
    def create_fill_lot(self, payload, headers):
        return self._request("POST", "/api/fill-lots", payload, headers)

    def list_fill_lots(self, headers, params=None):
        return self._request("GET", "/api/fill-lots", headers=headers, params=params)

    def get_fill_lot(self, fill_lot_id, headers):
        return self._request("GET", f"/api/fill-lots/{fill_lot_id}", headers=headers)

    def assign_cylinder_to_lot(self, fill_lot_id, payload, headers):
        return self._request(
            "POST", f"/api/fill-lots/{fill_lot_id}/cylinders", payload, headers
        )

    def start_fill(self, fill_lot_id, headers):
        return self._request("POST", f"/api/fill-lots/{fill_lot_id}/start-fill", {}, headers)

    def complete_fill(self, fill_lot_id, payload, headers):
        return self._request(
            "POST", f"/api/fill-lots/{fill_lot_id}/complete-fill", payload, headers
        )

    def rework_fill_lot(self, fill_lot_id, headers):
        return self._request("POST", f"/api/fill-lots/{fill_lot_id}/rework", {}, headers)

    def vent_fill_lot(self, fill_lot_id, headers):
        return self._request("POST", f"/api/fill-lots/{fill_lot_id}/vent", {}, headers)

    def recall_fill_lot(self, fill_lot_id, headers):
        return self._request("POST", f"/api/fill-lots/{fill_lot_id}/recall", {}, headers)

    # --- Purity analyses (PRD §3.4) ---
    def create_purity_analysis(self, payload, headers):
        return self._request("POST", "/api/purity-analyses", payload, headers)

    def list_purity_analyses(self, headers, params=None):
        return self._request("GET", "/api/purity-analyses", headers=headers, params=params)

    def get_purity_analysis(self, analysis_id, headers):
        return self._request("GET", f"/api/purity-analyses/{analysis_id}", headers=headers)

    def override_purity_analysis(self, analysis_id, headers):
        return self._request(
            "POST", f"/api/purity-analyses/{analysis_id}/override", {}, headers
        )

    # --- Customer accounts (PRD §3.5) ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/api/customers/{customer_id}", payload, headers)

    def post_payment(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/payments", payload, headers
        )

    # --- Cylinder rentals (PRD §3.5) ---
    def create_rental(self, payload, headers):
        return self._request("POST", "/api/rentals", payload, headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/api/rentals", headers=headers, params=params)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/api/rentals/{rental_id}", headers=headers)

    def return_rental(self, rental_id, payload, headers):
        return self._request("POST", f"/api/rentals/{rental_id}/return", payload, headers)

    def settle_loss(self, rental_id, headers):
        return self._request("POST", f"/api/rentals/{rental_id}/settle-loss", {}, headers)

    # --- Drivers (PRD §3.7) ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/api/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/api/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/api/drivers/{driver_id}", headers=headers)

    def patch_driver(self, driver_id, payload, headers):
        return self._request("PATCH", f"/api/drivers/{driver_id}", payload, headers)

    def set_driver_status(self, driver_id, payload, headers):
        return self._request("POST", f"/api/drivers/{driver_id}/set-status", payload, headers)

    # --- Delivery routes (PRD §3.7) ---
    def create_route(self, payload, headers):
        return self._request("POST", "/api/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/api/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/api/routes/{route_id}", headers=headers)

    def assign_driver(self, route_id, payload, headers):
        return self._request("POST", f"/api/routes/{route_id}/assign-driver", payload, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/api/routes/{route_id}/dispatch", {}, headers)

    def set_route_status(self, route_id, payload, headers):
        return self._request("POST", f"/api/routes/{route_id}/set-status", payload, headers)

    # --- Bulk installations (PRD §3.8) ---
    def create_installation(self, payload, headers):
        return self._request("POST", "/api/bulk-installations", payload, headers)

    def list_installations(self, headers, params=None):
        return self._request("GET", "/api/bulk-installations", headers=headers, params=params)

    def get_installation(self, installation_id, headers):
        return self._request(
            "GET", f"/api/bulk-installations/{installation_id}", headers=headers
        )

    def set_installation_status(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/api/bulk-installations/{installation_id}/set-status",
            payload, headers,
        )

    # --- Replenishment orders (PRD §3.8) ---
    def create_replenishment_order(self, payload, headers):
        return self._request("POST", "/api/replenishment-orders", payload, headers)

    def list_replenishment_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/replenishment-orders", headers=headers, params=params
        )

    def get_replenishment_order(self, order_id, headers):
        return self._request(
            "GET", f"/api/replenishment-orders/{order_id}", headers=headers
        )

    def set_replenishment_order_status(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/replenishment-orders/{order_id}/set-status", payload, headers
        )

    # --- Blend orders (PRD §3.9) ---
    def create_blend_order(self, payload, headers):
        return self._request("POST", "/api/blend-orders", payload, headers)

    def list_blend_orders(self, headers, params=None):
        return self._request("GET", "/api/blend-orders", headers=headers, params=params)

    def get_blend_order(self, blend_order_id, headers):
        return self._request("GET", f"/api/blend-orders/{blend_order_id}", headers=headers)

    def approve_blend_order(self, blend_order_id, headers):
        return self._request(
            "POST", f"/api/blend-orders/{blend_order_id}/approve", {}, headers
        )

    def start_blend(self, blend_order_id, headers):
        return self._request(
            "POST", f"/api/blend-orders/{blend_order_id}/start-blend", {}, headers
        )

    def complete_blend(self, blend_order_id, headers):
        return self._request(
            "POST", f"/api/blend-orders/{blend_order_id}/complete-blend", {}, headers
        )

    # --- Billing runs (PRD §3.6) ---
    def create_billing_run(self, payload, headers):
        return self._request("POST", "/api/billing-runs", payload, headers)

    def list_billing_runs(self, headers, params=None):
        return self._request("GET", "/api/billing-runs", headers=headers, params=params)

    def get_billing_run(self, billing_run_id, headers):
        return self._request("GET", f"/api/billing-runs/{billing_run_id}", headers=headers)

    def finalize_billing_run(self, billing_run_id, headers):
        return self._request(
            "POST", f"/api/billing-runs/{billing_run_id}/finalize", {}, headers
        )

    def post_billing_run(self, billing_run_id, headers):
        return self._request(
            "POST", f"/api/billing-runs/{billing_run_id}/post", {}, headers
        )


api_client = ApiClient()
