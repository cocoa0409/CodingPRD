"""API client with one method per declared endpoint."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Bonus plans ──────────────────────────────────────────────────────
    def create_bonus_plan(self, payload, headers):
        return self._request("POST", "/bonus-plans", payload, headers)

    def list_bonus_plans(self, headers, params=None):
        return self._request("GET", "/bonus-plans", headers=headers, params=params)

    def get_bonus_plan(self, plan_id, headers):
        return self._request("GET", f"/bonus-plans/{plan_id}", headers=headers)

    def get_funding_summary(self, plan_id, headers):
        return self._request(
            "GET", f"/bonus-plans/{plan_id}/funding-summary", headers=headers
        )

    def run_target_assignments(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/bonus-plans/{plan_id}/target-assignments", payload or {}, headers
        )

    def submit_plan_for_certification(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/bonus-plans/{plan_id}/submit-for-certification",
            payload or {},
            headers,
        )

    def decide_plan_certification(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/bonus-plans/{plan_id}/certification-decision", payload, headers
        )

    def fund_pool(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/bonus-plans/{plan_id}/fund-pool", payload or {}, headers
        )

    def open_calibration(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/bonus-plans/{plan_id}/open-calibration", payload or {}, headers
        )

    def lock_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/bonus-plans/{plan_id}/lock", payload or {}, headers
        )

    # ─── Company metrics ──────────────────────────────────────────────────
    def create_company_metric(self, payload, headers):
        return self._request("POST", "/company-metrics", payload, headers)

    def list_company_metrics(self, headers, params=None):
        return self._request("GET", "/company-metrics", headers=headers, params=params)

    def get_company_metric(self, metric_id, headers):
        return self._request("GET", f"/company-metrics/{metric_id}", headers=headers)

    def file_metric_actual(self, metric_id, payload, headers):
        return self._request(
            "POST", f"/company-metrics/{metric_id}/actual", payload, headers
        )

    # ─── Business units ───────────────────────────────────────────────────
    def create_business_unit(self, payload, headers):
        return self._request("POST", "/business-units", payload, headers)

    def list_business_units(self, headers, params=None):
        return self._request("GET", "/business-units", headers=headers, params=params)

    def get_business_unit(self, unit_id, headers):
        return self._request("GET", f"/business-units/{unit_id}", headers=headers)

    # ─── Job-level targets ────────────────────────────────────────────────
    def create_job_level_target(self, payload, headers):
        return self._request("POST", "/job-level-targets", payload, headers)

    def list_job_level_targets(self, headers, params=None):
        return self._request(
            "GET", "/job-level-targets", headers=headers, params=params
        )

    def get_job_level_target(self, target_id, headers):
        return self._request("GET", f"/job-level-targets/{target_id}", headers=headers)

    # ─── Participants ─────────────────────────────────────────────────────
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    # ─── Eligibility events ───────────────────────────────────────────────
    def create_eligibility_event(self, payload, headers):
        return self._request("POST", "/eligibility-events", payload, headers)

    def list_eligibility_events(self, headers, params=None):
        return self._request(
            "GET", "/eligibility-events", headers=headers, params=params
        )

    def get_eligibility_event(self, event_id, headers):
        return self._request(
            "GET", f"/eligibility-events/{event_id}", headers=headers
        )

    # ─── Business-unit pools ──────────────────────────────────────────────
    def create_bu_pool(self, payload, headers):
        return self._request("POST", "/bu-pools", payload, headers)

    def list_bu_pools(self, headers, params=None):
        return self._request("GET", "/bu-pools", headers=headers, params=params)

    def get_bu_pool(self, pool_id, headers):
        return self._request("GET", f"/bu-pools/{pool_id}", headers=headers)

    def submit_scorecard(self, pool_id, payload, headers):
        return self._request(
            "POST", f"/bu-pools/{pool_id}/submit-scorecard", payload, headers
        )

    def decide_scorecard(self, pool_id, payload, headers):
        return self._request(
            "POST", f"/bu-pools/{pool_id}/scorecard-decision", payload, headers
        )

    def submit_calibration(self, pool_id, headers, payload=None):
        return self._request(
            "POST", f"/bu-pools/{pool_id}/submit-calibration", payload or {}, headers
        )

    def decide_calibration(self, pool_id, payload, headers):
        return self._request(
            "POST", f"/bu-pools/{pool_id}/calibration-decision", payload, headers
        )

    # ─── Participant awards ───────────────────────────────────────────────
    def list_participant_awards(self, headers, params=None):
        return self._request(
            "GET", "/participant-awards", headers=headers, params=params
        )

    def get_participant_award(self, award_id, headers):
        return self._request(
            "GET", f"/participant-awards/{award_id}", headers=headers
        )

    def propose_allocation(self, award_id, payload, headers):
        return self._request(
            "POST", f"/participant-awards/{award_id}/propose-allocation", payload, headers
        )

    def retract_allocation(self, award_id, payload, headers):
        return self._request(
            "POST", f"/participant-awards/{award_id}/retract-allocation", payload, headers
        )

    def get_payout_preview(self, award_id, headers):
        return self._request(
            "GET", f"/participant-awards/{award_id}/payout-preview", headers=headers
        )

    # ─── Discretionary adjustments ────────────────────────────────────────
    def create_discretionary_adjustment(self, payload, headers):
        return self._request("POST", "/discretionary-adjustments", payload, headers)

    def list_discretionary_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/discretionary-adjustments", headers=headers, params=params
        )

    def get_discretionary_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/discretionary-adjustments/{adjustment_id}", headers=headers
        )

    def decide_discretionary_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST",
            f"/discretionary-adjustments/{adjustment_id}/decision",
            payload,
            headers,
        )

    def reverse_discretionary_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST",
            f"/discretionary-adjustments/{adjustment_id}/reverse",
            payload,
            headers,
        )

    # ─── Accrual periods ──────────────────────────────────────────────────
    def create_accrual_period(self, payload, headers):
        return self._request("POST", "/accrual-periods", payload, headers)

    def list_accrual_periods(self, headers, params=None):
        return self._request("GET", "/accrual-periods", headers=headers, params=params)

    def get_accrual_period(self, period_id, headers):
        return self._request("GET", f"/accrual-periods/{period_id}", headers=headers)

    def post_accrual_period(self, period_id, headers, payload=None):
        return self._request(
            "POST", f"/accrual-periods/{period_id}/post", payload or {}, headers
        )

    def reverse_accrual_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/accrual-periods/{period_id}/reverse", payload, headers
        )

    # ─── Payout runs ──────────────────────────────────────────────────────
    def create_payout_run(self, payload, headers):
        return self._request("POST", "/payout-runs", payload, headers)

    def list_payout_runs(self, headers, params=None):
        return self._request("GET", "/payout-runs", headers=headers, params=params)

    def get_payout_run(self, payout_run_id, headers):
        return self._request("GET", f"/payout-runs/{payout_run_id}", headers=headers)

    def execute_payout_run(self, payout_run_id, headers, payload=None):
        return self._request(
            "POST", f"/payout-runs/{payout_run_id}/execute", payload or {}, headers
        )

    def settle_true_up(self, payout_run_id, headers, payload=None):
        return self._request(
            "POST", f"/payout-runs/{payout_run_id}/settle-true-up", payload or {}, headers
        )

    # ─── Disputes ─────────────────────────────────────────────────────────
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def assign_dispute_review(self, dispute_id, headers, payload=None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/assign-review", payload or {}, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", payload, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
