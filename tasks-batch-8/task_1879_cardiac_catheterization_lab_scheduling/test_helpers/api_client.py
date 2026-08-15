"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/cath-lab/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Cath lab rooms
    # ------------------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", "/cath-lab/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/cath-lab/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/cath-lab/rooms/{room_id}", headers=headers)

    def patch_room(self, room_id, payload, headers):
        return self._request("PATCH", f"/cath-lab/rooms/{room_id}", payload, headers)

    # ------------------------------------------------------------------
    # Staff members
    # ------------------------------------------------------------------
    def create_staff(self, payload, headers):
        return self._request("POST", "/cath-lab/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/cath-lab/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/cath-lab/staff/{staff_id}", headers=headers)

    def patch_staff(self, staff_id, payload, headers):
        return self._request("PATCH", f"/cath-lab/staff/{staff_id}", payload, headers)

    def list_staff_assignments(self, staff_id, headers, params=None):
        return self._request("GET", f"/cath-lab/staff/{staff_id}/assignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Cath cases
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/cath-lab/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cath-lab/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cath-lab/cases/{case_id}", headers=headers)

    def schedule_case(self, case_id, payload, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/schedule",
                             payload, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/cancel", {}, headers)

    def start_case(self, case_id, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/start", {}, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/complete", {}, headers)

    def attest_auc(self, case_id, payload, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/auc-attestation",
                             payload, headers)

    # ------------------------------------------------------------------
    # Staff assignments
    # ------------------------------------------------------------------
    def create_staff_assignment(self, case_id, payload, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/staff-assignments",
                             payload, headers)

    def list_case_staff_assignments(self, case_id, headers, params=None):
        return self._request("GET", f"/cath-lab/cases/{case_id}/staff-assignments",
                             headers=headers, params=params)

    def release_staff_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/cath-lab/staff-assignments/{assignment_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Device lots
    # ------------------------------------------------------------------
    def create_device_lot(self, payload, headers):
        return self._request("POST", "/cath-lab/device-lots", payload, headers)

    def list_device_lots(self, headers, params=None):
        return self._request("GET", "/cath-lab/device-lots", headers=headers,
                             params=params)

    def get_device_lot(self, lot_id, headers):
        return self._request("GET", f"/cath-lab/device-lots/{lot_id}", headers=headers)

    def restock_device_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/cath-lab/device-lots/{lot_id}/restock",
                             payload, headers)

    def list_lot_usages(self, lot_id, headers, params=None):
        return self._request("GET", f"/cath-lab/device-lots/{lot_id}/usages",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Device usages
    # ------------------------------------------------------------------
    def create_device_usage(self, case_id, payload, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/device-usages",
                             payload, headers)

    def list_case_device_usages(self, case_id, headers, params=None):
        return self._request("GET", f"/cath-lab/cases/{case_id}/device-usages",
                             headers=headers, params=params)

    def implant_device_usage(self, usage_id, headers):
        return self._request("POST", f"/cath-lab/device-usages/{usage_id}/implant",
                             {}, headers)

    def release_device_usage(self, usage_id, headers):
        return self._request("POST", f"/cath-lab/device-usages/{usage_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Dose records
    # ------------------------------------------------------------------
    def create_dose_record(self, case_id, payload, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/dose-records",
                             payload, headers)

    def list_case_dose_records(self, case_id, headers, params=None):
        return self._request("GET", f"/cath-lab/cases/{case_id}/dose-records",
                             headers=headers, params=params)

    def void_dose_record(self, record_id, headers):
        return self._request("POST", f"/cath-lab/dose-records/{record_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Recovery beds
    # ------------------------------------------------------------------
    def create_recovery_bed(self, payload, headers):
        return self._request("POST", "/cath-lab/recovery-beds", payload, headers)

    def list_recovery_beds(self, headers, params=None):
        return self._request("GET", "/cath-lab/recovery-beds", headers=headers,
                             params=params)

    def get_recovery_bed(self, bed_id, headers):
        return self._request("GET", f"/cath-lab/recovery-beds/{bed_id}",
                             headers=headers)

    def patch_recovery_bed(self, bed_id, payload, headers):
        return self._request("PATCH", f"/cath-lab/recovery-beds/{bed_id}",
                             payload, headers)

    def release_recovery_bed(self, bed_id, headers):
        return self._request("POST", f"/cath-lab/recovery-beds/{bed_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Registry submissions
    # ------------------------------------------------------------------
    def create_registry_submission(self, case_id, headers):
        return self._request("POST", f"/cath-lab/cases/{case_id}/registry-submissions",
                             {}, headers)

    def list_case_registry_submissions(self, case_id, headers, params=None):
        return self._request("GET",
                             f"/cath-lab/cases/{case_id}/registry-submissions",
                             headers=headers, params=params)

    def get_registry_submission(self, submission_id, headers):
        return self._request("GET",
                             f"/cath-lab/registry-submissions/{submission_id}",
                             headers=headers)

    def submit_registry_submission(self, submission_id, headers):
        return self._request("POST",
                             f"/cath-lab/registry-submissions/{submission_id}/submit",
                             {}, headers)

    def record_submission_decision(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/cath-lab/registry-submissions/{submission_id}/record-decision",
            payload, headers)

    def revise_registry_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/cath-lab/registry-submissions/{submission_id}/revise",
            payload, headers)


api_client = ApiClient()
