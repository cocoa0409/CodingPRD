"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- CutTypes ----
    def create_cut_type(self, payload, headers):
        return self._request("POST", "/cut-types", payload, headers=headers)

    def get_cut_type(self, cut_type_id, headers):
        return self._request("GET", f"/cut-types/{cut_type_id}", headers=headers)

    def list_cut_types(self, headers, params=None):
        return self._request("GET", "/cut-types", headers=headers, params=params)

    # ---- PricingPolicies ----
    def create_pricing_policy(self, payload, headers):
        return self._request("POST", "/pricing-policies", payload, headers=headers)

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/pricing-policies/{policy_id}", headers=headers)

    # ---- InventoryLots ----
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/inventory-lots", payload, headers=headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def start_aging(self, lot_id, payload, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/start-aging", payload, headers=headers)

    def complete_aging(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/complete-aging", {}, headers=headers)

    def discard_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/discard", {}, headers=headers)

    def list_lot_draws_for_lot(self, lot_id, headers, params=None):
        return self._request("GET", f"/inventory-lots/{lot_id}/draws", headers=headers, params=params)

    # ---- DryAgeLockers ----
    def create_locker(self, payload, headers):
        return self._request("POST", "/dry-age-lockers", payload, headers=headers)

    def get_locker(self, locker_id, headers):
        return self._request("GET", f"/dry-age-lockers/{locker_id}", headers=headers)

    def create_temp_reading(self, locker_id, payload, headers):
        return self._request("POST", f"/dry-age-lockers/{locker_id}/temp-readings", payload, headers=headers)

    def list_temp_readings(self, locker_id, headers, params=None):
        return self._request("GET", f"/dry-age-lockers/{locker_id}/temp-readings", headers=headers, params=params)

    def release_locker(self, locker_id, payload, headers):
        return self._request("POST", f"/dry-age-lockers/{locker_id}/release", payload, headers=headers)

    # ---- AnimalShares / ShareClaims ----
    def create_animal_share(self, payload, headers):
        return self._request("POST", "/animal-shares", payload, headers=headers)

    def get_animal_share(self, share_id, headers):
        return self._request("GET", f"/animal-shares/{share_id}", headers=headers)

    def break_down_share(self, share_id, payload, headers):
        return self._request("POST", f"/animal-shares/{share_id}/break-down", payload, headers=headers)

    def cancel_share(self, share_id, headers):
        return self._request("POST", f"/animal-shares/{share_id}/cancel", {}, headers=headers)

    def create_share_claim(self, payload, headers):
        return self._request("POST", "/share-claims", payload, headers=headers)

    def get_share_claim(self, claim_id, headers):
        return self._request("GET", f"/share-claims/{claim_id}", headers=headers)

    def list_share_claims(self, headers, params=None):
        return self._request("GET", "/share-claims", headers=headers, params=params)

    def cancel_share_claim(self, claim_id, headers):
        return self._request("POST", f"/share-claims/{claim_id}/cancel", {}, headers=headers)

    # ---- HolidayWindows ----
    def create_holiday_window(self, payload, headers):
        return self._request("POST", "/holiday-windows", payload, headers=headers)

    def get_holiday_window(self, window_id, headers):
        return self._request("GET", f"/holiday-windows/{window_id}", headers=headers)

    # ---- CustomOrders / OrderLines ----
    def list_custom_orders(self, headers, params=None):
        return self._request("GET", "/custom-orders", headers=headers, params=params)

    def create_custom_order(self, payload, headers):
        return self._request("POST", "/custom-orders", payload, headers=headers)

    def get_custom_order(self, order_id, headers):
        return self._request("GET", f"/custom-orders/{order_id}", headers=headers)

    def list_order_lines_for_order(self, order_id, headers, params=None):
        return self._request("GET", f"/custom-orders/{order_id}/order-lines", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/custom-orders/{order_id}/confirm", {}, headers=headers)

    def fill_order(self, order_id, headers):
        return self._request("POST", f"/custom-orders/{order_id}/fill", {}, headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/custom-orders/{order_id}/cancel", {}, headers=headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def draw_line(self, line_id, payload, headers):
        return self._request("POST", f"/order-lines/{line_id}/draw", payload, headers=headers)

    def short_line(self, line_id, headers):
        return self._request("POST", f"/order-lines/{line_id}/short", {}, headers=headers)

    # ---- SausageBatches / BatchInputs ----
    def create_sausage_batch(self, payload, headers):
        return self._request("POST", "/sausage-batches", payload, headers=headers)

    def get_sausage_batch(self, batch_id, headers):
        return self._request("GET", f"/sausage-batches/{batch_id}", headers=headers)

    def list_sausage_batches(self, headers, params=None):
        return self._request("GET", "/sausage-batches", headers=headers, params=params)

    def add_batch_input(self, batch_id, payload, headers):
        return self._request("POST", f"/sausage-batches/{batch_id}/inputs", payload, headers=headers)

    def list_batch_inputs_for_batch(self, batch_id, headers, params=None):
        return self._request("GET", f"/sausage-batches/{batch_id}/inputs", headers=headers, params=params)

    def reserve_batch(self, batch_id, headers):
        return self._request("POST", f"/sausage-batches/{batch_id}/reserve", {}, headers=headers)

    def produce_batch(self, batch_id, headers):
        return self._request("POST", f"/sausage-batches/{batch_id}/produce", {}, headers=headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/sausage-batches/{batch_id}/cancel", {}, headers=headers)

    # ---- LotDraws / BatchInputs / TempReadings single reads + lists ----
    def get_lot_draw(self, draw_id, headers):
        return self._request("GET", f"/lot-draws/{draw_id}", headers=headers)

    def list_lot_draws(self, headers, params=None):
        return self._request("GET", "/lot-draws", headers=headers, params=params)

    def get_batch_input(self, input_id, headers):
        return self._request("GET", f"/batch-inputs/{input_id}", headers=headers)

    def list_batch_inputs(self, headers, params=None):
        return self._request("GET", "/batch-inputs", headers=headers, params=params)

    def get_temp_reading(self, reading_id, headers):
        return self._request("GET", f"/temp-readings/{reading_id}", headers=headers)

    # ---- Test clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
