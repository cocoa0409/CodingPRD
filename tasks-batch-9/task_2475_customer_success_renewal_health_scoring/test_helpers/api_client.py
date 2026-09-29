"""Typed client covering every endpoint declared in PRD §4.

One method per row of the endpoint table, in table order. Each method takes the
caller's headers explicitly, because almost every rule in this API is scoped by
role or by acting-user identity and a test must be able to vary the caller
freely.

PRD §4 declares single-row reads for accounts, managers, coverage assignments,
sponsor contacts, save plays, escalation cases, renewal forecasts and expansion
opportunities only. Signals, executive engagements, outcome goals, onboarding
milestones, remediation commitments and advocacy enrollments are readable
through their listing endpoints, so this client exposes no `get_*` method for
them and tests reach those rows through the list calls.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH, DAILY_SWEEP_PATH


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper over the customer-success HTTP surface."""

    def patch(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> requests.Response:
        """PATCH verb.

        `GenericApiClient` ships get/post/put/delete only, while PRD §4 declares
        three PATCH endpoints (`PATCH /accounts/{id}`, `PATCH /csms/{id}` and
        `PATCH /sponsor-contacts/{id}`), so the verb is added here.
        """
        return self._request("PATCH", path, payload=json, headers=headers)

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    def create_account(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /accounts"""
        return self.post("/accounts", json=payload, headers=headers)

    def get_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /accounts/{id}"""
        return self.get(f"/accounts/{account_id}", headers=headers)

    def list_accounts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /accounts"""
        return self.get("/accounts", headers=headers, params=params)

    def patch_account(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /accounts/{id}"""
        return self.patch(f"/accounts/{account_id}", json=payload, headers=headers)

    def account_lifecycle(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /accounts/{id}/lifecycle"""
        return self.post(
            f"/accounts/{account_id}/lifecycle", json=payload, headers=headers
        )

    def health_recompute(
        self,
        account_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /accounts/{id}/health-recompute"""
        return self.post(
            f"/accounts/{account_id}/health-recompute",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def segment_account(
        self,
        account_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /accounts/{id}/segmentation"""
        return self.post(
            f"/accounts/{account_id}/segmentation",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_health_summary(
        self, account_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /accounts/{id}/health-summary"""
        return self.get(f"/accounts/{account_id}/health-summary", headers=headers)

    # ------------------------------------------------------------------
    # Customer-success managers
    # ------------------------------------------------------------------

    def create_csm(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /csms"""
        return self.post("/csms", json=payload, headers=headers)

    def get_csm(self, csm_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /csms/{id}"""
        return self.get(f"/csms/{csm_id}", headers=headers)

    def patch_csm(
        self, csm_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /csms/{id}"""
        return self.patch(f"/csms/{csm_id}", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Coverage assignments
    # ------------------------------------------------------------------

    def create_coverage_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /coverage-assignments"""
        return self.post("/coverage-assignments", json=payload, headers=headers)

    def get_coverage_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /coverage-assignments/{id}"""
        return self.get(f"/coverage-assignments/{assignment_id}", headers=headers)

    def list_coverage_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /coverage-assignments"""
        return self.get("/coverage-assignments", headers=headers, params=params)

    def release_coverage_assignment(
        self,
        assignment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /coverage-assignments/{id}/release"""
        return self.post(
            f"/coverage-assignments/{assignment_id}/release",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Account signals
    # ------------------------------------------------------------------

    def create_signal(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /accounts/{id}/signals"""
        return self.post(
            f"/accounts/{account_id}/signals", json=payload, headers=headers
        )

    def list_signals(
        self,
        account_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /accounts/{id}/signals"""
        return self.get(
            f"/accounts/{account_id}/signals", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Sponsor contacts
    # ------------------------------------------------------------------

    def create_sponsor_contact(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /accounts/{id}/sponsor-contacts"""
        return self.post(
            f"/accounts/{account_id}/sponsor-contacts", json=payload, headers=headers
        )

    def get_sponsor_contact(
        self, sponsor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /sponsor-contacts/{id}"""
        return self.get(f"/sponsor-contacts/{sponsor_id}", headers=headers)

    def list_sponsor_contacts(
        self,
        account_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /accounts/{id}/sponsor-contacts"""
        return self.get(
            f"/accounts/{account_id}/sponsor-contacts", headers=headers, params=params
        )

    def patch_sponsor_contact(
        self, sponsor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """PATCH /sponsor-contacts/{id}"""
        return self.patch(
            f"/sponsor-contacts/{sponsor_id}", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Executive engagements
    # ------------------------------------------------------------------

    def create_executive_engagement(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /accounts/{id}/executive-engagements"""
        return self.post(
            f"/accounts/{account_id}/executive-engagements",
            json=payload,
            headers=headers,
        )

    def list_account_engagements(
        self,
        account_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /accounts/{id}/executive-engagements"""
        return self.get(
            f"/accounts/{account_id}/executive-engagements",
            headers=headers,
            params=params,
        )

    def list_sponsor_engagements(
        self,
        sponsor_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /sponsor-contacts/{id}/executive-engagements"""
        return self.get(
            f"/sponsor-contacts/{sponsor_id}/executive-engagements",
            headers=headers,
            params=params,
        )

    def record_engagement_outcome(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /executive-engagements/{id}/outcome"""
        return self.post(
            f"/executive-engagements/{engagement_id}/outcome",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Outcome goals
    # ------------------------------------------------------------------

    def create_outcome_goal(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /accounts/{id}/outcome-goals"""
        return self.post(
            f"/accounts/{account_id}/outcome-goals", json=payload, headers=headers
        )

    def list_outcome_goals(
        self,
        account_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /accounts/{id}/outcome-goals"""
        return self.get(
            f"/accounts/{account_id}/outcome-goals", headers=headers, params=params
        )

    def record_goal_progress(
        self, goal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /outcome-goals/{id}/progress"""
        return self.post(
            f"/outcome-goals/{goal_id}/progress", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Onboarding milestones
    # ------------------------------------------------------------------

    def create_milestone(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /accounts/{id}/onboarding-milestones"""
        return self.post(
            f"/accounts/{account_id}/onboarding-milestones",
            json=payload,
            headers=headers,
        )

    def list_milestones(
        self,
        account_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /accounts/{id}/onboarding-milestones"""
        return self.get(
            f"/accounts/{account_id}/onboarding-milestones",
            headers=headers,
            params=params,
        )

    def transition_milestone(
        self, milestone_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /onboarding-milestones/{id}/transition"""
        return self.post(
            f"/onboarding-milestones/{milestone_id}/transition",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Save plays
    # ------------------------------------------------------------------

    def create_save_play(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /save-plays"""
        return self.post("/save-plays", json=payload, headers=headers)

    def get_save_play(self, play_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /save-plays/{id}"""
        return self.get(f"/save-plays/{play_id}", headers=headers)

    def list_save_plays(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /save-plays"""
        return self.get("/save-plays", headers=headers, params=params)

    def transition_save_play(
        self, play_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /save-plays/{id}/transition"""
        return self.post(
            f"/save-plays/{play_id}/transition", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Escalation cases and remediation commitments
    # ------------------------------------------------------------------

    def create_escalation_case(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /escalation-cases"""
        return self.post("/escalation-cases", json=payload, headers=headers)

    def get_escalation_case(
        self, case_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /escalation-cases/{id}"""
        return self.get(f"/escalation-cases/{case_id}", headers=headers)

    def list_escalation_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /escalation-cases"""
        return self.get("/escalation-cases", headers=headers, params=params)

    def transition_escalation_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /escalation-cases/{id}/transition"""
        return self.post(
            f"/escalation-cases/{case_id}/transition", json=payload, headers=headers
        )

    def create_remediation_commitment(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /escalation-cases/{id}/remediation-commitments"""
        return self.post(
            f"/escalation-cases/{case_id}/remediation-commitments",
            json=payload,
            headers=headers,
        )

    def list_remediation_commitments(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /escalation-cases/{id}/remediation-commitments"""
        return self.get(
            f"/escalation-cases/{case_id}/remediation-commitments",
            headers=headers,
            params=params,
        )

    def transition_remediation_commitment(
        self, commitment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /remediation-commitments/{id}/transition"""
        return self.post(
            f"/remediation-commitments/{commitment_id}/transition",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Renewal forecasts
    # ------------------------------------------------------------------

    def create_renewal_forecast(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /renewal-forecasts"""
        return self.post("/renewal-forecasts", json=payload, headers=headers)

    def get_renewal_forecast(
        self, forecast_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /renewal-forecasts/{id}"""
        return self.get(f"/renewal-forecasts/{forecast_id}", headers=headers)

    def list_renewal_forecasts(
        self,
        account_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /accounts/{id}/renewal-forecasts"""
        return self.get(
            f"/accounts/{account_id}/renewal-forecasts", headers=headers, params=params
        )

    def submit_renewal_forecast(
        self,
        forecast_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """POST /renewal-forecasts/{id}/submit"""
        return self.post(
            f"/renewal-forecasts/{forecast_id}/submit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def reconcile_renewal_forecast(
        self, forecast_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /renewal-forecasts/{id}/reconcile"""
        return self.post(
            f"/renewal-forecasts/{forecast_id}/reconcile", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Expansion opportunities
    # ------------------------------------------------------------------

    def create_expansion_opportunity(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /expansion-opportunities"""
        return self.post("/expansion-opportunities", json=payload, headers=headers)

    def get_expansion_opportunity(
        self, opportunity_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /expansion-opportunities/{id}"""
        return self.get(f"/expansion-opportunities/{opportunity_id}", headers=headers)

    def list_expansion_opportunities(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /expansion-opportunities"""
        return self.get("/expansion-opportunities", headers=headers, params=params)

    def transition_expansion_opportunity(
        self, opportunity_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /expansion-opportunities/{id}/transition"""
        return self.post(
            f"/expansion-opportunities/{opportunity_id}/transition",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Advocacy enrollments
    # ------------------------------------------------------------------

    def create_advocacy_enrollment(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /accounts/{id}/advocacy-enrollments"""
        return self.post(
            f"/accounts/{account_id}/advocacy-enrollments",
            json=payload,
            headers=headers,
        )

    def list_advocacy_enrollments(
        self,
        account_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /accounts/{id}/advocacy-enrollments"""
        return self.get(
            f"/accounts/{account_id}/advocacy-enrollments",
            headers=headers,
            params=params,
        )

    def transition_advocacy_enrollment(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /advocacy-enrollments/{id}/transition"""
        return self.post(
            f"/advocacy-enrollments/{enrollment_id}/transition",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Logical clock and operational sweep
    # ------------------------------------------------------------------

    def set_clock(
        self, current_utc: str, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /_clock/set_current_utc"""
        return self.post(
            CLOCK_PATH, json={"current_utc": current_utc}, headers=headers
        )

    def run_daily_sweep(
        self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """POST /_ops/daily-sweep"""
        return self.post(
            DAILY_SWEEP_PATH,
            json=payload if payload is not None else {},
            headers=headers,
        )
