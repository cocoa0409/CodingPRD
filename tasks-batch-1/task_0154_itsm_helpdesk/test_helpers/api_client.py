"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------------- #
    # Category
    # ----------------------------------------------------------------- #
    def create_category(self, payload, headers):
        return self._request("POST", "/categories", payload, headers)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/categories/{category_id}", headers=headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/categories", headers=headers, params=params)

    # ----------------------------------------------------------------- #
    # SlaPolicy
    # ----------------------------------------------------------------- #
    def create_sla_policy(self, payload, headers):
        return self._request("POST", "/sla-policies", payload, headers)

    def get_sla_policy(self, policy_id, headers):
        return self._request("GET", f"/sla-policies/{policy_id}", headers=headers)

    # ----------------------------------------------------------------- #
    # AssignmentGroup
    # ----------------------------------------------------------------- #
    def create_assignment_group(self, payload, headers):
        return self._request("POST", "/assignment-groups", payload, headers)

    def get_assignment_group(self, group_id, headers):
        return self._request("GET", f"/assignment-groups/{group_id}", headers=headers)

    def get_group_load(self, group_id, headers):
        return self._request("GET", f"/assignment-groups/{group_id}/load", headers=headers)

    def get_group_csat(self, group_id, headers):
        return self._request("GET", f"/assignment-groups/{group_id}/csat", headers=headers)

    # ----------------------------------------------------------------- #
    # Ticket
    # ----------------------------------------------------------------- #
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def route_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/route", payload, headers)

    def assign_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/assign", payload, headers)

    def start_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/start", {}, headers)

    def reprioritize_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/reprioritize", payload, headers)

    def hold_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/hold", {}, headers)

    def resume_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/resume", {}, headers)

    def attach_change(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/attach-change", payload, headers)

    def link_problem(self, ticket_id, payload, headers):
        return self._request("POST", f"/tickets/{ticket_id}/link-problem", payload, headers)

    def resolve_ticket(self, ticket_id, headers, payload=None):
        return self._request("POST", f"/tickets/{ticket_id}/resolve", payload or {}, headers)

    def reopen_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/reopen", {}, headers)

    def close_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/close", {}, headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/cancel", {}, headers)

    # ----------------------------------------------------------------- #
    # Problem / KnownError
    # ----------------------------------------------------------------- #
    def create_problem(self, payload, headers):
        return self._request("POST", "/problems", payload, headers)

    def get_problem(self, problem_id, headers):
        return self._request("GET", f"/problems/{problem_id}", headers=headers)

    def list_problems(self, headers, params=None):
        return self._request("GET", "/problems", headers=headers, params=params)

    def identify_root_cause(self, problem_id, payload, headers):
        return self._request("POST", f"/problems/{problem_id}/identify-root-cause", payload, headers)

    def create_known_error(self, problem_id, payload, headers):
        return self._request("POST", f"/problems/{problem_id}/known-errors", payload, headers)

    def list_known_errors(self, problem_id, headers, params=None):
        return self._request("GET", f"/problems/{problem_id}/known-errors", headers=headers, params=params)

    def resolve_problem(self, problem_id, headers):
        return self._request("POST", f"/problems/{problem_id}/resolve", {}, headers)

    def get_known_error(self, known_error_id, headers):
        return self._request("GET", f"/known-errors/{known_error_id}", headers=headers)

    # ----------------------------------------------------------------- #
    # KbArticle
    # ----------------------------------------------------------------- #
    def create_kb_article(self, payload, headers):
        return self._request("POST", "/kb-articles", payload, headers)

    def get_kb_article(self, article_id, headers):
        return self._request("GET", f"/kb-articles/{article_id}", headers=headers)

    def list_kb_articles(self, headers, params=None):
        return self._request("GET", "/kb-articles", headers=headers, params=params)

    # ----------------------------------------------------------------- #
    # ChangeRequest / CabVote
    # ----------------------------------------------------------------- #
    def create_change_request(self, payload, headers):
        return self._request("POST", "/change-requests", payload, headers)

    def get_change_request(self, change_id, headers):
        return self._request("GET", f"/change-requests/{change_id}", headers=headers)

    def list_change_requests(self, headers, params=None):
        return self._request("GET", "/change-requests", headers=headers, params=params)

    def submit_change(self, change_id, headers):
        return self._request("POST", f"/change-requests/{change_id}/submit", {}, headers)

    def cast_vote(self, change_id, payload, headers):
        return self._request("POST", f"/change-requests/{change_id}/votes", payload, headers)

    def list_votes(self, change_id, headers, params=None):
        return self._request("GET", f"/change-requests/{change_id}/votes", headers=headers, params=params)

    def implement_change(self, change_id, headers):
        return self._request("POST", f"/change-requests/{change_id}/implement", {}, headers)

    def fail_change(self, change_id, headers):
        return self._request("POST", f"/change-requests/{change_id}/fail", {}, headers)

    # ----------------------------------------------------------------- #
    # CsatSurvey
    # ----------------------------------------------------------------- #
    def create_csat_survey(self, payload, headers):
        return self._request("POST", "/csat-surveys", payload, headers)

    def get_csat_survey(self, survey_id, headers):
        return self._request("GET", f"/csat-surveys/{survey_id}", headers=headers)

    def list_csat_surveys(self, headers, params=None):
        return self._request("GET", "/csat-surveys", headers=headers, params=params)

    # ----------------------------------------------------------------- #
    # Asset
    # ----------------------------------------------------------------- #
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_asset_tickets(self, asset_id, headers, params=None):
        return self._request("GET", f"/assets/{asset_id}/tickets", headers=headers, params=params)

    def retire_asset(self, asset_id, headers):
        return self._request("POST", f"/assets/{asset_id}/retire", {}, headers)

    # ----------------------------------------------------------------- #
    # Test-driving clock
    # ----------------------------------------------------------------- #
    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
