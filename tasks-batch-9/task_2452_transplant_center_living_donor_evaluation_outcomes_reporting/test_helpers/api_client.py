"""API client: one method per endpoint defined in the PRD.

Every endpoint is rooted at the service root; there is no version or namespace
prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Programs, staff, theatres and the logical clock
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def run_compliance_sweep(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/programs/{program_id}/compliance-sweep", payload or {}, headers
        )

    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def list_program_staff_members(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/staff-members", headers=headers, params=params
        )

    def create_operating_room(self, payload, headers):
        return self._request("POST", "/operating-rooms", payload, headers)

    def list_program_operating_rooms(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/operating-rooms",
            headers=headers,
            params=params,
        )

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Recipient candidacy and the waitlist ledger
    # ------------------------------------------------------------------
    def create_recipient_candidate(self, payload, headers):
        return self._request("POST", "/recipient-candidates", payload, headers)

    def create_recipient_status_update(self, recipient_id, payload, headers):
        return self._request(
            "POST", f"/recipient-candidates/{recipient_id}/status-updates", payload, headers
        )

    def list_recipient_candidates(self, headers, params=None):
        return self._request("GET", "/recipient-candidates", headers=headers, params=params)

    def get_recipient_candidate(self, recipient_id, headers):
        return self._request(
            "GET", f"/recipient-candidates/{recipient_id}", headers=headers
        )

    def list_waitlist_events(self, recipient_id, headers, params=None):
        return self._request(
            "GET",
            f"/recipient-candidates/{recipient_id}/waitlist-events",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Donor referral and independent advocacy
    # ------------------------------------------------------------------
    def create_donor_candidate(self, payload, headers):
        return self._request("POST", "/donor-candidates", payload, headers)

    def assign_advocate(self, donor_id, payload, headers):
        return self._request(
            "POST", f"/donor-candidates/{donor_id}/advocate-assignment", payload, headers
        )

    def record_consent_disclosure(self, donor_id, headers, payload=None):
        return self._request(
            "POST",
            f"/donor-candidates/{donor_id}/consent-disclosure",
            payload or {},
            headers,
        )

    def record_advocacy_determination(self, donor_id, payload, headers):
        return self._request(
            "POST",
            f"/donor-candidates/{donor_id}/advocacy-determination",
            payload,
            headers,
        )

    def list_donor_candidates(self, headers, params=None):
        return self._request("GET", "/donor-candidates", headers=headers, params=params)

    def get_donor_candidate(self, donor_id, headers):
        return self._request("GET", f"/donor-candidates/{donor_id}", headers=headers)

    def list_donor_follow_ups(self, donor_id, headers, params=None):
        return self._request(
            "GET",
            f"/donor-candidates/{donor_id}/donor-follow-ups",
            headers=headers,
            params=params,
        )

    def list_donor_cost_claims(self, donor_id, headers, params=None):
        return self._request(
            "GET",
            f"/donor-candidates/{donor_id}/donor-cost-claims",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Clinical evaluation
    # ------------------------------------------------------------------
    def create_donor_evaluation(self, payload, headers):
        return self._request("POST", "/donor-evaluations", payload, headers)

    def record_evaluation_determination(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"/donor-evaluations/{evaluation_id}/determination", payload, headers
        )

    def resubmit_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"/donor-evaluations/{evaluation_id}/resubmission", payload, headers
        )

    def list_donor_evaluations(self, headers, params=None):
        return self._request("GET", "/donor-evaluations", headers=headers, params=params)

    def get_donor_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/donor-evaluations/{evaluation_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Exchange chains and segments
    # ------------------------------------------------------------------
    def create_exchange_chain(self, payload, headers):
        return self._request("POST", "/exchange-chains", payload, headers)

    def create_chain_segment(self, chain_id, payload, headers):
        return self._request(
            "POST", f"/exchange-chains/{chain_id}/segments", payload, headers
        )

    def validate_chain(self, chain_id, headers, payload=None):
        return self._request(
            "POST", f"/exchange-chains/{chain_id}/validation", payload or {}, headers
        )

    def commit_chain(self, chain_id, headers, payload=None):
        return self._request(
            "POST", f"/exchange-chains/{chain_id}/commitment", payload or {}, headers
        )

    def break_chain(self, chain_id, payload, headers):
        return self._request(
            "POST", f"/exchange-chains/{chain_id}/break", payload, headers
        )

    def list_exchange_chains(self, headers, params=None):
        return self._request("GET", "/exchange-chains", headers=headers, params=params)

    def get_exchange_chain(self, chain_id, headers):
        return self._request("GET", f"/exchange-chains/{chain_id}", headers=headers)

    def send_segment_offer(self, segment_id, payload, headers):
        return self._request(
            "POST", f"/chain-segments/{segment_id}/offer", payload, headers
        )

    def record_offer_response(self, segment_id, payload, headers):
        return self._request(
            "POST", f"/chain-segments/{segment_id}/offer-response", payload, headers
        )

    def record_transplant_completion(self, segment_id, payload, headers):
        return self._request(
            "POST", f"/chain-segments/{segment_id}/transplant-completion", payload, headers
        )

    def list_chain_segments(self, headers, params=None):
        return self._request("GET", "/chain-segments", headers=headers, params=params)

    def get_chain_segment(self, segment_id, headers):
        return self._request("GET", f"/chain-segments/{segment_id}", headers=headers)

    # ------------------------------------------------------------------
    # Theatre bookings
    # ------------------------------------------------------------------
    def create_procedure_booking(self, payload, headers):
        return self._request("POST", "/procedure-bookings", payload, headers)

    def cancel_procedure_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/procedure-bookings/{booking_id}/cancellation", payload, headers
        )

    def list_procedure_bookings(self, headers, params=None):
        return self._request("GET", "/procedure-bookings", headers=headers, params=params)

    def get_procedure_booking(self, booking_id, headers):
        return self._request("GET", f"/procedure-bookings/{booking_id}", headers=headers)

    # ------------------------------------------------------------------
    # Donor follow-up
    # ------------------------------------------------------------------
    def submit_follow_up(self, follow_up_id, payload, headers):
        return self._request(
            "POST", f"/donor-follow-ups/{follow_up_id}/submission", payload, headers
        )

    def waive_follow_up(self, follow_up_id, payload, headers):
        return self._request(
            "POST", f"/donor-follow-ups/{follow_up_id}/waiver", payload, headers
        )

    # ------------------------------------------------------------------
    # Outcome reviews and improvement plans
    # ------------------------------------------------------------------
    def create_outcome_review(self, payload, headers):
        return self._request("POST", "/outcome-reviews", payload, headers)

    def finalize_outcome_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/outcome-reviews/{review_id}/finalization", payload or {}, headers
        )

    def list_outcome_reviews(self, headers, params=None):
        return self._request("GET", "/outcome-reviews", headers=headers, params=params)

    def get_outcome_review(self, review_id, headers):
        return self._request("GET", f"/outcome-reviews/{review_id}", headers=headers)

    def list_review_improvement_plans(self, review_id, headers, params=None):
        return self._request(
            "GET",
            f"/outcome-reviews/{review_id}/improvement-plans",
            headers=headers,
            params=params,
        )

    def create_improvement_plan(self, payload, headers):
        return self._request("POST", "/improvement-plans", payload, headers)

    def transition_improvement_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/improvement-plans/{plan_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Donor cost claims
    # ------------------------------------------------------------------
    def create_donor_cost_claim(self, payload, headers):
        return self._request("POST", "/donor-cost-claims", payload, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/donor-cost-claims/{claim_id}/adjudication", payload, headers
        )

    def reverse_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/donor-cost-claims/{claim_id}/reversal", payload, headers
        )


api_client = ApiClient()
