"""API client: one method per endpoint defined in the Grant Management PRD (§4)."""
import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # Under --isolation per-test-server the runner restarts the server via
    # start.sh before every test. A pooled keep-alive socket left over from a
    # prior test can be handed a request against the freshly restarted process,
    # which surfaces as a stale-connection BadStatusLine/ConnectionError. This
    # is purely a test-client transport artifact (not an API behavior): force
    # Connection: close so no socket is reused, and retry once if the transport
    # still trips on a stale connection. PRD semantics are unaffected.
    def _request(self, method, path, payload=None, headers=None, params=None):
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        last_exc = None
        for _ in range(2):
            try:
                return super()._request(method, path, payload=payload, headers=hdrs, params=params)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError) as exc:
                last_exc = exc
                try:
                    self.session.close()
                except Exception:
                    pass
                self.session = requests.Session()
        raise last_exc

    # ---- NofoApplication ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/applications/{app_id}", headers=headers)

    def submit_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/submit", {}, headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/withdraw", {}, headers)

    def begin_review_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/begin-review", {}, headers)

    def request_revisions_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/request-revisions", {}, headers)

    def award_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/award", {}, headers)

    def reject_application(self, app_id, headers):
        return self._request("POST", f"/applications/{app_id}/reject", {}, headers)

    # ---- Award ----
    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def suspend_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/suspend", payload, headers)

    def reinstate_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/reinstate", payload, headers)

    def initiate_closeout_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/initiate-closeout", payload, headers)

    def close_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/close", payload, headers)

    # ---- IndirectCostRate ----
    def create_indirect_cost_rate(self, payload, headers):
        return self._request("POST", "/indirect-cost-rates", payload, headers)

    def list_indirect_cost_rates(self, headers, params=None):
        return self._request("GET", "/indirect-cost-rates", headers=headers, params=params)

    def get_indirect_cost_rate(self, rate_id, headers):
        return self._request("GET", f"/indirect-cost-rates/{rate_id}", headers=headers)

    # ---- Subaward ----
    def create_subaward(self, payload, headers):
        return self._request("POST", "/subawards", payload, headers)

    def list_subawards(self, headers, params=None):
        return self._request("GET", "/subawards", headers=headers, params=params)

    def get_subaward(self, sub_id, headers):
        return self._request("GET", f"/subawards/{sub_id}", headers=headers)

    def approve_subaward(self, sub_id, headers):
        return self._request("POST", f"/subawards/{sub_id}/approve", {}, headers)

    def activate_subaward(self, sub_id, headers):
        return self._request("POST", f"/subawards/{sub_id}/activate", {}, headers)

    def terminate_subaward(self, sub_id, headers):
        return self._request("POST", f"/subawards/{sub_id}/terminate", {}, headers)

    # ---- RestrictedFund ----
    def create_restricted_fund(self, payload, headers):
        return self._request("POST", "/restricted-funds", payload, headers)

    def list_restricted_funds(self, headers, params=None):
        return self._request("GET", "/restricted-funds", headers=headers, params=params)

    def get_restricted_fund(self, fund_id, headers):
        return self._request("GET", f"/restricted-funds/{fund_id}", headers=headers)

    def list_fund_allocations(self, fund_id, headers, params=None):
        return self._request("GET", f"/restricted-funds/{fund_id}/allocations", headers=headers, params=params)

    # ---- Drawdown ----
    def create_drawdown(self, payload, headers):
        return self._request("POST", "/drawdowns", payload, headers)

    def list_drawdowns(self, headers, params=None):
        return self._request("GET", "/drawdowns", headers=headers, params=params)

    def get_drawdown(self, dd_id, headers):
        return self._request("GET", f"/drawdowns/{dd_id}", headers=headers)

    def list_drawdown_allocations(self, dd_id, headers, params=None):
        return self._request("GET", f"/drawdowns/{dd_id}/allocations", headers=headers, params=params)

    def disburse_drawdown(self, dd_id, headers):
        return self._request("POST", f"/drawdowns/{dd_id}/disburse", {}, headers)

    def return_drawdown(self, dd_id, headers):
        return self._request("POST", f"/drawdowns/{dd_id}/return", {}, headers)

    # ---- FinancialReport ----
    def create_financial_report(self, payload, headers):
        return self._request("POST", "/financial-reports", payload, headers)

    def list_financial_reports(self, headers, params=None):
        return self._request("GET", "/financial-reports", headers=headers, params=params)

    def get_financial_report(self, fr_id, headers):
        return self._request("GET", f"/financial-reports/{fr_id}", headers=headers)

    def certify_financial_report(self, fr_id, headers):
        return self._request("POST", f"/financial-reports/{fr_id}/certify", {}, headers)

    def accept_financial_report(self, fr_id, headers):
        return self._request("POST", f"/financial-reports/{fr_id}/accept", {}, headers)

    def reject_financial_report(self, fr_id, headers):
        return self._request("POST", f"/financial-reports/{fr_id}/reject", {}, headers)

    def revise_financial_report(self, fr_id, headers):
        return self._request("POST", f"/financial-reports/{fr_id}/revise", {}, headers)

    # ---- ProgressReport ----
    def create_progress_report(self, payload, headers):
        return self._request("POST", "/progress-reports", payload, headers)

    def list_progress_reports(self, headers, params=None):
        return self._request("GET", "/progress-reports", headers=headers, params=params)

    def get_progress_report(self, pr_id, headers):
        return self._request("GET", f"/progress-reports/{pr_id}", headers=headers)

    def accept_progress_report(self, pr_id, headers):
        return self._request("POST", f"/progress-reports/{pr_id}/accept", {}, headers)

    def return_progress_report(self, pr_id, headers):
        return self._request("POST", f"/progress-reports/{pr_id}/return", {}, headers)

    def resubmit_progress_report(self, pr_id, headers):
        return self._request("POST", f"/progress-reports/{pr_id}/resubmit", {}, headers)

    # ---- SingleAudit / AuditFinding ----
    def create_single_audit(self, payload, headers):
        return self._request("POST", "/single-audits", payload, headers)

    def list_single_audits(self, headers, params=None):
        return self._request("GET", "/single-audits", headers=headers, params=params)

    def get_single_audit(self, sa_id, headers):
        return self._request("GET", f"/single-audits/{sa_id}", headers=headers)

    def submit_single_audit(self, sa_id, headers):
        return self._request("POST", f"/single-audits/{sa_id}/submit", {}, headers)

    def resolve_single_audit(self, sa_id, headers):
        return self._request("POST", f"/single-audits/{sa_id}/resolve", {}, headers)

    def create_finding(self, sa_id, payload, headers):
        return self._request("POST", f"/single-audits/{sa_id}/findings", payload, headers)

    def list_findings(self, sa_id, headers, params=None):
        return self._request("GET", f"/single-audits/{sa_id}/findings", headers=headers, params=params)

    def resolve_finding(self, finding_id, headers):
        return self._request("POST", f"/audit-findings/{finding_id}/resolve", {}, headers)


api_client = ApiClient()
