"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- FlushingProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", headers=headers)

    def sweep_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/sweep", headers=headers)

    # --- PressureZone ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    # --- PrivateOwner ---
    def create_private_owner(self, payload, headers):
        return self._request("POST", "/private-owners", payload, headers)

    # --- Hydrant ---
    def create_hydrant(self, payload, headers):
        return self._request("POST", "/hydrants", payload, headers)

    def list_hydrants(self, headers, params=None):
        return self._request("GET", "/hydrants", headers=headers, params=params)

    def get_hydrant(self, hydrant_id, headers):
        return self._request("GET", f"/hydrants/{hydrant_id}", headers=headers)

    def decommission_hydrant(self, hydrant_id, headers):
        return self._request("POST", f"/hydrants/{hydrant_id}/decommission", headers=headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/record", payload, headers)

    def verify_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/verify", payload, headers)

    # --- FlowTest ---
    def create_flow_test(self, payload, headers):
        return self._request("POST", "/flow-tests", payload, headers)

    def list_flow_tests(self, headers, params=None):
        return self._request("GET", "/flow-tests", headers=headers, params=params)

    def get_flow_test(self, flow_test_id, headers):
        return self._request("GET", f"/flow-tests/{flow_test_id}", headers=headers)

    def submit_flow_test_results(self, flow_test_id, payload, headers):
        return self._request("POST", f"/flow-tests/{flow_test_id}/results", payload, headers)

    def review_flow_test(self, flow_test_id, payload, headers):
        return self._request("POST", f"/flow-tests/{flow_test_id}/review", payload, headers)

    def reschedule_flow_test(self, flow_test_id, payload, headers):
        return self._request("POST", f"/flow-tests/{flow_test_id}/reschedule", payload, headers)

    def cancel_flow_test(self, flow_test_id, headers):
        return self._request("POST", f"/flow-tests/{flow_test_id}/cancel", headers=headers)

    # --- FlushSequence ---
    def create_flush_sequence(self, payload, headers):
        return self._request("POST", "/flush-sequences", payload, headers)

    def list_flush_sequences(self, headers, params=None):
        return self._request("GET", "/flush-sequences", headers=headers, params=params)

    def get_flush_sequence(self, sequence_id, headers):
        return self._request("GET", f"/flush-sequences/{sequence_id}", headers=headers)

    def start_flush_sequence(self, sequence_id, payload, headers):
        return self._request("POST", f"/flush-sequences/{sequence_id}/start", payload, headers)

    def execute_flush_step(self, sequence_id, payload, headers):
        return self._request("POST", f"/flush-sequences/{sequence_id}/execute-step", payload, headers)

    def complete_flush_sequence(self, sequence_id, payload, headers):
        return self._request("POST", f"/flush-sequences/{sequence_id}/complete", payload, headers)

    def abort_flush_sequence(self, sequence_id, headers):
        return self._request("POST", f"/flush-sequences/{sequence_id}/abort", headers=headers)

    # --- WaterQualityComplaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def link_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/link", payload, headers)

    def close_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/close", payload, headers)

    # --- HydrantOutage ---
    def create_outage(self, payload, headers):
        return self._request("POST", "/outages", payload, headers)

    def list_outages(self, headers, params=None):
        return self._request("GET", "/outages", headers=headers, params=params)

    def get_outage(self, outage_id, headers):
        return self._request("GET", f"/outages/{outage_id}", headers=headers)

    def acknowledge_outage_notification(self, outage_id, headers):
        return self._request("POST", f"/outages/{outage_id}/acknowledge-notification", headers=headers)

    def close_outage(self, outage_id, headers):
        return self._request("POST", f"/outages/{outage_id}/close", headers=headers)

    # --- RepairWorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def add_work_order_part_line(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/part-lines", payload, headers)

    def submit_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/submit", headers=headers)

    def approve_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/approve", payload, headers)

    def reject_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/reject", payload, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", headers=headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", headers=headers)

    # --- Part ---
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def restock_part(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/restock", payload, headers)

    # --- ISOSnapshot ---
    def create_iso_snapshot(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/iso-snapshots", payload, headers)

    def list_iso_snapshots(self, headers, params=None):
        return self._request("GET", "/iso-snapshots", headers=headers, params=params)

    def get_iso_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/iso-snapshots/{snapshot_id}", headers=headers)

    def publish_iso_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/iso-snapshots/{snapshot_id}/publish", headers=headers)

    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
