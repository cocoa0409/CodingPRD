"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Governance policy (PRD §2.8) ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/governance/policy", payload, headers)

    def get_policy(self, headers):
        return self._request("GET", "/governance/policy", headers=headers)

    def update_policy(self, payload, headers):
        return self._request("PATCH", "/governance/policy", payload, headers)

    # --- Physicians (PRD §3.1) ---
    def create_physician(self, payload, headers):
        return self._request("POST", "/governance/physicians", payload, headers)

    def list_physicians(self, headers, params=None):
        return self._request("GET", "/governance/physicians", headers=headers, params=params)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/governance/physicians/{physician_id}", headers=headers)

    def set_physician_standing(self, physician_id, payload, headers):
        return self._request(
            "POST", f"/governance/physicians/{physician_id}/standing", payload, headers
        )

    # --- Board seats (PRD §3.3) ---
    def create_board_seat(self, payload, headers):
        return self._request("POST", "/governance/board-seats", payload, headers)

    def list_board_seats(self, headers, params=None):
        return self._request("GET", "/governance/board-seats", headers=headers, params=params)

    def get_board_seat(self, seat_id, headers):
        return self._request("GET", f"/governance/board-seats/{seat_id}", headers=headers)

    def appoint_board_seat(self, seat_id, payload, headers):
        return self._request(
            "POST", f"/governance/board-seats/{seat_id}/appoint", payload, headers
        )

    # --- Committees (PRD §3.3) ---
    def create_committee(self, payload, headers):
        return self._request("POST", "/governance/committees", payload, headers)

    def list_committees(self, headers, params=None):
        return self._request("GET", "/governance/committees", headers=headers, params=params)

    def get_committee(self, committee_id, headers):
        return self._request("GET", f"/governance/committees/{committee_id}", headers=headers)

    def add_committee_member(self, committee_id, payload, headers):
        return self._request(
            "POST", f"/governance/committees/{committee_id}/members", payload, headers
        )

    def remove_committee_member(self, committee_id, physician_id, headers):
        return self._request(
            "POST",
            f"/governance/committees/{committee_id}/members/{physician_id}/remove",
            {},
            headers,
        )

    def dissolve_committee(self, committee_id, headers):
        return self._request(
            "POST", f"/governance/committees/{committee_id}/dissolve", {}, headers
        )

    # --- Buy-in offers (PRD §3.2) ---
    def create_buy_in_offer(self, payload, headers):
        return self._request("POST", "/governance/buy-in-offers", payload, headers)

    def list_buy_in_offers(self, headers, params=None):
        return self._request("GET", "/governance/buy-in-offers", headers=headers, params=params)

    def get_buy_in_offer(self, offer_id, headers):
        return self._request("GET", f"/governance/buy-in-offers/{offer_id}", headers=headers)

    def respond_buy_in_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/governance/buy-in-offers/{offer_id}/respond", payload, headers
        )

    def pay_installment(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/governance/buy-in-offers/{offer_id}/pay-installment", payload, headers
        )

    # --- Motions (PRD §3.4) ---
    def create_motion(self, payload, headers):
        return self._request("POST", "/governance/motions", payload, headers)

    def list_motions(self, headers, params=None):
        return self._request("GET", "/governance/motions", headers=headers, params=params)

    def get_motion(self, motion_id, headers):
        return self._request("GET", f"/governance/motions/{motion_id}", headers=headers)

    def propose_motion(self, motion_id, headers):
        return self._request("POST", f"/governance/motions/{motion_id}/propose", {}, headers)

    def open_motion(self, motion_id, headers):
        return self._request("POST", f"/governance/motions/{motion_id}/open", {}, headers)

    def table_motion(self, motion_id, headers):
        return self._request("POST", f"/governance/motions/{motion_id}/table", {}, headers)

    def resume_motion(self, motion_id, headers):
        return self._request("POST", f"/governance/motions/{motion_id}/resume", {}, headers)

    def withdraw_motion(self, motion_id, headers):
        return self._request("POST", f"/governance/motions/{motion_id}/withdraw", {}, headers)

    def close_motion(self, motion_id, headers):
        return self._request("POST", f"/governance/motions/{motion_id}/close", {}, headers)

    # --- Votes (PRD §3.4) ---
    def cast_vote(self, motion_id, payload, headers):
        return self._request("POST", f"/governance/motions/{motion_id}/votes", payload, headers)

    def list_motion_votes(self, motion_id, headers, params=None):
        return self._request(
            "GET", f"/governance/motions/{motion_id}/votes", headers=headers, params=params
        )

    def list_physician_votes(self, physician_id, headers, params=None):
        return self._request(
            "GET", f"/governance/physicians/{physician_id}/votes", headers=headers, params=params
        )

    # --- Capital calls and assessments (PRD §3.5) ---
    def list_capital_calls(self, headers, params=None):
        return self._request("GET", "/governance/capital-calls", headers=headers, params=params)

    def get_capital_call(self, call_id, headers):
        return self._request("GET", f"/governance/capital-calls/{call_id}", headers=headers)

    def bill_capital_call(self, call_id, headers):
        return self._request("POST", f"/governance/capital-calls/{call_id}/bill", {}, headers)

    def list_call_assessments(self, call_id, headers, params=None):
        return self._request(
            "GET",
            f"/governance/capital-calls/{call_id}/assessments",
            headers=headers,
            params=params,
        )

    def list_physician_assessments(self, physician_id, headers, params=None):
        return self._request(
            "GET",
            f"/governance/physicians/{physician_id}/assessments",
            headers=headers,
            params=params,
        )

    def pay_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/governance/capital-call-assessments/{assessment_id}/pay",
            payload,
            headers,
        )

    # --- Distributions (PRD §3.5) ---
    def list_distributions(self, headers, params=None):
        return self._request("GET", "/governance/distributions", headers=headers, params=params)

    def get_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/governance/distributions/{distribution_id}", headers=headers
        )

    def pay_allocation(self, distribution_id, physician_id, headers):
        return self._request(
            "POST",
            f"/governance/distributions/{distribution_id}/allocations/{physician_id}/pay",
            {},
            headers,
        )

    def void_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/governance/distributions/{distribution_id}/void", {}, headers
        )

    # --- Exit valuations (PRD §3.6) ---
    def create_exit_valuation(self, payload, headers):
        return self._request("POST", "/governance/exit-valuations", payload, headers)

    def list_exit_valuations(self, headers, params=None):
        return self._request(
            "GET", "/governance/exit-valuations", headers=headers, params=params
        )

    def get_exit_valuation(self, valuation_id, headers):
        return self._request(
            "GET", f"/governance/exit-valuations/{valuation_id}", headers=headers
        )

    def appraise_exit_valuation(self, valuation_id, payload, headers):
        return self._request(
            "POST", f"/governance/exit-valuations/{valuation_id}/appraise", payload, headers
        )

    def dispute_exit_valuation(self, valuation_id, headers):
        return self._request(
            "POST", f"/governance/exit-valuations/{valuation_id}/dispute", {}, headers
        )

    def arbitrate_exit_valuation(self, valuation_id, headers):
        return self._request(
            "POST", f"/governance/exit-valuations/{valuation_id}/arbitrate", {}, headers
        )

    def finalize_exit_valuation(self, valuation_id, payload, headers):
        return self._request(
            "POST", f"/governance/exit-valuations/{valuation_id}/finalize", payload, headers
        )

    # --- COI disclosures (PRD §3.7) ---
    def create_coi_disclosure(self, payload, headers):
        return self._request("POST", "/governance/coi-disclosures", payload, headers)

    def list_coi_disclosures(self, headers, params=None):
        return self._request(
            "GET", "/governance/coi-disclosures", headers=headers, params=params
        )

    def get_coi_disclosure(self, disclosure_id, headers):
        return self._request(
            "GET", f"/governance/coi-disclosures/{disclosure_id}", headers=headers
        )

    def review_coi_disclosure(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/governance/coi-disclosures/{disclosure_id}/review", payload, headers
        )

    # --- Merger proposals (PRD §3.8) ---
    def create_merger_proposal(self, payload, headers):
        return self._request("POST", "/governance/merger-proposals", payload, headers)

    def list_merger_proposals(self, headers, params=None):
        return self._request(
            "GET", "/governance/merger-proposals", headers=headers, params=params
        )

    def get_merger_proposal(self, proposal_id, headers):
        return self._request(
            "GET", f"/governance/merger-proposals/{proposal_id}", headers=headers
        )

    def advance_merger_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/governance/merger-proposals/{proposal_id}/advance", payload, headers
        )

    def decide_merger_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/governance/merger-proposals/{proposal_id}/decide", payload, headers
        )

    # --- Test-driving logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
