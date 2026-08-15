"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/endoscopy/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/endoscopy/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/endoscopy/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/endoscopy/patients", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Providers (endoscopists)
    # ------------------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/endoscopy/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/endoscopy/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/endoscopy/providers", headers=headers, params=params)

    def patch_provider(self, provider_id, payload, headers):
        return self._request("PATCH", f"/endoscopy/providers/{provider_id}", payload, headers)

    # ------------------------------------------------------------------
    # Procedure types
    # ------------------------------------------------------------------
    def create_procedure_type(self, payload, headers):
        return self._request("POST", "/endoscopy/procedure-types", payload, headers)

    def get_procedure_type(self, type_id, headers):
        return self._request("GET", f"/endoscopy/procedure-types/{type_id}", headers=headers)

    def list_procedure_types(self, headers, params=None):
        return self._request("GET", "/endoscopy/procedure-types", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", "/endoscopy/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/endoscopy/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/endoscopy/rooms", headers=headers, params=params)

    def patch_room(self, room_id, payload, headers):
        return self._request("PATCH", f"/endoscopy/rooms/{room_id}", payload, headers)

    # ------------------------------------------------------------------
    # Anesthesia providers
    # ------------------------------------------------------------------
    def create_anesthesia_provider(self, payload, headers):
        return self._request("POST", "/endoscopy/anesthesia-providers", payload, headers)

    def get_anesthesia_provider(self, ap_id, headers):
        return self._request("GET", f"/endoscopy/anesthesia-providers/{ap_id}", headers=headers)

    def list_anesthesia_providers(self, headers, params=None):
        return self._request("GET", "/endoscopy/anesthesia-providers", headers=headers, params=params)

    def patch_anesthesia_provider(self, ap_id, payload, headers):
        return self._request("PATCH", f"/endoscopy/anesthesia-providers/{ap_id}", payload, headers)

    # ------------------------------------------------------------------
    # Scopes
    # ------------------------------------------------------------------
    def create_scope(self, payload, headers):
        return self._request("POST", "/endoscopy/scopes", payload, headers)

    def get_scope(self, scope_id, headers):
        return self._request("GET", f"/endoscopy/scopes/{scope_id}", headers=headers)

    def list_scopes(self, headers, params=None):
        return self._request("GET", "/endoscopy/scopes", headers=headers, params=params)

    def send_scope_to_reprocessing(self, scope_id, headers):
        return self._request("POST", f"/endoscopy/scopes/{scope_id}/send-to-reprocessing",
                             {}, headers)

    def retire_scope(self, scope_id, headers):
        return self._request("POST", f"/endoscopy/scopes/{scope_id}/retire", {}, headers)

    def release_quarantine(self, scope_id, payload, headers):
        return self._request("POST", f"/endoscopy/scopes/{scope_id}/release-quarantine",
                             payload, headers)

    # ------------------------------------------------------------------
    # Procedure bookings
    # ------------------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/endoscopy/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/endoscopy/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/endoscopy/bookings", headers=headers, params=params)

    def patch_booking(self, booking_id, payload, headers):
        return self._request("PATCH", f"/endoscopy/bookings/{booking_id}", payload, headers)

    def confirm_prep(self, booking_id, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/confirm-prep",
                             {}, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/check-in",
                             {}, headers)

    def start_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/start",
                             payload, headers)

    def record_prep_assessment(self, booking_id, payload, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/record-prep-assessment",
                             payload, headers)

    def complete_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/complete",
                             payload, headers)

    def abort_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/abort",
                             payload, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/cancel",
                             payload, headers)

    def mark_no_show(self, booking_id, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/mark-no-show",
                             {}, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/endoscopy/bookings/{booking_id}/reschedule",
                             payload, headers)

    # ------------------------------------------------------------------
    # Anesthesia assignments
    # ------------------------------------------------------------------
    def create_anesthesia_assignment(self, payload, headers):
        return self._request("POST", "/endoscopy/anesthesia-assignments", payload, headers)

    def get_anesthesia_assignment(self, assignment_id, headers):
        return self._request("GET", f"/endoscopy/anesthesia-assignments/{assignment_id}",
                             headers=headers)

    def list_anesthesia_assignments(self, headers, params=None):
        return self._request("GET", "/endoscopy/anesthesia-assignments",
                             headers=headers, params=params)

    def confirm_anesthesia_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/endoscopy/anesthesia-assignments/{assignment_id}/confirm",
                             {}, headers)

    def cancel_anesthesia_assignment(self, assignment_id, payload, headers):
        return self._request("POST",
                             f"/endoscopy/anesthesia-assignments/{assignment_id}/cancel",
                             payload, headers)

    # ------------------------------------------------------------------
    # Scope usages
    # ------------------------------------------------------------------
    def list_scope_usages(self, headers, params=None):
        return self._request("GET", "/endoscopy/scope-usages", headers=headers, params=params)

    def get_scope_usage(self, usage_id, headers):
        return self._request("GET", f"/endoscopy/scope-usages/{usage_id}", headers=headers)

    def void_scope_usage(self, usage_id, payload, headers):
        return self._request("POST", f"/endoscopy/scope-usages/{usage_id}/void",
                             payload, headers)

    # ------------------------------------------------------------------
    # Reprocessing cycles
    # ------------------------------------------------------------------
    def create_reprocessing_cycle(self, payload, headers):
        return self._request("POST", "/endoscopy/reprocessing-cycles", payload, headers)

    def get_reprocessing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/endoscopy/reprocessing-cycles/{cycle_id}",
                             headers=headers)

    def list_reprocessing_cycles(self, headers, params=None):
        return self._request("GET", "/endoscopy/reprocessing-cycles",
                             headers=headers, params=params)

    def advance_cycle_step(self, cycle_id, payload, headers):
        return self._request("POST",
                             f"/endoscopy/reprocessing-cycles/{cycle_id}/steps/advance",
                             payload, headers)

    # ------------------------------------------------------------------
    # Culture tests
    # ------------------------------------------------------------------
    def create_culture_test(self, payload, headers):
        return self._request("POST", "/endoscopy/culture-tests", payload, headers)

    def get_culture_test(self, culture_id, headers):
        return self._request("GET", f"/endoscopy/culture-tests/{culture_id}", headers=headers)

    def list_culture_tests(self, headers, params=None):
        return self._request("GET", "/endoscopy/culture-tests", headers=headers, params=params)

    def result_culture_test(self, culture_id, payload, headers):
        return self._request("POST", f"/endoscopy/culture-tests/{culture_id}/result",
                             payload, headers)

    # ------------------------------------------------------------------
    # Quarantine cases
    # ------------------------------------------------------------------
    def list_quarantine_cases(self, headers, params=None):
        return self._request("GET", "/endoscopy/quarantine-cases", headers=headers, params=params)

    def get_quarantine_case(self, case_id, headers):
        return self._request("GET", f"/endoscopy/quarantine-cases/{case_id}", headers=headers)

    def list_quarantine_case_exposures(self, case_id, headers, params=None):
        return self._request("GET", f"/endoscopy/quarantine-cases/{case_id}/exposures",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Specimens
    # ------------------------------------------------------------------
    def create_specimen(self, payload, headers):
        return self._request("POST", "/endoscopy/specimens", payload, headers)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/endoscopy/specimens/{specimen_id}", headers=headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/endoscopy/specimens", headers=headers, params=params)

    def label_specimen(self, specimen_id, headers):
        return self._request("POST", f"/endoscopy/specimens/{specimen_id}/label", {}, headers)

    def handoff_specimen(self, specimen_id, payload, headers):
        return self._request("POST", f"/endoscopy/specimens/{specimen_id}/handoff",
                             payload, headers)

    def receive_specimen(self, specimen_id, headers):
        return self._request("POST", f"/endoscopy/specimens/{specimen_id}/receive", {}, headers)

    def reject_specimen(self, specimen_id, payload, headers):
        return self._request("POST", f"/endoscopy/specimens/{specimen_id}/reject",
                             payload, headers)

    def result_specimen(self, specimen_id, payload, headers):
        return self._request("POST", f"/endoscopy/specimens/{specimen_id}/result",
                             payload, headers)

    # ------------------------------------------------------------------
    # Quality reports and utilization
    # ------------------------------------------------------------------
    def create_quality_report(self, payload, headers):
        return self._request("POST", "/endoscopy/quality-reports", payload, headers)

    def get_quality_report(self, report_id, headers):
        return self._request("GET", f"/endoscopy/quality-reports/{report_id}", headers=headers)

    def list_quality_reports(self, headers, params=None):
        return self._request("GET", "/endoscopy/quality-reports", headers=headers, params=params)

    def get_room_utilization(self, headers, date):
        return self._request("GET", "/endoscopy/reports/room-utilization",
                             headers=headers, params={"date": date})


api_client = ApiClient()
