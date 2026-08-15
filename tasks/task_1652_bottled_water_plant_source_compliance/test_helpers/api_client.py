"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock / injection (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def inject_bottle_wash_cycles(self, payload, headers):
        return self._request("POST", "/api/_inject/bottle-wash-cycles", payload, headers)

    # --- Plant ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/api/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/api/plants/{plant_id}", headers=headers)

    def run_compliance(self, plant_id, headers):
        return self._request("POST", f"/api/plants/{plant_id}/compliance-runs", headers=headers)

    # --- WaterSourcePermit ---
    def create_permit(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/permits", payload, headers)

    def list_plant_permits(self, plant_id, headers, params=None):
        return self._request("GET", f"/api/plants/{plant_id}/permits", headers=headers, params=params)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/api/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/api/permits/{permit_id}", headers=headers)

    def suspend_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/suspend", headers=headers)

    def reinstate_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/reinstate", headers=headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/close", headers=headers)

    # --- WithdrawalEvent ---
    def create_withdrawal_event(self, permit_id, payload, headers):
        return self._request("POST", f"/api/permits/{permit_id}/withdrawal-events", payload, headers)

    def list_permit_withdrawal_events(self, permit_id, headers, params=None):
        return self._request("GET", f"/api/permits/{permit_id}/withdrawal-events", headers=headers, params=params)

    def list_withdrawal_events(self, headers, params=None):
        return self._request("GET", "/api/withdrawal-events", headers=headers, params=params)

    def get_withdrawal_event(self, event_id, headers):
        return self._request("GET", f"/api/withdrawal-events/{event_id}", headers=headers)

    def void_withdrawal_event(self, event_id, headers):
        return self._request("POST", f"/api/withdrawal-events/{event_id}/void", headers=headers)

    # --- TreatmentRun ---
    def create_treatment_run(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/treatment-runs", payload, headers)

    def get_treatment_run(self, run_id, headers):
        return self._request("GET", f"/api/treatment-runs/{run_id}", headers=headers)

    def list_treatment_runs(self, headers, params=None):
        return self._request("GET", "/api/treatment-runs", headers=headers, params=params)

    def start_treatment_run(self, run_id, headers):
        return self._request("POST", f"/api/treatment-runs/{run_id}/start", headers=headers)

    def record_run_parameters(self, run_id, payload, headers):
        return self._request("POST", f"/api/treatment-runs/{run_id}/record-parameters", payload, headers)

    def validate_treatment_run(self, run_id, headers):
        return self._request("POST", f"/api/treatment-runs/{run_id}/validate", headers=headers)

    def reprocess_treatment_run(self, run_id, headers):
        return self._request("POST", f"/api/treatment-runs/{run_id}/reprocess", headers=headers)

    def cancel_treatment_run(self, run_id, headers):
        return self._request("POST", f"/api/treatment-runs/{run_id}/cancel", headers=headers)

    # --- LabTest ---
    def create_lab_test(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/lab-tests", payload, headers)

    def get_lab_test(self, test_id, headers):
        return self._request("GET", f"/api/lab-tests/{test_id}", headers=headers)

    def list_lab_tests(self, headers, params=None):
        return self._request("GET", "/api/lab-tests", headers=headers, params=params)

    def record_lab_result(self, test_id, payload, headers):
        return self._request("POST", f"/api/lab-tests/{test_id}/record-result", payload, headers)

    # --- BottlingLine / PreformDelivery ---
    def create_bottling_line(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/bottling-lines", payload, headers)

    def get_bottling_line(self, line_id, headers):
        return self._request("GET", f"/api/bottling-lines/{line_id}", headers=headers)

    def list_bottling_lines(self, headers, params=None):
        return self._request("GET", "/api/bottling-lines", headers=headers, params=params)

    def create_preform_delivery(self, line_id, payload, headers):
        return self._request("POST", f"/api/bottling-lines/{line_id}/preform-deliveries", payload, headers)

    def list_line_preform_deliveries(self, line_id, headers, params=None):
        return self._request("GET", f"/api/bottling-lines/{line_id}/preform-deliveries", headers=headers, params=params)

    def list_preform_deliveries(self, headers, params=None):
        return self._request("GET", "/api/preform-deliveries", headers=headers, params=params)

    def get_preform_delivery(self, delivery_id, headers):
        return self._request("GET", f"/api/preform-deliveries/{delivery_id}", headers=headers)

    def qc_verdict_preform_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/api/preform-deliveries/{delivery_id}/qc-verdict", payload, headers)

    # --- ProductionLot ---
    def create_production_lot(self, line_id, payload, headers):
        return self._request("POST", f"/api/bottling-lines/{line_id}/production-lots", payload, headers)

    def get_production_lot(self, lot_id, headers):
        return self._request("GET", f"/api/production-lots/{lot_id}", headers=headers)

    def list_production_lots(self, headers, params=None):
        return self._request("GET", "/api/production-lots", headers=headers, params=params)

    def start_production_lot(self, lot_id, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/start", headers=headers)

    def complete_production_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/complete", payload, headers)

    def release_production_lot(self, lot_id, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/release", headers=headers)

    def reject_production_lot(self, lot_id, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/reject", headers=headers)

    def rework_complete_production_lot(self, lot_id, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/rework-complete", headers=headers)

    def cancel_production_lot(self, lot_id, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/cancel", headers=headers)

    # --- RecallEvent ---
    def create_recall(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/api/recalls/{recall_id}", headers=headers)

    def list_plant_recalls(self, plant_id, headers, params=None):
        return self._request("GET", f"/api/plants/{plant_id}/recalls", headers=headers, params=params)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/api/recalls", headers=headers, params=params)

    def post_recall_recovery(self, recall_id, payload, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/recoveries", payload, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/close", headers=headers)

    # --- WashBatch ---
    def create_wash_batch(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/wash-batches", payload, headers)

    def get_wash_batch(self, batch_id, headers):
        return self._request("GET", f"/api/wash-batches/{batch_id}", headers=headers)

    def list_plant_wash_batches(self, plant_id, headers, params=None):
        return self._request("GET", f"/api/plants/{plant_id}/wash-batches", headers=headers, params=params)

    def list_wash_batches(self, headers, params=None):
        return self._request("GET", "/api/wash-batches", headers=headers, params=params)

    def assign_bottles(self, batch_id, payload, headers):
        return self._request("POST", f"/api/wash-batches/{batch_id}/assign-bottles", payload, headers)

    def start_wash_batch(self, batch_id, headers):
        return self._request("POST", f"/api/wash-batches/{batch_id}/start", headers=headers)

    def complete_wash_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/wash-batches/{batch_id}/complete", payload, headers)

    def cancel_wash_batch(self, batch_id, headers):
        return self._request("POST", f"/api/wash-batches/{batch_id}/cancel", headers=headers)

    # --- ReturnableBottle ---
    def create_bottle(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/bottles", payload, headers)

    def get_bottle(self, bottle_id, headers):
        return self._request("GET", f"/api/bottles/{bottle_id}", headers=headers)

    def list_bottles(self, headers, params=None):
        return self._request("GET", "/api/bottles", headers=headers, params=params)

    def fill_bottle(self, bottle_id, payload, headers):
        return self._request("POST", f"/api/bottles/{bottle_id}/fill", payload, headers)

    def deliver_bottle(self, bottle_id, headers):
        return self._request("POST", f"/api/bottles/{bottle_id}/deliver", headers=headers)

    def return_bottle(self, bottle_id, headers):
        return self._request("POST", f"/api/bottles/{bottle_id}/return", headers=headers)

    def retire_bottle(self, bottle_id, headers):
        return self._request("POST", f"/api/bottles/{bottle_id}/retire", headers=headers)

    # --- CommunityWaterReport ---
    def create_community_report(self, plant_id, payload, headers):
        return self._request("POST", f"/api/plants/{plant_id}/community-reports", payload, headers)

    def get_community_report(self, report_id, headers):
        return self._request("GET", f"/api/community-reports/{report_id}", headers=headers)

    def list_community_reports(self, headers, params=None):
        return self._request("GET", "/api/community-reports", headers=headers, params=params)

    def publish_community_report(self, report_id, headers):
        return self._request("POST", f"/api/community-reports/{report_id}/publish", headers=headers)

    def supersede_community_report(self, report_id, headers):
        return self._request("POST", f"/api/community-reports/{report_id}/supersede", headers=headers)


api_client = ApiClient()
