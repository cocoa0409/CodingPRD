"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- StaffingPlan ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/sped-staffing/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/sped-staffing/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/sped-staffing/plans/{plan_id}", headers=headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/sped-staffing/plans/{plan_id}/activate", headers=headers)

    def begin_reconciliation(self, plan_id, headers):
        return self._request("POST", f"/sped-staffing/plans/{plan_id}/begin-reconciliation", headers=headers)

    def reopen_plan(self, plan_id, headers):
        return self._request("POST", f"/sped-staffing/plans/{plan_id}/reopen", headers=headers)

    def close_plan(self, plan_id, headers):
        return self._request("POST", f"/sped-staffing/plans/{plan_id}/close", headers=headers)

    # --- Building ---
    def create_building(self, payload, headers):
        return self._request("POST", "/sped-staffing/buildings", payload, headers)

    def list_buildings(self, headers, params=None):
        return self._request("GET", "/sped-staffing/buildings", headers=headers, params=params)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/sped-staffing/buildings/{building_id}", headers=headers)

    # --- Student ---
    def create_student(self, payload, headers):
        return self._request("POST", "/sped-staffing/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/sped-staffing/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/sped-staffing/students/{student_id}", headers=headers)

    def activate_iep(self, student_id, headers):
        return self._request("POST", f"/sped-staffing/students/{student_id}/activate-iep", headers=headers)

    # --- ServiceChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/sped-staffing/service-change-orders", payload, headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/sped-staffing/service-change-orders", headers=headers, params=params)

    def get_change_order(self, order_id, headers):
        return self._request("GET", f"/sped-staffing/service-change-orders/{order_id}", headers=headers)

    def approve_change_order(self, order_id, headers):
        return self._request("POST", f"/sped-staffing/service-change-orders/{order_id}/approve", headers=headers)

    def return_change_order(self, order_id, headers):
        return self._request("POST", f"/sped-staffing/service-change-orders/{order_id}/return", headers=headers)

    def effectuate_change_order(self, order_id, headers):
        return self._request("POST", f"/sped-staffing/service-change-orders/{order_id}/effectuate", headers=headers)

    def cancel_change_order(self, order_id, headers):
        return self._request("POST", f"/sped-staffing/service-change-orders/{order_id}/cancel", headers=headers)

    # --- Paraprofessional ---
    def create_para(self, payload, headers):
        return self._request("POST", "/sped-staffing/paraprofessionals", payload, headers)

    def list_paras(self, headers, params=None):
        return self._request("GET", "/sped-staffing/paraprofessionals", headers=headers, params=params)

    def get_para(self, para_id, headers):
        return self._request("GET", f"/sped-staffing/paraprofessionals/{para_id}", headers=headers)

    def set_para_status(self, para_id, payload, headers):
        return self._request("POST", f"/sped-staffing/paraprofessionals/{para_id}/set-status", payload, headers)

    def add_qualification(self, para_id, payload, headers):
        return self._request("POST", f"/sped-staffing/paraprofessionals/{para_id}/qualifications", payload, headers)

    def revoke_qualification(self, para_id, payload, headers):
        return self._request("POST", f"/sped-staffing/paraprofessionals/{para_id}/qualifications/revoke", payload, headers)

    # --- Assignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/sped-staffing/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/sped-staffing/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/sped-staffing/assignments/{assignment_id}", headers=headers)

    def verify_qualifications(self, assignment_id, headers):
        return self._request("POST", f"/sped-staffing/assignments/{assignment_id}/verify-qualifications", headers=headers)

    def activate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/sped-staffing/assignments/{assignment_id}/activate", headers=headers)

    def suspend_assignment(self, assignment_id, headers):
        return self._request("POST", f"/sped-staffing/assignments/{assignment_id}/suspend", headers=headers)

    def resume_assignment(self, assignment_id, headers):
        return self._request("POST", f"/sped-staffing/assignments/{assignment_id}/resume", headers=headers)

    def end_assignment(self, assignment_id, headers):
        return self._request("POST", f"/sped-staffing/assignments/{assignment_id}/end", headers=headers)

    # --- CoveragePlan ---
    def create_coverage_plan(self, payload, headers):
        return self._request("POST", "/sped-staffing/coverage-plans", payload, headers)

    def list_coverage_plans(self, headers, params=None):
        return self._request("GET", "/sped-staffing/coverage-plans", headers=headers, params=params)

    def get_coverage_plan(self, coverage_plan_id, headers):
        return self._request("GET", f"/sped-staffing/coverage-plans/{coverage_plan_id}", headers=headers)

    def publish_coverage_plan(self, coverage_plan_id, headers):
        return self._request("POST", f"/sped-staffing/coverage-plans/{coverage_plan_id}/publish", headers=headers)

    def reopen_coverage_plan(self, coverage_plan_id, headers):
        return self._request("POST", f"/sped-staffing/coverage-plans/{coverage_plan_id}/reopen", headers=headers)

    def lock_coverage_plan(self, coverage_plan_id, headers):
        return self._request("POST", f"/sped-staffing/coverage-plans/{coverage_plan_id}/lock", headers=headers)

    def reconcile_coverage_plan(self, coverage_plan_id, headers):
        return self._request("POST", f"/sped-staffing/coverage-plans/{coverage_plan_id}/reconcile", headers=headers)

    # --- AbsenceReport ---
    def create_absence(self, payload, headers):
        return self._request("POST", "/sped-staffing/absence-reports", payload, headers)

    def list_absences(self, headers, params=None):
        return self._request("GET", "/sped-staffing/absence-reports", headers=headers, params=params)

    def get_absence(self, absence_id, headers):
        return self._request("GET", f"/sped-staffing/absence-reports/{absence_id}", headers=headers)

    def escalate_absence(self, absence_id, headers):
        return self._request("POST", f"/sped-staffing/absence-reports/{absence_id}/escalate", headers=headers)

    def cancel_absence(self, absence_id, headers):
        return self._request("POST", f"/sped-staffing/absence-reports/{absence_id}/cancel", headers=headers)

    def run_backfill_offers(self, absence_id, headers):
        return self._request("POST", f"/sped-staffing/absence-reports/{absence_id}/backfill-offers", headers=headers)

    # --- BackfillAssignment ---
    def list_backfills(self, headers, params=None):
        return self._request("GET", "/sped-staffing/backfill-assignments", headers=headers, params=params)

    def get_backfill(self, backfill_id, headers):
        return self._request("GET", f"/sped-staffing/backfill-assignments/{backfill_id}", headers=headers)

    def accept_backfill(self, backfill_id, headers):
        return self._request("POST", f"/sped-staffing/backfill-assignments/{backfill_id}/accept", headers=headers)

    def decline_backfill(self, backfill_id, headers):
        return self._request("POST", f"/sped-staffing/backfill-assignments/{backfill_id}/decline", headers=headers)

    def cancel_backfill(self, backfill_id, headers):
        return self._request("POST", f"/sped-staffing/backfill-assignments/{backfill_id}/cancel", headers=headers)

    # --- TimesheetEntry ---
    def create_timesheet(self, payload, headers):
        return self._request("POST", "/sped-staffing/timesheets", payload, headers)

    def list_timesheets(self, headers, params=None):
        return self._request("GET", "/sped-staffing/timesheets", headers=headers, params=params)

    def get_timesheet(self, timesheet_id, headers):
        return self._request("GET", f"/sped-staffing/timesheets/{timesheet_id}", headers=headers)

    def submit_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/sped-staffing/timesheets/{timesheet_id}/submit", headers=headers)

    def approve_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/sped-staffing/timesheets/{timesheet_id}/approve", headers=headers)

    def reject_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/sped-staffing/timesheets/{timesheet_id}/reject", headers=headers)

    # --- Evaluation ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/sped-staffing/evaluations", payload, headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/sped-staffing/evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/sped-staffing/evaluations/{evaluation_id}", headers=headers)

    def submit_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/sped-staffing/evaluations/{evaluation_id}/submit", headers=headers)

    def countersign_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/sped-staffing/evaluations/{evaluation_id}/countersign", headers=headers)

    def acknowledge_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/sped-staffing/evaluations/{evaluation_id}/acknowledge", headers=headers)

    def dispute_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/sped-staffing/evaluations/{evaluation_id}/dispute", headers=headers)

    def resolve_evaluation(self, evaluation_id, payload, headers):
        return self._request("POST", f"/sped-staffing/evaluations/{evaluation_id}/resolve", payload, headers)

    # --- AllocationFormula ---
    def create_formula(self, payload, headers):
        return self._request("POST", "/sped-staffing/allocation-formulas", payload, headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/sped-staffing/allocation-formulas", headers=headers, params=params)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/sped-staffing/allocation-formulas/{formula_id}", headers=headers)

    def publish_formula(self, formula_id, headers):
        return self._request("POST", f"/sped-staffing/allocation-formulas/{formula_id}/publish", headers=headers)

    # --- FundingAllocation ---
    def compute_allocations(self, payload, headers):
        return self._request("POST", "/sped-staffing/funding-allocations/compute", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/sped-staffing/funding-allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/sped-staffing/funding-allocations/{allocation_id}", headers=headers)


api_client = ApiClient()
