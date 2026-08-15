"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/fleet/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/fleet/customers/{customer_id}", headers=headers)

    def list_customer_operators(self, customer_id, headers, params=None):
        return self._request("GET", f"/fleet/customers/{customer_id}/operators",
                             headers=headers, params=params)

    # ---- Units, meter readings, fuel events ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/fleet/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/fleet/units/{unit_id}", headers=headers)

    def create_meter_reading(self, unit_id, payload, headers):
        return self._request("POST", f"/fleet/units/{unit_id}/meter-readings",
                             payload, headers)

    def list_meter_readings(self, unit_id, headers, params=None):
        return self._request("GET", f"/fleet/units/{unit_id}/meter-readings",
                             headers=headers, params=params)

    def create_fuel_event(self, unit_id, payload, headers):
        return self._request("POST", f"/fleet/units/{unit_id}/fuel-events",
                             payload, headers)

    def list_fuel_events(self, unit_id, headers, params=None):
        return self._request("GET", f"/fleet/units/{unit_id}/fuel-events",
                             headers=headers, params=params)

    # ---- Quotes ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/fleet/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/fleet/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/fleet/quotes", headers=headers, params=params)

    def create_quote_line(self, quote_id, payload, headers):
        return self._request("POST", f"/fleet/quotes/{quote_id}/lines", payload, headers)

    def list_quote_lines(self, quote_id, headers, params=None):
        return self._request("GET", f"/fleet/quotes/{quote_id}/lines",
                             headers=headers, params=params)

    def submit_quote(self, quote_id, headers):
        return self._request("POST", f"/fleet/quotes/{quote_id}/submit", headers=headers)

    def revise_quote(self, quote_id, headers):
        return self._request("POST", f"/fleet/quotes/{quote_id}/revise", headers=headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/fleet/quotes/{quote_id}/accept", headers=headers)

    # ---- Rental contracts ----
    def create_rental_contract(self, payload, headers):
        return self._request("POST", "/fleet/rental-contracts", payload, headers)

    def get_rental_contract(self, contract_id, headers):
        return self._request("GET", f"/fleet/rental-contracts/{contract_id}",
                             headers=headers)

    def list_rental_contracts(self, headers, params=None):
        return self._request("GET", "/fleet/rental-contracts", headers=headers,
                             params=params)

    def checkout_rental_contract(self, contract_id, headers):
        return self._request("POST", f"/fleet/rental-contracts/{contract_id}/checkout",
                             headers=headers)

    def return_rental_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/fleet/rental-contracts/{contract_id}/return",
                             payload, headers)

    def cancel_rental_contract(self, contract_id, headers):
        return self._request("POST", f"/fleet/rental-contracts/{contract_id}/cancel",
                             headers=headers)

    # ---- Service calls & technicians ----
    def create_service_call(self, payload, headers):
        return self._request("POST", "/fleet/service-calls", payload, headers)

    def get_service_call(self, call_id, headers):
        return self._request("GET", f"/fleet/service-calls/{call_id}", headers=headers)

    def list_service_calls(self, headers, params=None):
        return self._request("GET", "/fleet/service-calls", headers=headers,
                             params=params)

    def dispatch_service_call(self, call_id, payload, headers):
        return self._request("POST", f"/fleet/service-calls/{call_id}/dispatch",
                             payload, headers)

    def release_service_call(self, call_id, headers):
        return self._request("POST", f"/fleet/service-calls/{call_id}/release",
                             headers=headers)

    def resolve_service_call(self, call_id, payload, headers):
        return self._request("POST", f"/fleet/service-calls/{call_id}/resolve",
                             payload, headers)

    def create_technician(self, payload, headers):
        return self._request("POST", "/fleet/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/fleet/technicians/{technician_id}", headers=headers)

    def restock_van(self, technician_id, payload, headers):
        return self._request("POST", f"/fleet/technicians/{technician_id}/van-stock",
                             payload, headers)

    def deactivate_technician(self, technician_id, headers):
        return self._request("POST", f"/fleet/technicians/{technician_id}/deactivate",
                             headers=headers)

    # ---- Operators & certifications ----
    def create_operator(self, payload, headers):
        return self._request("POST", "/fleet/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/fleet/operators/{operator_id}", headers=headers)

    def issue_certification(self, operator_id, payload, headers):
        return self._request("POST", f"/fleet/operators/{operator_id}/certifications",
                             payload, headers)

    def list_certifications(self, operator_id, headers, params=None):
        return self._request("GET", f"/fleet/operators/{operator_id}/certifications",
                             headers=headers, params=params)

    def renew_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/fleet/certifications/{certification_id}/renew",
                             payload, headers)

    def revoke_certification(self, certification_id, headers):
        return self._request("POST", f"/fleet/certifications/{certification_id}/revoke",
                             headers=headers)

    # ---- Lease contracts & inspections ----
    def create_lease_contract(self, payload, headers):
        return self._request("POST", "/fleet/lease-contracts", payload, headers)

    def get_lease_contract(self, lease_id, headers):
        return self._request("GET", f"/fleet/lease-contracts/{lease_id}", headers=headers)

    def list_lease_contracts(self, headers, params=None):
        return self._request("GET", "/fleet/lease-contracts", headers=headers,
                             params=params)

    def return_lease_contract(self, lease_id, payload, headers):
        return self._request("POST", f"/fleet/lease-contracts/{lease_id}/return",
                             payload, headers)

    def create_lease_inspection(self, lease_id, payload, headers):
        return self._request("POST", f"/fleet/lease-contracts/{lease_id}/inspections",
                             payload, headers)

    def list_lease_inspections(self, lease_id, headers, params=None):
        return self._request("GET", f"/fleet/lease-contracts/{lease_id}/inspections",
                             headers=headers, params=params)

    def approve_inspection(self, inspection_id, headers):
        return self._request("POST", f"/fleet/inspections/{inspection_id}/approve",
                             headers=headers)

    def settle_lease_contract(self, lease_id, headers):
        return self._request("POST", f"/fleet/lease-contracts/{lease_id}/settle",
                             headers=headers)

    # ---- Reconditioning ----
    def create_reconditioning_order(self, payload, headers):
        return self._request("POST", "/fleet/reconditioning-orders", payload, headers)

    def get_reconditioning_order(self, order_id, headers):
        return self._request("GET", f"/fleet/reconditioning-orders/{order_id}",
                             headers=headers)

    def list_reconditioning_orders(self, headers, params=None):
        return self._request("GET", "/fleet/reconditioning-orders", headers=headers,
                             params=params)

    def complete_reconditioning_order(self, order_id, payload, headers):
        return self._request("POST",
                             f"/fleet/reconditioning-orders/{order_id}/complete",
                             payload, headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
