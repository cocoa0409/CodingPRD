"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Ingredient ----
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/ingredients", payload, headers)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/ingredients/{ingredient_id}", headers=headers)

    # ---- MenuItem ----
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    # ---- RecipeLine ----
    def create_recipe_line(self, payload, headers):
        return self._request("POST", "/recipe-lines", payload, headers)

    def get_recipe_line(self, recipe_line_id, headers):
        return self._request("GET", f"/recipe-lines/{recipe_line_id}", headers=headers)

    def list_recipe_lines(self, headers, params=None):
        return self._request("GET", "/recipe-lines", headers=headers, params=params)

    # ---- Station ----
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    # ---- EquipmentItem ----
    def create_equipment_item(self, payload, headers):
        return self._request("POST", "/equipment-items", payload, headers)

    def get_equipment_item(self, equipment_id, headers):
        return self._request("GET", f"/equipment-items/{equipment_id}", headers=headers)

    def get_equipment_availability(self, equipment_id, headers, params=None):
        return self._request(
            "GET", f"/equipment-items/{equipment_id}/availability",
            headers=headers, params=params,
        )

    # ---- StaffMember ----
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    # ---- EventOrder ----
    def create_event_order(self, payload, headers):
        return self._request("POST", "/event-orders", payload, headers)

    def get_event_order(self, order_id, headers):
        return self._request("GET", f"/event-orders/{order_id}", headers=headers)

    def list_event_orders(self, headers, params=None):
        return self._request("GET", "/event-orders", headers=headers, params=params)

    def generate_quote(self, order_id, payload, headers):
        return self._request("POST", f"/event-orders/{order_id}/quotes", payload, headers)

    def revise_order(self, order_id, headers):
        return self._request("POST", f"/event-orders/{order_id}/revise", {}, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/event-orders/{order_id}/confirm", {}, headers)

    def start_production(self, order_id, headers):
        return self._request("POST", f"/event-orders/{order_id}/start-production", {}, headers)

    def pack_order(self, order_id, headers):
        return self._request("POST", f"/event-orders/{order_id}/pack", {}, headers)

    def dispatch_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/event-orders/{order_id}/dispatch", payload or {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/event-orders/{order_id}/complete", {}, headers)

    def actualize_order(self, order_id, payload, headers):
        return self._request("POST", f"/event-orders/{order_id}/actualize", payload, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/event-orders/{order_id}/cancel", payload or {}, headers)

    # ---- OrderLine ----
    def create_order_line(self, payload, headers):
        return self._request("POST", "/order-lines", payload, headers)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def delete_order_line(self, order_line_id, headers):
        return self._request("DELETE", f"/order-lines/{order_line_id}", headers=headers)

    # ---- Quote ----
    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    # ---- ProductionRun ----
    def create_production_run(self, payload, headers):
        return self._request("POST", "/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/start", {}, headers)

    def complete_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/complete", {}, headers)

    def reschedule_run(self, run_id, headers, payload=None):
        return self._request("POST", f"/production-runs/{run_id}/reschedule", payload or {}, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/cancel", {}, headers)

    # ---- RentalReservation ----
    def create_rental_reservation(self, payload, headers):
        return self._request("POST", "/rental-reservations", payload, headers)

    def get_rental_reservation(self, reservation_id, headers):
        return self._request("GET", f"/rental-reservations/{reservation_id}", headers=headers)

    def list_rental_reservations(self, headers, params=None):
        return self._request("GET", "/rental-reservations", headers=headers, params=params)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{reservation_id}/cancel", {}, headers)

    # ---- StaffAssignment ----
    def create_staff_assignment(self, payload, headers):
        return self._request("POST", "/staff-assignments", payload, headers)

    def get_staff_assignment(self, assignment_id, headers):
        return self._request("GET", f"/staff-assignments/{assignment_id}", headers=headers)

    def list_staff_assignments(self, headers, params=None):
        return self._request("GET", "/staff-assignments", headers=headers, params=params)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/staff-assignments/{assignment_id}/confirm", {}, headers)

    def checkin_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/staff-assignments/{assignment_id}/check-in", payload, headers)

    def checkout_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/staff-assignments/{assignment_id}/check-out", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/staff-assignments/{assignment_id}/cancel", {}, headers)


api_client = ApiClient()
