"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Fiscal periods
    # ------------------------------------------------------------------
    def create_fiscal_period(self, payload, headers):
        return self._request("POST", "/fiscal-periods", payload, headers)

    def get_fiscal_period(self, period_id, headers):
        return self._request("GET", f"/fiscal-periods/{period_id}", headers=headers)

    def list_fiscal_periods(self, headers, params=None):
        return self._request("GET", "/fiscal-periods", headers=headers, params=params)

    def fiscal_period_status_action(self, period_id, payload, headers):
        return self._request(
            "POST", f"/fiscal-periods/{period_id}/status-actions", payload, headers
        )

    def fiscal_period_board_override(self, period_id, payload, headers):
        return self._request(
            "POST", f"/fiscal-periods/{period_id}/board-override", payload, headers
        )

    def get_sustainability(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/fiscal-periods/{period_id}/sustainability", headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Membership tiers
    # ------------------------------------------------------------------
    def create_membership_tier(self, payload, headers):
        return self._request("POST", "/membership-tiers", payload, headers)

    def get_membership_tier(self, tier_id, headers):
        return self._request("GET", f"/membership-tiers/{tier_id}", headers=headers)

    def list_membership_tiers(self, headers, params=None):
        return self._request("GET", "/membership-tiers", headers=headers, params=params)

    def publish_membership_tier(self, tier_id, headers):
        return self._request(
            "POST", f"/membership-tiers/{tier_id}/publish", {}, headers
        )

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def member_lifecycle_action(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/lifecycle-actions", payload, headers
        )

    def member_tier_change(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/tier-change", payload, headers
        )

    # ------------------------------------------------------------------
    # Coverage areas
    # ------------------------------------------------------------------
    def create_coverage_area(self, payload, headers):
        return self._request("POST", "/coverage-areas", payload, headers)

    def get_coverage_area(self, area_id, headers):
        return self._request("GET", f"/coverage-areas/{area_id}", headers=headers)

    def list_coverage_areas(self, headers, params=None):
        return self._request("GET", "/coverage-areas", headers=headers, params=params)

    def get_transparency_report(self, area_id, headers, params=None):
        return self._request(
            "GET", f"/coverage-areas/{area_id}/transparency-report", headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Funders
    # ------------------------------------------------------------------
    def create_funder(self, payload, headers):
        return self._request("POST", "/funders", payload, headers)

    def get_funder(self, funder_id, headers):
        return self._request("GET", f"/funders/{funder_id}", headers=headers)

    def list_funders(self, headers, params=None):
        return self._request("GET", "/funders", headers=headers, params=params)

    def funder_independence_clearance(self, funder_id, payload, headers):
        return self._request(
            "POST", f"/funders/{funder_id}/independence-clearance", payload, headers
        )

    # ------------------------------------------------------------------
    # Firewall disclosures
    # ------------------------------------------------------------------
    def create_firewall_disclosure(self, payload, headers):
        return self._request("POST", "/firewall-disclosures", payload, headers)

    def get_firewall_disclosure(self, disclosure_id, headers):
        return self._request(
            "GET", f"/firewall-disclosures/{disclosure_id}", headers=headers
        )

    def list_firewall_disclosures(self, headers, params=None):
        return self._request(
            "GET", "/firewall-disclosures", headers=headers, params=params
        )

    def attest_firewall_disclosure(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/firewall-disclosures/{disclosure_id}/attest", payload, headers
        )

    # ------------------------------------------------------------------
    # Influence contacts
    # ------------------------------------------------------------------
    def create_influence_contact(self, payload, headers):
        return self._request("POST", "/influence-contacts", payload, headers)

    def get_influence_contact(self, contact_id, headers):
        return self._request("GET", f"/influence-contacts/{contact_id}", headers=headers)

    def list_influence_contacts(self, headers, params=None):
        return self._request("GET", "/influence-contacts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Gift offers
    # ------------------------------------------------------------------
    def create_gift_offer(self, payload, headers):
        return self._request("POST", "/gift-offers", payload, headers)

    def get_gift_offer(self, offer_id, headers):
        return self._request("GET", f"/gift-offers/{offer_id}", headers=headers)

    def list_gift_offers(self, headers, params=None):
        return self._request("GET", "/gift-offers", headers=headers, params=params)

    def submit_gift_offer_for_review(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/gift-offers/{offer_id}/submit-for-review", payload, headers
        )

    def gift_offer_independence_review(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/gift-offers/{offer_id}/independence-review", payload, headers
        )

    def gift_offer_board_ratification(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/gift-offers/{offer_id}/board-ratification", payload, headers
        )

    def accept_gift_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/gift-offers/{offer_id}/accept", payload, headers
        )

    # ------------------------------------------------------------------
    # Grant proposals
    # ------------------------------------------------------------------
    def create_grant_proposal(self, payload, headers):
        return self._request("POST", "/grant-proposals", payload, headers)

    def get_grant_proposal(self, proposal_id, headers):
        return self._request("GET", f"/grant-proposals/{proposal_id}", headers=headers)

    def list_grant_proposals(self, headers, params=None):
        return self._request("GET", "/grant-proposals", headers=headers, params=params)

    def grant_proposal_pipeline_action(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/grant-proposals/{proposal_id}/pipeline-actions", payload, headers
        )

    def grant_proposal_internal_review(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/grant-proposals/{proposal_id}/internal-review", payload, headers
        )

    def grant_proposal_record_outcome(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/grant-proposals/{proposal_id}/record-outcome", payload, headers
        )

    def release_restricted_funds(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/grant-proposals/{proposal_id}/release-restricted-funds",
            payload, headers,
        )

    def reinstate_grant_proposal(self, proposal_id, headers):
        return self._request(
            "POST", f"/grant-proposals/{proposal_id}/reinstate", {}, headers
        )

    def close_grant_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/grant-proposals/{proposal_id}/close", payload, headers
        )

    def list_grant_proposal_reports(self, proposal_id, headers, params=None):
        return self._request(
            "GET", f"/grant-proposals/{proposal_id}/reports", headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Grant reports
    # ------------------------------------------------------------------
    def get_grant_report(self, report_id, headers):
        return self._request("GET", f"/grant-reports/{report_id}", headers=headers)

    def list_grant_reports(self, headers, params=None):
        return self._request("GET", "/grant-reports", headers=headers, params=params)

    def submit_grant_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/grant-reports/{report_id}/submit", payload, headers
        )

    def review_grant_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/grant-reports/{report_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Contributions
    # ------------------------------------------------------------------
    def create_contribution(self, payload, headers):
        return self._request("POST", "/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/contributions/{contribution_id}", headers=headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", "/contributions", headers=headers, params=params)

    def settle_contribution(self, contribution_id, payload, headers):
        return self._request(
            "POST", f"/contributions/{contribution_id}/settlement", payload, headers
        )

    def refund_contribution(self, contribution_id, payload, headers):
        return self._request(
            "POST", f"/contributions/{contribution_id}/refund", payload, headers
        )

    def acknowledge_contribution(self, contribution_id, payload, headers):
        return self._request(
            "POST", f"/contributions/{contribution_id}/acknowledge", payload, headers
        )

    # ------------------------------------------------------------------
    # Collaborations
    # ------------------------------------------------------------------
    def create_collaboration(self, payload, headers):
        return self._request("POST", "/collaborations", payload, headers)

    def get_collaboration(self, collaboration_id, headers):
        return self._request(
            "GET", f"/collaborations/{collaboration_id}", headers=headers
        )

    def list_collaborations(self, headers, params=None):
        return self._request("GET", "/collaborations", headers=headers, params=params)

    def create_collaboration_partner(self, collaboration_id, payload, headers):
        return self._request(
            "POST", f"/collaborations/{collaboration_id}/partners", payload, headers
        )

    def list_collaboration_partners(self, collaboration_id, headers, params=None):
        return self._request(
            "GET", f"/collaborations/{collaboration_id}/partners", headers=headers,
            params=params,
        )

    def collaboration_status_action(self, collaboration_id, payload, headers):
        return self._request(
            "POST", f"/collaborations/{collaboration_id}/status-actions", payload,
            headers,
        )

    def get_collaboration_partner(self, partner_id, headers):
        return self._request(
            "GET", f"/collaboration-partners/{partner_id}", headers=headers
        )

    def withdraw_collaboration_partner(self, partner_id, payload, headers):
        return self._request(
            "POST", f"/collaboration-partners/{partner_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock and operations
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def daily_sweep(self, headers):
        return self._request("POST", "/ops/daily-sweep", {}, headers)


api_client = ApiClient()
