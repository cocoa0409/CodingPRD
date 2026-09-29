"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the Staffing Data Reporting API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------

    def create_facility(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def get_audit_readiness(
        self, facility_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/facilities/{facility_id}/audit-readiness",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Reporting periods
    # ------------------------------------------------------------------

    def create_reporting_period(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/reporting-periods", payload, headers)

    def get_reporting_period(self, period_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reporting-periods/{period_id}", headers=headers)

    def list_reporting_periods(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/reporting-periods", headers=headers, params=params)

    def close_reporting_period(self, period_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/reporting-periods/{period_id}/close", {}, headers
        )

    # ------------------------------------------------------------------
    # Job categories
    # ------------------------------------------------------------------

    def create_job_category(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/job-categories", payload, headers)

    def get_job_category(self, job_category_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/job-categories/{job_category_id}", headers=headers
        )

    def list_job_categories(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/job-categories", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def create_worker(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/workers", payload, headers)

    def get_worker(self, worker_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/workers/{worker_id}", headers=headers)

    def list_workers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/workers", headers=headers, params=params)

    def terminate_worker(self, worker_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/workers/{worker_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Staffing vendors
    # ------------------------------------------------------------------

    def create_vendor(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def suspend_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", {}, headers)

    # ------------------------------------------------------------------
    # Agency hour batches
    # ------------------------------------------------------------------

    def create_vendor_submission(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/vendor-submissions", payload, headers)

    def get_vendor_submission(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vendor-submissions/{batch_id}", headers=headers)

    def list_vendor_submissions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/vendor-submissions", headers=headers, params=params
        )

    def submit_vendor_submission(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/vendor-submissions/{batch_id}/submit", {}, headers
        )

    def accept_vendor_submission(
        self, batch_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vendor-submissions/{batch_id}/accept", payload, headers
        )

    def reject_vendor_submission(
        self, batch_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vendor-submissions/{batch_id}/reject", payload, headers
        )

    def revoke_vendor_submission(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/vendor-submissions/{batch_id}/revoke", {}, headers
        )

    # ------------------------------------------------------------------
    # Payroll documents
    # ------------------------------------------------------------------

    def create_payroll_record(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/payroll-records", payload, headers)

    def get_payroll_record(self, payroll_record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/payroll-records/{payroll_record_id}", headers=headers
        )

    def list_payroll_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/payroll-records", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Quarterly submissions
    # ------------------------------------------------------------------

    def create_submission(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/submissions", payload, headers)

    def get_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def list_submission_findings(
        self, submission_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/submissions/{submission_id}/findings",
            headers=headers,
            params=params,
        )

    def get_validation_finding(self, finding_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/validation-findings/{finding_id}", headers=headers
        )

    def get_submission_hprd(
        self, submission_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/submissions/{submission_id}/hprd", headers=headers, params=params
        )

    def validate_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/submissions/{submission_id}/validate", {}, headers
        )

    def submit_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/submissions/{submission_id}/submit", {}, headers)

    def accept_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/submissions/{submission_id}/accept", {}, headers)

    def reject_submission(
        self, submission_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/submissions/{submission_id}/reject", payload, headers
        )

    def reopen_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/submissions/{submission_id}/reopen", {}, headers)

    def waive_finding(
        self,
        submission_id: str,
        finding_id: str,
        payload: Any,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/submissions/{submission_id}/findings/{finding_id}/waive",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Hour entries
    # ------------------------------------------------------------------

    def create_hour_entry(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/hour-entries", payload, headers)

    def get_hour_entry(self, hour_entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hour-entries/{hour_entry_id}", headers=headers)

    def list_hour_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/hour-entries", headers=headers, params=params)

    def replace_hour_entry_allocations(
        self, hour_entry_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "PUT", f"/hour-entries/{hour_entry_id}/allocations", payload, headers
        )

    def void_hour_entry(self, hour_entry_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/hour-entries/{hour_entry_id}/void", {}, headers
        )

    def verify_hour_entry(
        self, hour_entry_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/hour-entries/{hour_entry_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Census days
    # ------------------------------------------------------------------

    def create_census_day(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/census-days", payload, headers)

    def get_census_day(self, census_day_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/census-days/{census_day_id}", headers=headers)

    def list_census_days(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/census-days", headers=headers, params=params)

    def update_census_day(
        self, census_day_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/census-days/{census_day_id}", payload, headers)

    def reconcile_census_day(self, census_day_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/census-days/{census_day_id}/reconcile", {}, headers
        )

    # ------------------------------------------------------------------
    # Staffing measures
    # ------------------------------------------------------------------

    def create_staffing_measure(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/staffing-measures", payload, headers)

    def get_staffing_measure(self, measure_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/staffing-measures/{measure_id}", headers=headers)

    def list_staffing_measures(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/staffing-measures", headers=headers, params=params)

    def publish_staffing_measure(self, measure_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/staffing-measures/{measure_id}/publish", {}, headers
        )

    # ------------------------------------------------------------------
    # Discrepancy cases
    # ------------------------------------------------------------------

    def create_discrepancy_case(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/discrepancy-cases", payload, headers)

    def get_discrepancy_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/discrepancy-cases/{case_id}", headers=headers)

    def list_discrepancy_cases(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/discrepancy-cases", headers=headers, params=params)

    def request_case_info(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/discrepancy-cases/{case_id}/request-info", payload, headers
        )

    def respond_to_case(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/discrepancy-cases/{case_id}/respond", payload, headers
        )

    def substantiate_case(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/discrepancy-cases/{case_id}/substantiate", payload, headers
        )

    def dismiss_case(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/discrepancy-cases/{case_id}/dismiss", payload, headers
        )

    # ------------------------------------------------------------------
    # Rating appeals
    # ------------------------------------------------------------------

    def create_rating_appeal(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/rating-appeals", payload, headers)

    def get_rating_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rating-appeals/{appeal_id}", headers=headers)

    def list_rating_appeals(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/rating-appeals", headers=headers, params=params)

    def grant_rating_appeal(
        self, appeal_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/rating-appeals/{appeal_id}/grant", payload, headers
        )

    def deny_rating_appeal(self, appeal_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rating-appeals/{appeal_id}/deny", payload, headers
        )


api_client = ApiClient()
