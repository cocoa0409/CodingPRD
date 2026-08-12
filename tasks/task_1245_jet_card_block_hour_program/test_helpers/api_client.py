"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock / ops sweep ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def ops_run(self, headers):
        return self._request("POST", "/ops/run", {}, headers)

    # --- CardProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    # --- Peak / blackout windows ---
    def create_peak_window(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/peak_windows", payload, headers)

    def list_peak_windows(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/peak_windows", headers=headers, params=params)

    def create_blackout_window(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/blackout_windows", payload, headers)

    def list_blackout_windows(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/blackout_windows", headers=headers, params=params)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers)

    # --- JetCard ---
    def create_card(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/cards", payload, headers)

    def activate_card(self, card_id, headers):
        return self._request("POST", f"/cards/{card_id}/activate", {}, headers)

    def suspend_card(self, card_id, headers):
        return self._request("POST", f"/cards/{card_id}/suspend", {}, headers)

    def resume_card(self, card_id, headers):
        return self._request("POST", f"/cards/{card_id}/resume", {}, headers)

    def get_card(self, card_id, headers):
        return self._request("GET", f"/cards/{card_id}", headers=headers)

    def list_member_cards(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/cards", headers=headers, params=params)

    def get_card_projection(self, card_id, headers):
        return self._request("GET", f"/cards/{card_id}/projection", headers=headers)

    def list_ledger(self, card_id, headers, params=None):
        return self._request("GET", f"/cards/{card_id}/ledger", headers=headers, params=params)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/aircraft", headers=headers, params=params)

    # --- TripRequest ---
    def create_trip(self, card_id, payload, headers):
        return self._request("POST", f"/cards/{card_id}/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def list_card_trips(self, card_id, headers, params=None):
        return self._request("GET", f"/cards/{card_id}/trips", headers=headers, params=params)

    def confirm_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/confirm", {}, headers)

    def dispatch_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/dispatch", payload, headers)

    def depart_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/depart", {}, headers)

    def complete_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/complete", payload, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/cancel", {}, headers)

    def no_show_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/no_show", {}, headers)

    # --- TripLeg ---
    def list_trip_legs(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/legs", headers=headers, params=params)

    # --- Invoice ---
    def get_trip_invoice(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}/invoice", headers=headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark_paid", {}, headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", {}, headers)

    def write_off_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/write_off", {}, headers)

    # --- Refund ---
    def create_refund(self, card_id, payload, headers):
        return self._request("POST", f"/cards/{card_id}/refunds", payload, headers)

    def list_refunds(self, card_id, headers, params=None):
        return self._request("GET", f"/cards/{card_id}/refunds", headers=headers, params=params)

    def submit_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/submit", {}, headers)

    def approve_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/approve", {}, headers)

    def deny_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/refunds/{refund_id}/deny", payload, headers)

    def settle_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/settle", {}, headers)

    # --- Fractional upgrade ---
    def create_fractional_upgrade(self, card_id, payload, headers):
        return self._request("POST", f"/cards/{card_id}/fractional_upgrades", payload, headers)

    def list_fractional_upgrades(self, card_id, headers, params=None):
        return self._request("GET", f"/cards/{card_id}/fractional_upgrades", headers=headers, params=params)

    # --- Escrow ---
    def get_escrow(self, card_id, headers):
        return self._request("GET", f"/cards/{card_id}/escrow", headers=headers)


api_client = ApiClient()
