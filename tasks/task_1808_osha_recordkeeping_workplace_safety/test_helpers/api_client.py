"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/safety/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------
    def create_company(self, payload, headers):
        return self._request("POST", "/safety/companies", payload, headers)

    def get_company(self, company_id, headers):
        return self._request("GET", f"/safety/companies/{company_id}",
                             headers=headers)

    def list_company_employees(self, company_id, headers, params=None):
        return self._request("GET", f"/safety/companies/{company_id}/employees",
                             headers=headers, params=params)

    def list_company_establishments(self, company_id, headers, params=None):
        return self._request("GET",
                             f"/safety/companies/{company_id}/establishments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Establishments
    # ------------------------------------------------------------------
    def create_establishment(self, payload, headers):
        return self._request("POST", "/safety/establishments", payload, headers)

    def get_establishment(self, establishment_id, headers):
        return self._request("GET",
                             f"/safety/establishments/{establishment_id}",
                             headers=headers)

    def get_establishment_rates(self, establishment_id, year, headers):
        return self._request("GET",
                             f"/safety/establishments/{establishment_id}/rates",
                             headers=headers, params={"year": year})

    def list_establishment_cases(self, establishment_id, headers, params=None):
        return self._request("GET",
                             f"/safety/establishments/{establishment_id}/cases",
                             headers=headers, params=params)

    def list_establishment_summaries(self, establishment_id, headers, params=None):
        return self._request("GET",
                             f"/safety/establishments/{establishment_id}/summaries",
                             headers=headers, params=params)

    def list_establishment_hour_logs(self, establishment_id, headers, params=None):
        return self._request("GET",
                             f"/safety/establishments/{establishment_id}/hour-logs",
                             headers=headers, params=params)

    def list_establishment_inspections(self, establishment_id, headers, params=None):
        return self._request("GET",
                             f"/safety/establishments/{establishment_id}/inspections",
                             headers=headers, params=params)

    def list_establishment_corrective_actions(self, establishment_id, headers,
                                              params=None):
        return self._request(
            "GET",
            f"/safety/establishments/{establishment_id}/corrective-actions",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/safety/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/safety/employees/{employee_id}",
                             headers=headers)

    def update_employee(self, employee_id, payload, headers):
        return self._request("PATCH", f"/safety/employees/{employee_id}",
                             payload, headers)

    def list_employee_cases(self, employee_id, headers, params=None):
        return self._request("GET", f"/safety/employees/{employee_id}/cases",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Incident cases
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/safety/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/safety/cases/{case_id}", headers=headers)

    def classify_case(self, case_id, payload, headers):
        return self._request("POST", f"/safety/cases/{case_id}/classify",
                             payload, headers)

    def reclassify_case(self, case_id, payload, headers):
        return self._request("POST", f"/safety/cases/{case_id}/reclassify",
                             payload, headers)

    def close_day_count(self, case_id, payload, headers):
        return self._request("POST", f"/safety/cases/{case_id}/close-day-count",
                             payload, headers)

    def finalize_case(self, case_id, payload, headers):
        return self._request("POST", f"/safety/cases/{case_id}/finalize",
                             payload, headers)

    def list_day_entries(self, case_id, headers, params=None):
        return self._request("GET", f"/safety/cases/{case_id}/day-entries",
                             headers=headers, params=params)

    def add_day_entry(self, case_id, payload, headers):
        return self._request("POST", f"/safety/cases/{case_id}/day-entries",
                             payload, headers)

    def void_day_entry(self, case_id, entry_id, headers):
        return self._request(
            "POST", f"/safety/cases/{case_id}/day-entries/{entry_id}/void",
            {}, headers)

    def get_case_investigation(self, case_id, headers):
        return self._request("GET", f"/safety/cases/{case_id}/investigation",
                             headers=headers)

    def list_case_severe_reports(self, case_id, headers):
        return self._request("GET", f"/safety/cases/{case_id}/severe-reports",
                             headers=headers)

    def create_severe_report(self, case_id, payload, headers):
        return self._request("POST", f"/safety/cases/{case_id}/severe-reports",
                             payload, headers)

    def list_case_corrective_actions(self, case_id, headers, params=None):
        return self._request("GET",
                             f"/safety/cases/{case_id}/corrective-actions",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Investigations
    # ------------------------------------------------------------------
    def create_investigation(self, payload, headers):
        return self._request("POST", "/safety/investigations", payload, headers)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET",
                             f"/safety/investigations/{investigation_id}",
                             headers=headers)

    def submit_root_cause(self, investigation_id, payload, headers):
        return self._request(
            "POST",
            f"/safety/investigations/{investigation_id}/submit-root-cause",
            payload, headers)

    def reopen_investigation(self, investigation_id, headers):
        return self._request(
            "POST", f"/safety/investigations/{investigation_id}/reopen",
            {}, headers)

    def close_investigation(self, investigation_id, headers):
        return self._request(
            "POST", f"/safety/investigations/{investigation_id}/close",
            {}, headers)

    # ------------------------------------------------------------------
    # Corrective actions
    # ------------------------------------------------------------------
    def create_corrective_action(self, payload, headers):
        return self._request("POST", "/safety/corrective-actions", payload,
                             headers)

    def get_corrective_action(self, action_id, headers):
        return self._request("GET",
                             f"/safety/corrective-actions/{action_id}",
                             headers=headers)

    def complete_corrective_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/safety/corrective-actions/{action_id}/complete",
            payload, headers)

    def verify_corrective_action(self, action_id, headers):
        return self._request(
            "POST", f"/safety/corrective-actions/{action_id}/verify",
            {}, headers)

    def reject_verification(self, action_id, headers):
        return self._request(
            "POST",
            f"/safety/corrective-actions/{action_id}/reject-verification",
            {}, headers)

    def cancel_corrective_action(self, action_id, headers):
        return self._request(
            "POST", f"/safety/corrective-actions/{action_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Annual summaries (300A)
    # ------------------------------------------------------------------
    def create_summary(self, payload, headers):
        return self._request("POST", "/safety/summaries", payload, headers)

    def get_summary(self, summary_id, headers):
        return self._request("GET", f"/safety/summaries/{summary_id}",
                             headers=headers)

    def prepare_summary(self, summary_id, headers):
        return self._request("POST", f"/safety/summaries/{summary_id}/prepare",
                             {}, headers)

    def certify_summary(self, summary_id, payload, headers):
        return self._request("POST", f"/safety/summaries/{summary_id}/certify",
                             payload, headers)

    def post_summary(self, summary_id, headers):
        return self._request("POST", f"/safety/summaries/{summary_id}/post",
                             {}, headers)

    def amend_summary(self, summary_id, headers):
        return self._request("POST", f"/safety/summaries/{summary_id}/amend",
                             {}, headers)

    # ------------------------------------------------------------------
    # Hour logs
    # ------------------------------------------------------------------
    def create_hour_log(self, payload, headers):
        return self._request("POST", "/safety/hour-logs", payload, headers)

    def get_hour_log(self, hour_log_id, headers):
        return self._request("GET", f"/safety/hour-logs/{hour_log_id}",
                             headers=headers)

    def approve_hour_log(self, hour_log_id, headers):
        return self._request("POST",
                             f"/safety/hour-logs/{hour_log_id}/approve",
                             {}, headers)

    def reopen_hour_log(self, hour_log_id, headers):
        return self._request("POST",
                             f"/safety/hour-logs/{hour_log_id}/reopen",
                             {}, headers)

    # ------------------------------------------------------------------
    # Inspections and citations
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/safety/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/safety/inspections/{inspection_id}",
                             headers=headers)

    def close_inspection(self, inspection_id, headers):
        return self._request("POST",
                             f"/safety/inspections/{inspection_id}/close",
                             {}, headers)

    def list_inspection_citations(self, inspection_id, headers, params=None):
        return self._request("GET",
                             f"/safety/inspections/{inspection_id}/citations",
                             headers=headers, params=params)

    def create_citation(self, payload, headers):
        return self._request("POST", "/safety/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/safety/citations/{citation_id}",
                             headers=headers)

    def contest_citation(self, citation_id, headers):
        return self._request("POST",
                             f"/safety/citations/{citation_id}/contest",
                             {}, headers)

    def accept_final_order(self, citation_id, headers):
        return self._request(
            "POST", f"/safety/citations/{citation_id}/accept-final-order",
            {}, headers)

    def resolve_contest(self, citation_id, payload, headers):
        return self._request("POST",
                             f"/safety/citations/{citation_id}/resolve-contest",
                             payload, headers)

    def abate_citation(self, citation_id, payload, headers):
        return self._request("POST",
                             f"/safety/citations/{citation_id}/abate",
                             payload, headers)

    def list_citation_corrective_actions(self, citation_id, headers,
                                         params=None):
        return self._request(
            "GET", f"/safety/citations/{citation_id}/corrective-actions",
            headers=headers, params=params)


api_client = ApiClient()
