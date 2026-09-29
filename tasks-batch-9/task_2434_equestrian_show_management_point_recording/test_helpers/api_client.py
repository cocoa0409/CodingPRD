"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- shows
    def create_show(self, payload: dict, headers: dict):
        return self._request("POST", "/shows", payload, headers)

    def get_show(self, show_id: str, headers: dict):
        return self._request("GET", f"/shows/{show_id}", headers=headers)

    def submit_show_license(self, show_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/shows/{show_id}/license-submission", payload or {}, headers)

    def decide_show_license(self, show_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/shows/{show_id}/license-decision", payload, headers)

    # ---------------------------------------------------------------- rings
    def create_ring(self, show_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/shows/{show_id}/rings", payload, headers)

    def list_show_rings(self, show_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", f"/shows/{show_id}/rings", headers=headers, params=params)

    def get_ring(self, ring_id: str, headers: dict):
        return self._request("GET", f"/rings/{ring_id}", headers=headers)

    def record_footing_maintenance(self, ring_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/rings/{ring_id}/footing-maintenance", payload, headers)

    # ------------------------------------------------------------ divisions
    def create_division(self, show_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/shows/{show_id}/divisions", payload, headers)

    def list_show_divisions(self, show_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", f"/shows/{show_id}/divisions", headers=headers, params=params)

    # -------------------------------------------------------------- classes
    def create_class(self, division_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/divisions/{division_id}/classes", payload, headers)

    def get_class(self, class_id: str, headers: dict):
        return self._request("GET", f"/classes/{class_id}", headers=headers)

    def list_classes(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/classes", headers=headers, params=params)

    def open_class(self, class_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/classes/{class_id}/open", payload or {}, headers)

    def record_class_results(self, class_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/classes/{class_id}/results", payload, headers)

    def post_class_results(self, class_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/classes/{class_id}/post-results", payload or {}, headers)

    def void_class_results(self, class_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/classes/{class_id}/void-results", payload or {}, headers)

    def create_point_submission(self, class_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/classes/{class_id}/point-submissions", payload, headers)

    def list_class_point_submissions(self, class_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", f"/classes/{class_id}/point-submissions", headers=headers, params=params)

    def acknowledge_point_submission(self, submission_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/point-submissions/{submission_id}/acknowledgement", payload, headers)

    # ------------------------------------------------------------ ring slots
    def create_ring_slot(self, payload: dict, headers: dict):
        return self._request("POST", "/ring-slots", payload, headers)

    def get_ring_slot(self, slot_id: str, headers: dict):
        return self._request("GET", f"/ring-slots/{slot_id}", headers=headers)

    def list_ring_slots(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/ring-slots", headers=headers, params=params)

    def start_ring_slot(self, slot_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/ring-slots/{slot_id}/start", payload or {}, headers)

    def get_schedule_projection(self, show_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", f"/shows/{show_id}/schedule-projection", headers=headers, params=params)

    # ------------------------------------------------------------- officials
    def create_official(self, payload: dict, headers: dict):
        return self._request("POST", "/officials", payload, headers)

    def get_official(self, official_id: str, headers: dict):
        return self._request("GET", f"/officials/{official_id}", headers=headers)

    def create_official_assignment(self, payload: dict, headers: dict):
        return self._request("POST", "/official-assignments", payload, headers)

    def get_official_assignment(self, assignment_id: str, headers: dict):
        return self._request("GET", f"/official-assignments/{assignment_id}", headers=headers)

    def list_official_assignments(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/official-assignments", headers=headers, params=params)

    # ------------------------------------------------------- riders / horses
    def create_rider(self, payload: dict, headers: dict):
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id: str, headers: dict):
        return self._request("GET", f"/riders/{rider_id}", headers=headers)

    def get_rider_standings(self, rider_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", f"/riders/{rider_id}/standings", headers=headers, params=params)

    def create_horse(self, payload: dict, headers: dict):
        return self._request("POST", "/horses", payload, headers)

    def get_horse(self, horse_id: str, headers: dict):
        return self._request("GET", f"/horses/{horse_id}", headers=headers)

    # --------------------------------------------------------------- entries
    def create_entry(self, show_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/shows/{show_id}/entries", payload, headers)

    def get_entry(self, entry_id: str, headers: dict):
        return self._request("GET", f"/entries/{entry_id}", headers=headers)

    def list_entries(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/entries", headers=headers, params=params)

    def verify_entry(self, entry_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/entries/{entry_id}/verify", payload or {}, headers)

    def accept_entry(self, entry_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/entries/{entry_id}/accept", payload or {}, headers)

    def invoice_entry(self, entry_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/entries/{entry_id}/invoice", payload or {}, headers)

    def pay_entry(self, entry_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/entries/{entry_id}/payment", payload, headers)

    def withdraw_entry(self, entry_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/entries/{entry_id}/withdrawal", payload or {}, headers)

    # ---------------------------------------------------------- class entries
    def create_class_entry(self, payload: dict, headers: dict):
        return self._request("POST", "/class-entries", payload, headers)

    def get_class_entry(self, class_entry_id: str, headers: dict):
        return self._request("GET", f"/class-entries/{class_entry_id}", headers=headers)

    def list_class_entries(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/class-entries", headers=headers, params=params)

    # ------------------------------------------------------ compliance cases
    def create_compliance_case(self, entry_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/entries/{entry_id}/compliance-cases", payload, headers)

    def get_compliance_case(self, case_id: str, headers: dict):
        return self._request("GET", f"/compliance-cases/{case_id}", headers=headers)

    def list_compliance_cases(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/compliance-cases", headers=headers, params=params)

    def record_case_finding(self, case_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/compliance-cases/{case_id}/finding", payload, headers)

    # ------------------------------------------------------- coverage shifts
    def create_coverage_shift(self, show_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/shows/{show_id}/coverage-shifts", payload, headers)

    def list_show_coverage_shifts(self, show_id: str, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", f"/shows/{show_id}/coverage-shifts", headers=headers, params=params)

    def activate_coverage_shift(self, shift_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/coverage-shifts/{shift_id}/activate", payload or {}, headers)

    # ----------------------------------------------------------- logical clock
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
