"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------- customers
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/reinstate", {}, headers)

    # -------------------------------------------------------- catalog items
    def create_catalog_item(self, payload, headers):
        return self._request("POST", "/catalog-items", payload, headers)

    def get_catalog_item(self, item_id, headers):
        return self._request("GET", f"/catalog-items/{item_id}", headers=headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", "/catalog-items", headers=headers, params=params)

    def patch_catalog_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/catalog-items/{item_id}", payload, headers)

    def get_catalog_availability(self, item_id, start_date, end_date, headers):
        return self._request(
            "GET",
            f"/catalog-items/{item_id}/availability",
            headers=headers,
            params={"start_date": start_date, "end_date": end_date},
        )

    def list_catalog_item_recalls(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/catalog-items/{item_id}/recalls", headers=headers, params=params
        )

    # ------------------------------------------------------ inventory units
    def create_inventory_unit(self, payload, headers):
        return self._request("POST", "/inventory-units", payload, headers)

    def get_inventory_unit(self, unit_id, headers):
        return self._request("GET", f"/inventory-units/{unit_id}", headers=headers)

    def list_inventory_units(self, headers, params=None):
        return self._request("GET", "/inventory-units", headers=headers, params=params)

    def retire_inventory_unit(self, unit_id, headers):
        return self._request("POST", f"/inventory-units/{unit_id}/retire", {}, headers)

    def list_unit_cleaning_tickets(self, unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/inventory-units/{unit_id}/cleaning-tickets",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------- hotel partners
    def create_hotel_partner(self, payload, headers):
        return self._request("POST", "/hotel-partners", payload, headers)

    def get_hotel_partner(self, partner_id, headers):
        return self._request("GET", f"/hotel-partners/{partner_id}", headers=headers)

    def list_hotel_partners(self, headers, params=None):
        return self._request("GET", "/hotel-partners", headers=headers, params=params)

    def patch_hotel_partner(self, partner_id, payload, headers):
        return self._request("PATCH", f"/hotel-partners/{partner_id}", payload, headers)

    # ------------------------------------------------------ insurance plans
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/insurance-plans", payload, headers)

    def list_insurance_plans(self, headers, params=None):
        return self._request("GET", "/insurance-plans", headers=headers, params=params)

    def get_insurance_plan(self, plan_id, headers):
        return self._request("GET", f"/insurance-plans/{plan_id}", headers=headers)

    # -------------------------------------------------------- reservations
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/confirm", {}, headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel", {}, headers
        )

    def amend_reservation_dates(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/amend-dates", payload, headers
        )

    def settle_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/settle", {}, headers
        )

    def list_deposit_transactions(self, reservation_id, headers, params=None):
        return self._request(
            "GET",
            f"/reservations/{reservation_id}/deposit-transactions",
            headers=headers,
            params=params,
        )

    def list_reservation_extensions(self, reservation_id, headers, params=None):
        return self._request(
            "GET",
            f"/reservations/{reservation_id}/extensions",
            headers=headers,
            params=params,
        )

    def create_extension_request(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/extensions", payload, headers
        )

    # ---------------------------------------------------------- extensions
    def get_extension(self, extension_id, headers):
        return self._request("GET", f"/extensions/{extension_id}", headers=headers)

    def approve_extension(self, extension_id, headers):
        return self._request("POST", f"/extensions/{extension_id}/approve", {}, headers)

    def deny_extension(self, extension_id, headers):
        return self._request("POST", f"/extensions/{extension_id}/deny", {}, headers)

    # ----------------------------------------------------------- line items
    def get_reservation_line(self, line_id, headers):
        return self._request("GET", f"/reservation-lines/{line_id}", headers=headers)

    def list_reservation_lines(self, headers, params=None):
        return self._request("GET", "/reservation-lines", headers=headers, params=params)

    def list_line_damage_claims(self, line_id, headers, params=None):
        return self._request(
            "GET",
            f"/reservation-lines/{line_id}/damage-claims",
            headers=headers,
            params=params,
        )

    def reallocate_line(self, line_id, headers):
        return self._request(
            "POST", f"/reservation-lines/{line_id}/reallocate", {}, headers
        )

    # -------------------------------------------------------------- routes
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def add_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/routes/{route_id}/stops", headers=headers, params=params
        )

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", {}, headers)

    def recall_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/recall", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/complete", {}, headers)

    # --------------------------------------------------------------- stops
    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def list_all_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    def complete_route_stop(self, stop_id, headers):
        return self._request("POST", f"/route-stops/{stop_id}/complete", {}, headers)

    def fail_route_stop(self, stop_id, headers):
        return self._request("POST", f"/route-stops/{stop_id}/fail", {}, headers)

    # -------------------------------------------------------------- recalls
    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def activate_recall(self, recall_id, headers):
        return self._request("POST", f"/recalls/{recall_id}/activate", {}, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/recalls/{recall_id}/close", {}, headers)

    # ------------------------------------------------------ cleaning tickets
    def create_cleaning_ticket(self, payload, headers):
        return self._request("POST", "/cleaning-tickets", payload, headers)

    def get_cleaning_ticket(self, ticket_id, headers):
        return self._request("GET", f"/cleaning-tickets/{ticket_id}", headers=headers)

    def pass_cleaning_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/cleaning-tickets/{ticket_id}/pass", payload, headers
        )

    def fail_cleaning_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/cleaning-tickets/{ticket_id}/fail", payload, headers
        )

    # -------------------------------------------------------- damage claims
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def approve_damage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/approve", {}, headers
        )

    def deny_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/deny", {}, headers)

    def dispute_damage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/dispute", {}, headers
        )

    def reopen_damage_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/reopen", {}, headers
        )

    # --------------------------------------------------------------- clock
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
