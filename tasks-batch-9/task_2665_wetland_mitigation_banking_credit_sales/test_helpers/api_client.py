"""API client: one method per endpoint defined in the PRD.

All business endpoints are mounted under the /mitigation prefix; the logical
clock administration endpoint lives outside it.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/mitigation"


class ApiClient(GenericApiClient):
    # ── Sponsors ──────────────────────────────────────
    def create_sponsor(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/sponsors/{sponsor_id}", headers=headers)

    # ── Permittees ────────────────────────────────────
    def create_permittee(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/permittees", payload, headers)

    def get_permittee(self, permittee_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/permittees/{permittee_id}", headers=headers
        )

    def create_deposit(self, permittee_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/permittees/{permittee_id}/deposits", payload, headers
        )

    # ── Review team members ───────────────────────────
    def create_irt_member(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/irt-members", payload, headers)

    def get_irt_member(self, member_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/irt-members/{member_id}", headers=headers
        )

    def list_member_votes(self, member_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/irt-members/{member_id}/votes", headers=headers, params=params
        )

    # ── Mitigation banks ──────────────────────────────
    def create_bank(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/banks", payload, headers)

    def get_bank(self, bank_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/banks/{bank_id}", headers=headers)

    def list_banks(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/banks", headers=headers, params=params)

    def list_bank_prospectuses(self, bank_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/banks/{bank_id}/prospectuses", headers=headers, params=params
        )

    def list_bank_work_plans(self, bank_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/banks/{bank_id}/work-plans", headers=headers, params=params
        )

    def list_bank_performance_standards(
        self, bank_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/banks/{bank_id}/performance-standards",
            headers=headers,
            params=params,
        )

    def list_bank_ledger(self, bank_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/banks/{bank_id}/ledger", headers=headers, params=params
        )

    def get_credit_forecast(self, bank_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/banks/{bank_id}/credit-forecast", headers=headers, params=params
        )

    def execute_instrument(self, bank_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/banks/{bank_id}/execute-instrument", payload or {}, headers
        )

    def record_conservation_easement(self, bank_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/banks/{bank_id}/conservation-easement", payload, headers
        )

    def create_stewardship_contribution(self, bank_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/banks/{bank_id}/stewardship-contributions", payload, headers
        )

    def close_bank(self, bank_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/banks/{bank_id}/close", payload or {}, headers
        )

    # ── Prospectuses ──────────────────────────────────
    def create_prospectus(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/prospectuses", payload, headers)

    def get_prospectus(self, prospectus_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/prospectuses/{prospectus_id}", headers=headers
        )

    def submit_prospectus(self, prospectus_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/prospectuses/{prospectus_id}/submit", payload or {}, headers
        )

    def create_prospectus_vote(self, prospectus_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/prospectuses/{prospectus_id}/votes", payload, headers
        )

    def list_prospectus_votes(
        self, prospectus_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/prospectuses/{prospectus_id}/votes", headers=headers, params=params
        )

    def finalize_prospectus_review(self, prospectus_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST",
            f"{PREFIX}/prospectuses/{prospectus_id}/finalize-review",
            payload or {},
            headers,
        )

    # ── Work plans ────────────────────────────────────
    def create_work_plan(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/work-plans", payload, headers)

    def submit_work_plan(self, work_plan_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/work-plans/{work_plan_id}/submit", payload or {}, headers
        )

    def decide_work_plan(self, work_plan_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/work-plans/{work_plan_id}/decide", payload, headers
        )

    # ── Release milestones ────────────────────────────
    def create_milestone(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/milestones", payload, headers)

    def get_milestone(self, milestone_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/milestones", headers=headers, params=params)

    def claim_milestone(self, milestone_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/milestones/{milestone_id}/claim", payload or {}, headers
        )

    def approve_milestone_release(self, milestone_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/milestones/{milestone_id}/approve-release", payload, headers
        )

    # ── Monitoring reports ────────────────────────────
    def create_monitoring_report(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/monitoring-reports", payload, headers)

    def get_monitoring_report(self, report_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/monitoring-reports/{report_id}", headers=headers
        )

    def list_monitoring_reports(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/monitoring-reports", headers=headers, params=params
        )

    def submit_monitoring_report(self, report_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/monitoring-reports/{report_id}/submit", payload or {}, headers
        )

    def review_monitoring_report(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/monitoring-reports/{report_id}/review", payload, headers
        )

    # ── Remedial actions ──────────────────────────────
    def get_remedial_action(self, action_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/remedial-actions/{action_id}", headers=headers
        )

    def list_remedial_actions(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/remedial-actions", headers=headers, params=params
        )

    def submit_remedial_work(self, action_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/remedial-actions/{action_id}/submit-work", payload or {}, headers
        )

    def inspect_remedial_action(self, action_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/remedial-actions/{action_id}/inspect", payload, headers
        )

    # ── Credit sales ──────────────────────────────────
    def create_credit_sale(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/credit-sales", payload, headers)

    def get_credit_sale(self, sale_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/credit-sales/{sale_id}", headers=headers)

    def list_credit_sales(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/credit-sales", headers=headers, params=params)

    def reserve_credit_sale(self, sale_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/credit-sales/{sale_id}/reserve", payload or {}, headers
        )

    def execute_credit_sale(self, sale_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/credit-sales/{sale_id}/execute", payload or {}, headers
        )

    def assign_credit_sale(self, sale_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/credit-sales/{sale_id}/assign", payload or {}, headers
        )

    def cancel_credit_sale(self, sale_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/credit-sales/{sale_id}/cancel", payload, headers
        )

    def reverse_credit_sale(self, sale_id: str, headers: dict, payload: Any = None):
        return self._request(
            "POST", f"{PREFIX}/credit-sales/{sale_id}/reverse", payload or {}, headers
        )

    # ── Logical clock ─────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Raw helpers for negative header tests ─────────
    def raw_get(self, path: str, headers: Optional[Dict[str, str]] = None, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path: str, payload: Any = None, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
