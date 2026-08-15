"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.8) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- customers (PRD §3.1) ---
    def create_customer(self, payload: Dict, headers: Dict):
        return self._request("POST", "/heavy-haul/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict):
        return self._request(
            "GET", f"/heavy-haul/customers/{customer_id}", headers=headers
        )

    def reinstate_customer(self, customer_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/customers/{customer_id}/reinstate", {}, headers
        )

    # --- loads (PRD §3.2, §3.3, §3.7) ---
    def create_load(self, payload: Dict, headers: Dict):
        return self._request("POST", "/heavy-haul/loads", payload, headers)

    def list_loads(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/heavy-haul/loads", headers=headers, params=params)

    def get_load(self, load_id: str, headers: Dict):
        return self._request("GET", f"/heavy-haul/loads/{load_id}", headers=headers)

    def plan_load(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/plan", payload, headers
        )

    def survey_load(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/survey", payload, headers
        )

    def cancel_load(self, load_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/cancel", {}, headers
        )

    def depart_load(self, load_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/depart", {}, headers
        )

    def arrive_load(self, load_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/arrive", {}, headers
        )

    def release_hold_load(self, load_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/release-hold", {}, headers
        )

    def get_cost_estimate(self, load_id: str, headers: Dict):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/cost-estimate", headers=headers
        )

    # --- securement plans (PRD §3.4) ---
    def create_securement_plan(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/securement-plans", payload, headers
        )

    def list_securement_plans(self, load_id: str, headers: Dict,
                              params: Optional[Dict] = None):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/securement-plans",
            headers=headers, params=params,
        )

    def approve_securement_plan(self, plan_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/securement-plans/{plan_id}/approve", {}, headers
        )

    def reject_securement_plan(self, plan_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/securement-plans/{plan_id}/reject", {}, headers
        )

    # --- permits (PRD §3.5) ---
    def create_permit(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/permits", payload, headers
        )

    def list_permits(self, load_id: str, headers: Dict,
                     params: Optional[Dict] = None):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/permits",
            headers=headers, params=params,
        )

    def file_permit(self, permit_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/permits/{permit_id}/file", {}, headers
        )

    def grant_permit(self, permit_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/permits/{permit_id}/grant", payload, headers
        )

    def deny_permit(self, permit_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/permits/{permit_id}/deny", payload, headers
        )

    # --- escort bookings (PRD §3.6) ---
    def create_escort_booking(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/escort-bookings", payload, headers
        )

    def list_escort_bookings(self, load_id: str, headers: Dict,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/escort-bookings",
            headers=headers, params=params,
        )

    def cancel_escort_booking(self, booking_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/escort-bookings/{booking_id}/cancel", {}, headers
        )

    # --- crane appointments (PRD §3.6) ---
    def create_crane_appointment(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/crane-appointments",
            payload, headers,
        )

    def list_crane_appointments(self, load_id: str, headers: Dict,
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/crane-appointments",
            headers=headers, params=params,
        )

    # --- delay events (PRD §3.7) ---
    def create_delay_event(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/delay-events", payload, headers
        )

    def list_delay_events(self, load_id: str, headers: Dict,
                          params: Optional[Dict] = None):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/delay-events",
            headers=headers, params=params,
        )

    # --- scale tickets (PRD §3.8) ---
    def create_scale_ticket(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/scale-tickets", payload, headers
        )

    def list_scale_tickets(self, load_id: str, headers: Dict,
                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/scale-tickets",
            headers=headers, params=params,
        )

    # --- fines (PRD §3.9) ---
    def create_fine(self, load_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/fines", payload, headers
        )

    def list_fines(self, load_id: str, headers: Dict,
                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/fines",
            headers=headers, params=params,
        )

    def dispute_fine(self, fine_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/fines/{fine_id}/dispute", {}, headers
        )

    def resolve_fine(self, fine_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/fines/{fine_id}/resolve", payload, headers
        )

    # --- invoices (PRD §3.9) ---
    def create_invoice(self, load_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/loads/{load_id}/invoices", {}, headers
        )

    def list_invoices(self, load_id: str, headers: Dict,
                      params: Optional[Dict] = None):
        return self._request(
            "GET", f"/heavy-haul/loads/{load_id}/invoices",
            headers=headers, params=params,
        )

    def pay_invoice(self, invoice_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/invoices/{invoice_id}/pay", payload, headers
        )

    def void_invoice(self, invoice_id: str, headers: Dict):
        return self._request(
            "POST", f"/heavy-haul/invoices/{invoice_id}/void", {}, headers
        )


api_client = ApiClient()
