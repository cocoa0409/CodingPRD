"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

All paths are mounted under /clinical-ladder. Methods return raw
requests.Response so tests can assert status codes and envelopes.
"""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/clinical-ladder"


class ApiClient(GenericApiClient):
    # --- Nurses ---
    def create_nurse(self, payload, headers):
        return self._request("POST", f"{BASE}/nurses", payload, headers)

    def list_nurses(self, headers, params=None):
        return self._request("GET", f"{BASE}/nurses", headers=headers, params=params)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"{BASE}/nurses/{nurse_id}", headers=headers)

    def list_nurse_participation_events(self, nurse_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/nurses/{nurse_id}/participation-events",
            headers=headers, params=params,
        )

    def list_nurse_certifications(self, nurse_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/nurses/{nurse_id}/certifications",
            headers=headers, params=params,
        )

    def list_nurse_applications(self, nurse_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/nurses/{nurse_id}/applications",
            headers=headers, params=params,
        )

    def list_nurse_anniversary_reviews(self, nurse_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/nurses/{nurse_id}/anniversary-reviews",
            headers=headers, params=params,
        )

    # --- Ladder criteria ---
    def create_ladder_criterion(self, payload, headers):
        return self._request("POST", f"{BASE}/ladder-criteria", payload, headers)

    def list_ladder_criteria(self, headers, params=None):
        return self._request("GET", f"{BASE}/ladder-criteria", headers=headers, params=params)

    def get_ladder_criterion(self, criterion_id, headers):
        return self._request("GET", f"{BASE}/ladder-criteria/{criterion_id}", headers=headers)

    # --- Participation events ---
    def create_participation_event(self, payload, headers):
        return self._request("POST", f"{BASE}/participation-events", payload, headers)

    def list_participation_events(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/participation-events", headers=headers, params=params
        )

    def verify_participation_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/participation-events/{event_id}/verify", {}, headers
        )

    def void_participation_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/participation-events/{event_id}/void", {}, headers
        )

    # --- Certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", f"{BASE}/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", f"{BASE}/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request(
            "GET", f"{BASE}/certifications/{certification_id}", headers=headers
        )

    def list_certification_claims(self, certification_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/certifications/{certification_id}/reimbursement-claims",
            headers=headers, params=params,
        )

    def list_certification_bonuses(self, certification_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/certifications/{certification_id}/certification-bonuses",
            headers=headers, params=params,
        )

    def revoke_certification(self, certification_id, headers):
        return self._request(
            "POST", f"{BASE}/certifications/{certification_id}/revoke", {}, headers
        )

    # --- Reimbursement claims ---
    def create_reimbursement_claim(self, payload, headers):
        return self._request("POST", f"{BASE}/reimbursement-claims", payload, headers)

    def get_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{BASE}/reimbursement-claims/{claim_id}", headers=headers
        )

    def approve_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{BASE}/reimbursement-claims/{claim_id}/approve", {}, headers
        )

    def deny_reimbursement_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/reimbursement-claims/{claim_id}/deny", payload, headers
        )

    def pay_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{BASE}/reimbursement-claims/{claim_id}/pay", {}, headers
        )

    # --- Certification bonuses ---
    def pay_certification_bonus(self, bonus_id, headers):
        return self._request(
            "POST", f"{BASE}/certification-bonuses/{bonus_id}/pay", {}, headers
        )

    def claw_back_certification_bonus(self, bonus_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/certification-bonuses/{bonus_id}/claw-back",
            payload, headers,
        )

    # --- Applications and review ---
    def create_application(self, payload, headers):
        return self._request("POST", f"{BASE}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{BASE}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{BASE}/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"{BASE}/applications/{application_id}/submit", {}, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"{BASE}/applications/{application_id}/withdraw", {}, headers
        )

    def create_review_assignment(self, application_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/applications/{application_id}/assignments",
            payload, headers,
        )

    def list_application_assignments(self, application_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/applications/{application_id}/assignments",
            headers=headers, params=params,
        )

    def list_application_decisions(self, application_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/applications/{application_id}/decisions",
            headers=headers, params=params,
        )

    def return_application_for_revision(self, application_id, headers):
        return self._request(
            "POST", f"{BASE}/applications/{application_id}/return-for-revision",
            {}, headers,
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/applications/{application_id}/decide", payload, headers
        )

    # --- Review assignments ---
    def list_review_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/review-assignments", headers=headers, params=params
        )

    def get_review_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{BASE}/review-assignments/{assignment_id}", headers=headers
        )

    def score_review_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/review-assignments/{assignment_id}/score",
            payload, headers,
        )

    def recuse_review_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"{BASE}/review-assignments/{assignment_id}/recuse", {}, headers
        )

    # --- Anniversary reviews ---
    def create_anniversary_review(self, payload, headers):
        return self._request("POST", f"{BASE}/anniversary-reviews", payload, headers)

    def close_anniversary_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/anniversary-reviews/{review_id}/close", payload, headers
        )

    # --- Budget lines & retention snapshots ---
    def create_budget_line(self, payload, headers):
        return self._request("POST", f"{BASE}/budget-lines", payload, headers)

    def list_budget_lines(self, headers, params=None):
        return self._request("GET", f"{BASE}/budget-lines", headers=headers, params=params)

    def get_budget_line(self, budget_line_id, headers):
        return self._request(
            "GET", f"{BASE}/budget-lines/{budget_line_id}", headers=headers
        )

    def update_budget_line(self, budget_line_id, payload, headers):
        return self._request(
            "PUT", f"{BASE}/budget-lines/{budget_line_id}", payload, headers
        )

    def list_retention_snapshots(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/retention-snapshots", headers=headers, params=params
        )

    # --- Logical clock / ops sweep ---
    def set_current_utc(self, payload, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )

    def run_ops_cycle(self, headers):
        return self._request("POST", f"{BASE}/_ops/run_cycle", {}, headers)


api_client = ApiClient()
