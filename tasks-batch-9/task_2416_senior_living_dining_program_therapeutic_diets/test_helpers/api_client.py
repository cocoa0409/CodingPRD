"""API client: one method per endpoint defined in the PRD.

The service is deployed at the root of its host; there is no URL prefix in
front of the paths below.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------ community
    def create_community(self, payload, headers):
        return self._request("POST", "/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/communities/{community_id}", headers=headers)

    def list_community_venues(self, community_id, headers, params=None):
        return self._request(
            "GET", f"/communities/{community_id}/venues", headers=headers, params=params
        )

    def list_community_residents(self, community_id, headers, params=None):
        return self._request(
            "GET",
            f"/communities/{community_id}/residents",
            headers=headers,
            params=params,
        )

    def list_community_menu_cycles(self, community_id, headers, params=None):
        return self._request(
            "GET",
            f"/communities/{community_id}/menu-cycles",
            headers=headers,
            params=params,
        )

    def list_community_reconciliations(self, community_id, headers, params=None):
        return self._request(
            "GET",
            f"/communities/{community_id}/reconciliations",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------------------- venue
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venue_temperature_logs(self, venue_id, headers, params=None):
        return self._request(
            "GET", f"/venues/{venue_id}/temperature-logs", headers=headers, params=params
        )

    def create_temperature_log(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/temperature-logs", payload, headers
        )

    def get_seat_availability(self, venue_id, service_date, meal_period, headers):
        return self._request(
            "GET",
            f"/venues/{venue_id}/seat-availability",
            headers=headers,
            params={"service_date": service_date, "meal_period": meal_period},
        )

    # ------------------------------------------------------------- resident
    def create_resident(self, payload, headers):
        return self._request("POST", "/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    def set_dining_status(self, resident_id, dining_status, headers):
        return self._request(
            "POST",
            f"/residents/{resident_id}/dining-status",
            {"dining_status": dining_status},
            headers,
        )

    def create_substitution_rule(self, resident_id, payload, headers):
        return self._request(
            "POST", f"/residents/{resident_id}/substitution-rules", payload, headers
        )

    def list_substitution_rules(self, resident_id, headers, params=None):
        return self._request(
            "GET",
            f"/residents/{resident_id}/substitution-rules",
            headers=headers,
            params=params,
        )

    def create_intake_observation(self, resident_id, payload, headers):
        return self._request(
            "POST", f"/residents/{resident_id}/intake-observations", payload, headers
        )

    def list_intake_observations(self, resident_id, headers, params=None):
        return self._request(
            "GET",
            f"/residents/{resident_id}/intake-observations",
            headers=headers,
            params=params,
        )

    def list_resident_committee_feedback(self, resident_id, headers, params=None):
        return self._request(
            "GET",
            f"/residents/{resident_id}/committee-feedback",
            headers=headers,
            params=params,
        )

    def get_tray_card(self, resident_id, service_date, meal_period, headers):
        return self._request(
            "GET",
            f"/residents/{resident_id}/tray-card",
            headers=headers,
            params={"service_date": service_date, "meal_period": meal_period},
        )

    # ----------------------------------------------------------- diet order
    def create_diet_order(self, payload, headers):
        return self._request("POST", "/diet-orders", payload, headers)

    def get_diet_order(self, order_id, headers):
        return self._request("GET", f"/diet-orders/{order_id}", headers=headers)

    def list_diet_orders(self, headers, params=None):
        return self._request("GET", "/diet-orders", headers=headers, params=params)

    def dietitian_review_diet_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/diet-orders/{order_id}/dietitian-review", payload, headers
        )

    def resubmit_diet_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/diet-orders/{order_id}/resubmit", payload, headers
        )

    def discontinue_diet_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/diet-orders/{order_id}/discontinue", payload, headers
        )

    # ---------------------------------------------------------- reservation
    def create_reservation(self, payload, headers):
        return self._request("POST", "/seating-reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/seating-reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers, params=None):
        return self._request(
            "GET", "/seating-reservations", headers=headers, params=params
        )

    def seat_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/seating-reservations/{reservation_id}/seat", {}, headers
        )

    def release_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/seating-reservations/{reservation_id}/release", payload, headers
        )

    # ----------------------------------------------------------- menu cycle
    def create_menu_cycle(self, payload, headers):
        return self._request("POST", "/menu-cycles", payload, headers)

    def get_menu_cycle(self, cycle_id, headers):
        return self._request("GET", f"/menu-cycles/{cycle_id}", headers=headers)

    def create_menu_item(self, cycle_id, payload, headers):
        return self._request("POST", f"/menu-cycles/{cycle_id}/items", payload, headers)

    def list_menu_items(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/menu-cycles/{cycle_id}/items", headers=headers, params=params
        )

    def list_cycle_committee_feedback(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/menu-cycles/{cycle_id}/committee-feedback",
            headers=headers,
            params=params,
        )

    def submit_menu_cycle(self, cycle_id, headers):
        return self._request("POST", f"/menu-cycles/{cycle_id}/submit", {}, headers)

    def publish_menu_cycle(self, cycle_id, headers):
        return self._request("POST", f"/menu-cycles/{cycle_id}/publish", {}, headers)

    def refresh_menu_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/menu-cycles/{cycle_id}/refresh", payload, headers
        )

    def cast_committee_feedback(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/menu-cycles/{cycle_id}/committee-feedback", payload, headers
        )

    # ------------------------------------------------------------ menu item
    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"/menu-items/{item_id}", headers=headers)

    def list_therapeutic_extensions(self, item_id, headers, params=None):
        return self._request(
            "GET",
            f"/menu-items/{item_id}/therapeutic-extensions",
            headers=headers,
            params=params,
        )

    def create_therapeutic_extension(self, item_id, payload, headers):
        return self._request(
            "POST", f"/menu-items/{item_id}/therapeutic-extensions", payload, headers
        )

    def submit_therapeutic_extension(self, extension_id, headers):
        return self._request(
            "POST", f"/therapeutic-extensions/{extension_id}/submit", {}, headers
        )

    def review_therapeutic_extension(self, extension_id, payload, headers):
        return self._request(
            "POST", f"/therapeutic-extensions/{extension_id}/review", payload, headers
        )

    # --------------------------------------------------------- meal tickets
    def create_meal_ticket(self, payload, headers):
        return self._request("POST", "/meal-tickets", payload, headers)

    def get_meal_ticket(self, ticket_id, headers):
        return self._request("GET", f"/meal-tickets/{ticket_id}", headers=headers)

    def list_meal_tickets(self, headers, params=None):
        return self._request("GET", "/meal-tickets", headers=headers, params=params)

    def serve_meal_ticket(self, ticket_id, headers):
        return self._request("POST", f"/meal-tickets/{ticket_id}/serve", {}, headers)

    def void_meal_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/meal-tickets/{ticket_id}/void", payload, headers)

    # ------------------------------------------------------ reconciliations
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/reconciliations", payload, headers)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "GET", f"/reconciliations/{reconciliation_id}", headers=headers
        )

    def finalize_reconciliation(self, reconciliation_id, payload, headers):
        return self._request(
            "POST", f"/reconciliations/{reconciliation_id}/finalize", payload, headers
        )

    # ------------------------------------------------ plan-of-care reviews
    def get_plan_of_care_review(self, review_id, headers):
        return self._request(
            "GET", f"/plan-of-care-reviews/{review_id}", headers=headers
        )

    def list_plan_of_care_reviews(self, headers, params=None):
        return self._request(
            "GET", "/plan-of-care-reviews", headers=headers, params=params
        )

    def complete_plan_of_care_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/plan-of-care-reviews/{review_id}/complete", payload, headers
        )


api_client = ApiClient()
