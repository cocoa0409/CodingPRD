"""API client: one method per endpoint defined in the PRD (commercial fleet leasing)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Lessees -----
    def create_lessee(self, payload, headers):
        return self._request("POST", "/fleet/lessees", payload, headers)

    def get_lessee(self, lessee_id, headers):
        return self._request("GET", f"/fleet/lessees/{lessee_id}", headers=headers)

    def suspend_lessee(self, lessee_id, headers):
        return self._request("POST", f"/fleet/lessees/{lessee_id}/suspend", {}, headers)

    # ----- Drivers -----
    def create_driver(self, payload, headers):
        return self._request("POST", "/fleet/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/fleet/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/fleet/drivers", headers=headers, params=params)

    def suspend_license(self, driver_id, headers):
        return self._request(
            "POST", f"/fleet/drivers/{driver_id}/suspend-license", {}, headers
        )

    # ----- Vehicles -----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/fleet/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/fleet/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_telematics(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/vehicles/{vehicle_id}/telematics-readings",
            headers=headers, params=params,
        )

    def list_vehicle_maintenance(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/vehicles/{vehicle_id}/maintenance-orders",
            headers=headers, params=params,
        )

    # ----- Leases -----
    def create_lease(self, payload, headers):
        return self._request("POST", "/fleet/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/fleet/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/fleet/leases", headers=headers, params=params)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/fleet/leases/{lease_id}/activate", {}, headers)

    def cancel_lease(self, lease_id, headers):
        return self._request("POST", f"/fleet/leases/{lease_id}/cancel", {}, headers)

    def initiate_return(self, lease_id, headers):
        return self._request(
            "POST", f"/fleet/leases/{lease_id}/initiate-return", {}, headers
        )

    # ----- Allocations -----
    def create_allocation(self, payload, headers):
        return self._request("POST", "/fleet/allocations", payload, headers)

    def get_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/fleet/allocations/{allocation_id}", headers=headers
        )

    def list_allocations(self, headers, params=None):
        return self._request(
            "GET", "/fleet/allocations", headers=headers, params=params
        )

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/fleet/allocations/{allocation_id}/release", {}, headers
        )

    # ----- Fuel cards / transactions -----
    def create_fuel_card(self, payload, headers):
        return self._request("POST", "/fleet/fuel-cards", payload, headers)

    def get_fuel_card(self, card_id, headers):
        return self._request("GET", f"/fleet/fuel-cards/{card_id}", headers=headers)

    def list_fuel_cards(self, headers, params=None):
        return self._request("GET", "/fleet/fuel-cards", headers=headers, params=params)

    def create_fuel_transaction(self, payload, headers):
        return self._request("POST", "/fleet/fuel-transactions", payload, headers)

    def get_fuel_transaction(self, txn_id, headers):
        return self._request(
            "GET", f"/fleet/fuel-transactions/{txn_id}", headers=headers
        )

    def list_fuel_transactions(self, headers, params=None):
        return self._request(
            "GET", "/fleet/fuel-transactions", headers=headers, params=params
        )

    def void_fuel_transaction(self, txn_id, headers):
        return self._request(
            "POST", f"/fleet/fuel-transactions/{txn_id}/void", {}, headers
        )

    # ----- Telematics -----
    def create_telematics_reading(self, payload, headers):
        return self._request("POST", "/fleet/telematics-readings", payload, headers)

    # ----- Maintenance orders -----
    def create_maintenance_order(self, payload, headers):
        return self._request("POST", "/fleet/maintenance-orders", payload, headers)

    def get_maintenance_order(self, mo_id, headers):
        return self._request(
            "GET", f"/fleet/maintenance-orders/{mo_id}", headers=headers
        )

    def start_maintenance(self, mo_id, headers):
        return self._request(
            "POST", f"/fleet/maintenance-orders/{mo_id}/start", {}, headers
        )

    def complete_maintenance(self, mo_id, headers):
        return self._request(
            "POST", f"/fleet/maintenance-orders/{mo_id}/complete", {}, headers
        )

    def cancel_maintenance(self, mo_id, headers):
        return self._request(
            "POST", f"/fleet/maintenance-orders/{mo_id}/cancel", {}, headers
        )

    # ----- Repair orders -----
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/fleet/repair-orders", payload, headers)

    def get_repair_order(self, ro_id, headers):
        return self._request("GET", f"/fleet/repair-orders/{ro_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request(
            "GET", "/fleet/repair-orders", headers=headers, params=params
        )

    def assess_repair(self, ro_id, payload, headers):
        return self._request(
            "POST", f"/fleet/repair-orders/{ro_id}/assess", payload, headers
        )

    def approve_repair(self, ro_id, headers):
        return self._request(
            "POST", f"/fleet/repair-orders/{ro_id}/approve", {}, headers
        )

    def declare_total_loss(self, ro_id, headers):
        return self._request(
            "POST", f"/fleet/repair-orders/{ro_id}/declare-total-loss", {}, headers
        )

    def complete_repair(self, ro_id, headers):
        return self._request(
            "POST", f"/fleet/repair-orders/{ro_id}/complete", {}, headers
        )

    def settle_total_loss(self, ro_id, headers):
        return self._request(
            "POST", f"/fleet/repair-orders/{ro_id}/settle-total-loss", {}, headers
        )

    def reject_repair(self, ro_id, headers):
        return self._request(
            "POST", f"/fleet/repair-orders/{ro_id}/reject", {}, headers
        )

    # ----- Overage settlements -----
    def create_settlement(self, payload, headers):
        return self._request("POST", "/fleet/overage-settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/fleet/overage-settlements/{settlement_id}", headers=headers
        )

    def list_settlements(self, headers, params=None):
        return self._request(
            "GET", "/fleet/overage-settlements", headers=headers, params=params
        )

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/fleet/overage-settlements/{settlement_id}/finalize", {}, headers
        )

    # ----- IFTA returns -----
    def create_ifta_return(self, payload, headers):
        return self._request("POST", "/fleet/ifta-returns", payload, headers)

    def get_ifta_return(self, return_id, headers):
        return self._request(
            "GET", f"/fleet/ifta-returns/{return_id}", headers=headers
        )

    def list_ifta_returns(self, headers, params=None):
        return self._request(
            "GET", "/fleet/ifta-returns", headers=headers, params=params
        )

    def file_ifta_return(self, return_id, headers):
        return self._request(
            "POST", f"/fleet/ifta-returns/{return_id}/file", {}, headers
        )


api_client = ApiClient()
