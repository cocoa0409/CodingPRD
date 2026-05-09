"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- OperatingRoom ---
    def create_operating_room(self, payload, headers):
        return self._request("POST", "/operating-rooms", payload, headers)

    def list_operating_rooms(self, headers, params=None):
        return self._request("GET", "/operating-rooms", headers=headers, params=params)

    def get_operating_room(self, room_id, headers):
        return self._request("GET", f"/operating-rooms/{room_id}", headers=headers)

    # --- SurgicalCase ---
    def create_surgical_case(self, payload, headers):
        return self._request("POST", "/surgical-cases", payload, headers)

    def list_surgical_cases(self, headers, params=None):
        return self._request("GET", "/surgical-cases", headers=headers, params=params)

    def get_surgical_case(self, case_id, headers):
        return self._request("GET", f"/surgical-cases/{case_id}", headers=headers)

    def approve_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/surgical-cases/{case_id}/approve", payload or {}, headers)

    def reject_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/surgical-cases/{case_id}/reject", payload or {}, headers)

    def schedule_case(self, case_id, payload, headers):
        return self._request("POST", f"/surgical-cases/{case_id}/schedule", payload, headers)

    def start_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/surgical-cases/{case_id}/start", payload or {}, headers)

    def complete_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/surgical-cases/{case_id}/complete", payload or {}, headers)

    def cancel_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/surgical-cases/{case_id}/cancel", payload or {}, headers)

    def emergency_insert(self, payload, headers):
        return self._request("POST", "/surgical-cases/emergency-insert", payload, headers)

    # --- CaseAssignment ---
    def list_assignments(self, case_id, headers, params=None):
        return self._request("GET", f"/surgical-cases/{case_id}/assignments", headers=headers, params=params)

    def confirm_assignment(self, case_id, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/surgical-cases/{case_id}/assignments/{assignment_id}/confirm",
            payload or {},
            headers,
        )

    # --- StaffMember ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    # --- InstrumentSet ---
    def create_instrument_set(self, payload, headers):
        return self._request("POST", "/instrument-sets", payload, headers)

    def list_instrument_sets(self, headers, params=None):
        return self._request("GET", "/instrument-sets", headers=headers, params=params)

    def get_instrument_set(self, instrument_set_id, headers):
        return self._request("GET", f"/instrument-sets/{instrument_set_id}", headers=headers)

    def start_sterilization(self, instrument_set_id, headers, payload=None):
        return self._request(
            "POST",
            f"/instrument-sets/{instrument_set_id}/start-sterilization",
            payload or {},
            headers,
        )

    def complete_sterilization(self, instrument_set_id, headers, payload=None):
        return self._request(
            "POST",
            f"/instrument-sets/{instrument_set_id}/complete-sterilization",
            payload or {},
            headers,
        )

    # --- Settlement ---
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def pre_authorize_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST",
            f"/settlements/{settlement_id}/pre-authorize",
            payload,
            headers,
        )

    def itemize_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST",
            f"/settlements/{settlement_id}/itemize",
            payload,
            headers,
        )

    def settle_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/settlements/{settlement_id}/settle",
            payload or {},
            headers,
        )

    # --- AuditEntry ---
    def list_audit_entries(self, headers, params=None):
        return self._request("GET", "/audit-entries", headers=headers, params=params)

    # --- Test-driving capabilities ---
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_sterilization(self, headers, payload=None):
        return self._request("POST", "/_sweep/sterilization", payload or {}, headers)


api_client = ApiClient()
