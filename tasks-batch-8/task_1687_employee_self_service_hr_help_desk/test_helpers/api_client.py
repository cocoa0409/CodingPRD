"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Employees ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/hr-helpdesk/employees/{employee_id}", headers=headers)

    def set_employee_status(self, employee_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/employees/{employee_id}/status", payload, headers)

    def get_employee_audit_log(self, employee_id, headers, params=None):
        return self._request("GET", f"/hr-helpdesk/employees/{employee_id}/audit-log", headers=headers, params=params)

    # ---- Teams ----
    def create_team(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/teams", payload, headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/teams", headers=headers, params=params)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/hr-helpdesk/teams/{team_id}", headers=headers)

    # ---- Agents ----
    def create_agent(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/hr-helpdesk/agents/{agent_id}", headers=headers)

    # ---- Ticket categories ----
    def create_category(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/ticket-categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/ticket-categories", headers=headers, params=params)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/hr-helpdesk/ticket-categories/{category_id}", headers=headers)

    # ---- SLA policies ----
    def create_sla_policy(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/sla-policies", payload, headers)

    def list_sla_policies(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/sla-policies", headers=headers, params=params)

    def list_category_sla_policies(self, category_id, headers, params=None):
        return self._request(
            "GET", f"/hr-helpdesk/ticket-categories/{category_id}/sla-policies",
            headers=headers, params=params,
        )

    # ---- Knowledge base articles ----
    def create_kb_article(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/kb-articles", payload, headers)

    def list_kb_articles(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/kb-articles", headers=headers, params=params)

    def get_kb_article(self, article_id, headers):
        return self._request("GET", f"/hr-helpdesk/kb-articles/{article_id}", headers=headers)

    def submit_article_review(self, article_id, headers):
        return self._request("POST", f"/hr-helpdesk/kb-articles/{article_id}/submit-review", {}, headers)

    def publish_kb_article(self, article_id, headers):
        return self._request("POST", f"/hr-helpdesk/kb-articles/{article_id}/publish", {}, headers)

    def return_article_draft(self, article_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/kb-articles/{article_id}/return-draft", payload, headers)

    def archive_kb_article(self, article_id, headers):
        return self._request("POST", f"/hr-helpdesk/kb-articles/{article_id}/archive", {}, headers)

    # ---- Article views ----
    def create_article_view(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/article-views", payload, headers)

    def list_article_views(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/article-views", headers=headers, params=params)

    def get_article_view(self, view_id, headers):
        return self._request("GET", f"/hr-helpdesk/article-views/{view_id}", headers=headers)

    # ---- Tickets ----
    def create_ticket(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/tickets", payload, headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/hr-helpdesk/tickets/{ticket_id}", headers=headers)

    def triage_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/triage", payload, headers)

    def assign_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/assign", payload, headers)

    def respond_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/respond", payload, headers)

    def request_ticket_info(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/request-info", payload, headers)

    def provide_ticket_info(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/provide-info", payload, headers)

    def escalate_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/escalate", payload, headers)

    def resolve_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/resolve", payload, headers)

    def reopen_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/reopen", payload, headers)

    def close_ticket(self, ticket_id, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/close", {}, headers)

    def cancel_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/tickets/{ticket_id}/cancel", payload, headers)

    def list_ticket_events(self, ticket_id, headers, params=None):
        return self._request("GET", f"/hr-helpdesk/tickets/{ticket_id}/events", headers=headers, params=params)

    # ---- Data change requests & fraud verification ----
    def create_data_change_request(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/data-change-requests", payload, headers)

    def list_data_change_requests(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/data-change-requests", headers=headers, params=params)

    def get_data_change_request(self, dcr_id, headers):
        return self._request("GET", f"/hr-helpdesk/data-change-requests/{dcr_id}", headers=headers)

    def list_fraud_verifications(self, dcr_id, headers, params=None):
        return self._request(
            "GET", f"/hr-helpdesk/data-change-requests/{dcr_id}/fraud-verifications",
            headers=headers, params=params,
        )

    def verify_data_change_request(self, dcr_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/data-change-requests/{dcr_id}/verify", payload, headers)

    def approve_data_change_request(self, dcr_id, headers):
        return self._request("POST", f"/hr-helpdesk/data-change-requests/{dcr_id}/approve", {}, headers)

    def reject_data_change_request(self, dcr_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/data-change-requests/{dcr_id}/reject", payload, headers)

    def cancel_data_change_request(self, dcr_id, headers):
        return self._request("POST", f"/hr-helpdesk/data-change-requests/{dcr_id}/cancel", {}, headers)

    # ---- Surveys ----
    def list_surveys(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/hr-helpdesk/surveys/{survey_id}", headers=headers)

    def submit_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/hr-helpdesk/surveys/{survey_id}/submit", payload, headers)

    # ---- Seasonal staffing ----
    def create_staffing_window(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/staffing-windows", payload, headers)

    def list_staffing_windows(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/staffing-windows", headers=headers, params=params)

    def get_staffing_window(self, window_id, headers):
        return self._request("GET", f"/hr-helpdesk/staffing-windows/{window_id}", headers=headers)

    def cancel_staffing_window(self, window_id, headers):
        return self._request("POST", f"/hr-helpdesk/staffing-windows/{window_id}/cancel", {}, headers)

    def create_agent_shift(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/agent-shifts", payload, headers)

    def list_agent_shifts(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/agent-shifts", headers=headers, params=params)

    def get_agent_shift(self, shift_id, headers):
        return self._request("GET", f"/hr-helpdesk/agent-shifts/{shift_id}", headers=headers)

    def cancel_agent_shift(self, shift_id, headers):
        return self._request("POST", f"/hr-helpdesk/agent-shifts/{shift_id}/cancel", {}, headers)

    # ---- Audit trail ----
    def list_audit_log_entries(self, headers, params=None):
        return self._request("GET", "/hr-helpdesk/audit-log-entries", headers=headers, params=params)

    def get_audit_log_entry(self, entry_id, headers):
        return self._request("GET", f"/hr-helpdesk/audit-log-entries/{entry_id}", headers=headers)

    # ---- Metrics ----
    def get_deflection_metrics(self, headers, params):
        return self._request("GET", "/hr-helpdesk/metrics/deflection", headers=headers, params=params)

    def get_sla_attainment(self, headers, params):
        return self._request("GET", "/hr-helpdesk/metrics/sla-attainment", headers=headers, params=params)

    def get_csat_metrics(self, headers, params):
        return self._request("GET", "/hr-helpdesk/metrics/csat", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/hr-helpdesk/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
