"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- circles ---
    def create_circle(self, payload, headers):
        return self._request("POST", "/api/circles", payload, headers)

    def get_circle(self, circle_id, headers):
        return self._request("GET", f"/api/circles/{circle_id}", headers=headers)

    def list_circles(self, headers, params=None):
        return self._request("GET", "/api/circles", headers=headers, params=params)

    # --- giving cycles ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/api/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/api/cycles", headers=headers, params=params)

    def advance_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/api/cycles/{cycle_id}/advance", payload, headers
        )

    def get_cycle_ledger(self, cycle_id, headers):
        return self._request("GET", f"/api/cycles/{cycle_id}/ledger", headers=headers)

    def get_cycle_tally(self, cycle_id, headers):
        return self._request("GET", f"/api/cycles/{cycle_id}/tally", headers=headers)

    # --- members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    # --- memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/api/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/api/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/api/memberships", headers=headers, params=params)

    def accept_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/api/memberships/{membership_id}/accept", {}, headers
        )

    def renew_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/api/memberships/{membership_id}/renew", {}, headers
        )

    def lapse_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/api/memberships/{membership_id}/lapse", {}, headers
        )

    def withdraw_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/api/memberships/{membership_id}/withdraw", {}, headers
        )

    # --- contributions ---
    def create_contribution(self, payload, headers):
        return self._request("POST", "/api/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request(
            "GET", f"/api/contributions/{contribution_id}", headers=headers
        )

    def list_contributions(self, headers, params=None):
        return self._request("GET", "/api/contributions", headers=headers, params=params)

    def receive_contribution(self, contribution_id, headers):
        return self._request(
            "POST", f"/api/contributions/{contribution_id}/receive", {}, headers
        )

    def request_refund(self, contribution_id, headers):
        return self._request(
            "POST", f"/api/contributions/{contribution_id}/request-refund", {}, headers
        )

    def approve_refund(self, contribution_id, headers):
        return self._request(
            "POST", f"/api/contributions/{contribution_id}/approve-refund", {}, headers
        )

    def deny_refund(self, contribution_id, headers):
        return self._request(
            "POST", f"/api/contributions/{contribution_id}/deny-refund", {}, headers
        )

    # --- nonprofits ---
    def create_nonprofit(self, payload, headers):
        return self._request("POST", "/api/nonprofits", payload, headers)

    def get_nonprofit(self, nonprofit_id, headers):
        return self._request("GET", f"/api/nonprofits/{nonprofit_id}", headers=headers)

    def list_nonprofits(self, headers, params=None):
        return self._request("GET", "/api/nonprofits", headers=headers, params=params)

    # --- nominations ---
    def create_nomination(self, payload, headers):
        return self._request("POST", "/api/nominations", payload, headers)

    def get_nomination(self, nomination_id, headers):
        return self._request("GET", f"/api/nominations/{nomination_id}", headers=headers)

    def list_nominations(self, headers, params=None):
        return self._request("GET", "/api/nominations", headers=headers, params=params)

    def patch_nomination(self, nomination_id, payload, headers):
        return self._request(
            "PATCH", f"/api/nominations/{nomination_id}", payload, headers
        )

    def start_vetting(self, nomination_id, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/start-vetting", {}, headers
        )

    def request_info(self, nomination_id, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/request-info", {}, headers
        )

    def submit_info(self, nomination_id, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/submit-info", {}, headers
        )

    def advance_to_finalist(self, nomination_id, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/advance-to-finalist", {}, headers
        )

    def reject_nomination(self, nomination_id, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/reject", {}, headers
        )

    def withdraw_nomination(self, nomination_id, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/withdraw", {}, headers
        )

    # --- site visits ---
    def create_site_visit(self, payload, headers):
        return self._request("POST", "/api/site-visits", payload, headers)

    def get_site_visit(self, visit_id, headers):
        return self._request("GET", f"/api/site-visits/{visit_id}", headers=headers)

    def list_site_visits(self, headers, params=None):
        return self._request("GET", "/api/site-visits", headers=headers, params=params)

    def complete_site_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/api/site-visits/{visit_id}/complete", payload, headers
        )

    def cancel_site_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/api/site-visits/{visit_id}/cancel", {}, headers
        )

    def reschedule_site_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/api/site-visits/{visit_id}/reschedule", payload, headers
        )

    # --- learning sessions ---
    def create_learning_session(self, payload, headers):
        return self._request("POST", "/api/learning-sessions", payload, headers)

    def get_learning_session(self, session_id, headers):
        return self._request(
            "GET", f"/api/learning-sessions/{session_id}", headers=headers
        )

    def list_learning_sessions(self, headers, params=None):
        return self._request(
            "GET", "/api/learning-sessions", headers=headers, params=params
        )

    def rsvp_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/api/learning-sessions/{session_id}/rsvp", payload, headers
        )

    def complete_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/learning-sessions/{session_id}/complete", {}, headers
        )

    def cancel_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/learning-sessions/{session_id}/cancel", {}, headers
        )

    # --- ballots ---
    def create_ballot(self, payload, headers):
        return self._request("POST", "/api/ballots", payload, headers)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/api/ballots/{ballot_id}", headers=headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/api/ballots", headers=headers, params=params)

    def recast_ballot(self, ballot_id, payload, headers):
        return self._request(
            "POST", f"/api/ballots/{ballot_id}/recast", payload, headers
        )

    # --- awards ---
    def get_award(self, award_id, headers):
        return self._request("GET", f"/api/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/api/awards", headers=headers, params=params)

    # --- payouts ---
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/api/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/api/payouts", headers=headers, params=params)

    def approve_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/approve", {}, headers)

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/release", {}, headers)

    def mark_payout_failed(self, payout_id, headers):
        return self._request(
            "POST", f"/api/payouts/{payout_id}/mark-failed", {}, headers
        )

    def retry_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/retry", {}, headers)

    # --- grantee reports ---
    def get_report(self, report_id, headers):
        return self._request("GET", f"/api/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/api/reports", headers=headers, params=params)

    def submit_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/reports/{report_id}/submit", payload, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/api/reports/{report_id}/accept", {}, headers)

    def reject_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/reports/{report_id}/reject", payload, headers)

    # --- rollover decisions ---
    def create_rollover_decision(self, payload, headers):
        return self._request("POST", "/api/rollover-decisions", payload, headers)

    def get_rollover_decision(self, decision_id, headers):
        return self._request(
            "GET", f"/api/rollover-decisions/{decision_id}", headers=headers
        )

    def list_rollover_decisions(self, headers, params=None):
        return self._request(
            "GET", "/api/rollover-decisions", headers=headers, params=params
        )

    def approve_rollover(self, decision_id, headers):
        return self._request(
            "POST", f"/api/rollover-decisions/{decision_id}/approve", {}, headers
        )

    def execute_rollover(self, decision_id, headers):
        return self._request(
            "POST", f"/api/rollover-decisions/{decision_id}/execute", {}, headers
        )


api_client = ApiClient()
