"""One method per endpoint of PRD S4.

The client is a thin wrapper over the framework's ``GenericApiClient``: it adds
no behaviour beyond naming the paths, so a test never spells a URL inline.
Every method takes an explicit ``headers`` mapping because authorisation is
per-request in this contract (PRD S2.1).
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Json = Dict[str, Any]


class PlaApiClient(GenericApiClient):
    """Prior Learning Assessment API surface."""

    # ------------------------------------------------------------------
    # Programmes (PRD S3.1)
    # ------------------------------------------------------------------
    def create_program(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/programs", payload, headers=headers)

    def get_program(self, program_id: str, headers: Optional[Json] = None):
        return self.get(f"/programs/{program_id}", headers=headers)

    def patch_program(self, program_id: str, payload: Json, headers: Optional[Json] = None):
        return self._request("PATCH", f"/programs/{program_id}", payload, headers=headers)

    # ------------------------------------------------------------------
    # Courses and learning outcomes (PRD S3.1)
    # ------------------------------------------------------------------
    def create_course(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/courses", payload, headers=headers)

    def get_course(self, course_id: str, headers: Optional[Json] = None):
        return self.get(f"/courses/{course_id}", headers=headers)

    def get_learning_outcome(self, outcome_id: str, headers: Optional[Json] = None):
        return self.get(f"/learning-outcomes/{outcome_id}", headers=headers)

    def list_learning_outcomes(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/learning-outcomes", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Credential recommendations (PRD S3.2)
    # ------------------------------------------------------------------
    def create_recommendation(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/credential-recommendations", payload, headers=headers)

    def get_recommendation(self, recommendation_id: str, headers: Optional[Json] = None):
        return self.get(f"/credential-recommendations/{recommendation_id}", headers=headers)

    def patch_recommendation(self, recommendation_id: str, payload: Json, headers: Optional[Json] = None):
        return self._request(
            "PATCH", f"/credential-recommendations/{recommendation_id}", payload, headers=headers
        )

    def publish_recommendation(self, recommendation_id: str, payload: Optional[Json] = None,
                               headers: Optional[Json] = None):
        return self.post(
            f"/credential-recommendations/{recommendation_id}/publish", payload or {}, headers=headers
        )

    def retire_recommendation(self, recommendation_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(
            f"/credential-recommendations/{recommendation_id}/retire", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Articulation rules (PRD S3.2)
    # ------------------------------------------------------------------
    def create_rule(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/articulation-rules", payload, headers=headers)

    def submit_rule_for_review(self, rule_id: str, payload: Optional[Json] = None,
                               headers: Optional[Json] = None):
        return self.post(f"/articulation-rules/{rule_id}/submit-for-review", payload or {}, headers=headers)

    def approve_rule(self, rule_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/articulation-rules/{rule_id}/approve", payload, headers=headers)

    def suspend_rule(self, rule_id: str, payload: Optional[Json] = None, headers: Optional[Json] = None):
        return self.post(f"/articulation-rules/{rule_id}/suspend", payload or {}, headers=headers)

    def reinstate_rule(self, rule_id: str, payload: Optional[Json] = None, headers: Optional[Json] = None):
        return self.post(f"/articulation-rules/{rule_id}/reinstate", payload or {}, headers=headers)

    def get_rule(self, rule_id: str, headers: Optional[Json] = None):
        return self.get(f"/articulation-rules/{rule_id}", headers=headers)

    def list_rules(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/articulation-rules", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Students (PRD S3.3, S3.11)
    # ------------------------------------------------------------------
    def create_student(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/students", payload, headers=headers)

    def get_student(self, student_id: str, headers: Optional[Json] = None):
        return self.get(f"/students/{student_id}", headers=headers)

    def list_students(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/students", headers=headers, params=params)

    def patch_student(self, student_id: str, payload: Json, headers: Optional[Json] = None):
        return self._request("PATCH", f"/students/{student_id}", payload, headers=headers)

    def get_graduation_audit(self, student_id: str, headers: Optional[Json] = None):
        return self.get(f"/students/{student_id}/graduation-audit", headers=headers)

    # ------------------------------------------------------------------
    # Faculty assessors (PRD S3.6)
    # ------------------------------------------------------------------
    def create_assessor(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/faculty-assessors", payload, headers=headers)

    def get_assessor(self, assessor_id: str, headers: Optional[Json] = None):
        return self.get(f"/faculty-assessors/{assessor_id}", headers=headers)

    def list_assessors(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/faculty-assessors", headers=headers, params=params)

    def patch_assessor(self, assessor_id: str, payload: Json, headers: Optional[Json] = None):
        return self._request("PATCH", f"/faculty-assessors/{assessor_id}", payload, headers=headers)

    # ------------------------------------------------------------------
    # PLA claims (PRD S3.3, S3.5, S3.8, S3.11)
    # ------------------------------------------------------------------
    def create_claim(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/pla-claims", payload, headers=headers)

    def get_claim(self, claim_id: str, headers: Optional[Json] = None):
        return self.get(f"/pla-claims/{claim_id}", headers=headers)

    def list_claims(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/pla-claims", headers=headers, params=params)

    def submit_claim(self, claim_id: str, payload: Optional[Json] = None, headers: Optional[Json] = None):
        return self.post(f"/pla-claims/{claim_id}/submit", payload or {}, headers=headers)

    def withdraw_claim(self, claim_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/pla-claims/{claim_id}/withdraw", payload, headers=headers)

    def request_revision(self, claim_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/pla-claims/{claim_id}/request-revision", payload, headers=headers)

    def award_claim(self, claim_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/pla-claims/{claim_id}/award", payload, headers=headers)

    def deny_claim(self, claim_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/pla-claims/{claim_id}/deny", payload, headers=headers)

    def post_transcript(self, claim_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/pla-claims/{claim_id}/transcript-posting", payload, headers=headers)

    def reverse_transcript(self, claim_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/pla-claims/{claim_id}/transcript-posting/reversal", payload, headers=headers)

    # ------------------------------------------------------------------
    # Portfolios and artifacts (PRD S3.4)
    # ------------------------------------------------------------------
    def create_portfolio(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/portfolios", payload, headers=headers)

    def get_portfolio(self, portfolio_id: str, headers: Optional[Json] = None):
        return self.get(f"/portfolios/{portfolio_id}", headers=headers)

    def list_portfolios(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/portfolios", headers=headers, params=params)

    def add_artifact(self, portfolio_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/portfolios/{portfolio_id}/artifacts", payload, headers=headers)

    def delete_artifact(self, portfolio_id: str, artifact_id: str, headers: Optional[Json] = None):
        return self._request(
            "DELETE", f"/portfolios/{portfolio_id}/artifacts/{artifact_id}", headers=headers
        )

    def get_artifact(self, artifact_id: str, headers: Optional[Json] = None):
        return self.get(f"/artifacts/{artifact_id}", headers=headers)

    def list_artifacts(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/artifacts", headers=headers, params=params)

    def submit_portfolio(self, portfolio_id: str, payload: Optional[Json] = None,
                         headers: Optional[Json] = None):
        return self.post(f"/portfolios/{portfolio_id}/submit", payload or {}, headers=headers)

    # ------------------------------------------------------------------
    # Assessor assignments and rubric scoring (PRD S3.6, S3.7)
    # ------------------------------------------------------------------
    def create_assignment(self, claim_id: str, payload: Optional[Json] = None,
                          headers: Optional[Json] = None):
        return self.post(f"/pla-claims/{claim_id}/assessor-assignments", payload or {}, headers=headers)

    def get_assignment(self, assignment_id: str, headers: Optional[Json] = None):
        return self.get(f"/assessor-assignments/{assignment_id}", headers=headers)

    def list_assignments(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/assessor-assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id: str, payload: Optional[Json] = None,
                          headers: Optional[Json] = None):
        return self.post(f"/assessor-assignments/{assignment_id}/accept", payload or {}, headers=headers)

    def decline_assignment(self, assignment_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/assessor-assignments/{assignment_id}/decline", payload, headers=headers)

    def create_rubric_score(self, assignment_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/assessor-assignments/{assignment_id}/rubric-scores", payload, headers=headers)

    def get_rubric_score(self, score_id: str, headers: Optional[Json] = None):
        return self.get(f"/rubric-scores/{score_id}", headers=headers)

    def list_rubric_scores(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/rubric-scores", headers=headers, params=params)

    def complete_assignment(self, assignment_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/assessor-assignments/{assignment_id}/complete", payload, headers=headers)

    # ------------------------------------------------------------------
    # Fee invoices (PRD S3.10)
    # ------------------------------------------------------------------
    def get_invoice(self, invoice_id: str, headers: Optional[Json] = None):
        return self.get(f"/fee-invoices/{invoice_id}", headers=headers)

    def list_invoices(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/fee-invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/fee-invoices/{invoice_id}/payments", payload, headers=headers)

    def waive_invoice(self, invoice_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/fee-invoices/{invoice_id}/waive", payload, headers=headers)

    # ------------------------------------------------------------------
    # Appeals (PRD S3.9)
    # ------------------------------------------------------------------
    def create_appeal(self, payload: Json, headers: Optional[Json] = None):
        return self.post("/appeals", payload, headers=headers)

    def get_appeal(self, appeal_id: str, headers: Optional[Json] = None):
        return self.get(f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, params: Optional[Json] = None, headers: Optional[Json] = None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def assign_appeal_reviewer(self, appeal_id: str, payload: Optional[Json] = None,
                               headers: Optional[Json] = None):
        return self.post(f"/appeals/{appeal_id}/assign-reviewer", payload or {}, headers=headers)

    def decide_appeal(self, appeal_id: str, payload: Json, headers: Optional[Json] = None):
        return self.post(f"/appeals/{appeal_id}/decide", payload, headers=headers)

    # ------------------------------------------------------------------
    # Logical clock and escalation sweep (PRD S2.5, S3.6)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[Json] = None):
        return self.post("/_clock/set_current_utc", {"current_utc": current_utc}, headers=headers)

    def run_escalation_sweep(self, payload: Optional[Json] = None, headers: Optional[Json] = None):
        return self.post("/_sla/run-escalation-sweep", payload or {}, headers=headers)
