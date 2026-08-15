"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Plant ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    # --- HACCPPlan ---
    def create_haccp_plan(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/haccp-plans", payload, headers)

    def get_haccp_plan(self, plan_id, headers):
        return self._request("GET", f"/haccp-plans/{plan_id}", headers=headers)

    def list_haccp_plans(self, headers, params=None):
        return self._request("GET", "/haccp-plans", headers=headers, params=params)

    def submit_haccp_plan(self, plan_id, headers):
        return self._request("POST", f"/haccp-plans/{plan_id}/submit", {}, headers)

    def approve_haccp_plan(self, plan_id, headers):
        return self._request("POST", f"/haccp-plans/{plan_id}/approve", {}, headers)

    def reject_haccp_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/haccp-plans/{plan_id}/reject", payload, headers)

    def activate_haccp_plan(self, plan_id, headers):
        return self._request("POST", f"/haccp-plans/{plan_id}/activate", {}, headers)

    # --- CriticalControlPoint ---
    def create_ccp(self, plan_id, payload, headers):
        return self._request("POST", f"/haccp-plans/{plan_id}/ccps", payload, headers)

    def get_ccp(self, ccp_id, headers):
        return self._request("GET", f"/ccps/{ccp_id}", headers=headers)

    def list_ccps(self, headers, params=None):
        return self._request("GET", "/ccps", headers=headers, params=params)

    # --- CCPObservation ---
    def record_observation(self, ccp_id, payload, headers):
        return self._request("POST", f"/ccps/{ccp_id}/observations", payload, headers)

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"/observations/{observation_id}", headers=headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", "/observations", headers=headers, params=params)

    # --- Deviation ---
    def get_deviation(self, deviation_id, headers):
        return self._request("GET", f"/deviations/{deviation_id}", headers=headers)

    def list_deviations(self, headers, params=None):
        return self._request("GET", "/deviations", headers=headers, params=params)

    def log_corrective_action(self, deviation_id, payload, headers):
        return self._request(
            "POST", f"/deviations/{deviation_id}/log-corrective-action", payload, headers
        )

    def verify_deviation(self, deviation_id, headers):
        return self._request("POST", f"/deviations/{deviation_id}/verify", {}, headers)

    # --- InspectorShift ---
    def create_inspector_shift(self, plant_id, payload, headers):
        return self._request(
            "POST", f"/plants/{plant_id}/inspector-shifts", payload, headers
        )

    def get_inspector_shift(self, shift_id, headers):
        return self._request("GET", f"/inspector-shifts/{shift_id}", headers=headers)

    def list_inspector_shifts(self, headers, params=None):
        return self._request("GET", "/inspector-shifts", headers=headers, params=params)

    def check_in_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/inspector-shifts/{shift_id}/check-in", {}, headers
        )

    def check_out_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/inspector-shifts/{shift_id}/check-out", {}, headers
        )

    # --- ProductionDay ---
    def create_production_day(self, plant_id, payload, headers):
        return self._request(
            "POST", f"/plants/{plant_id}/production-days", payload, headers
        )

    def get_production_day(self, day_id, headers):
        return self._request("GET", f"/production-days/{day_id}", headers=headers)

    def list_production_days(self, headers, params=None):
        return self._request("GET", "/production-days", headers=headers, params=params)

    def open_production_day(self, day_id, headers):
        return self._request("POST", f"/production-days/{day_id}/open", {}, headers)

    def suspend_production_day(self, day_id, headers):
        return self._request("POST", f"/production-days/{day_id}/suspend", {}, headers)

    def close_production_day(self, day_id, headers):
        return self._request("POST", f"/production-days/{day_id}/close", {}, headers)

    # --- CarcassLot ---
    def receive_lot(self, day_id, payload, headers):
        return self._request("POST", f"/production-days/{day_id}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def pass_ante_mortem(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/pass-ante-mortem", {}, headers)

    def harvest_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/harvest", payload, headers)

    def chill_complete_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/chill-complete", payload, headers)

    def fabricate_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/fabricate", {}, headers)

    def complete_fabrication(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/complete-fabrication", payload, headers
        )

    def release_hold(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/release-hold", payload, headers)

    # --- CutRecord ---
    def create_cut_record(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/cut-records", payload, headers)

    def get_cut_record(self, cut_record_id, headers):
        return self._request("GET", f"/cut-records/{cut_record_id}", headers=headers)

    def list_cut_records(self, headers, params=None):
        return self._request("GET", "/cut-records", headers=headers, params=params)

    # --- PathogenSample ---
    def collect_pathogen_sample(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/pathogen-samples", payload, headers
        )

    def get_pathogen_sample(self, sample_id, headers):
        return self._request("GET", f"/pathogen-samples/{sample_id}", headers=headers)

    def list_pathogen_samples(self, headers, params=None):
        return self._request("GET", "/pathogen-samples", headers=headers, params=params)

    def report_sample_result(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/pathogen-samples/{sample_id}/report-result", payload, headers
        )

    # --- LabelApproval ---
    def create_label_approval(self, plant_id, payload, headers):
        return self._request(
            "POST", f"/plants/{plant_id}/label-approvals", payload, headers
        )

    def get_label_approval(self, label_id, headers):
        return self._request("GET", f"/label-approvals/{label_id}", headers=headers)

    def list_label_approvals(self, headers, params=None):
        return self._request("GET", "/label-approvals", headers=headers, params=params)

    def submit_label_approval(self, label_id, headers):
        return self._request("POST", f"/label-approvals/{label_id}/submit", {}, headers)

    def approve_label_approval(self, label_id, headers):
        return self._request("POST", f"/label-approvals/{label_id}/approve", {}, headers)

    def reject_label_approval(self, label_id, payload, headers):
        return self._request(
            "POST", f"/label-approvals/{label_id}/reject", payload, headers
        )

    # --- FinishedLot ---
    def create_finished_lot(self, day_id, payload, headers):
        return self._request(
            "POST", f"/production-days/{day_id}/finished-lots", payload, headers
        )

    def get_finished_lot(self, finished_lot_id, headers):
        return self._request("GET", f"/finished-lots/{finished_lot_id}", headers=headers)

    def list_finished_lots(self, headers, params=None):
        return self._request("GET", "/finished-lots", headers=headers, params=params)

    def ship_finished_lot(self, finished_lot_id, headers):
        return self._request("POST", f"/finished-lots/{finished_lot_id}/ship", {}, headers)

    def log_temperature(self, finished_lot_id, payload, headers):
        return self._request(
            "POST", f"/finished-lots/{finished_lot_id}/log-temperature", payload, headers
        )

    # --- HumaneHandlingAudit ---
    def create_humane_audit(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/humane-audits", payload, headers)

    def get_humane_audit(self, audit_id, headers):
        return self._request("GET", f"/humane-audits/{audit_id}", headers=headers)

    def list_humane_audits(self, headers, params=None):
        return self._request("GET", "/humane-audits", headers=headers, params=params)

    # --- NoncomplianceRecord ---
    def get_noncompliance_record(self, record_id, headers):
        return self._request(
            "GET", f"/noncompliance-records/{record_id}", headers=headers
        )

    def list_noncompliance_records(self, headers, params=None):
        return self._request(
            "GET", "/noncompliance-records", headers=headers, params=params
        )

    def appeal_noncompliance_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/noncompliance-records/{record_id}/appeal", payload, headers
        )

    def resolve_noncompliance_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/noncompliance-records/{record_id}/resolve", payload, headers
        )

    # --- RecallExercise ---
    def create_recall_exercise(self, plant_id, payload, headers):
        return self._request(
            "POST", f"/plants/{plant_id}/recall-exercises", payload, headers
        )

    def get_recall_exercise(self, exercise_id, headers):
        return self._request("GET", f"/recall-exercises/{exercise_id}", headers=headers)

    def list_recall_exercises(self, headers, params=None):
        return self._request("GET", "/recall-exercises", headers=headers, params=params)

    def complete_recall_exercise(self, exercise_id, payload, headers):
        return self._request(
            "POST", f"/recall-exercises/{exercise_id}/complete", payload, headers
        )

    # --- Test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
