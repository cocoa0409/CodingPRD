"""API client: one method per endpoint defined in the Benefits Open Enrollment PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Employee ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def terminate_employee(self, employee_id, headers, payload=None):
        return self._request("POST", f"/employees/{employee_id}/terminate", payload or {}, headers)

    # ---- WaitingPeriod ----
    def create_waiting_period(self, employee_id, payload, headers):
        return self._request("POST", f"/employees/{employee_id}/waiting-periods", payload, headers)

    def list_waiting_periods(self, employee_id, headers, params=None):
        return self._request("GET", f"/employees/{employee_id}/waiting-periods", headers=headers, params=params)

    # ---- PlanOffering ----
    def create_plan_offering(self, payload, headers):
        return self._request("POST", "/plan-offerings", payload, headers)

    def get_plan_offering(self, offering_id, headers):
        return self._request("GET", f"/plan-offerings/{offering_id}", headers=headers)

    def archive_plan_offering(self, offering_id, headers, payload=None):
        return self._request("POST", f"/plan-offerings/{offering_id}/archive", payload or {}, headers)

    # ---- PlanTier ----
    def create_plan_tier(self, payload, headers):
        return self._request("POST", "/plan-tiers", payload, headers)

    def get_plan_tier(self, tier_id, headers):
        return self._request("GET", f"/plan-tiers/{tier_id}", headers=headers)

    def list_plan_tiers(self, headers, params=None):
        return self._request("GET", "/plan-tiers", headers=headers, params=params)

    # ---- Dependent ----
    def create_dependent(self, employee_id, payload, headers):
        return self._request("POST", f"/employees/{employee_id}/dependents", payload, headers)

    def get_dependent(self, dependent_id, headers):
        return self._request("GET", f"/dependents/{dependent_id}", headers=headers)

    def list_dependents(self, headers, params=None):
        return self._request("GET", "/dependents", headers=headers, params=params)

    def request_info_dependent(self, dependent_id, headers, payload=None):
        return self._request("POST", f"/dependents/{dependent_id}/request-info", payload or {}, headers)

    def resubmit_dependent(self, dependent_id, headers, payload=None):
        return self._request("POST", f"/dependents/{dependent_id}/resubmit", payload or {}, headers)

    def verify_dependent(self, dependent_id, headers, payload=None):
        return self._request("POST", f"/dependents/{dependent_id}/verify", payload or {}, headers)

    def reject_dependent(self, dependent_id, headers, payload=None):
        return self._request("POST", f"/dependents/{dependent_id}/reject", payload or {}, headers)

    # ---- Enrollment ----
    def create_enrollment(self, employee_id, payload, headers):
        return self._request("POST", f"/employees/{employee_id}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", payload, headers)

    def submit_eoi_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/submit-eoi", payload or {}, headers)

    def cancel_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancel", payload or {}, headers)

    def add_dependent_to_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/add-dependent", payload, headers)

    def remove_dependent_from_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/remove-dependent", payload, headers)

    # ---- EOIRequest ----
    def get_eoi_request(self, eoi_id, headers):
        return self._request("GET", f"/eoi-requests/{eoi_id}", headers=headers)

    def list_eoi_requests(self, headers, params=None):
        return self._request("GET", "/eoi-requests", headers=headers, params=params)

    def decide_eoi_request(self, eoi_id, payload, headers):
        return self._request("POST", f"/eoi-requests/{eoi_id}/decide", payload, headers)

    # ---- LifeEvent ----
    def create_life_event(self, employee_id, payload, headers):
        return self._request("POST", f"/employees/{employee_id}/life-events", payload, headers)

    def get_life_event(self, life_event_id, headers):
        return self._request("GET", f"/life-events/{life_event_id}", headers=headers)

    def list_life_events(self, headers, params=None):
        return self._request("GET", "/life-events", headers=headers, params=params)

    def approve_life_event(self, life_event_id, payload, headers):
        return self._request("POST", f"/life-events/{life_event_id}/approve", payload, headers)

    def reject_life_event(self, life_event_id, headers, payload=None):
        return self._request("POST", f"/life-events/{life_event_id}/reject", payload or {}, headers)

    # ---- DeductionLine / payroll ----
    def run_payroll(self, payload, headers):
        return self._request("POST", "/_payroll/run", payload, headers)

    def get_deduction_line(self, line_id, headers):
        return self._request("GET", f"/deduction-lines/{line_id}", headers=headers)

    def list_deduction_lines(self, headers, params=None):
        return self._request("GET", "/deduction-lines", headers=headers, params=params)

    # ---- CarrierFeedRecord ----
    def get_carrier_feed_record(self, record_id, headers):
        return self._request("GET", f"/carrier-feed-records/{record_id}", headers=headers)

    def list_carrier_feed_records(self, headers, params=None):
        return self._request("GET", "/carrier-feed-records", headers=headers, params=params)

    # ---- Form1095C ----
    def generate_form_1095c(self, employee_id, payload, headers):
        return self._request("POST", f"/employees/{employee_id}/form-1095c", payload, headers)

    def get_form_1095c(self, form_id, headers):
        return self._request("GET", f"/form-1095c/{form_id}", headers=headers)

    def list_form_1095c(self, headers, params=None):
        return self._request("GET", "/form-1095c", headers=headers, params=params)

    def file_form_1095c(self, form_id, headers, payload=None):
        return self._request("POST", f"/form-1095c/{form_id}/file", payload or {}, headers)

    # ---- Clock (test-driving) ----
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
