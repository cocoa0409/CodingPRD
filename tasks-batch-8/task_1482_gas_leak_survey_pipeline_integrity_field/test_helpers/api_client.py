"""API client: one method per endpoint defined in the PRD (§4).

All paths are mounted under the /integrity-program prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/integrity-program"


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- PipeSegment ---
    def create_pipe_segment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pipe-segments", payload, headers)

    def list_pipe_segments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pipe-segments", headers=headers, params=params)

    def get_pipe_segment(self, segment_id, headers):
        return self._request("GET", f"{PREFIX}/pipe-segments/{segment_id}", headers=headers)

    def list_segment_leaks(self, segment_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/pipe-segments/{segment_id}/leaks", headers=headers, params=params)

    def list_segment_cp_readings(self, segment_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/pipe-segments/{segment_id}/cp-readings", headers=headers, params=params)

    def get_compliance_summary(self, segment_id, headers):
        return self._request("GET", f"{PREFIX}/pipe-segments/{segment_id}/compliance-summary", headers=headers)

    def get_next_survey_due(self, segment_id, headers):
        return self._request("GET", f"{PREFIX}/pipe-segments/{segment_id}/next-survey-due", headers=headers)

    def out_of_service_segment(self, segment_id, headers):
        return self._request("POST", f"{PREFIX}/pipe-segments/{segment_id}/out-of-service", {}, headers)

    def return_to_service_segment(self, segment_id, headers):
        return self._request("POST", f"{PREFIX}/pipe-segments/{segment_id}/return-to-service", {}, headers)

    def abandon_segment(self, segment_id, headers):
        return self._request("POST", f"{PREFIX}/pipe-segments/{segment_id}/abandon", {}, headers)

    # --- Instrument & Calibration ---
    def create_instrument(self, payload, headers):
        return self._request("POST", f"{PREFIX}/instruments", payload, headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"{PREFIX}/instruments/{instrument_id}", headers=headers)

    def list_calibrations(self, instrument_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/instruments/{instrument_id}/calibrations", headers=headers, params=params)

    def calibrate_instrument(self, instrument_id, payload, headers):
        return self._request("POST", f"{PREFIX}/instruments/{instrument_id}/calibrate", payload, headers)

    def retire_instrument(self, instrument_id, headers):
        return self._request("POST", f"{PREFIX}/instruments/{instrument_id}/retire", {}, headers)

    # --- Personnel ---
    def create_field_technician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/field-technicians", payload, headers)

    def list_field_technicians(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/field-technicians", headers=headers, params=params)

    def get_field_technician(self, tech_id, headers):
        return self._request("GET", f"{PREFIX}/field-technicians/{tech_id}", headers=headers)

    def create_compliance_officer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-officers", payload, headers)

    def list_compliance_officers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/compliance-officers", headers=headers, params=params)

    def get_compliance_officer(self, officer_id, headers):
        return self._request("GET", f"{PREFIX}/compliance-officers/{officer_id}", headers=headers)

    def create_calibration_tech(self, payload, headers):
        return self._request("POST", f"{PREFIX}/calibration-techs", payload, headers)

    def list_calibration_techs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/calibration-techs", headers=headers, params=params)

    def create_dispatch_coordinator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dispatch-coordinators", payload, headers)

    def list_dispatch_coordinators(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dispatch-coordinators", headers=headers, params=params)

    def create_integrity_analyst(self, payload, headers):
        return self._request("POST", f"{PREFIX}/integrity-analysts", payload, headers)

    def list_integrity_analysts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/integrity-analysts", headers=headers, params=params)

    # --- RepairCrew ---
    def create_repair_crew(self, payload, headers):
        return self._request("POST", f"{PREFIX}/repair-crews", payload, headers)

    def list_repair_crews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/repair-crews", headers=headers, params=params)

    def get_repair_crew(self, crew_id, headers):
        return self._request("GET", f"{PREFIX}/repair-crews/{crew_id}", headers=headers)

    def list_crew_repair_orders(self, crew_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/repair-crews/{crew_id}/repair-orders", headers=headers, params=params)

    def set_crew_off_duty(self, crew_id, headers):
        return self._request("POST", f"{PREFIX}/repair-crews/{crew_id}/set-off-duty", {}, headers)

    def set_crew_on_duty(self, crew_id, headers):
        return self._request("POST", f"{PREFIX}/repair-crews/{crew_id}/set-on-duty", {}, headers)

    # --- SurveyRoute & RouteSegmentAssignment ---
    def create_survey_route(self, payload, headers):
        return self._request("POST", f"{PREFIX}/survey-routes", payload, headers)

    def list_survey_routes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/survey-routes", headers=headers, params=params)

    def get_survey_route(self, route_id, headers):
        return self._request("GET", f"{PREFIX}/survey-routes/{route_id}", headers=headers)

    def list_route_segment_assignments(self, route_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/survey-routes/{route_id}/route-segment-assignments", headers=headers, params=params)

    def add_route_segment_assignment(self, route_id, payload, headers):
        return self._request("POST", f"{PREFIX}/survey-routes/{route_id}/route-segment-assignments", payload, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"{PREFIX}/survey-routes/{route_id}/dispatch", {}, headers)

    def start_route(self, route_id, headers):
        return self._request("POST", f"{PREFIX}/survey-routes/{route_id}/start", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"{PREFIX}/survey-routes/{route_id}/complete", {}, headers)

    def abort_route(self, route_id, headers):
        return self._request("POST", f"{PREFIX}/survey-routes/{route_id}/abort", {}, headers)

    # --- SurveyRun ---
    def create_survey_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/survey-runs", payload, headers)

    def list_survey_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/survey-runs", headers=headers, params=params)

    def get_survey_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/survey-runs/{run_id}", headers=headers)

    def submit_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/survey-runs/{run_id}/submit", {}, headers)

    def accept_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/survey-runs/{run_id}/accept", {}, headers)

    def reject_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/survey-runs/{run_id}/reject", {}, headers)

    # --- Leak ---
    def create_leak(self, payload, headers):
        return self._request("POST", f"{PREFIX}/leaks", payload, headers)

    def list_leaks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/leaks", headers=headers, params=params)

    def get_leak(self, leak_id, headers):
        return self._request("GET", f"{PREFIX}/leaks/{leak_id}", headers=headers)

    def list_regrade_events(self, leak_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/leaks/{leak_id}/regrade-events", headers=headers, params=params)

    def list_leak_repair_orders(self, leak_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/leaks/{leak_id}/repair-orders", headers=headers, params=params)

    def regrade_leak(self, leak_id, payload, headers):
        return self._request("POST", f"{PREFIX}/leaks/{leak_id}/regrade", payload, headers)

    def schedule_repair(self, leak_id, payload, headers):
        return self._request("POST", f"{PREFIX}/leaks/{leak_id}/schedule-repair", payload, headers)

    def verify_clear_leak(self, leak_id, headers):
        return self._request("POST", f"{PREFIX}/leaks/{leak_id}/verify-clear", {}, headers)

    # --- RepairOrder & ExcavationPermit ---
    def list_repair_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/repair-orders", headers=headers, params=params)

    def get_repair_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/repair-orders/{order_id}", headers=headers)

    def dispatch_repair_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/repair-orders/{order_id}/dispatch", payload, headers)

    def arrive_on_site(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/repair-orders/{order_id}/arrive-on-site", {}, headers)

    def mark_work_complete(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/repair-orders/{order_id}/mark-work-complete", {}, headers)

    def cancel_repair_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/repair-orders/{order_id}/cancel", {}, headers)

    def apply_permit(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/repair-orders/{order_id}/apply-permit", payload, headers)

    def list_excavation_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/excavation-permits", headers=headers, params=params)

    def get_excavation_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/excavation-permits/{permit_id}", headers=headers)

    def grant_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/excavation-permits/{permit_id}/grant", {}, headers)

    def deny_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/excavation-permits/{permit_id}/deny", {}, headers)

    # --- CathodicProtectionReading ---
    def create_cp_reading(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cp-readings", payload, headers)

    def list_cp_readings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cp-readings", headers=headers, params=params)

    def get_cp_reading(self, reading_id, headers):
        return self._request("GET", f"{PREFIX}/cp-readings/{reading_id}", headers=headers)

    def acknowledge_cp_reading(self, reading_id, headers):
        return self._request("POST", f"{PREFIX}/cp-readings/{reading_id}/acknowledge", {}, headers)

    def resolve_cp_reading(self, reading_id, headers):
        return self._request("POST", f"{PREFIX}/cp-readings/{reading_id}/resolve", {}, headers)

    # --- RiskModelSnapshot ---
    def create_risk_model_snapshot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/risk-model-snapshots", payload, headers)

    def list_risk_model_snapshots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/risk-model-snapshots", headers=headers, params=params)

    def get_risk_model_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"{PREFIX}/risk-model-snapshots/{snapshot_id}", headers=headers)

    # --- ComplianceReport ---
    def create_compliance_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-reports", payload, headers)

    def list_compliance_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/compliance-reports", headers=headers, params=params)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/compliance-reports/{report_id}", headers=headers)

    def bind_snapshots(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-reports/{report_id}/bind-snapshots", payload, headers)

    def submit_for_review(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-reports/{report_id}/submit-for-review", payload, headers)

    def submit_to_regulator(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/compliance-reports/{report_id}/submit-to-regulator", {}, headers)

    def record_acceptance(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/compliance-reports/{report_id}/record-acceptance", {}, headers)

    def record_rejection(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/compliance-reports/{report_id}/record-rejection", {}, headers)

    def request_resubmission(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/compliance-reports/{report_id}/request-resubmission", {}, headers)

    def reopen_draft(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/compliance-reports/{report_id}/reopen-draft", {}, headers)


api_client = ApiClient()
