"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/tlo/_clock/set_current_utc", payload, headers)

    # --- Departments ---
    def create_department(self, payload, headers):
        return self._request("POST", "/tlo/departments", payload, headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/tlo/departments", headers=headers, params=params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/tlo/departments/{department_id}", headers=headers)

    # --- Inventors ---
    def create_inventor(self, payload, headers):
        return self._request("POST", "/tlo/inventors", payload, headers)

    def list_inventors(self, headers, params=None):
        return self._request("GET", "/tlo/inventors", headers=headers, params=params)

    def get_inventor(self, inventor_id, headers):
        return self._request("GET", f"/tlo/inventors/{inventor_id}", headers=headers)

    def list_inventor_disclosure_entries(self, inventor_id, headers, params=None):
        return self._request("GET", f"/tlo/inventors/{inventor_id}/disclosure-entries",
                             headers=headers, params=params)

    def list_inventor_disputes(self, inventor_id, headers, params=None):
        return self._request("GET", f"/tlo/inventors/{inventor_id}/disputes",
                             headers=headers, params=params)

    def list_inventor_disclosures(self, inventor_id, headers, params=None):
        return self._request("GET", f"/tlo/inventors/{inventor_id}/disclosures",
                             headers=headers, params=params)

    def list_inventor_coi_plans(self, inventor_id, headers, params=None):
        return self._request("GET", f"/tlo/inventors/{inventor_id}/coi-plans",
                             headers=headers, params=params)

    # --- Disclosures ---
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/tlo/disclosures", payload, headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/tlo/disclosures", headers=headers, params=params)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/tlo/disclosures/{disclosure_id}", headers=headers)

    def add_roster_entry(self, disclosure_id, payload, headers):
        return self._request("POST", f"/tlo/disclosures/{disclosure_id}/inventors",
                             payload, headers)

    def list_roster_entries(self, disclosure_id, headers, params=None):
        return self._request("GET", f"/tlo/disclosures/{disclosure_id}/inventors",
                             headers=headers, params=params)

    def finalize_inventorship(self, disclosure_id, payload, headers):
        return self._request("POST",
                             f"/tlo/disclosures/{disclosure_id}/inventorship/finalize",
                             payload, headers)

    def record_assessment(self, disclosure_id, payload, headers):
        return self._request("POST", f"/tlo/disclosures/{disclosure_id}/assessment",
                             payload, headers)

    def record_decision(self, disclosure_id, payload, headers):
        return self._request("POST", f"/tlo/disclosures/{disclosure_id}/decision",
                             payload, headers)

    def clear_cost_review(self, disclosure_id, headers):
        return self._request("POST",
                             f"/tlo/disclosures/{disclosure_id}/cost-review/clear",
                             {}, headers)

    # --- Roster entries (top-level actions) ---
    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/tlo/disclosure-entries/{entry_id}", headers=headers)

    def confirm_entry(self, entry_id, headers):
        return self._request("POST", f"/tlo/disclosure-entries/{entry_id}/confirm",
                             {}, headers)

    def dispute_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/tlo/disclosure-entries/{entry_id}/dispute",
                             payload, headers)

    def list_entry_disputes(self, entry_id, headers, params=None):
        return self._request("GET", f"/tlo/disclosure-entries/{entry_id}/disputes",
                             headers=headers, params=params)

    # --- Inventorship disputes ---
    def list_disputes(self, headers, params=None):
        return self._request("GET", "/tlo/inventorship-disputes",
                             headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/tlo/inventorship-disputes/{dispute_id}",
                             headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST",
                             f"/tlo/inventorship-disputes/{dispute_id}/resolve",
                             payload, headers)

    # --- Patent applications ---
    def create_patent_application(self, disclosure_id, payload, headers):
        return self._request("POST",
                             f"/tlo/disclosures/{disclosure_id}/patent-applications",
                             payload, headers)

    def list_patent_applications(self, disclosure_id, headers, params=None):
        return self._request("GET",
                             f"/tlo/disclosures/{disclosure_id}/patent-applications",
                             headers=headers, params=params)

    def get_patent_application(self, application_id, headers):
        return self._request("GET", f"/tlo/patent-applications/{application_id}",
                             headers=headers)

    def record_office_action(self, application_id, payload, headers):
        return self._request("POST",
                             f"/tlo/patent-applications/{application_id}/office-action",
                             payload, headers)

    def file_response(self, application_id, payload, headers):
        return self._request("POST",
                             f"/tlo/patent-applications/{application_id}/file-response",
                             payload, headers)

    def grant_application(self, application_id, payload, headers):
        return self._request("POST",
                             f"/tlo/patent-applications/{application_id}/grant",
                             payload, headers)

    def abandon_application(self, application_id, headers):
        return self._request("POST",
                             f"/tlo/patent-applications/{application_id}/abandon",
                             {}, headers)

    def add_cost(self, application_id, payload, headers):
        return self._request("POST", f"/tlo/patent-applications/{application_id}/costs",
                             payload, headers)

    def list_costs(self, application_id, headers, params=None):
        return self._request("GET", f"/tlo/patent-applications/{application_id}/costs",
                             headers=headers, params=params)

    # --- Startups ---
    def create_startup(self, disclosure_id, payload, headers):
        return self._request("POST", f"/tlo/disclosures/{disclosure_id}/startups",
                             payload, headers)

    def list_startups(self, disclosure_id, headers, params=None):
        return self._request("GET", f"/tlo/disclosures/{disclosure_id}/startups",
                             headers=headers, params=params)

    def get_startup(self, startup_id, headers):
        return self._request("GET", f"/tlo/startups/{startup_id}", headers=headers)

    def issue_equity(self, startup_id, payload, headers):
        return self._request("POST", f"/tlo/startups/{startup_id}/issue-equity",
                             payload, headers)

    def dissolve_startup(self, startup_id, headers):
        return self._request("POST", f"/tlo/startups/{startup_id}/dissolve", {}, headers)

    def list_startup_licenses(self, startup_id, headers, params=None):
        return self._request("GET", f"/tlo/startups/{startup_id}/licenses",
                             headers=headers, params=params)

    # --- Conflict-of-interest plans ---
    def create_coi_plan(self, startup_id, payload, headers):
        return self._request("POST", f"/tlo/startups/{startup_id}/coi-plans",
                             payload, headers)

    def list_coi_plans(self, startup_id, headers, params=None):
        return self._request("GET", f"/tlo/startups/{startup_id}/coi-plans",
                             headers=headers, params=params)

    def get_coi_plan(self, plan_id, headers):
        return self._request("GET", f"/tlo/coi-plans/{plan_id}", headers=headers)

    def approve_coi_plan(self, plan_id, headers):
        return self._request("POST", f"/tlo/coi-plans/{plan_id}/approve", {}, headers)

    def reject_coi_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/tlo/coi-plans/{plan_id}/reject", payload, headers)

    def revise_coi_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/tlo/coi-plans/{plan_id}", payload, headers)

    # --- Licenses ---
    def create_license(self, disclosure_id, payload, headers):
        return self._request("POST", f"/tlo/disclosures/{disclosure_id}/licenses",
                             payload, headers)

    def list_licenses(self, disclosure_id, headers, params=None):
        return self._request("GET", f"/tlo/disclosures/{disclosure_id}/licenses",
                             headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/tlo/licenses/{license_id}", headers=headers)

    def counter_license(self, license_id, payload, headers):
        return self._request("POST", f"/tlo/licenses/{license_id}/counter",
                             payload, headers)

    def execute_license(self, license_id, payload, headers):
        return self._request("POST", f"/tlo/licenses/{license_id}/execute",
                             payload, headers)

    def declare_default(self, license_id, payload, headers):
        return self._request("POST", f"/tlo/licenses/{license_id}/declare-default",
                             payload, headers)

    def cure_license(self, license_id, headers):
        return self._request("POST", f"/tlo/licenses/{license_id}/cure", {}, headers)

    def terminate_license(self, license_id, payload, headers):
        return self._request("POST", f"/tlo/licenses/{license_id}/terminate",
                             payload, headers)

    # --- Milestones ---
    def create_milestone(self, license_id, payload, headers):
        return self._request("POST", f"/tlo/licenses/{license_id}/milestones",
                             payload, headers)

    def list_milestones(self, license_id, headers, params=None):
        return self._request("GET", f"/tlo/licenses/{license_id}/milestones",
                             headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/tlo/milestones/{milestone_id}", headers=headers)

    def achieve_milestone(self, license_id, milestone_id, headers):
        return self._request(
            "POST",
            f"/tlo/licenses/{license_id}/milestones/{milestone_id}/achieve",
            {}, headers)

    def waive_milestone(self, license_id, milestone_id, payload, headers):
        return self._request(
            "POST",
            f"/tlo/licenses/{license_id}/milestones/{milestone_id}/waive",
            payload, headers)

    # --- Royalty reports ---
    def create_royalty_report(self, license_id, payload, headers):
        return self._request("POST", f"/tlo/licenses/{license_id}/royalty-reports",
                             payload, headers)

    def list_royalty_reports(self, license_id, headers, params=None):
        return self._request("GET", f"/tlo/licenses/{license_id}/royalty-reports",
                             headers=headers, params=params)

    def get_royalty_report(self, report_id, headers):
        return self._request("GET", f"/tlo/royalty-reports/{report_id}", headers=headers)

    def accept_royalty_report(self, report_id, headers):
        return self._request("POST", f"/tlo/royalty-reports/{report_id}/accept",
                             {}, headers)

    # --- Royalty distributions ---
    def create_distribution(self, report_id, headers):
        return self._request("POST", f"/tlo/royalty-reports/{report_id}/distribution",
                             {}, headers)

    def get_report_distribution(self, report_id, headers):
        return self._request("GET", f"/tlo/royalty-reports/{report_id}/distribution",
                             headers=headers)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/tlo/distributions/{distribution_id}",
                             headers=headers)

    def recalculate_distribution(self, distribution_id, headers):
        return self._request("POST",
                             f"/tlo/distributions/{distribution_id}/recalculate",
                             {}, headers)

    def approve_distribution(self, distribution_id, payload, headers):
        return self._request("POST", f"/tlo/distributions/{distribution_id}/approve",
                             payload, headers)

    def pay_distribution(self, distribution_id, headers):
        return self._request("POST", f"/tlo/distributions/{distribution_id}/pay",
                             {}, headers)

    def cancel_distribution(self, distribution_id, payload, headers):
        return self._request("POST", f"/tlo/distributions/{distribution_id}/cancel",
                             payload, headers)

    # --- Federal compliance reports ---
    def create_compliance_report(self, disclosure_id, payload, headers):
        return self._request("POST",
                             f"/tlo/disclosures/{disclosure_id}/compliance-reports",
                             payload, headers)

    def list_compliance_reports(self, disclosure_id, headers, params=None):
        return self._request("GET",
                             f"/tlo/disclosures/{disclosure_id}/compliance-reports",
                             headers=headers, params=params)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/tlo/compliance-reports/{report_id}",
                             headers=headers)

    def submit_compliance_report(self, report_id, headers):
        return self._request("POST", f"/tlo/compliance-reports/{report_id}/submit",
                             {}, headers)

    def certify_compliance_report(self, report_id, headers):
        return self._request("POST", f"/tlo/compliance-reports/{report_id}/certify",
                             {}, headers)

    def reject_compliance_report(self, report_id, payload, headers):
        return self._request("POST", f"/tlo/compliance-reports/{report_id}/reject",
                             payload, headers)

    def record_agency_response(self, report_id, payload, headers):
        return self._request("POST",
                             f"/tlo/compliance-reports/{report_id}/agency-response",
                             payload, headers)


api_client = ApiClient()
