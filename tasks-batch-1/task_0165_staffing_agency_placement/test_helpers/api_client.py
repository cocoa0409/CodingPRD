"""API client for the Staffing Agency Placement API.

One method per endpoint. Subclasses the framework's GenericApiClient, which
supplies the base _request() implementation, envelope handling, and the
API_BASE_URL wiring.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/staffing/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/staffing/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/staffing/clients/{client_id}/suspend", headers=headers)

    # --- Skill ---
    def create_skill(self, payload, headers):
        return self._request("POST", "/staffing/skills", payload, headers)

    def get_skill(self, skill_id, headers):
        return self._request("GET", f"/staffing/skills/{skill_id}", headers=headers)

    # --- Candidate ---
    def create_candidate(self, payload, headers):
        return self._request("POST", "/staffing/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/staffing/candidates/{candidate_id}", headers=headers)

    def patch_candidate(self, candidate_id, payload, headers):
        return self._request("PATCH", f"/staffing/candidates/{candidate_id}", payload, headers)

    # --- JobOrder ---
    def create_job_order(self, payload, headers):
        return self._request("POST", "/staffing/job-orders", payload, headers)

    def list_job_orders(self, headers, params=None):
        return self._request("GET", "/staffing/job-orders", headers=headers, params=params)

    def get_job_order(self, job_order_id, headers):
        return self._request("GET", f"/staffing/job-orders/{job_order_id}", headers=headers)

    def patch_job_order(self, job_order_id, payload, headers):
        return self._request("PATCH", f"/staffing/job-orders/{job_order_id}", payload, headers)

    # --- Submission ---
    def create_submission(self, payload, headers):
        return self._request("POST", "/staffing/submissions", payload, headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/staffing/submissions", headers=headers, params=params)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/staffing/submissions/{submission_id}", headers=headers)

    def patch_submission(self, submission_id, payload, headers):
        return self._request("PATCH", f"/staffing/submissions/{submission_id}", payload, headers)

    # --- Interview ---
    def create_interview(self, submission_id, payload, headers):
        return self._request("POST", f"/staffing/submissions/{submission_id}/interviews", payload, headers)

    def list_interviews(self, submission_id, headers, params=None):
        return self._request("GET", f"/staffing/submissions/{submission_id}/interviews", headers=headers, params=params)

    def patch_interview(self, interview_id, payload, headers):
        return self._request("PATCH", f"/staffing/interviews/{interview_id}", payload, headers)

    # --- Placement ---
    def create_placement(self, payload, headers):
        return self._request("POST", "/staffing/placements", payload, headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/staffing/placements", headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/staffing/placements/{placement_id}", headers=headers)

    def list_placement_timesheets(self, placement_id, headers, params=None):
        return self._request("GET", f"/staffing/placements/{placement_id}/timesheets", headers=headers, params=params)

    def patch_placement(self, placement_id, payload, headers):
        return self._request("PATCH", f"/staffing/placements/{placement_id}", payload, headers)

    def convert_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/staffing/placements/{placement_id}/convert", payload, headers)

    # --- Timesheet ---
    def create_timesheet(self, payload, headers):
        return self._request("POST", "/staffing/timesheets", payload, headers)

    def list_timesheets(self, headers, params=None):
        return self._request("GET", "/staffing/timesheets", headers=headers, params=params)

    def get_timesheet(self, timesheet_id, headers):
        return self._request("GET", f"/staffing/timesheets/{timesheet_id}", headers=headers)

    def patch_timesheet(self, timesheet_id, payload, headers):
        return self._request("PATCH", f"/staffing/timesheets/{timesheet_id}", payload, headers)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/staffing/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/staffing/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/staffing/invoices/{invoice_id}", headers=headers)

    def list_invoice_line_items(self, invoice_id, headers, params=None):
        return self._request("GET", f"/staffing/invoices/{invoice_id}/line-items", headers=headers, params=params)

    def add_invoice_line_item(self, invoice_id, payload, headers):
        return self._request("POST", f"/staffing/invoices/{invoice_id}/line-items", payload, headers)

    def patch_invoice(self, invoice_id, payload, headers):
        return self._request("PATCH", f"/staffing/invoices/{invoice_id}", payload, headers)

    # --- ConversionFee ---
    def list_conversion_fees(self, headers, params=None):
        return self._request("GET", "/staffing/conversion-fees", headers=headers, params=params)

    def get_conversion_fee(self, conversion_fee_id, headers):
        return self._request("GET", f"/staffing/conversion-fees/{conversion_fee_id}", headers=headers)


api_client = ApiClient()
