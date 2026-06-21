"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customer ───────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ─── MeasurementProfile ─────────────────────────────────────────────
    def create_measurement_profile(self, payload, headers):
        return self._request("POST", "/measurement-profiles", payload, headers)

    def get_measurement_profile(self, profile_id, headers):
        return self._request("GET", f"/measurement-profiles/{profile_id}", headers=headers)

    def list_measurement_profiles(self, headers, params=None):
        return self._request("GET", "/measurement-profiles", headers=headers, params=params)

    # ─── Fabric ─────────────────────────────────────────────────────────
    def create_fabric(self, payload, headers):
        return self._request("POST", "/fabrics", payload, headers)

    def get_fabric(self, fabric_id, headers):
        return self._request("GET", f"/fabrics/{fabric_id}", headers=headers)

    def list_fabrics(self, headers, params=None):
        return self._request("GET", "/fabrics", headers=headers, params=params)

    def update_fabric(self, fabric_id, payload, headers):
        return self._request("PATCH", f"/fabrics/{fabric_id}", payload, headers)

    def list_fabric_option_lines(self, fabric_id, headers, params=None):
        return self._request("GET", f"/fabrics/{fabric_id}/option-lines", headers=headers, params=params)

    # ─── Tailor ─────────────────────────────────────────────────────────
    def create_tailor(self, payload, headers):
        return self._request("POST", "/tailors", payload, headers)

    def get_tailor(self, tailor_id, headers):
        return self._request("GET", f"/tailors/{tailor_id}", headers=headers)

    def list_tailors(self, headers, params=None):
        return self._request("GET", "/tailors", headers=headers, params=params)

    def list_tailor_fittings(self, tailor_id, headers, params=None):
        return self._request("GET", f"/tailors/{tailor_id}/fittings", headers=headers, params=params)

    # ─── FittingRoom ────────────────────────────────────────────────────
    def create_fitting_room(self, payload, headers):
        return self._request("POST", "/fitting-rooms", payload, headers)

    def get_fitting_room(self, room_id, headers):
        return self._request("GET", f"/fitting-rooms/{room_id}", headers=headers)

    def list_fitting_rooms(self, headers, params=None):
        return self._request("GET", "/fitting-rooms", headers=headers, params=params)

    def list_room_fittings(self, room_id, headers, params=None):
        return self._request("GET", f"/fitting-rooms/{room_id}/fittings", headers=headers, params=params)

    # ─── GroupOrder ─────────────────────────────────────────────────────
    def create_group_order(self, payload, headers):
        return self._request("POST", "/group-orders", payload, headers)

    def get_group_order(self, group_id, headers):
        return self._request("GET", f"/group-orders/{group_id}", headers=headers)

    def list_group_orders(self, headers, params=None):
        return self._request("GET", "/group-orders", headers=headers, params=params)

    def list_group_member_orders(self, group_id, headers, params=None):
        return self._request("GET", f"/group-orders/{group_id}/orders", headers=headers, params=params)

    def lock_group_order(self, group_id, payload, headers):
        return self._request("POST", f"/group-orders/{group_id}/lock", payload, headers)

    def cancel_group_order(self, group_id, payload, headers):
        return self._request("POST", f"/group-orders/{group_id}/cancel", payload, headers)

    # ─── GarmentOrder ───────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def confirm_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/confirm", payload if payload is not None else {}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/cancel", payload if payload is not None else {}, headers)

    def pickup_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pickup", payload, headers)

    def get_pickup(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/pickup", headers=headers, params=params)

    # ─── GarmentOptionLine ──────────────────────────────────────────────
    def create_option_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/option-lines", payload, headers)

    def list_option_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/option-lines", headers=headers, params=params)

    def delete_option_line(self, order_id, line_id, headers):
        return self._request("DELETE", f"/orders/{order_id}/option-lines/{line_id}", headers=headers)

    # ─── Fitting ────────────────────────────────────────────────────────
    def create_fitting(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fittings", payload, headers)

    def list_fittings(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/fittings", headers=headers, params=params)

    def record_fitting_outcome(self, order_id, fitting_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fittings/{fitting_id}/record-outcome", payload, headers)

    # ─── AlterationTicket ───────────────────────────────────────────────
    def create_alteration(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/alterations", payload, headers)

    def list_alterations(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/alterations", headers=headers, params=params)

    def complete_alteration(self, order_id, ticket_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/alterations/{ticket_id}/complete", payload if payload is not None else {}, headers)

    def void_alteration(self, order_id, ticket_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/alterations/{ticket_id}/void", payload if payload is not None else {}, headers)

    # ─── Payment ────────────────────────────────────────────────────────
    def create_payment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/payments", payload, headers)

    def list_payments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/payments", headers=headers, params=params)

    def apply_credit(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/apply-credit", payload, headers)


api_client = ApiClient()
