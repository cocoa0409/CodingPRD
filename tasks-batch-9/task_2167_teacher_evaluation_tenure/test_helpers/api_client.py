"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Evaluation policies ──────────────────────────────────────────────
    def create_evaluation_policy(self, payload, headers):
        return self._request("POST", "/evaluation-policies", payload, headers)

    def get_evaluation_policy(self, policy_id, headers):
        return self._request("GET", f"/evaluation-policies/{policy_id}", headers=headers)

    # ─── Schools ──────────────────────────────────────────────────────────
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    # ─── Educators ────────────────────────────────────────────────────────
    def create_educator(self, payload, headers):
        return self._request("POST", "/educators", payload, headers)

    def get_educator(self, educator_id, headers):
        return self._request("GET", f"/educators/{educator_id}", headers=headers)

    def list_educators(self, headers, params=None):
        return self._request("GET", "/educators", headers=headers, params=params)

    def tenure_recommendation(self, educator_id, payload, headers):
        return self._request(
            "POST", f"/educators/{educator_id}/tenure-recommendation", payload, headers
        )

    def tenure_decision(self, educator_id, payload, headers):
        return self._request(
            "POST", f"/educators/{educator_id}/tenure-decision", payload, headers
        )

    # ─── Evaluators & calibration ─────────────────────────────────────────
    def create_evaluator(self, payload, headers):
        return self._request("POST", "/evaluators", payload, headers)

    def get_evaluator(self, evaluator_id, headers):
        return self._request("GET", f"/evaluators/{evaluator_id}", headers=headers)

    def create_calibration_review(self, payload, headers):
        return self._request("POST", "/calibration-reviews", payload, headers)

    def list_calibration_reviews(self, evaluator_id, headers, params=None):
        return self._request(
            "GET", f"/evaluators/{evaluator_id}/calibration-reviews",
            headers=headers, params=params,
        )

    def decide_calibration_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/calibration-reviews/{review_id}/decide", payload, headers
        )

    # ─── Evaluation cycles ────────────────────────────────────────────────
    def create_evaluation_cycle(self, payload, headers):
        return self._request("POST", "/evaluation-cycles", payload, headers)

    def get_evaluation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/evaluation-cycles/{cycle_id}", headers=headers)

    def list_evaluation_cycles(self, headers, params=None):
        return self._request("GET", "/evaluation-cycles", headers=headers, params=params)

    def submit_evaluation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/evaluation-cycles/{cycle_id}/submit", {}, headers)

    def finalize_evaluation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/evaluation-cycles/{cycle_id}/finalize", {}, headers)

    def close_evaluation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/evaluation-cycles/{cycle_id}/close", {}, headers)

    # ─── Observations ─────────────────────────────────────────────────────
    def create_observation(self, payload, headers):
        return self._request("POST", "/observations", payload, headers)

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"/observations/{observation_id}", headers=headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", "/observations", headers=headers, params=params)

    def conduct_observation(self, observation_id, headers):
        return self._request("POST", f"/observations/{observation_id}/conduct", {}, headers)

    def create_rubric_score(self, observation_id, payload, headers):
        return self._request(
            "POST", f"/observations/{observation_id}/rubric-scores", payload, headers
        )

    def list_rubric_scores(self, observation_id, headers, params=None):
        return self._request(
            "GET", f"/observations/{observation_id}/rubric-scores",
            headers=headers, params=params,
        )

    def create_evidence_artifact(self, observation_id, payload, headers):
        return self._request(
            "POST", f"/observations/{observation_id}/evidence-artifacts", payload, headers
        )

    def list_evidence_artifacts(self, observation_id, headers, params=None):
        return self._request(
            "GET", f"/observations/{observation_id}/evidence-artifacts",
            headers=headers, params=params,
        )

    def withdraw_evidence_artifact(self, artifact_id, headers):
        return self._request(
            "POST", f"/evidence-artifacts/{artifact_id}/withdraw", {}, headers
        )

    def submit_observation(self, observation_id, headers):
        return self._request("POST", f"/observations/{observation_id}/submit", {}, headers)

    def return_observation(self, observation_id, payload, headers):
        return self._request(
            "POST", f"/observations/{observation_id}/return", payload, headers
        )

    def accept_observation(self, observation_id, headers):
        return self._request("POST", f"/observations/{observation_id}/accept", {}, headers)

    def void_observation(self, observation_id, payload, headers):
        return self._request("POST", f"/observations/{observation_id}/void", payload, headers)

    # ─── Growth measures ──────────────────────────────────────────────────
    def create_growth_measure(self, payload, headers):
        return self._request("POST", "/growth-measures", payload, headers)

    def list_growth_measures(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/evaluation-cycles/{cycle_id}/growth-measures",
            headers=headers, params=params,
        )

    def certify_growth_measure(self, measure_id, headers):
        return self._request("POST", f"/growth-measures/{measure_id}/certify", {}, headers)

    # ─── Improvement plans ────────────────────────────────────────────────
    def get_improvement_plan(self, plan_id, headers):
        return self._request("GET", f"/improvement-plans/{plan_id}", headers=headers)

    def list_improvement_plans(self, headers, params=None):
        return self._request("GET", "/improvement-plans", headers=headers, params=params)

    def extend_improvement_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/improvement-plans/{plan_id}/extend", payload, headers)

    def close_improvement_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/improvement-plans/{plan_id}/close", payload, headers)

    # ─── Appeals ──────────────────────────────────────────────────────────
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def review_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/review", {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ─── Grievances ───────────────────────────────────────────────────────
    def create_grievance(self, payload, headers):
        return self._request("POST", "/grievances", payload, headers)

    def get_grievance(self, grievance_id, headers):
        return self._request("GET", f"/grievances/{grievance_id}", headers=headers)

    def list_grievances(self, headers, params=None):
        return self._request("GET", "/grievances", headers=headers, params=params)

    def decide_grievance(self, grievance_id, payload, headers):
        return self._request("POST", f"/grievances/{grievance_id}/decide", payload, headers)

    # ─── Reports & clock ──────────────────────────────────────────────────
    def get_rating_distribution(self, headers, params=None):
        return self._request(
            "GET", "/reports/rating-distribution", headers=headers, params=params
        )

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
