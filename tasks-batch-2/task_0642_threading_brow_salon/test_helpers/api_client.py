"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Salon -----------------------------------------------------------
    def create_salon(self, payload, headers):
        return self._request("POST", "/salon-svc/salons", payload, headers)

    def list_salons(self, headers, params=None):
        return self._request("GET", "/salon-svc/salons", headers=headers, params=params)

    def get_salon(self, salon_id, headers):
        return self._request("GET", f"/salon-svc/salons/{salon_id}", headers=headers)

    def open_salon(self, salon_id, payload, headers):
        return self._request(
            "POST", f"/salon-svc/salons/{salon_id}/open", payload, headers
        )

    def close_salon(self, salon_id, payload, headers):
        return self._request(
            "POST", f"/salon-svc/salons/{salon_id}/close", payload, headers
        )

    # ---- Technician ------------------------------------------------------
    def create_technician(self, payload, headers):
        return self._request("POST", "/salon-svc/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request(
            "GET", "/salon-svc/technicians", headers=headers, params=params
        )

    def get_technician(self, technician_id, headers):
        return self._request(
            "GET", f"/salon-svc/technicians/{technician_id}", headers=headers
        )

    # ---- Chair -----------------------------------------------------------
    def create_chair(self, payload, headers):
        return self._request("POST", "/salon-svc/chairs", payload, headers)

    def list_chairs(self, headers, params=None):
        return self._request("GET", "/salon-svc/chairs", headers=headers, params=params)

    def get_chair(self, chair_id, headers):
        return self._request("GET", f"/salon-svc/chairs/{chair_id}", headers=headers)

    def mark_chair_sanitized(self, chair_id, headers):
        return self._request(
            "POST", f"/salon-svc/chairs/{chair_id}/mark-sanitized", {}, headers
        )

    def take_chair_out_of_service(self, chair_id, headers):
        return self._request(
            "POST", f"/salon-svc/chairs/{chair_id}/take-out-of-service", {}, headers
        )

    def return_chair_to_service(self, chair_id, headers):
        return self._request(
            "POST", f"/salon-svc/chairs/{chair_id}/return-to-service", {}, headers
        )

    # ---- Member ----------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/salon-svc/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/salon-svc/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/salon-svc/members/{member_id}", headers=headers)

    def create_loyalty_adjustment(self, member_id, payload, headers):
        return self._request(
            "POST", f"/salon-svc/members/{member_id}/loyalty-adjustments", payload, headers
        )

    # ---- LoyaltyLedgerEntry ----------------------------------------------
    def list_loyalty_entries(self, headers, params=None):
        return self._request(
            "GET", "/salon-svc/loyalty-entries", headers=headers, params=params
        )

    def get_loyalty_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/salon-svc/loyalty-entries/{entry_id}", headers=headers
        )

    # ---- MembershipPackage -----------------------------------------------
    def create_package(self, payload, headers):
        return self._request("POST", "/salon-svc/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/salon-svc/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/salon-svc/packages/{package_id}", headers=headers)

    def activate_package(self, package_id, headers):
        return self._request(
            "POST", f"/salon-svc/packages/{package_id}/activate", {}, headers
        )

    def cancel_package(self, package_id, headers):
        return self._request(
            "POST", f"/salon-svc/packages/{package_id}/cancel", {}, headers
        )

    # ---- ServiceMenuItem -------------------------------------------------
    def create_service_menu_item(self, payload, headers):
        return self._request("POST", "/salon-svc/service-menu-items", payload, headers)

    def list_service_menu_items(self, headers, params=None):
        return self._request(
            "GET", "/salon-svc/service-menu-items", headers=headers, params=params
        )

    def get_service_menu_item(self, service_item_id, headers):
        return self._request(
            "GET", f"/salon-svc/service-menu-items/{service_item_id}", headers=headers
        )

    # ---- AddOn -----------------------------------------------------------
    def create_add_on(self, payload, headers):
        return self._request("POST", "/salon-svc/add-ons", payload, headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/salon-svc/add-ons", headers=headers, params=params)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/salon-svc/add-ons/{add_on_id}", headers=headers)

    # ---- RetailProduct ---------------------------------------------------
    def create_retail_product(self, payload, headers):
        return self._request("POST", "/salon-svc/retail-products", payload, headers)

    def list_retail_products(self, headers, params=None):
        return self._request(
            "GET", "/salon-svc/retail-products", headers=headers, params=params
        )

    def get_retail_product(self, retail_product_id, headers):
        return self._request(
            "GET", f"/salon-svc/retail-products/{retail_product_id}", headers=headers
        )

    # ---- QueueTicket -----------------------------------------------------
    def create_queue_ticket(self, payload, headers):
        return self._request("POST", "/salon-svc/queue-tickets", payload, headers)

    def list_queue_tickets(self, headers, params=None):
        return self._request(
            "GET", "/salon-svc/queue-tickets", headers=headers, params=params
        )

    def get_queue_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/salon-svc/queue-tickets/{ticket_id}", headers=headers
        )

    def call_queue_ticket(self, ticket_id, headers, payload=None):
        return self._request(
            "POST", f"/salon-svc/queue-tickets/{ticket_id}/call", payload or {}, headers
        )

    def requeue_queue_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/salon-svc/queue-tickets/{ticket_id}/requeue", {}, headers
        )

    def no_show_queue_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/salon-svc/queue-tickets/{ticket_id}/no-show", {}, headers
        )

    def cancel_queue_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/salon-svc/queue-tickets/{ticket_id}/cancel", {}, headers
        )

    # ---- ServiceVisit ----------------------------------------------------
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/salon-svc/service-visits", payload, headers)

    def list_service_visits(self, headers, params=None):
        return self._request(
            "GET", "/salon-svc/service-visits", headers=headers, params=params
        )

    def get_service_visit(self, visit_id, headers):
        return self._request(
            "GET", f"/salon-svc/service-visits/{visit_id}", headers=headers
        )

    def add_line_item(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/salon-svc/service-visits/{visit_id}/line-items", payload, headers
        )

    def list_visit_line_items(self, visit_id, headers, params=None):
        return self._request(
            "GET",
            f"/salon-svc/service-visits/{visit_id}/line-items",
            headers=headers,
            params=params,
        )

    def complete_service_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/salon-svc/service-visits/{visit_id}/complete", {}, headers
        )

    def settle_service_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/salon-svc/service-visits/{visit_id}/settle", payload or {}, headers
        )

    def void_service_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/salon-svc/service-visits/{visit_id}/void", {}, headers
        )

    # ---- VisitLineItem ---------------------------------------------------
    def list_line_items(self, headers, params=None):
        return self._request(
            "GET", "/salon-svc/visit-line-items", headers=headers, params=params
        )

    def get_line_item(self, line_id, headers):
        return self._request(
            "GET", f"/salon-svc/visit-line-items/{line_id}", headers=headers
        )

    def void_line_item(self, line_id, headers):
        return self._request(
            "POST", f"/salon-svc/visit-line-items/{line_id}/void", {}, headers
        )


api_client = ApiClient()
