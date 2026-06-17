"""API client: one method per endpoint defined in the PRD (§4).

Subclasses GenericApiClient; the base _request() handles the envelope.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Locations ──────────────────────────────────────────────────────
    def create_location(self, payload, headers):
        return self._request("POST", "/rental/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/rental/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/rental/locations", headers=headers, params=params)

    def get_location_availability(self, location_id, headers, params=None):
        return self._request(
            "GET", f"/rental/locations/{location_id}/availability",
            headers=headers, params=params,
        )

    # ── Equipment classes ──────────────────────────────────────────────
    def create_equipment_class(self, payload, headers):
        return self._request("POST", "/rental/equipment-classes", payload, headers)

    def get_equipment_class(self, class_id, headers):
        return self._request("GET", f"/rental/equipment-classes/{class_id}", headers=headers)

    def list_equipment_classes(self, headers, params=None):
        return self._request("GET", "/rental/equipment-classes", headers=headers, params=params)

    # ── Coverage plans ─────────────────────────────────────────────────
    def create_coverage_plan(self, payload, headers):
        return self._request("POST", "/rental/coverage-plans", payload, headers)

    def list_coverage_plans(self, headers, params=None):
        return self._request("GET", "/rental/coverage-plans", headers=headers, params=params)

    # ── Supplies ───────────────────────────────────────────────────────
    def create_supply(self, payload, headers):
        return self._request("POST", "/rental/supplies", payload, headers)

    def get_supply(self, supply_id, headers):
        return self._request("GET", f"/rental/supplies/{supply_id}", headers=headers)

    def list_supplies(self, headers, params=None):
        return self._request("GET", "/rental/supplies", headers=headers, params=params)

    def list_supply_line_items(self, supply_id, headers, params=None):
        return self._request(
            "GET", f"/rental/supplies/{supply_id}/line-items", headers=headers, params=params,
        )

    # ── Equipment units ────────────────────────────────────────────────
    def create_equipment(self, payload, headers):
        return self._request("POST", "/rental/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/rental/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/rental/equipment", headers=headers, params=params)

    def maintenance_equipment(self, equipment_id, headers):
        return self._request(
            "POST", f"/rental/equipment/{equipment_id}/maintenance", headers=headers,
        )

    def clear_maintenance_equipment(self, equipment_id, headers):
        return self._request(
            "POST", f"/rental/equipment/{equipment_id}/clear-maintenance", headers=headers,
        )

    def retire_equipment(self, equipment_id, headers):
        return self._request(
            "POST", f"/rental/equipment/{equipment_id}/retire", headers=headers,
        )

    # ── Customers ──────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/rental/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/rental/customers/{customer_id}", headers=headers)

    def verify_license(self, customer_id, headers):
        return self._request(
            "POST", f"/rental/customers/{customer_id}/verify-license", headers=headers,
        )

    # ── Reservations ───────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/rental/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/rental/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/rental/reservations", headers=headers, params=params)

    def add_supply(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/rental/reservations/{reservation_id}/supplies", payload, headers,
        )

    def remove_supply(self, reservation_id, line_id, headers):
        return self._request(
            "DELETE", f"/rental/reservations/{reservation_id}/supplies/{line_id}",
            headers=headers,
        )

    def list_reservation_supplies(self, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/rental/reservations/{reservation_id}/supplies",
            headers=headers, params=params,
        )

    def add_addon(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/rental/reservations/{reservation_id}/addons", payload, headers,
        )

    def list_reservation_addons(self, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/rental/reservations/{reservation_id}/addons",
            headers=headers, params=params,
        )

    def confirm_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/rental/reservations/{reservation_id}/confirm", headers=headers,
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/rental/reservations/{reservation_id}/cancel", headers=headers,
        )

    def dispatch_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/rental/reservations/{reservation_id}/dispatch", payload, headers,
        )

    # ── Contracts ──────────────────────────────────────────────────────
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/rental/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/rental/contracts", headers=headers, params=params)

    def return_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/rental/contracts/{contract_id}/return", payload, headers,
        )

    def file_damage_report(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/rental/contracts/{contract_id}/damage-reports", payload, headers,
        )

    def list_damage_reports(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/rental/contracts/{contract_id}/damage-reports",
            headers=headers, params=params,
        )

    def settle_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/rental/contracts/{contract_id}/settle", payload, headers,
        )

    def void_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/rental/contracts/{contract_id}/void", headers=headers,
        )

    def list_ledger(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/rental/contracts/{contract_id}/ledger", headers=headers, params=params,
        )

    # ── Drop-off transfers ─────────────────────────────────────────────
    def create_transfer(self, payload, headers):
        return self._request("POST", "/rental/transfers", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/rental/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/rental/transfers", headers=headers, params=params)

    def approve_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/rental/transfers/{transfer_id}/approve", headers=headers,
        )

    def reject_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/rental/transfers/{transfer_id}/reject", headers=headers,
        )

    def complete_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/rental/transfers/{transfer_id}/complete", headers=headers,
        )


api_client = ApiClient()
