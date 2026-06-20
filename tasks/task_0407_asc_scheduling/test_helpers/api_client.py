"""API client: one method per endpoint defined in the PRD (Section 4).

All endpoints are mounted under /asc.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Facilities ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/asc/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/asc/facilities/{facility_id}", headers=headers)

    def advance_clock(self, facility_id, payload, headers):
        return self._request("POST", f"/asc/facilities/{facility_id}/clock", payload, headers)

    # ---- Operating Rooms ----
    def create_operating_room(self, payload, headers):
        return self._request("POST", "/asc/operating-rooms", payload, headers)

    def list_operating_rooms(self, headers, params=None):
        return self._request("GET", "/asc/operating-rooms", headers=headers, params=params)

    def get_operating_room(self, or_id, headers):
        return self._request("GET", f"/asc/operating-rooms/{or_id}", headers=headers)

    def set_operating_room_status(self, or_id, payload, headers):
        return self._request("POST", f"/asc/operating-rooms/{or_id}/status", payload, headers)

    # ---- Recovery Bays ----
    def create_recovery_bay(self, payload, headers):
        return self._request("POST", "/asc/recovery-bays", payload, headers)

    def list_recovery_bays(self, headers, params=None):
        return self._request("GET", "/asc/recovery-bays", headers=headers, params=params)

    def get_recovery_bay(self, bay_id, headers):
        return self._request("GET", f"/asc/recovery-bays/{bay_id}", headers=headers)

    def set_recovery_bay_status(self, bay_id, payload, headers):
        return self._request("POST", f"/asc/recovery-bays/{bay_id}/status", payload, headers)

    # ---- Anesthesiologists ----
    def create_anesthesiologist(self, payload, headers):
        return self._request("POST", "/asc/anesthesiologists", payload, headers)

    def list_anesthesiologists(self, headers, params=None):
        return self._request("GET", "/asc/anesthesiologists", headers=headers, params=params)

    def get_anesthesiologist(self, anesth_id, headers):
        return self._request("GET", f"/asc/anesthesiologists/{anesth_id}", headers=headers)

    def get_coverage_load(self, anesth_id, headers, params=None):
        return self._request("GET", f"/asc/anesthesiologists/{anesth_id}/coverage-load", headers=headers, params=params)

    # ---- Surgeons ----
    def create_surgeon(self, payload, headers):
        return self._request("POST", "/asc/surgeons", payload, headers)

    def list_surgeons(self, headers, params=None):
        return self._request("GET", "/asc/surgeons", headers=headers, params=params)

    def get_surgeon(self, surgeon_id, headers):
        return self._request("GET", f"/asc/surgeons/{surgeon_id}", headers=headers)

    def update_surgeon(self, surgeon_id, payload, headers):
        return self._request("PATCH", f"/asc/surgeons/{surgeon_id}", payload, headers)

    # ---- Procedures ----
    def create_procedure(self, payload, headers):
        return self._request("POST", "/asc/procedures", payload, headers)

    def list_procedures(self, headers, params=None):
        return self._request("GET", "/asc/procedures", headers=headers, params=params)

    def get_procedure(self, procedure_id, headers):
        return self._request("GET", f"/asc/procedures/{procedure_id}", headers=headers)

    # ---- Supply Items ----
    def create_supply_item(self, payload, headers):
        return self._request("POST", "/asc/supply-items", payload, headers)

    def list_supply_items(self, headers, params=None):
        return self._request("GET", "/asc/supply-items", headers=headers, params=params)

    def get_supply_item(self, item_id, headers):
        return self._request("GET", f"/asc/supply-items/{item_id}", headers=headers)

    def restock_supply_item(self, item_id, payload, headers):
        return self._request("POST", f"/asc/supply-items/{item_id}/restock", payload, headers)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/asc/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/asc/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/asc/patients/{patient_id}", headers=headers)

    # ---- Surgical Days ----
    def create_surgical_day(self, payload, headers):
        return self._request("POST", "/asc/surgical-days", payload, headers)

    def list_surgical_days(self, headers, params=None):
        return self._request("GET", "/asc/surgical-days", headers=headers, params=params)

    def get_surgical_day(self, day_id, headers):
        return self._request("GET", f"/asc/surgical-days/{day_id}", headers=headers)

    def lock_day(self, day_id, headers):
        return self._request("POST", f"/asc/surgical-days/{day_id}/lock", {}, headers)

    def reopen_day(self, day_id, headers):
        return self._request("POST", f"/asc/surgical-days/{day_id}/reopen", {}, headers)

    def close_day(self, day_id, headers):
        return self._request("POST", f"/asc/surgical-days/{day_id}/close", {}, headers)

    # ---- Surgeon Blocks ----
    def create_surgeon_block(self, payload, headers):
        return self._request("POST", "/asc/surgeon-blocks", payload, headers)

    def list_surgeon_blocks(self, headers, params=None):
        return self._request("GET", "/asc/surgeon-blocks", headers=headers, params=params)

    def get_surgeon_block(self, block_id, headers):
        return self._request("GET", f"/asc/surgeon-blocks/{block_id}", headers=headers)

    def confirm_block(self, block_id, headers):
        return self._request("POST", f"/asc/surgeon-blocks/{block_id}/confirm", {}, headers)

    def release_block(self, block_id, headers):
        return self._request("POST", f"/asc/surgeon-blocks/{block_id}/release", {}, headers)

    def book_case(self, block_id, payload, headers):
        return self._request("POST", f"/asc/surgeon-blocks/{block_id}/cases", payload, headers)

    # ---- Surgical Cases ----
    def list_surgical_cases(self, headers, params=None):
        return self._request("GET", "/asc/surgical-cases", headers=headers, params=params)

    def get_surgical_case(self, case_id, headers):
        return self._request("GET", f"/asc/surgical-cases/{case_id}", headers=headers)

    def reschedule_case(self, case_id, payload, headers):
        return self._request("PATCH", f"/asc/surgical-cases/{case_id}/reschedule", payload, headers)

    def assign_anesthesia(self, case_id, payload, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/assign-anesthesia", payload, headers)

    def assign_recovery(self, case_id, payload, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/assign-recovery", payload, headers)

    def record_clearance_check(self, case_id, payload, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/clearance-checks", payload, headers)

    def clearance_reset(self, case_id, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/clearance-reset", {}, headers)

    def clear_case(self, case_id, payload, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/clear", payload, headers)

    def start_case(self, case_id, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/start", {}, headers)

    def case_to_recovery(self, case_id, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/to-recovery", {}, headers)

    def complete_case(self, case_id, payload, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/complete", payload, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/cancel", {}, headers)

    # ---- Case Implants ----
    def attach_implant(self, case_id, payload, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/implants", payload, headers)

    def patch_implant(self, implant_id, payload, headers):
        return self._request("PATCH", f"/asc/case-implants/{implant_id}", payload, headers)

    def release_implant(self, case_id, implant_id, headers):
        return self._request("POST", f"/asc/surgical-cases/{case_id}/implants/{implant_id}/release", {}, headers)

    def list_case_implants(self, headers, params=None):
        return self._request("GET", "/asc/case-implants", headers=headers, params=params)

    def get_case_implant(self, implant_id, headers):
        return self._request("GET", f"/asc/case-implants/{implant_id}", headers=headers)

    # ---- Clearance Checks (top-level read) ----
    def list_clearance_checks(self, headers, params=None):
        return self._request("GET", "/asc/clearance-checks", headers=headers, params=params)

    def get_clearance_check(self, check_id, headers):
        return self._request("GET", f"/asc/clearance-checks/{check_id}", headers=headers)


api_client = ApiClient()
