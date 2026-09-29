"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the /comp prefix except the test-only logical
clock endpoint.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/comp"


class ApiClient(GenericApiClient):

    # ─── Logical clock (test-only, not under /comp) ───

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Compensation cycles ──────────────────────────

    def create_cycle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cycles", headers=headers, params=params)

    def advance_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/advance", payload, headers
        )

    # ─── Partners ─────────────────────────────────────

    def create_partner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"{PREFIX}/partners/{partner_id}", headers=headers)

    def list_partners(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/partners", headers=headers, params=params)

    def notice_of_departure(self, partner_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/partners/{partner_id}/notice-of-departure", payload, headers
        )

    def capital_contribution(self, partner_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/partners/{partner_id}/capital-contribution", payload, headers
        )

    def list_partner_credit_allocations(self, partner_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/partners/{partner_id}/credit-allocations",
            headers=headers,
            params=params,
        )

    # ─── Matters ──────────────────────────────────────

    def create_matter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/matters", payload, headers)

    def get_matter(self, matter_id, headers):
        return self._request("GET", f"{PREFIX}/matters/{matter_id}", headers=headers)

    def list_matters(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/matters", headers=headers, params=params)

    def post_matter_financials(self, matter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/matters/{matter_id}/financials", payload, headers
        )

    def set_matter_status(self, matter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/matters/{matter_id}/status", payload, headers
        )

    def list_matter_credit_allocations(self, matter_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/matters/{matter_id}/credit-allocations",
            headers=headers,
            params=params,
        )

    # ─── Credit allocations ───────────────────────────

    def get_credit_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/credit-allocations/{allocation_id}", headers=headers
        )

    # ─── Contribution records ─────────────────────────

    def create_contribution_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contribution-records", payload, headers)

    def get_contribution_record(self, record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/contribution-records/{record_id}", headers=headers
        )

    def list_contribution_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contribution-records", headers=headers, params=params
        )

    def verify_contribution_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contribution-records/{record_id}/verify", payload, headers
        )

    # ─── Credit claims ────────────────────────────────

    def create_credit_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/credit-claims", payload, headers)

    def get_credit_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/credit-claims/{claim_id}", headers=headers)

    def list_credit_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/credit-claims", headers=headers, params=params
        )

    def submit_credit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/credit-claims/{claim_id}/submit", payload, headers
        )

    def dispute_credit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/credit-claims/{claim_id}/dispute", payload, headers
        )

    def adjudicate_credit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/credit-claims/{claim_id}/adjudicate", payload, headers
        )

    # ─── Self-assessments ─────────────────────────────

    def create_self_assessment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/self-assessments", payload, headers)

    def get_self_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/self-assessments/{assessment_id}", headers=headers
        )

    def list_self_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/self-assessments", headers=headers, params=params
        )

    def submit_self_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/self-assessments/{assessment_id}/submit", payload, headers
        )

    def review_decision_self_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/self-assessments/{assessment_id}/review-decision",
            payload,
            headers,
        )

    # ─── Peer reviews ─────────────────────────────────

    def create_peer_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/peer-reviews", payload, headers)

    def get_peer_review(self, review_id, headers):
        return self._request("GET", f"{PREFIX}/peer-reviews/{review_id}", headers=headers)

    def list_peer_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/peer-reviews", headers=headers, params=params
        )

    def decide_peer_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/peer-reviews/{review_id}/decide", payload, headers
        )

    # ─── Committee ballots ────────────────────────────

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"{PREFIX}/ballots/{ballot_id}", headers=headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ballots", headers=headers, params=params)

    def cast_ballot(self, ballot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ballots/{ballot_id}/cast", payload, headers
        )

    # ─── Compensation awards ──────────────────────────

    def get_award(self, award_id, headers):
        return self._request("GET", f"{PREFIX}/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/awards", headers=headers, params=params)

    def draw_run(self, award_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/awards/{award_id}/draw-run", payload, headers
        )

    def true_up(self, award_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/awards/{award_id}/true-up", payload, headers
        )

    def list_draw_payments(self, award_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/awards/{award_id}/draw-payments", headers=headers, params=params
        )

    def get_draw_payment(self, payment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/draw-payments/{payment_id}", headers=headers
        )

    # ─── Credit transitions ───────────────────────────

    def get_credit_transition(self, transition_id, headers):
        return self._request(
            "GET", f"{PREFIX}/credit-transitions/{transition_id}", headers=headers
        )

    def list_credit_transitions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/credit-transitions", headers=headers, params=params
        )

    def effectuate_credit_transition(self, transition_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/credit-transitions/{transition_id}/effectuate",
            payload,
            headers,
        )

    def void_credit_transition(self, transition_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/credit-transitions/{transition_id}/void", payload, headers
        )


api_client = ApiClient()
