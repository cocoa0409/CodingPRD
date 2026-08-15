"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Substitute Teacher Pool API."""

    # --- Test-driving logical clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Districts ---
    def create_district(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/districts", payload, headers)

    def get_district(self, district_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/districts/{district_id}", headers=headers)

    def update_district(self, district_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PUT", f"/districts/{district_id}", payload, headers)

    # --- Schools ---
    def create_school(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def list_schools(self, district_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/districts/{district_id}/schools", headers=headers, params=params)

    # --- Staff members ---
    def create_staff_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/staff-members/{staff_member_id}", headers=headers)

    def list_staff_members(self, school_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/schools/{school_id}/staff-members", headers=headers, params=params)

    # --- Substitutes ---
    def create_substitute(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/substitutes", payload, headers)

    def get_substitute(self, substitute_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/substitutes/{substitute_id}", headers=headers)

    def list_substitutes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/substitutes", headers=headers, params=params)

    def activate_substitute(self, substitute_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/substitutes/{substitute_id}/activate", {}, headers)

    def suspend_substitute(self, substitute_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/substitutes/{substitute_id}/suspend", payload or {}, headers)

    # --- Qualifications ---
    def create_qualification(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/qualifications", payload, headers)

    def list_qualifications(self, substitute_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/substitutes/{substitute_id}/qualifications", headers=headers, params=params)

    # --- Clearances ---
    def create_clearance(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/clearances", payload, headers)

    def verify_clearance(self, clearance_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/clearances/{clearance_id}/verify", {}, headers)

    def list_clearances(self, substitute_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/substitutes/{substitute_id}/clearances", headers=headers, params=params)

    # --- School-substitute marks ---
    def create_mark(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/marks", payload, headers)

    def lift_mark(self, mark_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/marks/{mark_id}/lift", {}, headers)

    def list_school_marks(self, school_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/schools/{school_id}/marks", headers=headers, params=params)

    def list_substitute_marks(self, substitute_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/substitutes/{substitute_id}/marks", headers=headers, params=params)

    # --- Absences ---
    def create_absence(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/absences", payload, headers)

    def get_absence(self, absence_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/absences/{absence_id}", headers=headers)

    def list_absences(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/absences", headers=headers, params=params)

    def update_absence(self, absence_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PUT", f"/absences/{absence_id}", payload, headers)

    def cancel_absence(self, absence_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/absences/{absence_id}/cancel", {}, headers)

    def review_absence(self, absence_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/absences/{absence_id}/review", payload, headers)

    def claim_absence(self, absence_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/absences/{absence_id}/claim", payload, headers)

    # --- Dispatch batches ---
    def create_dispatch_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dispatch-batches", payload, headers)

    def get_dispatch_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dispatch-batches/{batch_id}", headers=headers)

    def list_dispatch_batches(self, district_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/districts/{district_id}/dispatch-batches", headers=headers, params=params)

    # --- Assignments ---
    def create_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def respond_assignment(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/assignments/{assignment_id}/respond", payload, headers)

    def cancel_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/assignments/{assignment_id}/cancel", {}, headers)

    def report_assignment_outcome(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/assignments/{assignment_id}/report-outcome", payload, headers)

    def verify_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/assignments/{assignment_id}/verify", {}, headers)

    def extend_assignment(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/assignments/{assignment_id}/extend", payload, headers)

    # --- Internal coverages ---
    def create_internal_coverage(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/internal-coverages", payload, headers)

    def get_internal_coverage(self, coverage_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/internal-coverages/{coverage_id}", headers=headers)

    def list_absence_coverages(self, absence_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/absences/{absence_id}/internal-coverages", headers=headers, params=params)

    def list_staff_member_coverages(self, staff_member_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/staff-members/{staff_member_id}/internal-coverages", headers=headers, params=params)

    def review_internal_coverage(self, coverage_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/internal-coverages/{coverage_id}/review", payload, headers)

    def confirm_coverage_worked(self, coverage_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/internal-coverages/{coverage_id}/confirm-worked", {}, headers)

    def cancel_internal_coverage(self, coverage_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/internal-coverages/{coverage_id}/cancel", {}, headers)

    # --- Timesheets ---
    def create_timesheet(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/timesheets", payload, headers)

    def get_timesheet(self, timesheet_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/timesheets/{timesheet_id}", headers=headers)

    def list_assignment_timesheets(self, assignment_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/assignments/{assignment_id}/timesheets", headers=headers, params=params)

    def list_payroll_period_timesheets(self, payroll_period_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/payroll-periods/{payroll_period_id}/timesheets", headers=headers, params=params)

    def review_timesheet(self, timesheet_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/timesheets/{timesheet_id}/review", payload, headers)

    def resubmit_timesheet(self, timesheet_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PUT", f"/timesheets/{timesheet_id}", payload, headers)

    # --- Payroll periods ---
    def create_payroll_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/payroll-periods", payload, headers)

    def get_payroll_period(self, payroll_period_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/payroll-periods/{payroll_period_id}", headers=headers)

    def list_payroll_periods(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/payroll-periods", headers=headers, params=params)

    def export_payroll_period(self, payroll_period_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/payroll-periods/{payroll_period_id}/export", {}, headers)

    # --- Performance flags ---
    def create_performance_flag(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/performance-flags", payload, headers)

    def list_substitute_flags(self, substitute_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/substitutes/{substitute_id}/performance-flags", headers=headers, params=params)

    def list_school_flags(self, school_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/schools/{school_id}/performance-flags", headers=headers, params=params)

    def review_performance_flag(self, flag_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/performance-flags/{flag_id}/review", payload, headers)

    # --- Analytics ---
    def get_fill_rate(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/analytics/fill-rate", headers=headers, params=params)


api_client = ApiClient()
