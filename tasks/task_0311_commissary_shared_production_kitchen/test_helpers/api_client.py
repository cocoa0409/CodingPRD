"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP call, envelope parsing, and Response object construction.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ---- Member ----
    def register_member(self, payload, headers):
        return self._request("POST", "/members/register", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def top_up_wallet(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/wallet/top-ups", payload, headers)

    def suspend_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/suspend", payload, headers)

    def reinstate_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", payload, headers)

    def close_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/close", payload, headers)

    # ---- Station ----
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def update_station(self, station_id, payload, headers):
        return self._request("PATCH", f"/stations/{station_id}", payload, headers)

    def list_station_bookings(self, station_id, headers, params=None):
        return self._request("GET", f"/stations/{station_id}/bookings", headers=headers, params=params)

    # ---- Booking ----
    def create_booking(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/bookings", payload, headers)

    def list_member_bookings(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/bookings", headers=headers, params=params)

    def get_member_booking(self, member_id, booking_id, headers):
        return self._request("GET", f"/members/{member_id}/bookings/{booking_id}", headers=headers)

    def cancel_booking(self, member_id, booking_id, headers):
        return self._request("POST", f"/members/{member_id}/bookings/{booking_id}/cancel", headers=headers)

    def complete_booking(self, member_id, booking_id, headers):
        return self._request("POST", f"/members/{member_id}/bookings/{booking_id}/complete", headers=headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    # ---- StorageUnit ----
    def create_storage_unit(self, payload, headers):
        return self._request("POST", "/storage-units", payload, headers)

    def list_storage_units(self, headers, params=None):
        return self._request("GET", "/storage-units", headers=headers, params=params)

    def get_storage_unit(self, unit_id, headers):
        return self._request("GET", f"/storage-units/{unit_id}", headers=headers)

    def create_temp_log(self, unit_id, payload, headers):
        return self._request("POST", f"/storage-units/{unit_id}/temp-logs", payload, headers)

    def list_temp_logs_for_unit(self, unit_id, headers, params=None):
        return self._request("GET", f"/storage-units/{unit_id}/temp-logs", headers=headers, params=params)

    def certify_temp_log(self, unit_id, log_id, headers):
        return self._request("POST", f"/storage-units/{unit_id}/temp-logs/{log_id}/certify", headers=headers)

    def certify_compliant(self, unit_id, headers):
        return self._request("POST", f"/storage-units/{unit_id}/certify-compliant", headers=headers)

    def get_temp_log(self, log_id, headers):
        return self._request("GET", f"/temp-logs/{log_id}", headers=headers)

    def list_temp_logs(self, headers, params=None):
        return self._request("GET", "/temp-logs", headers=headers, params=params)

    # ---- StorageAssignment ----
    def create_storage_assignment(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/storage-assignments", payload, headers)

    def list_member_storage_assignments(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/storage-assignments", headers=headers, params=params)

    def list_unit_storage_assignments(self, unit_id, headers, params=None):
        return self._request("GET", f"/storage-units/{unit_id}/storage-assignments", headers=headers, params=params)

    def get_member_storage_assignment(self, member_id, assignment_id, headers):
        return self._request("GET", f"/members/{member_id}/storage-assignments/{assignment_id}", headers=headers)

    def release_storage_assignment(self, member_id, assignment_id, headers):
        return self._request("POST", f"/members/{member_id}/storage-assignments/{assignment_id}/release", headers=headers)

    def release_quarantine(self, member_id, assignment_id, headers):
        return self._request("POST", f"/members/{member_id}/storage-assignments/{assignment_id}/release-quarantine", headers=headers)

    def get_storage_assignment(self, assignment_id, headers):
        return self._request("GET", f"/storage-assignments/{assignment_id}", headers=headers)

    def list_storage_assignments(self, headers, params=None):
        return self._request("GET", "/storage-assignments", headers=headers, params=params)

    # ---- Ingredient ----
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/ingredients", payload, headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/ingredients", headers=headers, params=params)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/ingredients/{ingredient_id}", headers=headers)

    def list_ingredient_recipe_components(self, ingredient_id, headers, params=None):
        return self._request("GET", f"/ingredients/{ingredient_id}/recipe-components", headers=headers, params=params)

    def list_ingredient_orders_for_ingredient(self, ingredient_id, headers, params=None):
        return self._request("GET", f"/ingredients/{ingredient_id}/ingredient-orders", headers=headers, params=params)

    # ---- Recipe + RecipeComponent ----
    def create_recipe(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/recipes", payload, headers)

    def list_member_recipes(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/recipes", headers=headers, params=params)

    def get_member_recipe(self, member_id, recipe_id, headers):
        return self._request("GET", f"/members/{member_id}/recipes/{recipe_id}", headers=headers)

    def add_recipe_component(self, member_id, recipe_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/recipes/{recipe_id}/components", payload, headers)

    def list_recipe_components(self, member_id, recipe_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/recipes/{recipe_id}/components", headers=headers, params=params)

    def publish_recipe(self, member_id, recipe_id, headers):
        return self._request("POST", f"/members/{member_id}/recipes/{recipe_id}/publish", headers=headers)

    def revise_recipe(self, member_id, recipe_id, headers):
        return self._request("POST", f"/members/{member_id}/recipes/{recipe_id}/revise", headers=headers)

    def retire_recipe(self, member_id, recipe_id, headers):
        return self._request("POST", f"/members/{member_id}/recipes/{recipe_id}/retire", headers=headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/recipes", headers=headers, params=params)

    def get_recipe_component(self, component_id, headers):
        return self._request("GET", f"/recipe-components/{component_id}", headers=headers)

    def list_all_recipe_components(self, headers, params=None):
        return self._request("GET", "/recipe-components", headers=headers, params=params)

    def list_recipe_batches(self, member_id, recipe_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/recipes/{recipe_id}/batches", headers=headers, params=params)

    # ---- ProductionBatch ----
    def create_batch(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/batches", payload, headers)

    def list_member_batches(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/batches", headers=headers, params=params)

    def get_member_batch(self, member_id, batch_id, headers):
        return self._request("GET", f"/members/{member_id}/batches/{batch_id}", headers=headers)

    def start_batch(self, member_id, batch_id, headers):
        return self._request("POST", f"/members/{member_id}/batches/{batch_id}/start", headers=headers)

    def complete_batch(self, member_id, batch_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/batches/{batch_id}/complete", payload, headers)

    def scrap_batch(self, member_id, batch_id, headers):
        return self._request("POST", f"/members/{member_id}/batches/{batch_id}/scrap", headers=headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    # ---- IngredientOrder ----
    def create_ingredient_order(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/ingredient-orders", payload, headers)

    def list_member_ingredient_orders(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/ingredient-orders", headers=headers, params=params)

    def receive_ingredient_order(self, member_id, order_id, headers):
        return self._request("POST", f"/members/{member_id}/ingredient-orders/{order_id}/receive", headers=headers)

    def cancel_ingredient_order(self, member_id, order_id, headers):
        return self._request("POST", f"/members/{member_id}/ingredient-orders/{order_id}/cancel", headers=headers)

    def get_ingredient_order(self, order_id, headers):
        return self._request("GET", f"/ingredient-orders/{order_id}", headers=headers)

    def list_ingredient_orders(self, headers, params=None):
        return self._request("GET", "/ingredient-orders", headers=headers, params=params)

    # ---- EventPackout ----
    def create_packout(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/packouts", payload, headers)

    def list_member_packouts(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/packouts", headers=headers, params=params)

    def get_member_packout(self, member_id, packout_id, headers):
        return self._request("GET", f"/members/{member_id}/packouts/{packout_id}", headers=headers)

    def seal_packout(self, member_id, packout_id, headers):
        return self._request("POST", f"/members/{member_id}/packouts/{packout_id}/seal", headers=headers)

    def ship_packout(self, member_id, packout_id, headers):
        return self._request("POST", f"/members/{member_id}/packouts/{packout_id}/ship", headers=headers)

    def get_packout(self, packout_id, headers):
        return self._request("GET", f"/packouts/{packout_id}", headers=headers)

    def list_packouts(self, headers, params=None):
        return self._request("GET", "/packouts", headers=headers, params=params)

    # ---- Invoice ----
    def create_invoice(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/invoices", payload, headers)

    def list_member_invoices(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/invoices", headers=headers, params=params)

    def get_member_invoice(self, member_id, invoice_id, headers):
        return self._request("GET", f"/members/{member_id}/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, member_id, invoice_id, headers):
        return self._request("POST", f"/members/{member_id}/invoices/{invoice_id}/issue", headers=headers)

    def pay_invoice(self, member_id, invoice_id, headers):
        return self._request("POST", f"/members/{member_id}/invoices/{invoice_id}/pay", headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)


api_client = ApiClient()
