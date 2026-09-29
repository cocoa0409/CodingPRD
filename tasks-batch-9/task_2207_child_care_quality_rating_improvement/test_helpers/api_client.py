"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock and operational checkpoints -------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    def run_expiry_run(self, headers, payload=None):
        return self._request("POST", "/qris/expiry-runs", payload or {}, headers=headers)

    # --- Standard domains ---------------------------------------------------
    def create_standard_domain(self, payload, headers):
        return self._request("POST", "/standard-domains", payload, headers=headers)

    def list_standard_domains(self, headers, params=None):
        return self._request("GET", "/standard-domains", headers=headers, params=params)

    # --- Providers ----------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def decide_enrollment(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/enrollment-decisions", payload, headers=headers
        )

    def change_provider_status(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/status-changes", payload, headers=headers
        )

    # --- Staff credentials --------------------------------------------------
    def create_staff_credential(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/staff-credentials", payload, headers=headers
        )

    def list_staff_credentials(self, headers, params=None):
        return self._request("GET", "/staff-credentials", headers=headers, params=params)

    def get_staff_credential(self, credential_id, headers):
        return self._request("GET", f"/staff-credentials/{credential_id}", headers=headers)

    def registry_link(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/staff-credentials/{credential_id}/registry-link", payload, headers=headers
        )

    def get_credential_compliance(self, provider_id, headers):
        return self._request(
            "GET", f"/providers/{provider_id}/credential-compliance", headers=headers
        )

    # --- Rating cycles ------------------------------------------------------
    def create_rating_cycle(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/rating-cycles", payload, headers=headers
        )

    def list_rating_cycles(self, headers, params=None):
        return self._request("GET", "/rating-cycles", headers=headers, params=params)

    def get_rating_cycle(self, rating_cycle_id, headers):
        return self._request("GET", f"/rating-cycles/{rating_cycle_id}", headers=headers)

    def get_score_preview(self, rating_cycle_id, headers, params=None):
        return self._request(
            "GET", f"/rating-cycles/{rating_cycle_id}/score-preview", headers=headers, params=params
        )

    # --- Self-assessments ---------------------------------------------------
    def create_self_assessment(self, rating_cycle_id, payload, headers):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/self-assessments", payload, headers=headers
        )

    def list_self_assessments(self, headers, params=None):
        return self._request("GET", "/self-assessments", headers=headers, params=params)

    def get_self_assessment(self, self_assessment_id, headers):
        return self._request("GET", f"/self-assessments/{self_assessment_id}", headers=headers)

    def decide_verification(self, self_assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/self-assessments/{self_assessment_id}/verification-decisions",
            payload,
            headers=headers,
        )

    # --- Observers ----------------------------------------------------------
    def create_observer(self, payload, headers):
        return self._request("POST", "/observers", payload, headers=headers)

    def list_observers(self, headers, params=None):
        return self._request("GET", "/observers", headers=headers, params=params)

    def certify_observer(self, observer_id, payload, headers):
        return self._request(
            "POST", f"/observers/{observer_id}/reliability-certifications", payload, headers=headers
        )

    # --- Observation visits and scores --------------------------------------
    def create_observation_visit(self, rating_cycle_id, payload, headers):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/observation-visits", payload, headers=headers
        )

    def list_observation_visits(self, headers, params=None):
        return self._request("GET", "/observation-visits", headers=headers, params=params)

    def get_observation_visit(self, observation_visit_id, headers):
        return self._request(
            "GET", f"/observation-visits/{observation_visit_id}", headers=headers
        )

    def submit_score(self, observation_visit_id, payload, headers):
        return self._request(
            "POST", f"/observation-visits/{observation_visit_id}/scores", payload, headers=headers
        )

    def list_observation_scores(self, headers, params=None):
        return self._request("GET", "/observation-scores", headers=headers, params=params)

    def get_observation_score(self, observation_score_id, headers):
        return self._request(
            "GET", f"/observation-scores/{observation_score_id}", headers=headers
        )

    def finalize_visit(self, observation_visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/observation-visits/{observation_visit_id}/finalize",
            payload or {},
            headers=headers,
        )

    def cancel_visit(self, observation_visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/observation-visits/{observation_visit_id}/cancel",
            payload or {},
            headers=headers,
        )

    # --- Award and publication ---------------------------------------------
    def award_cycle(self, rating_cycle_id, payload, headers):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/award", payload, headers=headers
        )

    def publish_cycle(self, rating_cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/publish", payload or {}, headers=headers
        )

    def list_public_ratings(self, headers, params=None):
        return self._request("GET", "/public/ratings", headers=headers, params=params)

    # --- Appeals ------------------------------------------------------------
    def create_appeal(self, rating_cycle_id, payload, headers):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/appeals", payload, headers=headers
        )

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def appeal_review_action(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/review-actions", payload, headers=headers
        )

    def appeal_provider_action(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/provider-actions", payload, headers=headers
        )

    # --- Published-data disputes -------------------------------------------
    def create_data_dispute(self, rating_cycle_id, payload, headers):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/data-disputes", payload, headers=headers
        )

    def list_data_disputes(self, headers, params=None):
        return self._request("GET", "/data-disputes", headers=headers, params=params)

    def get_data_dispute(self, data_dispute_id, headers):
        return self._request("GET", f"/data-disputes/{data_dispute_id}", headers=headers)

    def dispute_triage_action(self, data_dispute_id, payload, headers):
        return self._request(
            "POST", f"/data-disputes/{data_dispute_id}/triage-actions", payload, headers=headers
        )

    # --- Improvement grants -------------------------------------------------
    def create_improvement_grant(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/improvement-grants", payload, headers=headers
        )

    def list_improvement_grants(self, headers, params=None):
        return self._request("GET", "/improvement-grants", headers=headers, params=params)

    def get_improvement_grant(self, improvement_grant_id, headers):
        return self._request(
            "GET", f"/improvement-grants/{improvement_grant_id}", headers=headers
        )

    def grant_decision(self, improvement_grant_id, payload, headers):
        return self._request(
            "POST", f"/improvement-grants/{improvement_grant_id}/accept", payload, headers=headers
        )

    def create_expenditure(self, improvement_grant_id, payload, headers):
        return self._request(
            "POST",
            f"/improvement-grants/{improvement_grant_id}/expenditures",
            payload,
            headers=headers,
        )

    def list_grant_expenditures(self, headers, params=None):
        return self._request("GET", "/grant-expenditures", headers=headers, params=params)

    def get_grant_expenditure(self, grant_expenditure_id, headers):
        return self._request(
            "GET", f"/grant-expenditures/{grant_expenditure_id}", headers=headers
        )

    def adjudicate_expenditure(self, grant_expenditure_id, payload, headers):
        return self._request(
            "POST",
            f"/grant-expenditures/{grant_expenditure_id}/adjudicate",
            payload,
            headers=headers,
        )

    def reimburse_grant(self, improvement_grant_id, headers, payload=None):
        return self._request(
            "POST",
            f"/improvement-grants/{improvement_grant_id}/reimburse",
            payload or {},
            headers=headers,
        )

    def close_grant(self, improvement_grant_id, headers, payload=None):
        return self._request(
            "POST",
            f"/improvement-grants/{improvement_grant_id}/close",
            payload or {},
            headers=headers,
        )

    # --- Coaching -----------------------------------------------------------
    def create_coaching_allocation(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/coaching-allocations", payload, headers=headers
        )

    def list_coaching_allocations(self, headers, params=None):
        return self._request("GET", "/coaching-allocations", headers=headers, params=params)

    def get_coaching_allocation(self, coaching_allocation_id, headers):
        return self._request(
            "GET", f"/coaching-allocations/{coaching_allocation_id}", headers=headers
        )

    def accept_coaching_allocation(self, coaching_allocation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/coaching-allocations/{coaching_allocation_id}/accept",
            payload or {},
            headers=headers,
        )

    def create_coaching_session(self, coaching_allocation_id, payload, headers):
        return self._request(
            "POST",
            f"/coaching-allocations/{coaching_allocation_id}/sessions",
            payload,
            headers=headers,
        )

    def list_coaching_sessions(self, headers, params=None):
        return self._request("GET", "/coaching-sessions", headers=headers, params=params)

    def get_coaching_session(self, coaching_session_id, headers):
        return self._request("GET", f"/coaching-sessions/{coaching_session_id}", headers=headers)

    def complete_coaching_session(self, coaching_session_id, payload, headers):
        return self._request(
            "POST", f"/coaching-sessions/{coaching_session_id}/complete", payload, headers=headers
        )

    def cancel_coaching_session(self, coaching_session_id, headers, payload=None):
        return self._request(
            "POST",
            f"/coaching-sessions/{coaching_session_id}/cancel",
            payload or {},
            headers=headers,
        )

    # --- Subsidy claims -----------------------------------------------------
    def create_subsidy_claim(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/subsidy-claims", payload, headers=headers
        )

    def list_subsidy_claims(self, headers, params=None):
        return self._request("GET", "/subsidy-claims", headers=headers, params=params)

    def get_subsidy_claim(self, subsidy_claim_id, headers):
        return self._request("GET", f"/subsidy-claims/{subsidy_claim_id}", headers=headers)

    def adjudicate_claim(self, subsidy_claim_id, payload, headers):
        return self._request(
            "POST", f"/subsidy-claims/{subsidy_claim_id}/adjudicate", payload, headers=headers
        )

    def pay_claim(self, subsidy_claim_id, headers, payload=None):
        return self._request(
            "POST", f"/subsidy-claims/{subsidy_claim_id}/pay", payload or {}, headers=headers
        )


api_client = ApiClient()
