"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/observer-program"


class ApiClient(GenericApiClient):
    # --- Fishery ---
    def create_fishery(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fisheries", payload, headers)

    def list_fisheries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fisheries", headers=headers, params=params)

    def get_fishery(self, fishery_id, headers):
        return self._request("GET", f"{PREFIX}/fisheries/{fishery_id}", headers=headers)

    def patch_fishery(self, fishery_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/fisheries/{fishery_id}", payload, headers)

    # --- VesselOperator ---
    def create_vessel_operator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vessel-operators", payload, headers)

    def list_vessel_operators(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/vessel-operators", headers=headers, params=params)

    def get_vessel_operator(self, operator_id, headers):
        return self._request("GET", f"{PREFIX}/vessel-operators/{operator_id}", headers=headers)

    # --- Vessel ---
    def create_vessel(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vessels", payload, headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/vessels", headers=headers, params=params)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"{PREFIX}/vessels/{vessel_id}", headers=headers)

    def patch_vessel(self, vessel_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/vessels/{vessel_id}", payload, headers)

    # --- Observer / Debriefer / EMReviewer registries ---
    def create_observer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/observers", payload, headers)

    def list_observers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/observers", headers=headers, params=params)

    def get_observer(self, observer_id, headers):
        return self._request("GET", f"{PREFIX}/observers/{observer_id}", headers=headers)

    def patch_observer(self, observer_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/observers/{observer_id}", payload, headers)

    def create_debriefer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/debriefers", payload, headers)

    def list_debriefers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/debriefers", headers=headers, params=params)

    def get_debriefer(self, debriefer_id, headers):
        return self._request("GET", f"{PREFIX}/debriefers/{debriefer_id}", headers=headers)

    def patch_debriefer(self, debriefer_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/debriefers/{debriefer_id}", payload, headers)

    def create_em_reviewer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/em-reviewers", payload, headers)

    def list_em_reviewers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/em-reviewers", headers=headers, params=params)

    def get_em_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"{PREFIX}/em-reviewers/{reviewer_id}", headers=headers)

    def patch_em_reviewer(self, reviewer_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/em-reviewers/{reviewer_id}", payload, headers)

    # --- CoveragePlan ---
    def create_coverage_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-plans", payload, headers)

    def list_coverage_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coverage-plans", headers=headers, params=params)

    def get_coverage_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/coverage-plans/{plan_id}", headers=headers)

    def publish_coverage_plan(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-plans/{plan_id}/publish", payload or {}, headers)

    def close_coverage_plan(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-plans/{plan_id}/close", payload, headers)

    # --- SelectionRun / SelectionNotice ---
    def create_selection_run(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-plans/{plan_id}/selection-runs", payload, headers)

    def list_selection_runs(self, plan_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/coverage-plans/{plan_id}/selection-runs", headers=headers, params=params)

    def get_selection_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/selection-runs/{run_id}", headers=headers)

    def list_selection_notices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/selection-notices", headers=headers, params=params)

    def get_selection_notice(self, notice_id, headers):
        return self._request("GET", f"{PREFIX}/selection-notices/{notice_id}", headers=headers)

    def accept_selection_notice(self, notice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/selection-notices/{notice_id}/accept", payload or {}, headers)

    def decline_selection_notice(self, notice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/selection-notices/{notice_id}/decline", payload or {}, headers)

    # --- Deployment ---
    def create_deployment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments", payload, headers)

    def list_deployments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/deployments", headers=headers, params=params)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"{PREFIX}/deployments/{deployment_id}", headers=headers)

    def reschedule_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/reschedule", payload, headers)

    def cancel_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/cancel", payload or {}, headers)

    def board_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/board", payload or {}, headers)

    def return_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/return", payload, headers)

    def submit_deployment_data(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/submit-data", payload or {}, headers)

    def assign_debriefer(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/assign-debriefer", payload, headers)

    def validate_data(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/validate-data", payload or {}, headers)

    def reject_data(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/reject-data", payload, headers)

    def close_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/close", payload or {}, headers)

    # --- SafetyInspection ---
    def create_safety_inspection(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/safety-inspections", payload, headers)

    def list_safety_inspections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/safety-inspections", headers=headers, params=params)

    def get_safety_inspection(self, inspection_id, headers):
        return self._request("GET", f"{PREFIX}/safety-inspections/{inspection_id}", headers=headers)

    # --- HaulSample ---
    def create_haul_sample(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/haul-samples", payload, headers)

    def list_haul_samples(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/haul-samples", headers=headers, params=params)

    def get_haul_sample(self, sample_id, headers):
        return self._request("GET", f"{PREFIX}/haul-samples/{sample_id}", headers=headers)

    def verify_haul_sample(self, sample_id, payload, headers):
        return self._request("POST", f"{PREFIX}/haul-samples/{sample_id}/verify", payload or {}, headers)

    def flag_haul_sample(self, sample_id, payload, headers):
        return self._request("POST", f"{PREFIX}/haul-samples/{sample_id}/flag", payload, headers)

    def discard_haul_sample(self, sample_id, payload, headers):
        return self._request("POST", f"{PREFIX}/haul-samples/{sample_id}/discard", payload, headers)

    # --- HarassmentReport ---
    def create_harassment_report(self, deployment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deployments/{deployment_id}/harassment-reports", payload, headers)

    def list_harassment_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/harassment-reports", headers=headers, params=params)

    def get_harassment_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/harassment-reports/{report_id}", headers=headers)

    def start_harassment_review(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/harassment-reports/{report_id}/start-review", payload or {}, headers)

    def substantiate_harassment_report(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/harassment-reports/{report_id}/substantiate", payload, headers)

    def dismiss_harassment_report(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/harassment-reports/{report_id}/dismiss", payload, headers)

    def appeal_harassment_report(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/harassment-reports/{report_id}/appeal", payload or {}, headers)

    def resolve_harassment_report(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/harassment-reports/{report_id}/resolve", payload, headers)

    # --- EMEnrollment ---
    def create_em_enrollment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/em-enrollments", payload, headers)

    def list_em_enrollments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/em-enrollments", headers=headers, params=params)

    def get_em_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{PREFIX}/em-enrollments/{enrollment_id}", headers=headers)

    def approve_em_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-enrollments/{enrollment_id}/approve", payload or {}, headers)

    def reject_em_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-enrollments/{enrollment_id}/reject", payload, headers)

    def activate_em_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-enrollments/{enrollment_id}/activate", payload or {}, headers)

    def suspend_em_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-enrollments/{enrollment_id}/suspend", payload or {}, headers)

    def terminate_em_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-enrollments/{enrollment_id}/terminate", payload or {}, headers)

    # --- EMTrip ---
    def create_em_trip(self, payload, headers):
        return self._request("POST", f"{PREFIX}/em-trips", payload, headers)

    def list_em_trips(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/em-trips", headers=headers, params=params)

    def get_em_trip(self, trip_id, headers):
        return self._request("GET", f"{PREFIX}/em-trips/{trip_id}", headers=headers)

    def submit_footage(self, trip_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-trips/{trip_id}/submit-footage", payload, headers)

    def assign_reviewer(self, trip_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-trips/{trip_id}/assign-reviewer", payload, headers)

    def record_review(self, trip_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-trips/{trip_id}/record-review", payload, headers)

    def accept_em_trip(self, trip_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-trips/{trip_id}/accept", payload or {}, headers)

    def reject_em_trip(self, trip_id, payload, headers):
        return self._request("POST", f"{PREFIX}/em-trips/{trip_id}/reject", payload, headers)

    # --- Invoice ---
    def generate_invoices(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-plans/{plan_id}/invoices/generate", payload or {}, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/issue", payload or {}, headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/payments", payload, headers)

    def create_adjustment(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/adjustments", payload, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/dispute", payload, headers)

    def resolve_dispute(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/resolve-dispute", payload or {}, headers)

    def waive_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/waive", payload, headers)

    # --- Ops checkpoint & logical clock ---
    def ops_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ops/run", payload or {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
