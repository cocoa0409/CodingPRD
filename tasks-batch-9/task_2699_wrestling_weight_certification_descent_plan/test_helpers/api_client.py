"""
One method per declared endpoint.

All resources are mounted at the root of the host with no additional URL
prefix.  Every method returns the raw ``requests.Response`` so that tests can
assert on the status code as well as on the body.  List methods take an
optional ``params`` dictionary that is forwarded as the query string.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP client for the Wrestling Weight Certification API."""

    # ── The logical clock ────────────────────────────────────────────
    def set_clock(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Seasons ──────────────────────────────────────────────────────
    def create_season(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/seasons/{season_id}", None, headers)

    def set_season_status(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/seasons/{season_id}/status", payload, headers)

    def create_growth_allowance(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/growth-allowances", payload, headers
        )

    def list_growth_allowances(
        self,
        season_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/seasons/{season_id}/growth-allowances", params, headers
        )

    def list_season_teams(
        self,
        season_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"/seasons/{season_id}/teams", params, headers)

    def run_compliance(
        self, season_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/compliance-run", {}, headers
        )

    # ── Teams ────────────────────────────────────────────────────────
    def create_team(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/teams", payload, headers)

    def get_team(self, team_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/teams/{team_id}", None, headers)

    # ── Assessors ────────────────────────────────────────────────────
    def create_assessor(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/assessors", payload, headers)

    def get_assessor(
        self, assessor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/assessors/{assessor_id}", None, headers)

    def create_training_record(
        self, assessor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/assessors/{assessor_id}/training-records", payload, headers
        )

    def suspend_assessor(
        self, assessor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/assessors/{assessor_id}/suspension", payload, headers
        )

    # ── Wrestlers ────────────────────────────────────────────────────
    def create_wrestler(
        self, team_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/teams/{team_id}/wrestlers", payload, headers)

    def get_wrestler(
        self, wrestler_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/wrestlers/{wrestler_id}", None, headers)

    def list_wrestlers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/wrestlers", params, headers)

    def disqualify_wrestler(
        self, wrestler_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/wrestlers/{wrestler_id}/disqualification", payload, headers
        )

    # ── Assessments ──────────────────────────────────────────────────
    def create_assessment(
        self, wrestler_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/wrestlers/{wrestler_id}/assessments", payload, headers
        )

    def finalize_assessment(
        self, assessment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/assessments/{assessment_id}/finalize", {}, headers
        )

    def get_assessment(
        self, assessment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/assessments/{assessment_id}", None, headers)

    def list_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/assessments", params, headers)

    # ── Appeals ──────────────────────────────────────────────────────
    def create_appeal(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/assessments/{assessment_id}/appeals", payload, headers
        )

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/appeals/{appeal_id}", None, headers)

    def list_appeals(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/appeals", params, headers)

    def assign_appeal_reviewer(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/appeals/{appeal_id}/assign-reviewer", payload, headers
        )

    def order_appeal_retest(
        self, appeal_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/order-retest", {}, headers)

    def decide_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ── Descent plans ────────────────────────────────────────────────
    def create_descent_plan(
        self, wrestler_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/wrestlers/{wrestler_id}/descent-plans", payload, headers
        )

    def get_descent_plan(
        self, plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/descent-plans/{plan_id}", None, headers)

    def list_descent_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/descent-plans", params, headers)

    def certify_descent_plan(
        self, plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/descent-plans/{plan_id}/certify", {}, headers)

    def revise_descent_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/descent-plans/{plan_id}/revise", payload, headers
        )

    def list_plan_milestones(
        self,
        plan_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/descent-plans/{plan_id}/milestones", params, headers
        )

    # ── Events ───────────────────────────────────────────────────────
    def create_event(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/seasons/{season_id}/events", payload, headers)

    def get_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/events/{event_id}", None, headers)

    def list_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/events", params, headers)

    def set_event_status(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/status", payload, headers)

    def seed_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/seed", {}, headers)

    # ── Tournament entries ───────────────────────────────────────────
    def create_entry(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/entries", payload, headers)

    def get_entry(self, entry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/entries/{entry_id}", None, headers)

    def list_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/entries", params, headers)

    def change_entry_weight_class(
        self, entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/entries/{entry_id}/weight-class-change", payload, headers
        )

    # ── Weigh-ins ────────────────────────────────────────────────────
    def create_weigh_in(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/weigh-ins", payload, headers)

    def get_weigh_in(
        self, weigh_in_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/weigh-ins/{weigh_in_id}", None, headers)

    def list_weigh_ins(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/weigh-ins", params, headers)

    # ── Eligibility checks ───────────────────────────────────────────
    def create_eligibility_check(
        self, wrestler_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/wrestlers/{wrestler_id}/eligibility-checks", payload, headers
        )

    def get_eligibility_check(
        self, check_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/eligibility-checks/{check_id}", None, headers)

    def list_eligibility_checks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/eligibility-checks", params, headers)

    # ── Health flags ─────────────────────────────────────────────────
    def get_health_flag(
        self, flag_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/health-flags/{flag_id}", None, headers)

    def list_health_flags(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/health-flags", params, headers)

    def review_health_flag(
        self, flag_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/health-flags/{flag_id}/review", payload, headers
        )

    # ── Program audits ───────────────────────────────────────────────
    def create_audit(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/seasons/{season_id}/audits", payload, headers)

    def get_audit(self, audit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audits/{audit_id}", None, headers)

    def list_audits(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/audits", params, headers)

    def finalize_audit(
        self, audit_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/audits/{audit_id}/finalize", {}, headers)
