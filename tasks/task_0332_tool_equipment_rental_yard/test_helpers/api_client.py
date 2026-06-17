"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── YardClock (test-driving) ─────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/rental-yard/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def get_clock(self, headers):
        return self._request("GET", "/rental-yard/_clock", headers=headers)

    # ─── RateCard ─────────────────────────────────────────────────
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rental-yard/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request(
            "GET", f"/rental-yard/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/rate-cards", headers=headers, params=params)

    # ─── RentalCatalogItem ────────────────────────────────────────
    def create_catalog_item(self, payload, headers):
        return self._request("POST", "/rental-yard/catalog-items", payload, headers)

    def get_catalog_item(self, item_id, headers):
        return self._request(
            "GET", f"/rental-yard/catalog-items/{item_id}", headers=headers)

    def list_catalog_items(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/catalog-items", headers=headers, params=params)

    # ─── EquipmentUnit ────────────────────────────────────────────
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/rental-yard/equipment-units", payload, headers)

    def get_equipment_unit(self, unit_id, headers):
        return self._request(
            "GET", f"/rental-yard/equipment-units/{unit_id}", headers=headers)

    def list_equipment_units(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/equipment-units", headers=headers, params=params)

    # ─── ContractorAccount ────────────────────────────────────────
    def create_contractor_account(self, payload, headers):
        return self._request(
            "POST", "/rental-yard/contractor-accounts", payload, headers)

    def get_contractor_account(self, account_id, headers):
        return self._request(
            "GET", f"/rental-yard/contractor-accounts/{account_id}", headers=headers)

    def list_contractor_accounts(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/contractor-accounts", headers=headers, params=params)

    def suspend_account(self, account_id, headers):
        return self._request(
            "POST", f"/rental-yard/contractor-accounts/{account_id}/suspend",
            headers=headers)

    def create_payment(self, account_id, payload, headers):
        return self._request(
            "POST", f"/rental-yard/contractor-accounts/{account_id}/payments",
            payload, headers)

    def list_account_ledger(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/rental-yard/contractor-accounts/{account_id}/ledger",
            headers=headers, params=params)

    def list_account_reservations(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/rental-yard/contractor-accounts/{account_id}/reservations",
            headers=headers, params=params)

    # ─── DeliveryTruck ────────────────────────────────────────────
    def create_delivery_truck(self, payload, headers):
        return self._request("POST", "/rental-yard/delivery-trucks", payload, headers)

    def get_delivery_truck(self, truck_id, headers):
        return self._request(
            "GET", f"/rental-yard/delivery-trucks/{truck_id}", headers=headers)

    def list_delivery_trucks(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/delivery-trucks", headers=headers, params=params)

    # ─── Reservation ──────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/rental-yard/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/rental-yard/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/reservations", headers=headers, params=params)

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/rental-yard/reservations/{reservation_id}/cancel",
            headers=headers)

    def dispatch_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/rental-yard/reservations/{reservation_id}/dispatch",
            payload, headers)

    def pickup_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/rental-yard/reservations/{reservation_id}/pickup",
            headers=headers)

    # ─── RentalAgreement ──────────────────────────────────────────
    def get_rental_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/rental-yard/rental-agreements/{agreement_id}", headers=headers)

    def list_rental_agreements(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/rental-agreements", headers=headers, params=params)

    def list_agreement_ledger_entries(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/rental-yard/rental-agreements/{agreement_id}/ledger-entries",
            headers=headers, params=params)

    def return_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/rental-yard/rental-agreements/{agreement_id}/return",
            headers=headers)

    # ─── ReturnInspection ─────────────────────────────────────────
    def create_return_inspection(self, payload, headers):
        return self._request(
            "POST", "/rental-yard/return-inspections", payload, headers)

    def get_return_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/rental-yard/return-inspections/{inspection_id}", headers=headers)

    def list_return_inspections(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/return-inspections", headers=headers, params=params)

    # ─── DamageCharge ─────────────────────────────────────────────
    def get_damage_charge(self, charge_id, headers):
        return self._request(
            "GET", f"/rental-yard/damage-charges/{charge_id}", headers=headers)

    def list_damage_charges(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/damage-charges", headers=headers, params=params)

    # ─── MaintenanceTicket ────────────────────────────────────────
    def create_maintenance_ticket(self, payload, headers):
        return self._request(
            "POST", "/rental-yard/maintenance-tickets", payload, headers)

    def get_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/rental-yard/maintenance-tickets/{ticket_id}", headers=headers)

    def list_maintenance_tickets(self, headers, params=None):
        return self._request(
            "GET", "/rental-yard/maintenance-tickets", headers=headers, params=params)

    def resolve_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/rental-yard/maintenance-tickets/{ticket_id}/resolve",
            headers=headers)


api_client = ApiClient()
