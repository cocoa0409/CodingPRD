"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Shop -------------------------------------------------------------
    def create_shop(self, payload, headers):
        return self._request("POST", "/shops", payload, headers)

    def list_shops(self, headers, params=None):
        return self._request("GET", "/shops", headers=headers, params=params)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    def close_shop(self, shop_id, headers):
        return self._request("POST", f"/shops/{shop_id}/close", {}, headers)

    def reopen_shop(self, shop_id, headers):
        return self._request("POST", f"/shops/{shop_id}/reopen", {}, headers)

    # ---- Barber -----------------------------------------------------------
    def create_barber(self, payload, headers):
        return self._request("POST", "/barbers", payload, headers)

    def list_barbers(self, headers, params=None):
        return self._request("GET", "/barbers", headers=headers, params=params)

    def get_barber(self, barber_id, headers):
        return self._request("GET", f"/barbers/{barber_id}", headers=headers)

    def activate_license(self, barber_id, headers):
        return self._request("POST", f"/barbers/{barber_id}/license/activate", {}, headers)

    def suspend_license(self, barber_id, headers):
        return self._request("POST", f"/barbers/{barber_id}/license/suspend", {}, headers)

    def revoke_license(self, barber_id, headers):
        return self._request("POST", f"/barbers/{barber_id}/license/revoke", {}, headers)

    def list_barber_settlements(self, barber_id, headers, params=None):
        return self._request(
            "GET", f"/barbers/{barber_id}/settlements", headers=headers, params=params
        )

    def create_settlement(self, barber_id, payload, headers):
        return self._request("POST", f"/barbers/{barber_id}/settlements", payload, headers)

    # ---- DailySettlement (top-level reads) --------------------------------
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    # ---- Chair ------------------------------------------------------------
    def create_chair(self, payload, headers):
        return self._request("POST", "/chairs", payload, headers)

    def list_chairs(self, headers, params=None):
        return self._request("GET", "/chairs", headers=headers, params=params)

    def get_chair(self, chair_id, headers):
        return self._request("GET", f"/chairs/{chair_id}", headers=headers)

    # ---- BarberShift ------------------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/cancel", {}, headers)

    # ---- ServiceMenuItem --------------------------------------------------
    def create_service(self, payload, headers):
        return self._request("POST", "/services", payload, headers)

    def list_services(self, headers, params=None):
        return self._request("GET", "/services", headers=headers, params=params)

    def get_service(self, service_id, headers):
        return self._request("GET", f"/services/{service_id}", headers=headers)

    def delist_service(self, service_id, headers):
        return self._request("POST", f"/services/{service_id}/delist", {}, headers)

    # ---- AddOn ------------------------------------------------------------
    def create_addon(self, payload, headers):
        return self._request("POST", "/addons", payload, headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/addons", headers=headers, params=params)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/addons/{addon_id}", headers=headers)

    def delist_addon(self, addon_id, headers):
        return self._request("POST", f"/addons/{addon_id}/delist", {}, headers)

    # ---- ProductSku -------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def delist_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/delist", {}, headers)

    # ---- Membership -------------------------------------------------------
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def retire_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/retire", {}, headers)

    # ---- Customer ---------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def subscribe_customer(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/subscribe", payload, headers
        )

    # ---- Appointment ------------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/check-in", {}, headers
        )

    def no_show_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/no-show", {}, headers
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", {}, headers
        )

    # ---- QueueTicket ------------------------------------------------------
    def create_queue_ticket(self, payload, headers):
        return self._request("POST", "/queue", payload, headers)

    def list_queue(self, headers, params=None):
        return self._request("GET", "/queue", headers=headers, params=params)

    def get_queue_ticket(self, queue_ticket_id, headers):
        return self._request("GET", f"/queue/{queue_ticket_id}", headers=headers)

    def serve_queue_ticket(self, queue_ticket_id, headers):
        return self._request("POST", f"/queue/{queue_ticket_id}/serve", {}, headers)

    def abandon_queue_ticket(self, queue_ticket_id, headers):
        return self._request("POST", f"/queue/{queue_ticket_id}/abandon", {}, headers)

    # ---- Ticket -----------------------------------------------------------
    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def set_ticket_lines(self, ticket_id, payload, headers):
        return self._request("PUT", f"/tickets/{ticket_id}/lines", payload, headers)

    def checkout_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/checkout", {}, headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/void", {}, headers)


api_client = ApiClient()
