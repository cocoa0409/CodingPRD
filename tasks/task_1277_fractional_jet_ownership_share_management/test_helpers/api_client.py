"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/resume", {}, headers)

    def wind_down_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/wind-down", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", {}, headers)

    # --- Aircraft classes ---
    def create_aircraft_class(self, payload, headers):
        return self._request("POST", "/aircraft-classes", payload, headers)

    def get_aircraft_class(self, class_id, headers):
        return self._request("GET", f"/aircraft-classes/{class_id}", headers=headers)

    def list_aircraft_classes(self, headers, params=None):
        return self._request("GET", "/aircraft-classes", headers=headers, params=params)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/aircraft", headers=headers, params=params)

    # --- Owners ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/owners", headers=headers, params=params)

    def suspend_owner(self, owner_id, headers):
        return self._request("POST", f"/owners/{owner_id}/suspend", {}, headers)

    def reinstate_owner(self, owner_id, headers):
        return self._request("POST", f"/owners/{owner_id}/reinstate", {}, headers)

    # --- Shares ---
    def create_share(self, payload, headers):
        return self._request("POST", "/shares", payload, headers)

    def get_share(self, share_id, headers):
        return self._request("GET", f"/shares/{share_id}", headers=headers)

    def list_shares(self, headers, params=None):
        return self._request("GET", "/shares", headers=headers, params=params)

    def activate_share(self, share_id, headers):
        return self._request("POST", f"/shares/{share_id}/activate", {}, headers)

    def exit_share(self, share_id, headers):
        return self._request("POST", f"/shares/{share_id}/exit", {}, headers)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking_quote(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/quote", headers=headers)

    def suggest_aircraft(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/suggest-aircraft", headers=headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def assign_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/assign", payload, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def complete_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", payload, headers)

    # --- Flight legs ---
    def list_flight_legs(self, headers, params=None):
        return self._request("GET", "/flight-legs", headers=headers, params=params)

    def get_flight_leg(self, leg_id, headers):
        return self._request("GET", f"/flight-legs/{leg_id}", headers=headers)

    # --- Invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def list_invoice_lines(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}/lines", headers=headers)

    def list_all_invoice_lines(self, headers, params=None):
        return self._request("GET", "/invoice-lines", headers=headers, params=params)

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/invoice-lines/{line_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", {}, headers)

    def resolve_dispute(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/resolve-dispute", payload, headers)

    # --- Transfer listings ---
    def create_transfer_listing(self, payload, headers):
        return self._request("POST", "/transfer-listings", payload, headers)

    def get_transfer_listing(self, listing_id, headers):
        return self._request("GET", f"/transfer-listings/{listing_id}", headers=headers)

    def list_transfer_listings(self, headers, params=None):
        return self._request("GET", "/transfer-listings", headers=headers, params=params)

    def accept_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/transfer-listings/{listing_id}/accept", payload, headers)

    def close_sale(self, listing_id, payload, headers):
        return self._request("POST", f"/transfer-listings/{listing_id}/close-sale", payload, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/transfer-listings/{listing_id}/withdraw", {}, headers)

    # --- Maintenance events ---
    def create_maintenance_event(self, payload, headers):
        return self._request("POST", "/maintenance-events", payload, headers)

    def get_maintenance_event(self, event_id, headers):
        return self._request("GET", f"/maintenance-events/{event_id}", headers=headers)

    def list_maintenance_events(self, headers, params=None):
        return self._request("GET", "/maintenance-events", headers=headers, params=params)

    def start_maintenance(self, event_id, headers):
        return self._request("POST", f"/maintenance-events/{event_id}/start", {}, headers)

    def complete_maintenance(self, event_id, payload, headers):
        return self._request("POST", f"/maintenance-events/{event_id}/complete", payload, headers)

    def cancel_maintenance(self, event_id, headers):
        return self._request("POST", f"/maintenance-events/{event_id}/cancel", {}, headers)

    # --- Depreciation schedules ---
    def get_depreciation_schedule(self, schedule_id, headers):
        return self._request("GET", f"/depreciation-schedules/{schedule_id}", headers=headers)

    def list_depreciation_schedules(self, headers, params=None):
        return self._request("GET", "/depreciation-schedules", headers=headers, params=params)

    # --- Exit requests ---
    def get_exit_request(self, exit_id, headers):
        return self._request("GET", f"/exit-requests/{exit_id}", headers=headers)

    def list_exit_requests(self, headers, params=None):
        return self._request("GET", "/exit-requests", headers=headers, params=params)

    def value_exit(self, exit_id, headers):
        return self._request("POST", f"/exit-requests/{exit_id}/value", {}, headers)

    def approve_exit(self, exit_id, headers):
        return self._request("POST", f"/exit-requests/{exit_id}/approve", {}, headers)

    def settle_exit(self, exit_id, headers):
        return self._request("POST", f"/exit-requests/{exit_id}/settle", {}, headers)

    def reject_exit(self, exit_id, headers):
        return self._request("POST", f"/exit-requests/{exit_id}/reject", {}, headers)

    def withdraw_exit(self, exit_id, headers):
        return self._request("POST", f"/exit-requests/{exit_id}/withdraw", {}, headers)


api_client = ApiClient()
