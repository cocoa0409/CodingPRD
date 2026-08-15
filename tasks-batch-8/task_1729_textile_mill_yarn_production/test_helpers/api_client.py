"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Fiber lots
    # ------------------------------------------------------------------
    def create_fiber_lot(self, payload, headers):
        return self._request("POST", "/mill/fiber-lots", payload, headers)

    def list_fiber_lots(self, headers, params=None):
        return self._request("GET", "/mill/fiber-lots", headers=headers, params=params)

    def get_fiber_lot(self, fiber_lot_id, headers):
        return self._request("GET", f"/mill/fiber-lots/{fiber_lot_id}", headers=headers)

    def list_fiber_lot_blend_components(self, fiber_lot_id, headers):
        return self._request(
            "GET", f"/mill/fiber-lots/{fiber_lot_id}/blend-components", headers=headers
        )

    # ------------------------------------------------------------------
    # Blend recipes and components
    # ------------------------------------------------------------------
    def create_blend_recipe(self, payload, headers):
        return self._request("POST", "/mill/blend-recipes", payload, headers)

    def list_blend_recipes(self, headers, params=None):
        return self._request("GET", "/mill/blend-recipes", headers=headers, params=params)

    def get_blend_recipe(self, recipe_id, headers):
        return self._request("GET", f"/mill/blend-recipes/{recipe_id}", headers=headers)

    def add_blend_component(self, recipe_id, payload, headers):
        return self._request(
            "POST", f"/mill/blend-recipes/{recipe_id}/components", payload, headers
        )

    def list_blend_components(self, recipe_id, headers):
        return self._request(
            "GET", f"/mill/blend-recipes/{recipe_id}/components", headers=headers
        )

    def approve_blend_recipe(self, recipe_id, payload, headers):
        return self._request(
            "POST", f"/mill/blend-recipes/{recipe_id}/approve", payload, headers
        )

    def reject_blend_recipe(self, recipe_id, headers):
        return self._request(
            "POST", f"/mill/blend-recipes/{recipe_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Spinning machines
    # ------------------------------------------------------------------
    def create_spinning_machine(self, payload, headers):
        return self._request("POST", "/mill/spinning-machines", payload, headers)

    def list_spinning_machines(self, headers, params=None):
        return self._request(
            "GET", "/mill/spinning-machines", headers=headers, params=params
        )

    def get_spinning_machine(self, machine_id, headers):
        return self._request(
            "GET", f"/mill/spinning-machines/{machine_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Yarn lots
    # ------------------------------------------------------------------
    def create_yarn_lot(self, payload, headers):
        return self._request("POST", "/mill/yarn-lots", payload, headers)

    def list_yarn_lots(self, headers, params=None):
        return self._request("GET", "/mill/yarn-lots", headers=headers, params=params)

    def get_yarn_lot(self, yarn_lot_id, headers):
        return self._request("GET", f"/mill/yarn-lots/{yarn_lot_id}", headers=headers)

    def reject_yarn_lot(self, yarn_lot_id, headers):
        return self._request(
            "POST", f"/mill/yarn-lots/{yarn_lot_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Machine assignments
    # ------------------------------------------------------------------
    def create_machine_assignment(self, payload, headers):
        return self._request("POST", "/mill/machine-assignments", payload, headers)

    def list_machine_assignments(self, headers, params=None):
        return self._request(
            "GET", "/mill/machine-assignments", headers=headers, params=params
        )

    def get_machine_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/mill/machine-assignments/{assignment_id}", headers=headers
        )

    def start_machine_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/mill/machine-assignments/{assignment_id}/start", {}, headers
        )

    def complete_machine_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/mill/machine-assignments/{assignment_id}/complete", {}, headers
        )

    def cancel_machine_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/mill/machine-assignments/{assignment_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Shade bands
    # ------------------------------------------------------------------
    def create_shade_band(self, payload, headers):
        return self._request("POST", "/mill/shade-bands", payload, headers)

    def list_shade_bands(self, headers, params=None):
        return self._request("GET", "/mill/shade-bands", headers=headers, params=params)

    def get_shade_band(self, shade_band_id, headers):
        return self._request("GET", f"/mill/shade-bands/{shade_band_id}", headers=headers)

    # ------------------------------------------------------------------
    # Lab dips
    # ------------------------------------------------------------------
    def create_lab_dip(self, payload, headers):
        return self._request("POST", "/mill/lab-dips", payload, headers)

    def list_lab_dips(self, headers, params=None):
        return self._request("GET", "/mill/lab-dips", headers=headers, params=params)

    def get_lab_dip(self, lab_dip_id, headers):
        return self._request("GET", f"/mill/lab-dips/{lab_dip_id}", headers=headers)

    def approve_lab_dip(self, lab_dip_id, headers):
        return self._request(
            "POST", f"/mill/lab-dips/{lab_dip_id}/approve", {}, headers
        )

    def reject_lab_dip(self, lab_dip_id, headers):
        return self._request(
            "POST", f"/mill/lab-dips/{lab_dip_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Dye lots and quality tests
    # ------------------------------------------------------------------
    def create_dye_lot(self, payload, headers):
        return self._request("POST", "/mill/dye-lots", payload, headers)

    def list_dye_lots(self, headers, params=None):
        return self._request("GET", "/mill/dye-lots", headers=headers, params=params)

    def get_dye_lot(self, dye_lot_id, headers):
        return self._request("GET", f"/mill/dye-lots/{dye_lot_id}", headers=headers)

    def start_dye_lot(self, dye_lot_id, headers):
        return self._request("POST", f"/mill/dye-lots/{dye_lot_id}/start", {}, headers)

    def create_quality_test(self, dye_lot_id, payload, headers):
        return self._request(
            "POST", f"/mill/dye-lots/{dye_lot_id}/quality-tests", payload, headers
        )

    def list_quality_tests(self, dye_lot_id, headers):
        return self._request(
            "GET", f"/mill/dye-lots/{dye_lot_id}/quality-tests", headers=headers
        )

    def patch_quality_test(self, quality_test_id, payload, headers):
        return self._request(
            "PATCH", f"/mill/quality-tests/{quality_test_id}", payload, headers
        )

    def submit_shade(self, dye_lot_id, headers):
        return self._request(
            "POST", f"/mill/dye-lots/{dye_lot_id}/submit-shade", {}, headers
        )

    def approve_dye_lot(self, dye_lot_id, headers):
        return self._request(
            "POST", f"/mill/dye-lots/{dye_lot_id}/approve", {}, headers
        )

    def reject_dye_lot(self, dye_lot_id, headers):
        return self._request(
            "POST", f"/mill/dye-lots/{dye_lot_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Finished rolls
    # ------------------------------------------------------------------
    def create_finished_roll(self, payload, headers):
        return self._request("POST", "/mill/finished-rolls", payload, headers)

    def list_finished_rolls(self, headers, params=None):
        return self._request("GET", "/mill/finished-rolls", headers=headers, params=params)

    def get_finished_roll(self, roll_id, headers):
        return self._request("GET", f"/mill/finished-rolls/{roll_id}", headers=headers)

    def ship_finished_roll(self, roll_id, headers):
        return self._request(
            "POST", f"/mill/finished-rolls/{roll_id}/ship", {}, headers
        )

    def release_finished_roll(self, roll_id, headers):
        return self._request(
            "POST", f"/mill/finished-rolls/{roll_id}/release", {}, headers
        )

    def close_out_finished_roll(self, roll_id, headers):
        return self._request(
            "POST", f"/mill/finished-rolls/{roll_id}/close-out", {}, headers
        )

    # ------------------------------------------------------------------
    # Customer orders
    # ------------------------------------------------------------------
    def create_customer_order(self, payload, headers):
        return self._request("POST", "/mill/customer-orders", payload, headers)

    def list_customer_orders(self, headers, params=None):
        return self._request(
            "GET", "/mill/customer-orders", headers=headers, params=params
        )

    def get_customer_order(self, order_id, headers):
        return self._request(
            "GET", f"/mill/customer-orders/{order_id}", headers=headers
        )

    def allocate_roll(self, order_id, payload, headers):
        return self._request(
            "POST", f"/mill/customer-orders/{order_id}/allocate", payload, headers
        )

    def cancel_customer_order(self, order_id, headers):
        return self._request(
            "POST", f"/mill/customer-orders/{order_id}/cancel", {}, headers
        )


api_client = ApiClient()
