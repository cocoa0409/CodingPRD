"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Gate registry -----------------------------------------------------
    def create_gate(self, payload, headers):
        return self._request("POST", "/gates", payload, headers)

    def get_gate(self, gate_id, headers):
        return self._request("GET", f"/gates/{gate_id}", headers=headers)

    def list_gates(self, headers, params=None):
        return self._request("GET", "/gates", headers=headers, params=params)

    def out_of_service_gate(self, gate_id, headers):
        return self._request("POST", f"/gates/{gate_id}/out-of-service", {}, headers)

    def list_gate_gate_assignments(self, gate_id, headers, params=None):
        return self._request("GET", f"/gates/{gate_id}/gate-assignments", headers=headers, params=params)

    # ---- RemoteStand registry ---------------------------------------------
    def create_remote_stand(self, payload, headers):
        return self._request("POST", "/remote-stands", payload, headers)

    def get_remote_stand(self, stand_id, headers):
        return self._request("GET", f"/remote-stands/{stand_id}", headers=headers)

    def list_remote_stands(self, headers, params=None):
        return self._request("GET", "/remote-stands", headers=headers, params=params)

    def list_remote_stand_gate_assignments(self, stand_id, headers, params=None):
        return self._request("GET", f"/remote-stands/{stand_id}/gate-assignments", headers=headers, params=params)

    # ---- CuteUnit registry -------------------------------------------------
    def create_cute_unit(self, payload, headers):
        return self._request("POST", "/cute-units", payload, headers)

    def get_cute_unit(self, unit_id, headers):
        return self._request("GET", f"/cute-units/{unit_id}", headers=headers)

    def list_cute_unit_cute_allocations(self, unit_id, headers, params=None):
        return self._request("GET", f"/cute-units/{unit_id}/cute-allocations", headers=headers, params=params)

    # ---- GroundEquipment registry -----------------------------------------
    def create_ground_equipment(self, payload, headers):
        return self._request("POST", "/ground-equipment", payload, headers)

    def get_ground_equipment(self, equipment_id, headers):
        return self._request("GET", f"/ground-equipment/{equipment_id}", headers=headers)

    def list_ground_equipment_gse_allocations(self, equipment_id, headers, params=None):
        return self._request("GET", f"/ground-equipment/{equipment_id}/gse-allocations", headers=headers, params=params)

    # ---- Flight ------------------------------------------------------------
    def create_flight(self, payload, headers):
        return self._request("POST", "/flights", payload, headers)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/flights/{flight_id}", headers=headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/flights", headers=headers, params=params)

    def activate_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/activate", {}, headers)

    def complete_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/complete", {}, headers)

    def irops_cancel_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/irops-cancel", {}, headers)

    def irops_divert_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/irops-divert", {}, headers)

    def list_flight_gate_assignments(self, flight_id, headers, params=None):
        return self._request("GET", f"/flights/{flight_id}/gate-assignments", headers=headers, params=params)

    def list_flight_slot_permits(self, flight_id, headers, params=None):
        return self._request("GET", f"/flights/{flight_id}/slot-permits", headers=headers, params=params)

    def list_flight_cute_allocations(self, flight_id, headers, params=None):
        return self._request("GET", f"/flights/{flight_id}/cute-allocations", headers=headers, params=params)

    def list_flight_gse_allocations(self, flight_id, headers, params=None):
        return self._request("GET", f"/flights/{flight_id}/gse-allocations", headers=headers, params=params)

    # ---- GateAssignment ----------------------------------------------------
    def create_gate_assignment(self, payload, headers):
        return self._request("POST", "/gate-assignments", payload, headers)

    def get_gate_assignment(self, assignment_id, headers):
        return self._request("GET", f"/gate-assignments/{assignment_id}", headers=headers)

    def list_gate_assignments(self, headers, params=None):
        return self._request("GET", "/gate-assignments", headers=headers, params=params)

    def occupy_gate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/gate-assignments/{assignment_id}/occupy", {}, headers)

    def tow_gate_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/gate-assignments/{assignment_id}/tow", payload, headers)

    def return_gate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/gate-assignments/{assignment_id}/return", {}, headers)

    def depart_gate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/gate-assignments/{assignment_id}/depart", {}, headers)

    def cancel_gate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/gate-assignments/{assignment_id}/cancel", {}, headers)

    # ---- SlotPermit --------------------------------------------------------
    def create_slot_permit(self, payload, headers):
        return self._request("POST", "/slot-permits", payload, headers)

    def get_slot_permit(self, permit_id, headers):
        return self._request("GET", f"/slot-permits/{permit_id}", headers=headers)

    def list_slot_permits(self, headers, params=None):
        return self._request("GET", "/slot-permits", headers=headers, params=params)

    def confirm_slot_permit(self, permit_id, headers):
        return self._request("POST", f"/slot-permits/{permit_id}/confirm", {}, headers)

    def redeem_slot_permit(self, permit_id, headers):
        return self._request("POST", f"/slot-permits/{permit_id}/redeem", {}, headers)

    def forfeit_slot_permit(self, permit_id, headers):
        return self._request("POST", f"/slot-permits/{permit_id}/forfeit", {}, headers)

    def cancel_slot_permit(self, permit_id, headers):
        return self._request("POST", f"/slot-permits/{permit_id}/cancel", {}, headers)

    # ---- CuteAllocation ----------------------------------------------------
    def create_cute_allocation(self, payload, headers):
        return self._request("POST", "/cute-allocations", payload, headers)

    def get_cute_allocation(self, allocation_id, headers):
        return self._request("GET", f"/cute-allocations/{allocation_id}", headers=headers)

    def list_cute_allocations(self, headers, params=None):
        return self._request("GET", "/cute-allocations", headers=headers, params=params)

    def release_cute_allocation(self, allocation_id, headers):
        return self._request("POST", f"/cute-allocations/{allocation_id}/release", {}, headers)

    # ---- GseAllocation -----------------------------------------------------
    def create_gse_allocation(self, payload, headers):
        return self._request("POST", "/gse-allocations", payload, headers)

    def get_gse_allocation(self, allocation_id, headers):
        return self._request("GET", f"/gse-allocations/{allocation_id}", headers=headers)

    def list_gse_allocations(self, headers, params=None):
        return self._request("GET", "/gse-allocations", headers=headers, params=params)

    def release_gse_allocation(self, allocation_id, headers):
        return self._request("POST", f"/gse-allocations/{allocation_id}/release", {}, headers)

    # ---- Test-driving clock ------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- Generic helpers for raw-path / custom-header tests ----------------
    def get_raw(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
