"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Organization ---------------------------------------------------
    def create_organization(self, payload, headers):
        return self._request("POST", "/api/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/api/organizations/{org_id}", headers=headers)

    def set_payout_account(self, org_id, payload, headers):
        return self._request(
            "POST", f"/api/organizations/{org_id}/payout-account", payload, headers
        )

    # ---- Campaign -------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/api/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/api/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/api/campaigns", headers=headers, params=params)

    def publish_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/api/campaigns/{campaign_id}/publish", {}, headers
        )

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/api/campaigns/{campaign_id}/close", {}, headers)

    def get_thermometer(self, campaign_id, headers):
        return self._request(
            "GET", f"/api/campaigns/{campaign_id}/thermometer", headers=headers
        )

    def get_leaderboard(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/api/campaigns/{campaign_id}/leaderboard", headers=headers,
            params=params,
        )

    def get_report(self, campaign_id, headers):
        return self._request(
            "GET", f"/api/campaigns/{campaign_id}/report", headers=headers
        )

    def create_payout(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/api/campaigns/{campaign_id}/payouts", payload, headers
        )

    # ---- Event ----------------------------------------------------------
    def create_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/api/events", headers=headers, params=params)

    # ---- Team -----------------------------------------------------------
    def create_team(self, payload, headers):
        return self._request("POST", "/api/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/api/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/api/teams", headers=headers, params=params)

    def disband_team(self, team_id, headers):
        return self._request("POST", f"/api/teams/{team_id}/disband", {}, headers)

    # ---- Participant ----------------------------------------------------
    def create_participant(self, payload, headers):
        return self._request("POST", "/api/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request(
            "GET", f"/api/participants/{participant_id}", headers=headers
        )

    def list_participants(self, headers, params=None):
        return self._request("GET", "/api/participants", headers=headers, params=params)

    def activate_participant(self, participant_id, headers):
        return self._request(
            "POST", f"/api/participants/{participant_id}/activate", {}, headers
        )

    def withdraw_participant(self, participant_id, headers):
        return self._request(
            "POST", f"/api/participants/{participant_id}/withdraw", {}, headers
        )

    # ---- Registration ---------------------------------------------------
    def create_registration(self, payload, headers):
        return self._request("POST", "/api/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/api/registrations/{registration_id}", headers=headers
        )

    def list_registrations(self, headers, params=None):
        return self._request(
            "GET", "/api/registrations", headers=headers, params=params
        )

    def confirm_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/confirm", {}, headers
        )

    def cancel_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/cancel", {}, headers
        )

    def check_in_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/check-in", {}, headers
        )

    def no_show_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/no-show", {}, headers
        )

    # ---- Donor / Donation -----------------------------------------------
    def create_donor(self, payload, headers):
        return self._request("POST", "/api/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/api/donors/{donor_id}", headers=headers)

    def create_donation(self, payload, headers):
        return self._request("POST", "/api/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/api/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/api/donations", headers=headers, params=params)

    def settle_donation(self, donation_id, payload, headers):
        return self._request(
            "POST", f"/api/donations/{donation_id}/settle", payload, headers
        )

    def refund_donation(self, donation_id, payload, headers):
        return self._request(
            "POST", f"/api/donations/{donation_id}/refund", payload, headers
        )

    # ---- Match pools ----------------------------------------------------
    def create_match_pool(self, payload, headers):
        return self._request("POST", "/api/match-pools", payload, headers)

    def get_match_pool(self, pool_id, headers):
        return self._request("GET", f"/api/match-pools/{pool_id}", headers=headers)

    def list_match_pools(self, headers, params=None):
        return self._request("GET", "/api/match-pools", headers=headers, params=params)

    def close_match_pool(self, pool_id, headers):
        return self._request("POST", f"/api/match-pools/{pool_id}/close", {}, headers)

    # ---- Incentives -----------------------------------------------------
    def create_incentive_tier(self, payload, headers):
        return self._request("POST", "/api/incentive-tiers", payload, headers)

    def get_incentive_tier(self, tier_id, headers):
        return self._request("GET", f"/api/incentive-tiers/{tier_id}", headers=headers)

    def list_incentive_tiers(self, headers, params=None):
        return self._request(
            "GET", "/api/incentive-tiers", headers=headers, params=params
        )

    def get_incentive_award(self, award_id, headers):
        return self._request(
            "GET", f"/api/incentive-awards/{award_id}", headers=headers
        )

    def list_incentive_awards(self, headers, params=None):
        return self._request(
            "GET", "/api/incentive-awards", headers=headers, params=params
        )

    def fulfill_incentive_award(self, award_id, headers):
        return self._request(
            "POST", f"/api/incentive-awards/{award_id}/fulfill", {}, headers
        )

    # ---- Receipts -------------------------------------------------------
    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/api/receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/api/receipts", headers=headers, params=params)

    def void_receipt(self, receipt_id, headers):
        return self._request("POST", f"/api/receipts/{receipt_id}/void", {}, headers)

    def reissue_receipt(self, receipt_id, headers):
        return self._request("POST", f"/api/receipts/{receipt_id}/reissue", {}, headers)

    # ---- Payouts --------------------------------------------------------
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/api/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/api/payouts", headers=headers, params=params)

    def review_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/review", {}, headers)

    def request_changes_payout(self, payout_id, payload, headers):
        return self._request(
            "POST", f"/api/payouts/{payout_id}/request-changes", payload, headers
        )

    def resubmit_payout(self, payout_id, payload, headers):
        return self._request(
            "POST", f"/api/payouts/{payout_id}/resubmit", payload, headers
        )

    def approve_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/approve", {}, headers)

    def reject_payout(self, payout_id, payload, headers):
        return self._request(
            "POST", f"/api/payouts/{payout_id}/reject", payload, headers
        )

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/release", {}, headers)

    def void_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/void", payload, headers)

    # ---- Logical clock --------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
