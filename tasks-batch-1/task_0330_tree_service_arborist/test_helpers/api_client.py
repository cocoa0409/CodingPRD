"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── ServiceArea (PRD §3.1) ─────────────────────────
    def create_service_area(self, payload, headers):
        return self._request("POST", "/service-areas", payload, headers)

    def list_service_areas(self, headers, params=None):
        return self._request("GET", "/service-areas", headers=headers, params=params)

    def get_service_area(self, area_id, headers):
        return self._request("GET", f"/service-areas/{area_id}", headers=headers)

    # ─── Crew (PRD §3.1) ────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def retire_crew(self, crew_id, headers):
        return self._request("POST", f"/crews/{crew_id}/retire", headers=headers)

    # ─── Equipment (PRD §3.1) ───────────────────────────
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def retire_equipment(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/retire", headers=headers)

    # ─── WorkOrder (PRD §3.2, §3.3, §3.10) ──────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def assess_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/assess", headers=headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", headers=headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", headers=headers)

    # ─── TreeAsset (PRD §3.2) ───────────────────────────
    def create_tree(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/trees", payload, headers)

    def list_trees(self, work_order_id, headers, params=None):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/trees", headers=headers, params=params,
        )

    def get_tree(self, work_order_id, tree_id, headers):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/trees/{tree_id}", headers=headers,
        )

    # ─── Estimate (PRD §3.4, §3.5, §3.7) ────────────────
    def create_estimate(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/estimates", payload or {}, headers,
        )

    def list_estimates(self, work_order_id, headers, params=None):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/estimates", headers=headers, params=params,
        )

    def get_estimate(self, work_order_id, estimate_id, headers):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/estimates/{estimate_id}", headers=headers,
        )

    def issue_estimate(self, work_order_id, estimate_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/estimates/{estimate_id}/issue",
            headers=headers,
        )

    def accept_estimate(self, work_order_id, estimate_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/estimates/{estimate_id}/accept",
            headers=headers,
        )

    def decline_estimate(self, work_order_id, estimate_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/estimates/{estimate_id}/decline",
            headers=headers,
        )

    # ─── LineItem (PRD §3.4) ────────────────────────────
    def create_line_item(self, payload, headers):
        return self._request("POST", "/line-items", payload, headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    # ─── Permit (PRD §3.6) ──────────────────────────────
    def create_permit(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/permits", payload, headers,
        )

    def list_permits(self, work_order_id, headers, params=None):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/permits", headers=headers, params=params,
        )

    def get_permit(self, work_order_id, permit_id, headers):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/permits/{permit_id}", headers=headers,
        )

    def submit_permit(self, work_order_id, permit_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/permits/{permit_id}/submit",
            headers=headers,
        )

    def request_permit_changes(self, work_order_id, permit_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/permits/{permit_id}/request-changes",
            headers=headers,
        )

    def decide_permit(self, work_order_id, permit_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/permits/{permit_id}/decide",
            payload, headers,
        )

    # ─── Booking (PRD §3.8, §3.9) ───────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def finalize_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/bookings/{booking_id}/finalize", payload, headers,
        )

    def release_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/release", headers=headers)

    # ─── DisposalTicket (PRD §3.9) ──────────────────────
    def create_disposal_ticket(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/disposal-tickets", payload, headers,
        )

    def list_disposal_tickets(self, work_order_id, headers, params=None):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/disposal-tickets",
            headers=headers, params=params,
        )

    def get_disposal_ticket(self, work_order_id, ticket_id, headers):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/disposal-tickets/{ticket_id}",
            headers=headers,
        )

    def finalize_disposal_ticket(self, work_order_id, ticket_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/disposal-tickets/{ticket_id}/finalize",
            headers=headers,
        )

    def void_disposal_ticket(self, work_order_id, ticket_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/disposal-tickets/{ticket_id}/void",
            headers=headers,
        )


api_client = ApiClient()
