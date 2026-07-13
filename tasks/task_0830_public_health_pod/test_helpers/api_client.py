"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- HazardPlan ---
    def create_hazard_plan(self, payload, headers):
        return self._request("POST", "/hazard-plans", payload, headers)

    def get_hazard_plan(self, hazard_plan_id, headers):
        return self._request("GET", f"/hazard-plans/{hazard_plan_id}", headers=headers)

    def list_hazard_plans(self, headers, params=None):
        return self._request("GET", "/hazard-plans", headers=headers, params=params)

    def activate_hazard_plan(self, hazard_plan_id, headers):
        return self._request("POST", f"/hazard-plans/{hazard_plan_id}/activate", {}, headers)

    def stand_down_hazard_plan(self, hazard_plan_id, headers):
        return self._request("POST", f"/hazard-plans/{hazard_plan_id}/stand_down", {}, headers)

    # --- POD ---
    def create_pod(self, payload, headers):
        return self._request("POST", "/pods", payload, headers)

    def get_pod(self, pod_id, headers):
        return self._request("GET", f"/pods/{pod_id}", headers=headers)

    def list_pods(self, headers, params=None):
        return self._request("GET", "/pods", headers=headers, params=params)

    def open_pod(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/open", {}, headers)

    def restrict_pod(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/restrict", {}, headers)

    def resume_pod(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/resume", {}, headers)

    def close_pod(self, pod_id, headers):
        return self._request("POST", f"/pods/{pod_id}/close", {}, headers)

    def get_pod_operational_metrics(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/pods/{pod_id}/operational-metrics", headers=headers, params=params
        )

    # --- StaffMember ---
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def verify_staff_credential(self, staff_member_id, headers):
        return self._request(
            "POST", f"/staff-members/{staff_member_id}/verify-credential", {}, headers
        )

    def revoke_staff_credential(self, staff_member_id, headers):
        return self._request(
            "POST", f"/staff-members/{staff_member_id}/revoke-credential", {}, headers
        )

    # --- ShiftAssignment ---
    def create_shift_assignment(self, payload, headers):
        return self._request("POST", "/shift-assignments", payload, headers)

    def get_shift_assignment(self, shift_assignment_id, headers):
        return self._request("GET", f"/shift-assignments/{shift_assignment_id}", headers=headers)

    def list_shift_assignments(self, headers, params=None):
        return self._request("GET", "/shift-assignments", headers=headers, params=params)

    def confirm_shift_assignment(self, shift_assignment_id, headers):
        return self._request(
            "POST", f"/shift-assignments/{shift_assignment_id}/confirm", {}, headers
        )

    def check_in_shift_assignment(self, shift_assignment_id, headers):
        return self._request(
            "POST", f"/shift-assignments/{shift_assignment_id}/check_in", {}, headers
        )

    def check_out_shift_assignment(self, shift_assignment_id, headers):
        return self._request(
            "POST", f"/shift-assignments/{shift_assignment_id}/check_out", {}, headers
        )

    def cancel_shift_assignment(self, shift_assignment_id, headers):
        return self._request(
            "POST", f"/shift-assignments/{shift_assignment_id}/cancel", {}, headers
        )

    # --- Countermeasure ---
    def create_countermeasure(self, payload, headers):
        return self._request("POST", "/countermeasures", payload, headers)

    def list_countermeasures(self, headers, params=None):
        return self._request("GET", "/countermeasures", headers=headers, params=params)

    # --- InventoryLot ---
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/inventory-lots", payload, headers)

    def get_inventory_lot(self, inventory_lot_id, headers):
        return self._request("GET", f"/inventory-lots/{inventory_lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    # --- AllocationRequest ---
    def create_allocation_request(self, payload, headers):
        return self._request("POST", "/allocation-requests", payload, headers)

    def get_allocation_request(self, allocation_request_id, headers):
        return self._request(
            "GET", f"/allocation-requests/{allocation_request_id}", headers=headers
        )

    def list_allocation_requests(self, headers, params=None):
        return self._request("GET", "/allocation-requests", headers=headers, params=params)

    def reserve_allocation_request(self, allocation_request_id, payload, headers):
        return self._request(
            "POST", f"/allocation-requests/{allocation_request_id}/reserve", payload, headers
        )

    def deny_allocation_request(self, allocation_request_id, headers):
        return self._request(
            "POST", f"/allocation-requests/{allocation_request_id}/deny", {}, headers
        )

    def fulfill_allocation_request(self, allocation_request_id, headers):
        return self._request(
            "POST", f"/allocation-requests/{allocation_request_id}/fulfill", {}, headers
        )

    def cancel_allocation_request(self, allocation_request_id, headers):
        return self._request(
            "POST", f"/allocation-requests/{allocation_request_id}/cancel", {}, headers
        )

    # --- DispensingEvent ---
    def create_dispensing_event(self, payload, headers):
        return self._request("POST", "/dispensing-events", payload, headers)

    def get_dispensing_event(self, dispensing_event_id, headers):
        return self._request("GET", f"/dispensing-events/{dispensing_event_id}", headers=headers)

    def list_dispensing_events(self, headers, params=None):
        return self._request("GET", "/dispensing-events", headers=headers, params=params)

    def screen_dispensing_event(self, dispensing_event_id, payload, headers):
        return self._request(
            "POST", f"/dispensing-events/{dispensing_event_id}/screen", payload, headers
        )

    def defer_dispensing_event(self, dispensing_event_id, payload, headers):
        return self._request(
            "POST", f"/dispensing-events/{dispensing_event_id}/defer", payload, headers
        )

    def rescreen_dispensing_event(self, dispensing_event_id, headers):
        return self._request(
            "POST", f"/dispensing-events/{dispensing_event_id}/rescreen", {}, headers
        )

    def refuse_dispensing_event(self, dispensing_event_id, headers):
        return self._request(
            "POST", f"/dispensing-events/{dispensing_event_id}/refuse", {}, headers
        )

    def dispense_dispensing_event(self, dispensing_event_id, payload, headers):
        return self._request(
            "POST", f"/dispensing-events/{dispensing_event_id}/dispense", payload, headers
        )

    # --- Drill ---
    def create_drill(self, payload, headers):
        return self._request("POST", "/drills", payload, headers)

    def get_drill(self, drill_id, headers):
        return self._request("GET", f"/drills/{drill_id}", headers=headers)

    def list_drills(self, headers, params=None):
        return self._request("GET", "/drills", headers=headers, params=params)

    def complete_drill(self, drill_id, payload, headers):
        return self._request("POST", f"/drills/{drill_id}/complete", payload, headers)

    def cancel_drill(self, drill_id, headers):
        return self._request("POST", f"/drills/{drill_id}/cancel", {}, headers)

    def close_drill_corrective_action(self, drill_id, headers):
        return self._request(
            "POST", f"/drills/{drill_id}/close_corrective_action", {}, headers
        )

    # --- SituationReport ---
    def create_situation_report(self, payload, headers):
        return self._request("POST", "/situation-reports", payload, headers)

    def get_situation_report(self, situation_report_id, headers):
        return self._request(
            "GET", f"/situation-reports/{situation_report_id}", headers=headers
        )

    def list_situation_reports(self, headers, params=None):
        return self._request("GET", "/situation-reports", headers=headers, params=params)

    # --- Test-driving clock endpoint ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
