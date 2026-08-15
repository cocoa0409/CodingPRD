"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/port-ops/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Terminals
    # ------------------------------------------------------------------
    def create_terminal(self, payload, headers):
        return self._request("POST", "/port-ops/terminals", payload, headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", "/port-ops/terminals", headers=headers, params=params)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/port-ops/terminals/{terminal_id}", headers=headers)

    def run_ops(self, terminal_id, headers):
        return self._request("POST", f"/port-ops/terminals/{terminal_id}/run-ops", {}, headers)

    def get_screening_requirement(self, terminal_id, headers, port_call_id, mode=None):
        params = {"port_call_id": port_call_id}
        if mode is not None:
            params["mode"] = mode
        return self._request(
            "GET", f"/port-ops/terminals/{terminal_id}/screening-requirement",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Berths
    # ------------------------------------------------------------------
    def create_berth(self, payload, headers):
        return self._request("POST", "/port-ops/berths", payload, headers)

    def list_berths(self, headers, params=None):
        return self._request("GET", "/port-ops/berths", headers=headers, params=params)

    def get_berth(self, berth_id, headers):
        return self._request("GET", f"/port-ops/berths/{berth_id}", headers=headers)

    def out_of_service_berth(self, berth_id, headers):
        return self._request("POST", f"/port-ops/berths/{berth_id}/out-of-service", {}, headers)

    def return_to_service_berth(self, berth_id, headers):
        return self._request("POST", f"/port-ops/berths/{berth_id}/return-to-service", {}, headers)

    # ------------------------------------------------------------------
    # Vessels
    # ------------------------------------------------------------------
    def create_vessel(self, payload, headers):
        return self._request("POST", "/port-ops/vessels", payload, headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/port-ops/vessels", headers=headers, params=params)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/port-ops/vessels/{vessel_id}", headers=headers)

    # ------------------------------------------------------------------
    # Port calls
    # ------------------------------------------------------------------
    def create_port_call(self, payload, headers):
        return self._request("POST", "/port-ops/port-calls", payload, headers)

    def list_port_calls(self, headers, params=None):
        return self._request("GET", "/port-ops/port-calls", headers=headers, params=params)

    def get_port_call(self, port_call_id, headers):
        return self._request("GET", f"/port-ops/port-calls/{port_call_id}", headers=headers)

    def delay_port_call(self, port_call_id, payload, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/delay", payload, headers)

    def confirm_revised_port_call(self, port_call_id, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/confirm-revised", {}, headers)

    def arrive_port_call(self, port_call_id, payload, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/arrive", payload, headers)

    def begin_turnaround(self, port_call_id, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/begin-turnaround", {}, headers)

    def depart_port_call(self, port_call_id, payload, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/depart", payload, headers)

    def close_port_call(self, port_call_id, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/close", {}, headers)

    def cancel_port_call(self, port_call_id, headers, payload=None):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/cancel",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Berth assignments
    # ------------------------------------------------------------------
    def create_berth_assignment(self, port_call_id, payload, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/berth-assignments",
                             payload, headers)

    def list_berth_assignments(self, headers, params=None):
        return self._request("GET", "/port-ops/berth-assignments", headers=headers, params=params)

    def get_berth_assignment(self, assignment_id, headers):
        return self._request("GET", f"/port-ops/berth-assignments/{assignment_id}", headers=headers)

    def confirm_berth_assignment(self, assignment_id, headers):
        return self._request("POST", f"/port-ops/berth-assignments/{assignment_id}/confirm",
                             {}, headers)

    # ------------------------------------------------------------------
    # Manifest entries
    # ------------------------------------------------------------------
    def create_manifest_entry(self, port_call_id, payload, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/manifest-entries",
                             payload, headers)

    def list_manifest_entries(self, headers, params=None):
        return self._request("GET", "/port-ops/manifest-entries", headers=headers, params=params)

    def get_manifest_entry(self, entry_id, headers):
        return self._request("GET", f"/port-ops/manifest-entries/{entry_id}", headers=headers)

    def check_in_manifest_entry(self, entry_id, headers):
        return self._request("POST", f"/port-ops/manifest-entries/{entry_id}/check-in", {}, headers)

    def screen_manifest_entry(self, entry_id, headers):
        return self._request("POST", f"/port-ops/manifest-entries/{entry_id}/screen", {}, headers)

    def board_manifest_entry(self, entry_id, headers):
        return self._request("POST", f"/port-ops/manifest-entries/{entry_id}/board", {}, headers)

    def offload_manifest_entry(self, entry_id, headers):
        return self._request("POST", f"/port-ops/manifest-entries/{entry_id}/offload", {}, headers)

    def disembark_manifest_entry(self, entry_id, headers):
        return self._request("POST", f"/port-ops/manifest-entries/{entry_id}/disembark", {}, headers)

    def customs_hold_manifest_entry(self, entry_id, headers):
        return self._request("POST", f"/port-ops/manifest-entries/{entry_id}/customs-hold",
                             {}, headers)

    def customs_release_manifest_entry(self, entry_id, headers):
        return self._request("POST", f"/port-ops/manifest-entries/{entry_id}/customs-release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Baggage items
    # ------------------------------------------------------------------
    def create_baggage_item(self, payload, headers):
        return self._request("POST", "/port-ops/baggage-items", payload, headers)

    def list_baggage_items(self, headers, params=None):
        return self._request("GET", "/port-ops/baggage-items", headers=headers, params=params)

    def get_baggage_item(self, bag_id, headers):
        return self._request("GET", f"/port-ops/baggage-items/{bag_id}", headers=headers)

    def stage_baggage_item(self, bag_id, headers):
        return self._request("POST", f"/port-ops/baggage-items/{bag_id}/stage", {}, headers)

    def load_baggage_item(self, bag_id, headers):
        return self._request("POST", f"/port-ops/baggage-items/{bag_id}/load", {}, headers)

    def report_mistag_baggage_item(self, bag_id, headers, payload=None):
        return self._request("POST", f"/port-ops/baggage-items/{bag_id}/report-mistag",
                             payload or {}, headers)

    def recover_baggage_item(self, bag_id, headers):
        return self._request("POST", f"/port-ops/baggage-items/{bag_id}/recover", {}, headers)

    def deliver_baggage_item(self, bag_id, headers):
        return self._request("POST", f"/port-ops/baggage-items/{bag_id}/deliver", {}, headers)

    # ------------------------------------------------------------------
    # Screening lanes
    # ------------------------------------------------------------------
    def create_screening_lane(self, payload, headers):
        return self._request("POST", "/port-ops/screening-lanes", payload, headers)

    def list_screening_lanes(self, headers, params=None):
        return self._request("GET", "/port-ops/screening-lanes", headers=headers, params=params)

    def get_screening_lane(self, lane_id, headers):
        return self._request("GET", f"/port-ops/screening-lanes/{lane_id}", headers=headers)

    def open_screening_lane(self, lane_id, payload, headers):
        return self._request("POST", f"/port-ops/screening-lanes/{lane_id}/open", payload, headers)

    def close_screening_lane(self, lane_id, headers):
        return self._request("POST", f"/port-ops/screening-lanes/{lane_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Customs cases
    # ------------------------------------------------------------------
    def create_customs_case(self, port_call_id, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/customs-cases",
                             {}, headers)

    def list_customs_cases(self, headers, params=None):
        return self._request("GET", "/port-ops/customs-cases", headers=headers, params=params)

    def get_customs_case(self, case_id, headers):
        return self._request("GET", f"/port-ops/customs-cases/{case_id}", headers=headers)

    def file_customs_case(self, case_id, headers):
        return self._request("POST", f"/port-ops/customs-cases/{case_id}/file", {}, headers)

    def hold_customs_case(self, case_id, payload, headers):
        return self._request("POST", f"/port-ops/customs-cases/{case_id}/hold", payload, headers)

    def clear_customs_case(self, case_id, headers):
        return self._request("POST", f"/port-ops/customs-cases/{case_id}/clear", {}, headers)

    # ------------------------------------------------------------------
    # Service orders
    # ------------------------------------------------------------------
    def create_service_order(self, port_call_id, payload, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/service-orders",
                             payload, headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/port-ops/service-orders", headers=headers, params=params)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/port-ops/service-orders/{order_id}", headers=headers)

    def approve_service_order(self, order_id, headers):
        return self._request("POST", f"/port-ops/service-orders/{order_id}/approve", {}, headers)

    def reject_service_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/port-ops/service-orders/{order_id}/reject",
                             payload or {}, headers)

    def start_service_order(self, order_id, headers):
        return self._request("POST", f"/port-ops/service-orders/{order_id}/start", {}, headers)

    def complete_service_order(self, order_id, payload, headers):
        return self._request("POST", f"/port-ops/service-orders/{order_id}/complete",
                             payload, headers)

    def cancel_service_order(self, order_id, headers):
        return self._request("POST", f"/port-ops/service-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def create_provisional_invoice(self, port_call_id, headers):
        return self._request("POST", f"/port-ops/port-calls/{port_call_id}/provisional-invoice",
                             {}, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/port-ops/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/port-ops/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/port-ops/invoices/{invoice_id}/issue", {}, headers)

    def settle_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/port-ops/invoices/{invoice_id}/settle", payload, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/port-ops/invoices/{invoice_id}/dispute", payload, headers)

    def post_invoice_adjustment(self, invoice_id, payload, headers):
        return self._request("POST", f"/port-ops/invoices/{invoice_id}/adjustments",
                             payload, headers)

    # ------------------------------------------------------------------
    # Transport slots
    # ------------------------------------------------------------------
    def create_transport_slot(self, payload, headers):
        return self._request("POST", "/port-ops/transport-slots", payload, headers)

    def list_transport_slots(self, headers, params=None):
        return self._request("GET", "/port-ops/transport-slots", headers=headers, params=params)

    def get_transport_slot(self, slot_id, headers):
        return self._request("GET", f"/port-ops/transport-slots/{slot_id}", headers=headers)

    def dispatch_transport_slot(self, slot_id, headers):
        return self._request("POST", f"/port-ops/transport-slots/{slot_id}/dispatch", {}, headers)

    def complete_transport_slot(self, slot_id, headers):
        return self._request("POST", f"/port-ops/transport-slots/{slot_id}/complete", {}, headers)

    def no_show_transport_slot(self, slot_id, headers):
        return self._request("POST", f"/port-ops/transport-slots/{slot_id}/no-show", {}, headers)

    def requeue_transport_slot(self, slot_id, headers):
        return self._request("POST", f"/port-ops/transport-slots/{slot_id}/requeue", {}, headers)

    # ------------------------------------------------------------------
    # Weather advisories
    # ------------------------------------------------------------------
    def create_weather_advisory(self, payload, headers):
        return self._request("POST", "/port-ops/weather-advisories", payload, headers)

    def list_weather_advisories(self, headers, params=None):
        return self._request("GET", "/port-ops/weather-advisories", headers=headers, params=params)

    def get_weather_advisory(self, advisory_id, headers):
        return self._request("GET", f"/port-ops/weather-advisories/{advisory_id}", headers=headers)

    def cancel_weather_advisory(self, advisory_id, headers):
        return self._request("POST", f"/port-ops/weather-advisories/{advisory_id}/cancel",
                             {}, headers)


api_client = ApiClient()
