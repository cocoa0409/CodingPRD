"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Station ----
    def create_station(self, payload, headers):
        return self._request("POST", "/deice-ops/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/deice-ops/stations/{station_id}", headers=headers)

    def run_ops_checkpoint(self, station_id, headers):
        return self._request(
            "POST", f"/deice-ops/stations/{station_id}/run_ops_checkpoint", {}, headers
        )

    # ---- Pad ----
    def create_pad(self, payload, headers):
        return self._request("POST", "/deice-ops/pads", payload, headers)

    def get_pad(self, pad_id, headers):
        return self._request("GET", f"/deice-ops/pads/{pad_id}", headers=headers)

    def list_pads(self, headers, params=None):
        return self._request("GET", "/deice-ops/pads", headers=headers, params=params)

    def take_pad_out_of_service(self, pad_id, headers):
        return self._request(
            "POST", f"/deice-ops/pads/{pad_id}/take_out_of_service", {}, headers
        )

    # ---- WeatherEvent ----
    def create_weather_event(self, payload, headers):
        return self._request("POST", "/deice-ops/weather-events", payload, headers)

    def get_weather_event(self, event_id, headers):
        return self._request(
            "GET", f"/deice-ops/weather-events/{event_id}", headers=headers
        )

    def list_weather_events(self, headers, params=None):
        return self._request(
            "GET", "/deice-ops/weather-events", headers=headers, params=params
        )

    def activate_weather_event(self, event_id, headers):
        return self._request(
            "POST", f"/deice-ops/weather-events/{event_id}/activate", {}, headers
        )

    def end_weather_event(self, event_id, headers):
        return self._request(
            "POST", f"/deice-ops/weather-events/{event_id}/end", {}, headers
        )

    def escalate_weather_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/deice-ops/weather-events/{event_id}/escalate", payload, headers
        )

    # ---- FluidTank ----
    def create_fluid_tank(self, payload, headers):
        return self._request("POST", "/deice-ops/fluid-tanks", payload, headers)

    def get_fluid_tank(self, tank_id, headers):
        return self._request("GET", f"/deice-ops/fluid-tanks/{tank_id}", headers=headers)

    def list_fluid_tanks(self, headers, params=None):
        return self._request(
            "GET", "/deice-ops/fluid-tanks", headers=headers, params=params
        )

    def replenish_fluid_tank(self, tank_id, payload, headers):
        return self._request(
            "POST", f"/deice-ops/fluid-tanks/{tank_id}/replenish", payload, headers
        )

    # ---- Airline ----
    def create_airline(self, payload, headers):
        return self._request("POST", "/deice-ops/airlines", payload, headers)

    def get_airline(self, airline_id, headers):
        return self._request("GET", f"/deice-ops/airlines/{airline_id}", headers=headers)

    # ---- DeiceRequest ----
    def create_deice_request(self, payload, headers):
        return self._request("POST", "/deice-ops/deice-requests", payload, headers)

    def get_deice_request(self, request_id, headers):
        return self._request(
            "GET", f"/deice-ops/deice-requests/{request_id}", headers=headers
        )

    def list_deice_requests(self, headers, params=None):
        return self._request(
            "GET", "/deice-ops/deice-requests", headers=headers, params=params
        )

    def assign_deice_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/deice-ops/deice-requests/{request_id}/assign", payload, headers
        )

    def defer_deice_request(self, request_id, headers):
        return self._request(
            "POST", f"/deice-ops/deice-requests/{request_id}/defer", {}, headers
        )

    def requeue_deice_request(self, request_id, headers):
        return self._request(
            "POST", f"/deice-ops/deice-requests/{request_id}/requeue", {}, headers
        )

    def abort_deice_request(self, request_id, headers):
        return self._request(
            "POST", f"/deice-ops/deice-requests/{request_id}/abort", {}, headers
        )

    # ---- DeiceOperation ----
    def get_deice_operation(self, operation_id, headers):
        return self._request(
            "GET", f"/deice-ops/deice-operations/{operation_id}", headers=headers
        )

    def list_deice_operations(self, headers, params=None):
        return self._request(
            "GET", "/deice-ops/deice-operations", headers=headers, params=params
        )

    def start_deice_operation(self, operation_id, payload, headers):
        return self._request(
            "POST", f"/deice-ops/deice-operations/{operation_id}/start", payload, headers
        )

    def complete_deice_operation(self, operation_id, payload, headers):
        return self._request(
            "POST",
            f"/deice-ops/deice-operations/{operation_id}/complete",
            payload,
            headers,
        )

    def void_deice_operation(self, operation_id, headers):
        return self._request(
            "POST", f"/deice-ops/deice-operations/{operation_id}/void", {}, headers
        )

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/deice-ops/inspections", payload, headers)

    def list_operation_inspections(self, operation_id, headers, params=None):
        return self._request(
            "GET",
            f"/deice-ops/deice-operations/{operation_id}/inspections",
            headers=headers,
            params=params,
        )

    # ---- DischargePermit ----
    def create_discharge_permit(self, payload, headers):
        return self._request("POST", "/deice-ops/discharge-permits", payload, headers)

    def get_discharge_permit(self, permit_id, headers):
        return self._request(
            "GET", f"/deice-ops/discharge-permits/{permit_id}", headers=headers
        )

    def list_discharge_permits(self, headers, params=None):
        return self._request(
            "GET", "/deice-ops/discharge-permits", headers=headers, params=params
        )

    def suspend_discharge_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/deice-ops/discharge-permits/{permit_id}/suspend", {}, headers
        )

    def reinstate_discharge_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/deice-ops/discharge-permits/{permit_id}/reinstate", {}, headers
        )

    # ---- EffluentReading ----
    def create_effluent_reading(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"/deice-ops/discharge-permits/{permit_id}/effluent-readings",
            payload,
            headers,
        )

    def list_effluent_readings(self, permit_id, headers):
        return self._request(
            "GET",
            f"/deice-ops/discharge-permits/{permit_id}/effluent-readings",
            headers=headers,
        )

    # ---- SpillReport ----
    def create_spill_report(self, payload, headers):
        return self._request("POST", "/deice-ops/spill-reports", payload, headers)

    def get_spill_report(self, spill_id, headers):
        return self._request(
            "GET", f"/deice-ops/spill-reports/{spill_id}", headers=headers
        )

    def list_spill_reports(self, headers, params=None):
        return self._request(
            "GET", "/deice-ops/spill-reports", headers=headers, params=params
        )

    def confirm_spill_report(self, spill_id, headers):
        return self._request(
            "POST", f"/deice-ops/spill-reports/{spill_id}/confirm", {}, headers
        )

    def close_spill_report(self, spill_id, headers):
        return self._request(
            "POST", f"/deice-ops/spill-reports/{spill_id}/close", {}, headers
        )

    # ---- RecyclingContract ----
    def create_recycling_contract(self, payload, headers):
        return self._request("POST", "/deice-ops/recycling-contracts", payload, headers)

    def get_recycling_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/deice-ops/recycling-contracts/{contract_id}", headers=headers
        )

    def list_recycling_contracts(self, headers, params=None):
        return self._request(
            "GET", "/deice-ops/recycling-contracts", headers=headers, params=params
        )

    def record_shipment(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/deice-ops/recycling-contracts/{contract_id}/record_shipment",
            payload,
            headers,
        )

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/deice-ops/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/deice-ops/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/deice-ops/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/deice-ops/invoices/{invoice_id}/issue", {}, headers
        )

    def void_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/deice-ops/invoices/{invoice_id}/void", {}, headers
        )

    # ---- Logical clock (test-driving) ----
    def set_current_utc(self, payload, headers):
        return self._request(
            "POST", "/deice-ops/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
