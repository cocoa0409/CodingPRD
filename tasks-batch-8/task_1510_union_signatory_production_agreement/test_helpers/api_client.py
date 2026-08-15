"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving capability, PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ProducerCompany ---
    def create_producer_company(self, payload, headers):
        return self._request("POST", "/union-compliance/producer-companies", payload, headers)

    def get_producer_company(self, company_id, headers):
        return self._request("GET", f"/union-compliance/producer-companies/{company_id}", headers=headers)

    def list_company_applications(self, company_id, headers, params=None):
        return self._request(
            "GET", f"/union-compliance/producer-companies/{company_id}/signatory-applications",
            headers=headers, params=params,
        )

    def list_company_productions(self, company_id, headers, params=None):
        return self._request(
            "GET", f"/union-compliance/producer-companies/{company_id}/productions",
            headers=headers, params=params,
        )

    # --- SignatoryApplication ---
    def create_signatory_application(self, payload, headers):
        return self._request("POST", "/union-compliance/signatory-applications", payload, headers)

    def submit_application(self, application_id, payload, headers):
        return self._request("POST", f"/union-compliance/signatory-applications/{application_id}/submit", payload, headers)

    def request_info(self, application_id, payload, headers):
        return self._request("POST", f"/union-compliance/signatory-applications/{application_id}/request-info", payload, headers)

    def provide_info(self, application_id, payload, headers):
        return self._request("POST", f"/union-compliance/signatory-applications/{application_id}/provide-info", payload, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/union-compliance/signatory-applications/{application_id}/decide", payload, headers)

    # --- Production ---
    def create_production(self, payload, headers):
        return self._request("POST", "/union-compliance/productions", payload, headers)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/union-compliance/productions/{production_id}", headers=headers)

    def create_budget_revision(self, production_id, payload, headers):
        return self._request("POST", f"/union-compliance/productions/{production_id}/budget-revisions", payload, headers)

    def start_production(self, production_id, headers):
        return self._request("POST", f"/union-compliance/productions/{production_id}/start-production", {}, headers)

    def wrap_production(self, production_id, headers):
        return self._request("POST", f"/union-compliance/productions/{production_id}/wrap-production", {}, headers)

    def close_production(self, production_id, headers):
        return self._request("POST", f"/union-compliance/productions/{production_id}/close", {}, headers)

    def list_production_bonds(self, production_id, headers, params=None):
        return self._request("GET", f"/union-compliance/productions/{production_id}/bonds", headers=headers, params=params)

    def list_production_crew_assignments(self, production_id, headers, params=None):
        return self._request("GET", f"/union-compliance/productions/{production_id}/crew-assignments", headers=headers, params=params)

    def list_production_grievances(self, production_id, headers, params=None):
        return self._request("GET", f"/union-compliance/productions/{production_id}/grievances", headers=headers, params=params)

    def list_production_contribution_reports(self, production_id, headers, params=None):
        return self._request("GET", f"/union-compliance/productions/{production_id}/contribution-reports", headers=headers, params=params)

    def list_production_audits(self, production_id, headers, params=None):
        return self._request("GET", f"/union-compliance/productions/{production_id}/audits", headers=headers, params=params)

    def list_production_force_majeure_events(self, production_id, headers, params=None):
        return self._request("GET", f"/union-compliance/productions/{production_id}/force-majeure-events", headers=headers, params=params)

    # --- Bond ---
    def post_bond(self, bond_id, payload, headers):
        return self._request("POST", f"/union-compliance/bonds/{bond_id}/post", payload, headers)

    def top_up_bond(self, bond_id, payload, headers):
        return self._request("POST", f"/union-compliance/bonds/{bond_id}/top-up", payload, headers)

    def release_bond(self, bond_id, headers):
        return self._request("POST", f"/union-compliance/bonds/{bond_id}/release", {}, headers)

    # --- CrewAssignment ---
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/union-compliance/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/union-compliance/crew-assignments/{assignment_id}", headers=headers)

    def list_assignment_work_day_logs(self, assignment_id, headers, params=None):
        return self._request("GET", f"/union-compliance/crew-assignments/{assignment_id}/work-day-logs", headers=headers, params=params)

    def list_assignment_grievances(self, assignment_id, headers, params=None):
        return self._request("GET", f"/union-compliance/crew-assignments/{assignment_id}/grievances", headers=headers, params=params)

    def transition_crew_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/union-compliance/crew-assignments/{assignment_id}/transition", payload, headers)

    # --- WorkDayLog ---
    def create_work_day_log(self, payload, headers):
        return self._request("POST", "/union-compliance/work-day-logs", payload, headers)

    def submit_work_day_log(self, log_id, headers):
        return self._request("POST", f"/union-compliance/work-day-logs/{log_id}/submit", {}, headers)

    def void_work_day_log(self, log_id, headers):
        return self._request("POST", f"/union-compliance/work-day-logs/{log_id}/void", {}, headers)

    # --- Grievance ---
    def create_grievance(self, payload, headers):
        return self._request("POST", "/union-compliance/grievances", payload, headers)

    def accept_grievance_intake(self, grievance_id, headers):
        return self._request("POST", f"/union-compliance/grievances/{grievance_id}/accept-intake", {}, headers)

    def propose_settlement(self, grievance_id, payload, headers):
        return self._request("POST", f"/union-compliance/grievances/{grievance_id}/propose-settlement", payload, headers)

    def respond_settlement(self, grievance_id, payload, headers):
        return self._request("POST", f"/union-compliance/grievances/{grievance_id}/respond-settlement", payload, headers)

    def escalate_grievance(self, grievance_id, headers):
        return self._request("POST", f"/union-compliance/grievances/{grievance_id}/escalate", {}, headers)

    def decide_grievance(self, grievance_id, payload, headers):
        return self._request("POST", f"/union-compliance/grievances/{grievance_id}/decide", payload, headers)

    def pay_grievance(self, grievance_id, payload, headers):
        return self._request("POST", f"/union-compliance/grievances/{grievance_id}/payments", payload, headers)

    def refund_grievance(self, grievance_id, payload, headers):
        return self._request("POST", f"/union-compliance/grievances/{grievance_id}/refunds", payload, headers)

    # --- ContributionReport ---
    def create_contribution_report(self, payload, headers):
        return self._request("POST", "/union-compliance/contribution-reports", payload, headers)

    def submit_contribution_report(self, report_id, headers):
        return self._request("POST", f"/union-compliance/contribution-reports/{report_id}/submit", {}, headers)

    def review_contribution_report(self, report_id, payload, headers):
        return self._request("POST", f"/union-compliance/contribution-reports/{report_id}/review", payload, headers)

    # --- Audit ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/union-compliance/audits", payload, headers)

    def issue_audit_findings(self, audit_id, headers):
        return self._request("POST", f"/union-compliance/audits/{audit_id}/issue-findings", {}, headers)

    def pay_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/union-compliance/audits/{audit_id}/payments", payload, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/union-compliance/audits/{audit_id}/close", {}, headers)

    # --- ForceMajeureEvent ---
    def create_force_majeure_event(self, payload, headers):
        return self._request("POST", "/union-compliance/force-majeure-events", payload, headers)

    def lift_force_majeure_event(self, event_id, headers):
        return self._request("POST", f"/union-compliance/force-majeure-events/{event_id}/lift", {}, headers)


api_client = ApiClient()
