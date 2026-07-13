"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (PRD §2.10) ───────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Organizers (PRD §3.1) ───────────────────────────────────────
    def create_organizer(self, payload, headers):
        return self._request("POST", "/organizers", payload, headers)

    def get_organizer(self, organizer_id, headers):
        return self._request("GET", f"/organizers/{organizer_id}", headers=headers)

    # ─── Beneficiaries (PRD §3.1) ────────────────────────────────────
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}", headers=headers)

    def withdrawal_setup(self, beneficiary_id, payload, headers):
        return self._request(
            "POST", f"/beneficiaries/{beneficiary_id}/withdrawal-setup", payload, headers
        )

    def submit_verification(self, beneficiary_id, headers, payload=None):
        return self._request(
            "POST",
            f"/beneficiaries/{beneficiary_id}/submit-verification",
            payload if payload is not None else {},
            headers,
        )

    def approve_verification(self, beneficiary_id, headers, payload=None):
        return self._request(
            "POST",
            f"/beneficiaries/{beneficiary_id}/approve-verification",
            payload if payload is not None else {},
            headers,
        )

    def reject_verification(self, beneficiary_id, payload, headers):
        return self._request(
            "POST", f"/beneficiaries/{beneficiary_id}/reject-verification", payload, headers
        )

    # ─── Donors (PRD §3.1) ───────────────────────────────────────────
    def create_donor(self, payload, headers):
        return self._request("POST", "/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    # ─── Campaigns (PRD §3.2) ────────────────────────────────────────
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def edit_campaign(self, campaign_id, payload, headers):
        return self._request("PATCH", f"/campaigns/{campaign_id}", payload, headers)

    def publish_campaign(self, campaign_id, headers, payload=None):
        return self._request(
            "POST",
            f"/campaigns/{campaign_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def pause_campaign(self, campaign_id, headers, payload=None):
        return self._request(
            "POST",
            f"/campaigns/{campaign_id}/pause",
            payload if payload is not None else {},
            headers,
        )

    def resume_campaign(self, campaign_id, headers, payload=None):
        return self._request(
            "POST",
            f"/campaigns/{campaign_id}/resume",
            payload if payload is not None else {},
            headers,
        )

    def complete_campaign(self, campaign_id, headers, payload=None):
        return self._request(
            "POST",
            f"/campaigns/{campaign_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_campaign(self, campaign_id, headers, payload=None):
        return self._request(
            "POST",
            f"/campaigns/{campaign_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Team Members (PRD §3.3) ─────────────────────────────────────
    def create_team_member(self, payload, headers):
        return self._request("POST", "/team-members", payload, headers)

    def get_team_member(self, team_member_id, headers):
        return self._request("GET", f"/team-members/{team_member_id}", headers=headers)

    def list_team_members(self, headers, params=None):
        return self._request("GET", "/team-members", headers=headers, params=params)

    def remove_team_member(self, team_member_id, headers, payload=None):
        return self._request(
            "POST",
            f"/team-members/{team_member_id}/remove",
            payload if payload is not None else {},
            headers,
        )

    # ─── Donations (PRD §3.4) ────────────────────────────────────────
    def create_donation(self, payload, headers):
        return self._request("POST", "/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/donations", headers=headers, params=params)

    def refund_donation(self, donation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/donations/{donation_id}/refund",
            payload if payload is not None else {},
            headers,
        )

    # ─── Updates / Thank-you notes (PRD §3.5) ────────────────────────
    def create_update(self, payload, headers):
        return self._request("POST", "/updates", payload, headers)

    def get_update(self, update_id, headers):
        return self._request("GET", f"/updates/{update_id}", headers=headers)

    def list_updates(self, headers, params=None):
        return self._request("GET", "/updates", headers=headers, params=params)

    # ─── Payouts (PRD §3.7) ──────────────────────────────────────────
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def process_payout(self, payout_id, headers, payload=None):
        return self._request(
            "POST",
            f"/payouts/{payout_id}/process",
            payload if payload is not None else {},
            headers,
        )

    def settle_payout(self, payout_id, headers, payload=None):
        return self._request(
            "POST",
            f"/payouts/{payout_id}/settle",
            payload if payload is not None else {},
            headers,
        )

    def fail_payout(self, payout_id, headers, payload=None):
        return self._request(
            "POST",
            f"/payouts/{payout_id}/fail",
            payload if payload is not None else {},
            headers,
        )

    def resume_payout(self, payout_id, headers, payload=None):
        return self._request(
            "POST",
            f"/payouts/{payout_id}/resume",
            payload if payload is not None else {},
            headers,
        )

    def reverse_payout(self, payout_id, headers, payload=None):
        return self._request(
            "POST",
            f"/payouts/{payout_id}/reverse",
            payload if payload is not None else {},
            headers,
        )

    # ─── Disputes (PRD §3.6) ─────────────────────────────────────────
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def assign_dispute(self, dispute_id, headers, payload=None):
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/assign",
            payload if payload is not None else {},
            headers,
        )

    def request_info_dispute(self, dispute_id, headers, payload=None):
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/request-info",
            payload if payload is not None else {},
            headers,
        )

    def provide_info_dispute(self, dispute_id, headers, payload=None):
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/provide-info",
            payload if payload is not None else {},
            headers,
        )

    def uphold_dispute(self, dispute_id, headers, payload=None):
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/uphold",
            payload if payload is not None else {},
            headers,
        )

    def reject_dispute(self, dispute_id, headers, payload=None):
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/reject",
            payload if payload is not None else {},
            headers,
        )

    # ─── Refunds (PRD §3.6) ──────────────────────────────────────────
    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    # ─── Holds (PRD §3.8) ────────────────────────────────────────────
    def create_hold(self, payload, headers):
        return self._request("POST", "/holds", payload, headers)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/holds/{hold_id}", headers=headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/holds", headers=headers, params=params)

    def release_hold(self, hold_id, headers, payload=None):
        return self._request(
            "POST",
            f"/holds/{hold_id}/release",
            payload if payload is not None else {},
            headers,
        )

    # ─── Feature Placements (PRD §3.8) ───────────────────────────────
    def create_feature_placement(self, payload, headers):
        return self._request("POST", "/feature-placements", payload, headers)

    def get_feature_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/feature-placements/{placement_id}", headers=headers
        )

    def list_feature_placements(self, headers, params=None):
        return self._request(
            "GET", "/feature-placements", headers=headers, params=params
        )

    def cancel_feature_placement(self, placement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/feature-placements/{placement_id}/cancel",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
