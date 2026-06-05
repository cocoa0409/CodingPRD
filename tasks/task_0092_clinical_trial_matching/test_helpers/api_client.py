"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Test-driving clock (PRD §3.8) ──────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Trial (PRD §3.1) ───────────────────────────────
    def create_trial(self, payload, headers):
        return self._request("POST", "/trials", payload, headers)

    def get_trial(self, trial_id, headers):
        return self._request("GET", f"/trials/{trial_id}", headers=headers)

    # ─── EligibilityCriterion (PRD §3.1) ────────────────
    def create_criterion(self, trial_id, payload, headers):
        return self._request("POST", f"/trials/{trial_id}/criteria", payload, headers)

    def list_criteria(self, trial_id, headers, params=None):
        return self._request("GET", f"/trials/{trial_id}/criteria", headers=headers, params=params)

    # ─── RandomizationArm (PRD §3.1) ────────────────────
    def create_arm(self, trial_id, payload, headers):
        return self._request("POST", f"/trials/{trial_id}/arms", payload, headers)

    def list_arms(self, trial_id, headers, params=None):
        return self._request("GET", f"/trials/{trial_id}/arms", headers=headers, params=params)

    # ─── ConsentDocument (PRD §3.2) ─────────────────────
    def create_consent_document(self, trial_id, payload, headers):
        return self._request("POST", f"/trials/{trial_id}/consent-documents", payload, headers)

    def list_consent_documents(self, trial_id, headers, params=None):
        return self._request("GET", f"/trials/{trial_id}/consent-documents", headers=headers, params=params)

    def activate_consent_document(self, trial_id, doc_id, payload, headers):
        return self._request(
            "POST", f"/trials/{trial_id}/consent-documents/{doc_id}/activate", payload, headers,
        )

    # ─── IRBReview (PRD §3.2) ───────────────────────────
    def create_irb_review(self, trial_id, payload, headers):
        return self._request("POST", f"/trials/{trial_id}/irb-reviews", payload, headers)

    def list_irb_reviews(self, trial_id, headers, params=None):
        return self._request("GET", f"/trials/{trial_id}/irb-reviews", headers=headers, params=params)

    def decide_irb_review(self, trial_id, review_id, payload, headers):
        return self._request(
            "POST", f"/trials/{trial_id}/irb-reviews/{review_id}/decide", payload, headers,
        )

    # ─── Participant (PRD §3.3) ─────────────────────────
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def update_participant(self, participant_id, payload, headers):
        return self._request("PATCH", f"/participants/{participant_id}", payload, headers)

    # ─── Screening (PRD §3.3) ───────────────────────────
    def screen_participant(self, trial_id, payload, headers):
        return self._request("POST", f"/trials/{trial_id}/screen-participant", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/screenings/{screening_id}", headers=headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/screenings", headers=headers, params=params)

    # ─── Enrollment (PRD §3.4) ──────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def transition_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/transition", payload, headers)

    def lift_hold(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/lift-hold", payload or {}, headers)

    # ─── Visit (PRD §3.6) ───────────────────────────────
    def create_visit(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/visits", payload, headers)

    def list_visits(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/visits", headers=headers, params=params)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", payload, headers)

    # ─── AdverseEvent (PRD §3.5) ────────────────────────
    def create_adverse_event(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/adverse-events", payload, headers)

    def list_adverse_events(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/adverse-events", headers=headers, params=params)

    def review_adverse_event(self, adverse_event_id, payload, headers):
        return self._request("POST", f"/adverse-events/{adverse_event_id}/review", payload, headers)

    # ─── CompensationPayment (PRD §3.7) ─────────────────
    def create_payment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/payments", payload or {}, headers)

    def list_payments(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/payments", headers=headers, params=params)

    def pay_payment(self, payment_id, headers, payload=None):
        return self._request("POST", f"/payments/{payment_id}/pay", payload or {}, headers)


api_client = ApiClient()
