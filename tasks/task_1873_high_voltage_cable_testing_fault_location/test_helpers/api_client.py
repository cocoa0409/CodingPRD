"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cable-diagnostics"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- CableCircuit ---
    def create_circuit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/circuits", payload, headers)

    def get_circuit(self, circuit_id, headers):
        return self._request("GET", f"{PREFIX}/circuits/{circuit_id}", headers=headers)

    def list_circuits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/circuits", headers=headers, params=params)

    def list_circuit_outage_windows(self, circuit_id, headers):
        return self._request("GET", f"{PREFIX}/circuits/{circuit_id}/outage-windows", headers=headers)

    def list_circuit_test_jobs(self, circuit_id, headers):
        return self._request("GET", f"{PREFIX}/circuits/{circuit_id}/test-jobs", headers=headers)

    def list_circuit_health_assessments(self, circuit_id, headers):
        return self._request("GET", f"{PREFIX}/circuits/{circuit_id}/health-assessments", headers=headers)

    def get_circuit_trend(self, circuit_id, headers):
        return self._request("GET", f"{PREFIX}/circuits/{circuit_id}/trend", headers=headers)

    # --- OutageWindow ---
    def create_outage_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/outage-windows", payload, headers)

    def get_outage_window(self, window_id, headers):
        return self._request("GET", f"{PREFIX}/outage-windows/{window_id}", headers=headers)

    def list_outage_windows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/outage-windows", headers=headers, params=params)

    def list_window_test_jobs(self, window_id, headers):
        return self._request("GET", f"{PREFIX}/outage-windows/{window_id}/test-jobs", headers=headers)

    def approve_window(self, window_id, headers):
        return self._request("POST", f"{PREFIX}/outage-windows/{window_id}/approve", headers=headers)

    def activate_window(self, window_id, headers):
        return self._request("POST", f"{PREFIX}/outage-windows/{window_id}/activate", headers=headers)

    def close_window(self, window_id, payload, headers):
        return self._request("POST", f"{PREFIX}/outage-windows/{window_id}/close", payload, headers)

    def cancel_window(self, window_id, headers):
        return self._request("POST", f"{PREFIX}/outage-windows/{window_id}/cancel", headers=headers)

    # --- TestJob ---
    def create_test_job(self, payload, headers):
        return self._request("POST", f"{PREFIX}/test-jobs", payload, headers)

    def get_test_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/test-jobs/{job_id}", headers=headers)

    def list_test_jobs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/test-jobs", headers=headers, params=params)

    def plan_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/test-jobs/{job_id}/plan", headers=headers)

    def reschedule_job(self, job_id, payload, headers):
        return self._request("POST", f"{PREFIX}/test-jobs/{job_id}/reschedule", payload, headers)

    def start_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/test-jobs/{job_id}/start", headers=headers)

    def suspend_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/test-jobs/{job_id}/suspend", headers=headers)

    def resume_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/test-jobs/{job_id}/resume", headers=headers)

    def complete_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/test-jobs/{job_id}/complete", headers=headers)

    def abort_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/test-jobs/{job_id}/abort", headers=headers)

    def get_job_invoice(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/test-jobs/{job_id}/invoice", headers=headers)

    def list_job_permits(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/test-jobs/{job_id}/isolation-permits", headers=headers)

    def list_job_test_series(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/test-jobs/{job_id}/test-series", headers=headers)

    def list_job_faults(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/test-jobs/{job_id}/faults", headers=headers)

    def list_job_assignments(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/test-jobs/{job_id}/equipment-assignments", headers=headers)

    # --- IsolationPermit ---
    def create_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/isolation-permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/isolation-permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/isolation-permits", headers=headers, params=params)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/isolation-permits/{permit_id}/issue", headers=headers)

    def verify_grounding(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/isolation-permits/{permit_id}/verify-grounding", headers=headers)

    def release_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/isolation-permits/{permit_id}/release", headers=headers)

    # --- TestSeries / TestReading ---
    def create_test_series(self, payload, headers):
        return self._request("POST", f"{PREFIX}/test-series", payload, headers)

    def get_test_series(self, series_id, headers):
        return self._request("GET", f"{PREFIX}/test-series/{series_id}", headers=headers)

    def list_test_series(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/test-series", headers=headers, params=params)

    def energize_series(self, series_id, headers):
        return self._request("POST", f"{PREFIX}/test-series/{series_id}/energize", headers=headers)

    def add_reading(self, series_id, payload, headers):
        return self._request("POST", f"{PREFIX}/test-series/{series_id}/readings", payload, headers)

    def list_readings(self, series_id, headers):
        return self._request("GET", f"{PREFIX}/test-series/{series_id}/readings", headers=headers)

    def list_series_faults(self, series_id, headers):
        return self._request("GET", f"{PREFIX}/test-series/{series_id}/faults", headers=headers)

    def evaluate_series(self, series_id, headers):
        return self._request("POST", f"{PREFIX}/test-series/{series_id}/evaluate", headers=headers)

    def accept_series(self, series_id, headers):
        return self._request("POST", f"{PREFIX}/test-series/{series_id}/accept", headers=headers)

    def invalidate_series(self, series_id, payload, headers):
        return self._request("POST", f"{PREFIX}/test-series/{series_id}/invalidate", payload, headers)

    # --- FaultRecord ---
    def create_fault(self, payload, headers):
        return self._request("POST", f"{PREFIX}/faults", payload, headers)

    def get_fault(self, fault_id, headers):
        return self._request("GET", f"{PREFIX}/faults/{fault_id}", headers=headers)

    def list_faults(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/faults", headers=headers, params=params)

    def pinpoint_fault(self, fault_id, payload, headers):
        return self._request("POST", f"{PREFIX}/faults/{fault_id}/pinpoint", payload, headers)

    def reopen_fault(self, fault_id, headers):
        return self._request("POST", f"{PREFIX}/faults/{fault_id}/reopen", headers=headers)

    def list_fault_test_series(self, fault_id, headers):
        return self._request("GET", f"{PREFIX}/faults/{fault_id}/test-series", headers=headers)

    def list_fault_excavations(self, fault_id, headers):
        return self._request("GET", f"{PREFIX}/faults/{fault_id}/excavation-orders", headers=headers)

    def list_fault_splices(self, fault_id, headers):
        return self._request("GET", f"{PREFIX}/faults/{fault_id}/repair-splices", headers=headers)

    # --- ExcavationOrder ---
    def create_excavation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/excavation-orders", payload, headers)

    def get_excavation(self, excavation_id, headers):
        return self._request("GET", f"{PREFIX}/excavation-orders/{excavation_id}", headers=headers)

    def list_excavations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/excavation-orders", headers=headers, params=params)

    def list_excavation_splices(self, excavation_id, headers):
        return self._request("GET", f"{PREFIX}/excavation-orders/{excavation_id}/repair-splices", headers=headers)

    def permit_excavation(self, excavation_id, headers):
        return self._request("POST", f"{PREFIX}/excavation-orders/{excavation_id}/permit", headers=headers)

    def start_excavation(self, excavation_id, headers):
        return self._request("POST", f"{PREFIX}/excavation-orders/{excavation_id}/start", headers=headers)

    def backfill_excavation(self, excavation_id, headers):
        return self._request("POST", f"{PREFIX}/excavation-orders/{excavation_id}/backfill", headers=headers)

    def cancel_excavation(self, excavation_id, headers):
        return self._request("POST", f"{PREFIX}/excavation-orders/{excavation_id}/cancel", headers=headers)

    # --- RepairSplice ---
    def create_splice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/repair-splices", payload, headers)

    def get_splice(self, splice_id, headers):
        return self._request("GET", f"{PREFIX}/repair-splices/{splice_id}", headers=headers)

    def list_splices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/repair-splices", headers=headers, params=params)

    def start_splice(self, splice_id, headers):
        return self._request("POST", f"{PREFIX}/repair-splices/{splice_id}/start", headers=headers)

    def cure_splice(self, splice_id, headers):
        return self._request("POST", f"{PREFIX}/repair-splices/{splice_id}/cure", headers=headers)

    def finish_curing(self, splice_id, headers):
        return self._request("POST", f"{PREFIX}/repair-splices/{splice_id}/finish-curing", headers=headers)

    def accept_splice(self, splice_id, headers):
        return self._request("POST", f"{PREFIX}/repair-splices/{splice_id}/accept", headers=headers)

    def reject_splice(self, splice_id, headers):
        return self._request("POST", f"{PREFIX}/repair-splices/{splice_id}/reject", headers=headers)

    # --- MobileUnit ---
    def create_mobile_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mobile-units", payload, headers)

    def get_mobile_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/mobile-units/{unit_id}", headers=headers)

    def list_mobile_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/mobile-units", headers=headers, params=params)

    def unit_maintenance(self, unit_id, headers):
        return self._request("POST", f"{PREFIX}/mobile-units/{unit_id}/maintenance", headers=headers)

    def unit_return_to_service(self, unit_id, headers):
        return self._request("POST", f"{PREFIX}/mobile-units/{unit_id}/return-to-service", headers=headers)

    def list_unit_assignments(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/mobile-units/{unit_id}/equipment-assignments", headers=headers)

    # --- EquipmentAssignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/equipment-assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/equipment-assignments", headers=headers, params=params)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/equipment-assignments/{assignment_id}/confirm", headers=headers)

    def activate_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/equipment-assignments/{assignment_id}/activate", headers=headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/equipment-assignments/{assignment_id}/release", headers=headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/equipment-assignments/{assignment_id}/cancel", headers=headers)

    # --- HealthAssessment ---
    def create_health_assessment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/health-assessments", payload, headers)

    def get_health_assessment(self, assessment_id, headers):
        return self._request("GET", f"{PREFIX}/health-assessments/{assessment_id}", headers=headers)

    def list_health_assessments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/health-assessments", headers=headers, params=params)

    def review_assessment(self, assessment_id, headers):
        return self._request("POST", f"{PREFIX}/health-assessments/{assessment_id}/review", headers=headers)

    def adopt_assessment(self, assessment_id, headers):
        return self._request("POST", f"{PREFIX}/health-assessments/{assessment_id}/adopt", headers=headers)


api_client = ApiClient()
