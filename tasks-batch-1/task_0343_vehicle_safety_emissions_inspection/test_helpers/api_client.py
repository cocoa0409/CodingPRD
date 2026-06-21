"""API client: one method per endpoint defined in the Vehicle Safety &
Emissions Inspection PRD (§4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Station ----
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    # ---- VehicleClassProfile ----
    def create_vehicle_class_profile(self, payload, headers):
        return self._request("POST", "/vehicle-class-profiles", payload, headers)

    def get_vehicle_class_profile(self, profile_id, headers):
        return self._request("GET", f"/vehicle-class-profiles/{profile_id}", headers=headers)

    def list_vehicle_class_profiles(self, headers, params=None):
        return self._request("GET", "/vehicle-class-profiles", headers=headers, params=params)

    # ---- Lane ----
    def create_lane(self, payload, headers):
        return self._request("POST", "/lanes", payload, headers)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/lanes/{lane_id}", headers=headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/lanes", headers=headers, params=params)

    def list_lane_appointments(self, lane_id, headers, params=None):
        return self._request("GET", f"/lanes/{lane_id}/appointments", headers=headers, params=params)

    # ---- AnalyzerReservation ----
    def create_analyzer_reservation(self, payload, headers):
        return self._request("POST", "/analyzer-reservations", payload, headers)

    def get_analyzer_reservation(self, reservation_id, headers):
        return self._request("GET", f"/analyzer-reservations/{reservation_id}", headers=headers)

    def list_analyzer_reservations(self, headers, params=None):
        return self._request("GET", "/analyzer-reservations", headers=headers, params=params)

    def release_analyzer_reservation(self, reservation_id, headers):
        return self._request("POST", f"/analyzer-reservations/{reservation_id}/release", {}, headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/no-show", {}, headers)

    # ---- InspectionRecord ----
    def create_inspection_record(self, payload, headers):
        return self._request("POST", "/inspection-records", payload, headers)

    def get_inspection_record(self, record_id, headers):
        return self._request("GET", f"/inspection-records/{record_id}", headers=headers)

    def list_inspection_records(self, headers, params=None):
        return self._request("GET", "/inspection-records", headers=headers, params=params)

    def decide_inspection_record(self, record_id, headers):
        return self._request("POST", f"/inspection-records/{record_id}/decide", {}, headers)

    def reinspect_inspection_record(self, record_id, payload, headers):
        return self._request("POST", f"/inspection-records/{record_id}/reinspect", payload, headers)

    def abort_inspection_record(self, record_id, headers):
        return self._request("POST", f"/inspection-records/{record_id}/abort", {}, headers)

    def get_waiver_eligibility(self, record_id, headers):
        return self._request("GET", f"/inspection-records/{record_id}/waiver-eligibility", headers=headers)

    def get_state_surcharge(self, record_id, headers):
        return self._request("GET", f"/inspection-records/{record_id}/state-surcharge", headers=headers)

    # ---- ChecklistResult ----
    def create_checklist_result(self, payload, headers):
        return self._request("POST", "/checklist-results", payload, headers)

    def get_checklist_result(self, result_id, headers):
        return self._request("GET", f"/checklist-results/{result_id}", headers=headers)

    def list_checklist_results(self, headers, params=None):
        return self._request("GET", "/checklist-results", headers=headers, params=params)

    # ---- EmissionsTest ----
    def create_emissions_test(self, payload, headers):
        return self._request("POST", "/emissions-tests", payload, headers)

    def get_emissions_test(self, test_id, headers):
        return self._request("GET", f"/emissions-tests/{test_id}", headers=headers)

    def list_emissions_tests(self, headers, params=None):
        return self._request("GET", "/emissions-tests", headers=headers, params=params)

    # ---- RepairOrder ----
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, order_id, headers):
        return self._request("GET", f"/repair-orders/{order_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def verify_repair_order(self, order_id, headers):
        return self._request("POST", f"/repair-orders/{order_id}/verify", {}, headers)

    def reject_repair_order(self, order_id, headers):
        return self._request("POST", f"/repair-orders/{order_id}/reject", {}, headers)

    # ---- WaiverRequest ----
    def create_waiver_request(self, payload, headers):
        return self._request("POST", "/waiver-requests", payload, headers)

    def get_waiver_request(self, request_id, headers):
        return self._request("GET", f"/waiver-requests/{request_id}", headers=headers)

    def list_waiver_requests(self, headers, params=None):
        return self._request("GET", "/waiver-requests", headers=headers, params=params)

    def decide_waiver_request(self, request_id, payload, headers):
        return self._request("POST", f"/waiver-requests/{request_id}/decide", payload, headers)

    # ---- Certificate ----
    def create_certificate(self, payload, headers):
        return self._request("POST", "/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def void_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/void", {}, headers)

    # ---- StateReportBatch + StateReportLine ----
    def create_state_report_batch(self, payload, headers):
        return self._request("POST", "/state-report-batches", payload, headers)

    def get_state_report_batch(self, batch_id, headers):
        return self._request("GET", f"/state-report-batches/{batch_id}", headers=headers)

    def list_state_report_batches(self, headers, params=None):
        return self._request("GET", "/state-report-batches", headers=headers, params=params)

    def attach_state_report_line(self, batch_id, payload, headers):
        return self._request("POST", f"/state-report-batches/{batch_id}/lines", payload, headers)

    def list_state_report_batch_lines(self, batch_id, headers, params=None):
        return self._request("GET", f"/state-report-batches/{batch_id}/lines", headers=headers, params=params)

    def get_state_report_line(self, line_id, headers):
        return self._request("GET", f"/state-report-lines/{line_id}", headers=headers)

    def list_state_report_lines(self, headers, params=None):
        return self._request("GET", "/state-report-lines", headers=headers, params=params)

    def detach_state_report_line(self, batch_id, record_id, headers):
        return self._request(
            "DELETE", f"/state-report-batches/{batch_id}/lines/{record_id}", headers=headers
        )

    def submit_state_report_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/state-report-batches/{batch_id}/submit", payload, headers)

    def decide_state_report_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/state-report-batches/{batch_id}/decide", payload, headers)

    def reopen_state_report_batch(self, batch_id, headers):
        return self._request("POST", f"/state-report-batches/{batch_id}/reopen", {}, headers)


api_client = ApiClient()
