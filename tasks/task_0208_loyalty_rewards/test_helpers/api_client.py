"""API client: one method per Loyalty Rewards endpoint."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Program config ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", {}, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    # ---- Tiers ----
    def create_tier(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/tiers", payload, headers)

    def list_tiers(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/tiers", headers=headers, params=params)

    # ---- Promotions ----
    def create_promotion(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/promotions", payload, headers)

    def list_promotions(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/promotions", headers=headers, params=params)

    def cancel_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/cancel", {}, headers)

    def refresh_promotions(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/refresh-promotions", {}, headers)

    # ---- Catalog rewards ----
    def create_reward(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/rewards", payload, headers)

    def list_rewards(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/rewards", headers=headers, params=params)

    def discontinue_reward(self, reward_id, headers):
        return self._request("POST", f"/rewards/{reward_id}/discontinue", {}, headers)

    # ---- Partner accounts ----
    def create_partner(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/partners", payload, headers)

    def pause_partner(self, partner_id, headers):
        return self._request("POST", f"/partners/{partner_id}/pause", {}, headers)

    def resume_partner(self, partner_id, headers):
        return self._request("POST", f"/partners/{partner_id}/resume", {}, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/partners/{partner_id}", headers=headers)

    def list_partners(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/partners", headers=headers, params=params)

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers)

    def reactivate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reactivate", {}, headers)

    def birthday_grant(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/birthday-grant", {}, headers)

    def list_member_lots(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/lots", headers=headers, params=params)

    # ---- Points transactions ----
    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    # ---- Purchase events ----
    def create_purchase_event(self, payload, headers):
        return self._request("POST", "/purchase-events", payload, headers)

    def get_purchase_event(self, purchase_event_id, headers):
        return self._request("GET", f"/purchase-events/{purchase_event_id}", headers=headers)

    def list_purchase_events(self, headers, params=None):
        return self._request("GET", "/purchase-events", headers=headers, params=params)

    # ---- Redemptions ----
    def create_redemption(self, payload, headers):
        return self._request("POST", "/redemptions", payload, headers)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/redemptions/{redemption_id}", headers=headers)

    def list_member_redemptions(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/redemptions", headers=headers, params=params)

    def list_redemption_lines(self, redemption_id, headers, params=None):
        return self._request("GET", f"/redemptions/{redemption_id}/lines", headers=headers, params=params)

    def get_redemption_line(self, line_id, headers):
        return self._request("GET", f"/redemption-lines/{line_id}", headers=headers)

    def list_all_redemption_lines(self, headers, params=None):
        return self._request("GET", "/redemption-lines", headers=headers, params=params)

    def confirm_redemption(self, redemption_id, payload, headers):
        return self._request("POST", f"/redemptions/{redemption_id}/confirm", payload, headers)

    def fulfill_redemption(self, redemption_id, headers):
        return self._request("POST", f"/redemptions/{redemption_id}/fulfill", {}, headers)

    def cancel_redemption(self, redemption_id, headers):
        return self._request("POST", f"/redemptions/{redemption_id}/cancel", {}, headers)

    # ---- Referrals ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def list_member_referrals(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/referrals", headers=headers, params=params)

    def revoke_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/revoke", {}, headers)

    # ---- Partner transfers ----
    def create_partner_transfer(self, payload, headers):
        return self._request("POST", "/partner-transfers", payload, headers)

    def get_partner_transfer(self, transfer_id, headers):
        return self._request("GET", f"/partner-transfers/{transfer_id}", headers=headers)

    def list_member_transfers(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/partner-transfers", headers=headers, params=params)

    def list_partner_transfers(self, partner_id, headers, params=None):
        return self._request("GET", f"/partners/{partner_id}/transfers", headers=headers, params=params)

    def settle_transfer(self, transfer_id, headers):
        return self._request("POST", f"/partner-transfers/{transfer_id}/settle", {}, headers)

    def reverse_transfer(self, transfer_id, headers):
        return self._request("POST", f"/partner-transfers/{transfer_id}/reverse", {}, headers)

    # ---- Transfer blackouts ----
    def create_blackout(self, partner_id, payload, headers):
        return self._request("POST", f"/partners/{partner_id}/blackouts", payload, headers)

    def get_blackout(self, blackout_id, headers):
        return self._request("GET", f"/blackouts/{blackout_id}", headers=headers)

    def list_blackouts(self, partner_id, headers, params=None):
        return self._request("GET", f"/partners/{partner_id}/blackouts", headers=headers, params=params)

    def cancel_blackout(self, blackout_id, headers):
        return self._request("POST", f"/blackouts/{blackout_id}/cancel", {}, headers)

    # ---- Maintenance / clock ----
    def sweep_expirations(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/sweep-expirations", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def advance_clock(self, months, headers):
        return self._request("POST", "/_clock/advance", {"months": months}, headers)


api_client = ApiClient()
