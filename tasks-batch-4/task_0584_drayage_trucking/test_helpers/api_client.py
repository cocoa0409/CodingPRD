"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Terminals ----
    def create_terminal(self, payload, headers):
        return self._request("POST", "/terminals", payload, headers)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/terminals/{terminal_id}", headers=headers)

    # ---- Chassis ----
    def create_chassis(self, payload, headers):
        return self._request("POST", "/chassis", payload, headers)

    def get_chassis(self, chassis_id, headers):
        return self._request("GET", f"/chassis/{chassis_id}", headers=headers)

    # ---- Drivers ----
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    # ---- Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def assign_chassis(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/assign-chassis", payload, headers)

    def release_chassis(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/release-chassis", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    # ---- Weigh tickets ----
    def create_weigh_ticket(self, payload, headers):
        return self._request("POST", "/weigh-tickets", payload, headers)

    def get_weigh_ticket(self, weigh_ticket_id, headers):
        return self._request("GET", f"/weigh-tickets/{weigh_ticket_id}", headers=headers)

    def list_weigh_tickets(self, headers, params=None):
        return self._request("GET", "/weigh-tickets", headers=headers, params=params)

    # ---- Appointments ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    # ---- Legs ----
    def create_leg(self, payload, headers):
        return self._request("POST", "/legs", payload, headers)

    def get_leg(self, leg_id, headers):
        return self._request("GET", f"/legs/{leg_id}", headers=headers)

    def list_legs(self, headers, params=None):
        return self._request("GET", "/legs", headers=headers, params=params)

    def dispatch_leg(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/dispatch", {}, headers)

    def complete_leg(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/complete", {}, headers)

    def cancel_leg(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/cancel", {}, headers)

    # ---- Permits ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/approve", {}, headers)

    # ---- Invoices ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def add_accessorial(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/accessorials", payload, headers)

    def list_accessorials(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}/accessorials", headers=headers)

    def void_accessorial(self, invoice_id, accessorial_id, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/accessorials/{accessorial_id}/void", {}, headers
        )


api_client = ApiClient()
