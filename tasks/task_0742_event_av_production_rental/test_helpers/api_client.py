"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (PRD §2.6) ─────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Customer ─────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Venue ────────────────────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ─── EquipmentItem ────────────────────────────────────────────────
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def get_equipment_availability(self, equipment_id, headers, params=None):
        return self._request(
            "GET", f"/equipment/{equipment_id}/availability", headers=headers, params=params
        )

    # ─── CrewMember ───────────────────────────────────────────────────
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}", headers=headers)

    # ─── RentalOrder ──────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/rental-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/rental-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/rental-orders", headers=headers, params=params)

    def quote_order(self, order_id, headers):
        return self._request("POST", f"/rental-orders/{order_id}/quote", {}, headers)

    def revise_order(self, order_id, headers):
        return self._request("POST", f"/rental-orders/{order_id}/revise", {}, headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/rental-orders/{order_id}/confirm", payload, headers)

    def load_out_order(self, order_id, headers):
        return self._request("POST", f"/rental-orders/{order_id}/load-out", {}, headers)

    def start_event_order(self, order_id, headers):
        return self._request("POST", f"/rental-orders/{order_id}/start-event", {}, headers)

    def load_in_order(self, order_id, headers):
        return self._request("POST", f"/rental-orders/{order_id}/load-in", {}, headers)

    def settle_order(self, order_id, headers):
        return self._request("POST", f"/rental-orders/{order_id}/settle", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/rental-orders/{order_id}/cancel", {}, headers)

    # ─── EquipmentReservation ─────────────────────────────────────────
    def create_reservation(self, order_id, payload, headers):
        return self._request("POST", f"/rental-orders/{order_id}/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/equipment-reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/equipment-reservations", headers=headers, params=params)

    def check_out_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/equipment-reservations/{reservation_id}/check-out", {}, headers
        )

    def check_in_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/equipment-reservations/{reservation_id}/check-in", payload, headers
        )

    def release_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/equipment-reservations/{reservation_id}/release", {}, headers
        )

    # ─── CrewAssignment ───────────────────────────────────────────────
    def create_crew_assignment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/rental-orders/{order_id}/crew-assignments", payload, headers
        )

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    def complete_crew_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/complete", payload, headers
        )

    def cancel_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/crew-assignments/{assignment_id}/cancel", {}, headers)

    # ─── SubRental ────────────────────────────────────────────────────
    def create_sub_rental(self, order_id, payload, headers):
        return self._request("POST", f"/rental-orders/{order_id}/sub-rentals", payload, headers)

    def get_sub_rental(self, sub_rental_id, headers):
        return self._request("GET", f"/sub-rentals/{sub_rental_id}", headers=headers)

    def list_sub_rentals(self, headers, params=None):
        return self._request("GET", "/sub-rentals", headers=headers, params=params)

    def confirm_sub_rental(self, sub_rental_id, headers):
        return self._request("POST", f"/sub-rentals/{sub_rental_id}/confirm", {}, headers)

    def return_sub_rental(self, sub_rental_id, headers):
        return self._request("POST", f"/sub-rentals/{sub_rental_id}/return", {}, headers)

    def cancel_sub_rental(self, sub_rental_id, headers):
        return self._request("POST", f"/sub-rentals/{sub_rental_id}/cancel", {}, headers)

    # ─── CertificateOfInsurance ───────────────────────────────────────
    def create_coi(self, order_id, payload, headers):
        return self._request(
            "POST", f"/rental-orders/{order_id}/certificates-of-insurance", payload, headers
        )

    def get_coi(self, coi_id, headers):
        return self._request("GET", f"/certificates-of-insurance/{coi_id}", headers=headers)

    def list_cois(self, headers, params=None):
        return self._request("GET", "/certificates-of-insurance", headers=headers, params=params)

    def approve_coi(self, coi_id, headers):
        return self._request("POST", f"/certificates-of-insurance/{coi_id}/approve", {}, headers)

    def reject_coi(self, coi_id, payload, headers):
        return self._request(
            "POST", f"/certificates-of-insurance/{coi_id}/reject", payload, headers
        )

    # ─── DamageReport ─────────────────────────────────────────────────
    def create_damage_report(self, order_id, payload, headers):
        return self._request("POST", f"/rental-orders/{order_id}/damage-reports", payload, headers)

    def get_damage_report(self, damage_report_id, headers):
        return self._request("GET", f"/damage-reports/{damage_report_id}", headers=headers)

    def list_damage_reports(self, headers, params=None):
        return self._request("GET", "/damage-reports", headers=headers, params=params)

    def assess_damage_report(self, damage_report_id, payload, headers):
        return self._request(
            "POST", f"/damage-reports/{damage_report_id}/assess", payload, headers
        )

    def charge_damage_report(self, damage_report_id, headers):
        return self._request("POST", f"/damage-reports/{damage_report_id}/charge", {}, headers)

    def waive_damage_report(self, damage_report_id, headers):
        return self._request("POST", f"/damage-reports/{damage_report_id}/waive", {}, headers)

    # ─── DepositLedgerEntry (read-only) ───────────────────────────────
    def get_deposit_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/deposit-ledger/{entry_id}", headers=headers)

    def list_deposit_ledger(self, headers, params=None):
        return self._request("GET", "/deposit-ledger", headers=headers, params=params)


api_client = ApiClient()
