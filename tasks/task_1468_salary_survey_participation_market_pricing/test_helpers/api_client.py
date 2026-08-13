"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Org / bootstrap ---
    def create_org(self, payload, headers):
        return self._request("POST", "/orgs", payload, headers)

    def get_org(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}", headers=headers)

    def list_orgs(self, headers, params=None):
        return self._request("GET", "/orgs", headers=headers, params=params)

    # --- Strategy policies ---
    def create_strategy(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/strategies", payload, headers)

    def get_strategy(self, strategy_id, headers):
        return self._request("GET", f"/strategies/{strategy_id}", headers=headers)

    def list_strategies(self, headers, params=None):
        return self._request("GET", "/strategies", headers=headers, params=params)

    def list_org_strategies(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/strategies", headers=headers)

    def activate_strategy(self, strategy_id, headers):
        return self._request("POST", f"/strategies/{strategy_id}/activate", {}, headers)

    def retire_strategy(self, strategy_id, headers):
        return self._request("POST", f"/strategies/{strategy_id}/retire", {}, headers)

    # --- Jobs ---
    def create_job(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def list_org_jobs(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/jobs", headers=headers)

    # --- Employees ---
    def create_employee(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def list_org_employees(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/employees", headers=headers)

    def list_job_employees(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}/employees", headers=headers)

    # --- Vendors ---
    def create_vendor(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def list_org_vendors(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/vendors", headers=headers)

    def activate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/activate", {}, headers)

    def terminate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/terminate", {}, headers)

    # --- Surveys ---
    def create_survey(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/surveys", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/surveys", headers=headers, params=params)

    def list_vendor_surveys(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}/surveys", headers=headers)

    def list_org_surveys(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/surveys", headers=headers)

    def open_survey(self, survey_id, headers):
        return self._request("POST", f"/surveys/{survey_id}/open", {}, headers)

    def close_survey(self, survey_id, headers):
        return self._request("POST", f"/surveys/{survey_id}/close", {}, headers)

    def accept_survey(self, survey_id, headers):
        return self._request("POST", f"/surveys/{survey_id}/accept", {}, headers)

    def reject_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/reject", payload, headers)

    # --- Survey benchmarks ---
    def create_benchmark(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/benchmarks", payload, headers)

    def get_benchmark(self, benchmark_id, headers):
        return self._request("GET", f"/benchmarks/{benchmark_id}", headers=headers)

    def list_benchmarks(self, headers, params=None):
        return self._request("GET", "/benchmarks", headers=headers, params=params)

    def list_survey_benchmarks(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}/benchmarks", headers=headers)

    # --- Submissions ---
    def create_submission(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def list_survey_submissions(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}/submissions", headers=headers)

    def list_employee_submissions(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}/submissions", headers=headers)

    def mark_submission_ready(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/mark_ready", {}, headers)

    def submit_submission(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/submit", {}, headers)

    def accept_submission(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/accept", {}, headers)

    def return_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/submissions/{submission_id}/return", payload, headers)

    def rework_submission(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/rework", {}, headers)

    # --- Survey job matches ---
    def create_match(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/matches", payload, headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def list_survey_matches(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}/matches", headers=headers)

    def list_job_matches(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}/matches", headers=headers)

    def review_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/review", {}, headers)

    def approve_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/approve", {}, headers)

    def reject_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/reject", {}, headers)

    def revise_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/revise", {}, headers)

    # --- Market composites ---
    def create_composite(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/composites", payload, headers)

    def get_composite(self, composite_id, headers):
        return self._request("GET", f"/composites/{composite_id}", headers=headers)

    def list_composites(self, headers, params=None):
        return self._request("GET", "/composites", headers=headers, params=params)

    def list_job_composites(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}/composites", headers=headers)

    def list_strategy_composites(self, strategy_id, headers):
        return self._request("GET", f"/strategies/{strategy_id}/composites", headers=headers)

    def recompute_composite(self, composite_id, headers):
        return self._request("POST", f"/composites/{composite_id}/recompute", {}, headers)

    def publish_composite(self, composite_id, payload, headers):
        return self._request("POST", f"/composites/{composite_id}/publish", payload, headers)

    # --- Adjustment cycles ---
    def create_cycle(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/cycles", headers=headers, params=params)

    def list_org_cycles(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/cycles", headers=headers)

    def lock_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/lock", {}, headers)

    def unlock_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/unlock", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/close", {}, headers)

    # --- Market adjustments ---
    def create_adjustment(self, cycle_id, payload, headers):
        return self._request("POST", f"/cycles/{cycle_id}/adjustments", payload, headers)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/adjustments/{adjustment_id}", headers=headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/adjustments", headers=headers, params=params)

    def list_cycle_adjustments(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}/adjustments", headers=headers)

    def list_employee_adjustments(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}/adjustments", headers=headers)

    def list_job_adjustments(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}/adjustments", headers=headers)

    def submit_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/submit", {}, headers)

    def approve_adjustment(self, adjustment_id, payload, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/approve", payload, headers)

    def reject_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/reject", {}, headers)

    def retract_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/retract", {}, headers)

    def apply_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/apply", {}, headers)

    # --- Compensation reports ---
    def create_report(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def list_org_reports(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/reports", headers=headers)

    def finalize_report(self, report_id, payload, headers):
        return self._request("POST", f"/reports/{report_id}/finalize", payload, headers)

    def present_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/present", {}, headers)

    # --- Audit events (read-only) ---
    def get_audit_event(self, event_id, headers):
        return self._request("GET", f"/audit_events/{event_id}", headers=headers)

    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit_events", headers=headers, params=params)

    def list_org_audit_events(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/audit_events", headers=headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
