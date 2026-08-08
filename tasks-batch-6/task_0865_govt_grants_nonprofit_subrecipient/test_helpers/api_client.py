"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
POST bodies default to an empty object for the many no-body transition endpoints.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Administrative clock ───
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Nonprofits ───
    def create_nonprofit(self, payload, headers):
        return self._request("POST", "/nonprofits", payload, headers)

    def get_nonprofit(self, nonprofit_id, headers):
        return self._request("GET", f"/nonprofits/{nonprofit_id}", headers=headers)

    def list_nonprofit_single_audits(self, nonprofit_id, headers, params=None):
        return self._request(
            "GET", f"/nonprofits/{nonprofit_id}/single-audits", headers=headers, params=params
        )

    # ─── NOFOs ───
    def create_nofo(self, payload, headers):
        return self._request("POST", "/nofos", payload, headers)

    def get_nofo(self, nofo_id, headers):
        return self._request("GET", f"/nofos/{nofo_id}", headers=headers)

    def close_intake(self, nofo_id, headers):
        return self._request("POST", f"/nofos/{nofo_id}/close-intake", {}, headers)

    # ─── Applications ───
    def create_application(self, nofo_id, payload, headers):
        return self._request("POST", f"/nofos/{nofo_id}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/start-review", {}, headers)

    def request_revision(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/request-revision", payload, headers
        )

    def award_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/award", {}, headers)

    def reject_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/reject", payload, headers)

    def create_review(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/reviews", payload, headers)

    def list_reviews(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/reviews", headers=headers, params=params
        )

    # ─── Subawards ───
    def get_subaward(self, subaward_id, headers):
        return self._request("GET", f"/subawards/{subaward_id}", headers=headers)

    def list_subawards(self, headers, params=None):
        return self._request("GET", "/subawards", headers=headers, params=params)

    def create_budget_line(self, subaward_id, payload, headers):
        return self._request("POST", f"/subawards/{subaward_id}/budget-lines", payload, headers)

    def list_budget_lines(self, subaward_id, headers, params=None):
        return self._request(
            "GET", f"/subawards/{subaward_id}/budget-lines", headers=headers, params=params
        )

    def activate_subaward(self, subaward_id, headers):
        return self._request("POST", f"/subawards/{subaward_id}/activate", {}, headers)

    def suspend_subaward(self, subaward_id, payload, headers):
        return self._request("POST", f"/subawards/{subaward_id}/suspend", payload, headers)

    def reinstate_subaward(self, subaward_id, headers):
        return self._request("POST", f"/subawards/{subaward_id}/reinstate", {}, headers)

    def terminate_subaward(self, subaward_id, payload, headers):
        return self._request("POST", f"/subawards/{subaward_id}/terminate", payload, headers)

    def initiate_closeout(self, subaward_id, headers):
        return self._request("POST", f"/subawards/{subaward_id}/initiate-closeout", {}, headers)

    def close_subaward(self, subaward_id, headers):
        return self._request("POST", f"/subawards/{subaward_id}/close", {}, headers)

    # ─── Drawdowns ───
    def create_drawdown(self, subaward_id, payload, headers):
        return self._request("POST", f"/subawards/{subaward_id}/drawdowns", payload, headers)

    def list_drawdowns(self, subaward_id, headers, params=None):
        return self._request(
            "GET", f"/subawards/{subaward_id}/drawdowns", headers=headers, params=params
        )

    def get_drawdown(self, drawdown_id, headers):
        return self._request("GET", f"/drawdowns/{drawdown_id}", headers=headers)

    def approve_drawdown(self, drawdown_id, payload, headers):
        return self._request("POST", f"/drawdowns/{drawdown_id}/approve", payload, headers)

    def return_drawdown(self, drawdown_id, payload, headers):
        return self._request("POST", f"/drawdowns/{drawdown_id}/return", payload, headers)

    def resubmit_drawdown(self, drawdown_id, headers):
        return self._request("POST", f"/drawdowns/{drawdown_id}/resubmit", {}, headers)

    def pay_drawdown(self, drawdown_id, headers):
        return self._request("POST", f"/drawdowns/{drawdown_id}/pay", {}, headers)

    # ─── Risk assessments ───
    def create_risk_assessment(self, subaward_id, headers):
        return self._request("POST", f"/subawards/{subaward_id}/risk-assessments", {}, headers)

    def list_risk_assessments(self, subaward_id, headers, params=None):
        return self._request(
            "GET", f"/subawards/{subaward_id}/risk-assessments", headers=headers, params=params
        )

    # ─── Monitoring visits ───
    def create_monitoring_visit(self, subaward_id, payload, headers):
        return self._request("POST", f"/subawards/{subaward_id}/monitoring-visits", payload, headers)

    def conduct_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/monitoring-visits/{visit_id}/conduct", payload, headers)

    def list_monitoring_visits(self, subaward_id, headers, params=None):
        return self._request(
            "GET", f"/subawards/{subaward_id}/monitoring-visits", headers=headers, params=params
        )

    # ─── Performance reports ───
    def create_performance_report(self, subaward_id, payload, headers):
        return self._request(
            "POST", f"/subawards/{subaward_id}/performance-reports", payload, headers
        )

    def list_performance_reports(self, subaward_id, headers, params=None):
        return self._request(
            "GET", f"/subawards/{subaward_id}/performance-reports", headers=headers, params=params
        )

    # ─── Single audits ───
    def create_single_audit(self, nonprofit_id, payload, headers):
        return self._request("POST", f"/nonprofits/{nonprofit_id}/single-audits", payload, headers)

    def accept_single_audit(self, audit_id, headers):
        return self._request("POST", f"/single-audits/{audit_id}/accept", {}, headers)

    # ─── Findings ───
    def list_findings(self, subaward_id, headers, params=None):
        return self._request(
            "GET", f"/subawards/{subaward_id}/findings", headers=headers, params=params
        )

    def submit_cap(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/submit-cap", payload, headers)

    def accept_cap(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/accept-cap", {}, headers)

    def reject_cap(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/reject-cap", payload, headers)

    def resolve_finding(self, finding_id, headers):
        return self._request("POST", f"/findings/{finding_id}/resolve", {}, headers)


api_client = ApiClient()
