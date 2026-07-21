"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Store ----
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # ---- Sku ----
    def create_sku(self, payload, headers):
        return self._request("POST", "/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/skus/{sku_id}", headers=headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def redeem_points(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/redeem", payload, headers)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def fulfill_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # ---- CookingClass ----
    def create_cooking_class(self, payload, headers):
        return self._request("POST", "/cooking-classes", payload, headers)

    def get_cooking_class(self, class_id, headers):
        return self._request("GET", f"/cooking-classes/{class_id}", headers=headers)

    def list_cooking_classes(self, headers, params=None):
        return self._request("GET", "/cooking-classes", headers=headers, params=params)

    def open_class(self, class_id, headers):
        return self._request("POST", f"/cooking-classes/{class_id}/open", {}, headers)

    def complete_class(self, class_id, headers):
        return self._request("POST", f"/cooking-classes/{class_id}/complete", {}, headers)

    def cancel_class(self, class_id, headers):
        return self._request("POST", f"/cooking-classes/{class_id}/cancel", {}, headers)

    # ---- ClassRegistration ----
    def create_class_registration(self, payload, headers):
        return self._request("POST", "/class-registrations", payload, headers)

    def get_class_registration(self, registration_id, headers):
        return self._request("GET", f"/class-registrations/{registration_id}", headers=headers)

    def list_class_registrations(self, headers, params=None):
        return self._request("GET", "/class-registrations", headers=headers, params=params)

    def mark_attendance(self, registration_id, payload, headers):
        return self._request("POST", f"/class-registrations/{registration_id}/mark-attendance", payload, headers)

    def cancel_class_registration(self, registration_id, headers):
        return self._request("POST", f"/class-registrations/{registration_id}/cancel", {}, headers)

    # ---- ServiceTicket ----
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def complete_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/complete", {}, headers)

    def cancel_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/cancel", {}, headers)

    # ---- Return ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", {}, headers)

    # ---- SpecialOrder ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/special-orders/{special_order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def quote_special_order(self, special_order_id, payload, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/quote", payload, headers)

    def request_revision(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/request-revision", {}, headers)

    def accept_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/accept", {}, headers)

    def cancel_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/cancel", {}, headers)

    # ---- Registry ----
    def create_registry(self, payload, headers):
        return self._request("POST", "/registries", payload, headers)

    def get_registry(self, registry_id, headers):
        return self._request("GET", f"/registries/{registry_id}", headers=headers)

    def list_registries(self, headers, params=None):
        return self._request("GET", "/registries", headers=headers, params=params)

    def purchase_registry(self, registry_id, payload, headers):
        return self._request("POST", f"/registries/{registry_id}/purchase", payload, headers)


api_client = ApiClient()
