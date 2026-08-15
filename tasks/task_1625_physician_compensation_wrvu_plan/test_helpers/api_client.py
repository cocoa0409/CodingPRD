"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (PRD §2.4) ───
    def set_clock(self, payload, headers):
        return self._request("POST", "/comp/_clock/set_current_utc", payload, headers)

    # ─── Physician roster (PRD §3.1) ───
    def create_physician(self, payload, headers):
        return self._request("POST", "/comp/physicians", payload, headers)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/comp/physicians/{physician_id}", headers=headers)

    # ─── Compensation plans (PRD §3.1-§3.2) ───
    def create_comp_plan(self, payload, headers):
        return self._request("POST", "/comp/comp-plans", payload, headers)

    def get_comp_plan(self, plan_id, headers):
        return self._request("GET", f"/comp/comp-plans/{plan_id}", headers=headers)

    def list_successor_plans(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/comp/comp-plans/{plan_id}/successor-plans", headers=headers, params=params
        )

    def update_comp_plan(self, plan_id, payload, headers):
        return self._request("PUT", f"/comp/comp-plans/{plan_id}", payload, headers)

    def submit_plan_review(self, plan_id, headers):
        return self._request("POST", f"/comp/comp-plans/{plan_id}/submit-review", {}, headers)

    def plan_review_decision(self, plan_id, payload, headers):
        return self._request("POST", f"/comp/comp-plans/{plan_id}/review-decision", payload, headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/comp/comp-plans/{plan_id}/activate", {}, headers)

    def close_plan(self, plan_id, headers):
        return self._request("POST", f"/comp/comp-plans/{plan_id}/close", {}, headers)

    # ─── CPT rate rows (PRD §3.1) ───
    def create_cpt_rate(self, plan_id, payload, headers):
        return self._request("POST", f"/comp/comp-plans/{plan_id}/cpt-rates", payload, headers)

    def list_cpt_rates(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/comp/comp-plans/{plan_id}/cpt-rates", headers=headers, params=params
        )

    def delete_cpt_rate(self, rate_id, headers):
        return self._request("DELETE", f"/comp/cpt-rates/{rate_id}", headers=headers)

    # ─── Physician agreements (PRD §3.3) ───
    def create_agreement(self, payload, headers):
        return self._request("POST", "/comp/physician-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/comp/physician-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/comp/physician-agreements/{agreement_id}", headers=headers)

    def submit_fmv(self, agreement_id, headers):
        return self._request(
            "POST", f"/comp/physician-agreements/{agreement_id}/submit-fmv", {}, headers
        )

    def fmv_review(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/comp/physician-agreements/{agreement_id}/fmv-review", payload, headers
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/comp/physician-agreements/{agreement_id}/activate", {}, headers
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/comp/physician-agreements/{agreement_id}/terminate", {}, headers
        )

    def repin_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/comp/physician-agreements/{agreement_id}/repin", {}, headers
        )

    # ─── Production captures (PRD §3.4) ───
    def create_capture(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/comp/physician-agreements/{agreement_id}/production-captures", payload, headers
        )

    def list_captures(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/comp/physician-agreements/{agreement_id}/production-captures",
            headers=headers,
            params=params,
        )

    def get_capture(self, capture_id, headers):
        return self._request("GET", f"/comp/production-captures/{capture_id}", headers=headers)

    def list_capture_corrections(self, capture_id, headers, params=None):
        return self._request(
            "GET", f"/comp/production-captures/{capture_id}/corrections", headers=headers, params=params
        )

    def list_supervision_credits(self, capture_id, headers, params=None):
        return self._request(
            "GET",
            f"/comp/production-captures/{capture_id}/supervision-credits",
            headers=headers,
            params=params,
        )

    def list_capture_disputes(self, capture_id, headers, params=None):
        return self._request(
            "GET", f"/comp/production-captures/{capture_id}/disputes", headers=headers, params=params
        )

    def validate_capture(self, capture_id, headers):
        return self._request("POST", f"/comp/production-captures/{capture_id}/validate", {}, headers)

    def void_capture(self, capture_id, headers):
        return self._request("POST", f"/comp/production-captures/{capture_id}/void", {}, headers)

    # ─── Supervision assignments (PRD §3.5) ───
    def create_supervision_assignment(self, payload, headers):
        return self._request("POST", "/comp/supervision-assignments", payload, headers)

    def list_supervision_assignments(self, headers, params=None):
        return self._request("GET", "/comp/supervision-assignments", headers=headers, params=params)

    def get_supervision_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/comp/supervision-assignments/{assignment_id}", headers=headers
        )

    def end_supervision_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/comp/supervision-assignments/{assignment_id}/end", payload, headers
        )

    # ─── Quality scorecards (PRD §3.6) ───
    def create_scorecard(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/comp/physician-agreements/{agreement_id}/quality-scorecards", payload, headers
        )

    def list_scorecards(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/comp/physician-agreements/{agreement_id}/quality-scorecards",
            headers=headers,
            params=params,
        )

    def finalize_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"/comp/quality-scorecards/{scorecard_id}/finalize", {}, headers)

    # ─── Compensation statements (PRD §3.7) ───
    def create_statement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/comp/physician-agreements/{agreement_id}/comp-statements", payload, headers
        )

    def list_statements(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/comp/physician-agreements/{agreement_id}/comp-statements",
            headers=headers,
            params=params,
        )

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/comp/comp-statements/{statement_id}", headers=headers)

    def submit_statement_review(self, statement_id, headers):
        return self._request(
            "POST", f"/comp/comp-statements/{statement_id}/submit-review", {}, headers
        )

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/comp/comp-statements/{statement_id}/finalize", {}, headers)

    def void_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/comp/comp-statements/{statement_id}/void", payload, headers)

    def list_statement_disputes(self, statement_id, headers, params=None):
        return self._request(
            "GET", f"/comp/comp-statements/{statement_id}/disputes", headers=headers, params=params
        )

    # ─── True-up runs (PRD §3.7) ───
    def create_trueup_run(self, plan_id, payload, headers):
        return self._request("POST", f"/comp/comp-plans/{plan_id}/true-up-runs", payload, headers)

    def list_trueup_runs(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/comp/comp-plans/{plan_id}/true-up-runs", headers=headers, params=params
        )

    def post_trueup_run(self, run_id, headers):
        return self._request("POST", f"/comp/true-up-runs/{run_id}/post", {}, headers)

    def void_trueup_run(self, run_id, headers):
        return self._request("POST", f"/comp/true-up-runs/{run_id}/void", {}, headers)

    # ─── Disputes (PRD §3.8) ───
    def create_dispute(self, payload, headers):
        return self._request("POST", "/comp/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/comp/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/comp/disputes/{dispute_id}", headers=headers)

    def start_dispute_review(self, dispute_id, headers):
        return self._request("POST", f"/comp/disputes/{dispute_id}/start-review", {}, headers)

    def request_correction(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/comp/disputes/{dispute_id}/request-correction", payload, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/comp/disputes/{dispute_id}/resolve", payload, headers)

    # ─── Plan change requests (PRD §3.9) ───
    def create_plan_change_request(self, payload, headers):
        return self._request("POST", "/comp/plan-change-requests", payload, headers)

    def list_plan_change_requests(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/comp/comp-plans/{plan_id}/plan-change-requests", headers=headers, params=params
        )

    def get_plan_change_request(self, pcr_id, headers):
        return self._request("GET", f"/comp/plan-change-requests/{pcr_id}", headers=headers)

    def model_plan_change(self, pcr_id, headers):
        return self._request("POST", f"/comp/plan-change-requests/{pcr_id}/model", {}, headers)

    def communicate_plan_change(self, pcr_id, headers):
        return self._request("POST", f"/comp/plan-change-requests/{pcr_id}/communicate", {}, headers)

    def revise_plan_change(self, pcr_id, headers):
        return self._request("POST", f"/comp/plan-change-requests/{pcr_id}/revise", {}, headers)

    def acknowledge_plan_change(self, pcr_id, headers):
        return self._request("POST", f"/comp/plan-change-requests/{pcr_id}/acknowledge", {}, headers)

    def activate_plan_change(self, pcr_id, headers):
        return self._request("POST", f"/comp/plan-change-requests/{pcr_id}/activate", {}, headers)

    def withdraw_plan_change(self, pcr_id, headers):
        return self._request("POST", f"/comp/plan-change-requests/{pcr_id}/withdraw", {}, headers)


api_client = ApiClient()
