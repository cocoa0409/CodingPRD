"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

Subclasses GenericApiClient; the base _request() handles HTTP and the response envelope.
For GET endpoints, filter/query parameters are passed via the payload argument (the base
client routes GET payloads to query params).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ── Program ──────────────────────────────────────────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/v1/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/v1/programs/{program_id}", headers=headers)

    # ── StateRule ────────────────────────────────────────────────────────
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/v1/state-rules", payload, headers)

    def get_state_rule(self, state_rule_id, headers):
        return self._request("GET", f"/v1/state-rules/{state_rule_id}", headers=headers)

    def list_state_rules(self, headers, params=None):
        return self._request("GET", "/v1/state-rules", headers=headers, params=params)

    # ── PromoCampaign ────────────────────────────────────────────────────
    def create_campaign(self, payload, headers):
        return self._request("POST", "/v1/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/v1/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/v1/campaigns", headers=headers, params=params)

    def sync_campaign_status(self, campaign_id, headers):
        return self._request("POST", f"/v1/campaigns/{campaign_id}/sync-status", {}, headers)

    # ── Customer ─────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customers/{customer_id}", headers=headers)

    # ── GiftCard ─────────────────────────────────────────────────────────
    def create_card(self, payload, headers):
        return self._request("POST", "/v1/cards", payload, headers)

    def get_card(self, card_id, headers):
        return self._request("GET", f"/v1/cards/{card_id}", headers=headers)

    def list_cards(self, headers, params=None):
        return self._request("GET", "/v1/cards", headers=headers, params=params)

    def activate_card(self, card_id, payload, headers):
        return self._request("POST", f"/v1/cards/{card_id}/activate", payload, headers)

    def reload_card(self, card_id, payload, headers):
        return self._request("POST", f"/v1/cards/{card_id}/reload", payload, headers)

    def assess_dormancy(self, card_id, headers):
        return self._request("POST", f"/v1/cards/{card_id}/assess-dormancy", {}, headers)

    def flag_card(self, card_id, headers):
        return self._request("POST", f"/v1/cards/{card_id}/flag", {}, headers)

    def freeze_card(self, card_id, headers):
        return self._request("POST", f"/v1/cards/{card_id}/freeze", {}, headers)

    def clear_risk(self, card_id, headers):
        return self._request("POST", f"/v1/cards/{card_id}/clear-risk", {}, headers)

    # ── LedgerEntry ──────────────────────────────────────────────────────
    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/v1/ledger-entries/{ledger_entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/v1/ledger-entries", headers=headers, params=params)

    # ── AuthorizationHold ────────────────────────────────────────────────
    def create_hold(self, payload, headers):
        return self._request("POST", "/v1/holds", payload, headers)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/v1/holds/{hold_id}", headers=headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/v1/holds", headers=headers, params=params)

    def release_hold(self, hold_id, headers):
        return self._request("POST", f"/v1/holds/{hold_id}/release", {}, headers)

    # ── Redemption ───────────────────────────────────────────────────────
    def create_redemption(self, payload, headers):
        return self._request("POST", "/v1/redemptions", payload, headers)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/v1/redemptions/{redemption_id}", headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/v1/redemptions", headers=headers, params=params)

    def amend_redemption(self, redemption_id, payload, headers):
        return self._request("PATCH", f"/v1/redemptions/{redemption_id}", payload, headers)

    def settle_redemption(self, redemption_id, payload, headers):
        return self._request("POST", f"/v1/redemptions/{redemption_id}/settle", payload, headers)

    def void_redemption(self, redemption_id, headers):
        return self._request("POST", f"/v1/redemptions/{redemption_id}/void", {}, headers)

    # ── RedemptionLeg ────────────────────────────────────────────────────
    def get_redemption_leg(self, leg_id, headers):
        return self._request("GET", f"/v1/redemption-legs/{leg_id}", headers=headers)

    def list_redemption_legs(self, headers, params=None):
        return self._request("GET", "/v1/redemption-legs", headers=headers, params=params)

    # ── BulkOrder ────────────────────────────────────────────────────────
    def create_bulk_order(self, payload, headers):
        return self._request("POST", "/v1/bulk-orders", payload, headers)

    def get_bulk_order(self, bulk_order_id, headers):
        return self._request("GET", f"/v1/bulk-orders/{bulk_order_id}", headers=headers)

    def list_bulk_orders(self, headers, params=None):
        return self._request("GET", "/v1/bulk-orders", headers=headers, params=params)

    def confirm_bulk_order(self, bulk_order_id, headers):
        return self._request("POST", f"/v1/bulk-orders/{bulk_order_id}/confirm", {}, headers)

    def activate_bulk_order(self, bulk_order_id, headers):
        return self._request("POST", f"/v1/bulk-orders/{bulk_order_id}/activate", {}, headers)

    def cancel_bulk_order(self, bulk_order_id, headers):
        return self._request("POST", f"/v1/bulk-orders/{bulk_order_id}/cancel", {}, headers)

    # ── ReplacementRequest ───────────────────────────────────────────────
    def create_replacement(self, payload, headers):
        return self._request("POST", "/v1/replacements", payload, headers)

    def get_replacement(self, replacement_id, headers):
        return self._request("GET", f"/v1/replacements/{replacement_id}", headers=headers)

    def list_replacements(self, headers, params=None):
        return self._request("GET", "/v1/replacements", headers=headers, params=params)

    def approve_replacement(self, replacement_id, payload, headers):
        return self._request("POST", f"/v1/replacements/{replacement_id}/approve", payload, headers)

    def reject_replacement(self, replacement_id, headers):
        return self._request("POST", f"/v1/replacements/{replacement_id}/reject", {}, headers)

    # ── RefundRequest ────────────────────────────────────────────────────
    def create_refund(self, payload, headers):
        return self._request("POST", "/v1/refunds", payload, headers)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/v1/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/v1/refunds", headers=headers, params=params)

    def approve_refund(self, refund_id, headers):
        return self._request("POST", f"/v1/refunds/{refund_id}/approve", {}, headers)

    def request_refund_revision(self, refund_id, headers):
        return self._request("POST", f"/v1/refunds/{refund_id}/request-revision", {}, headers)

    def resubmit_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/v1/refunds/{refund_id}/resubmit", payload, headers)

    def deny_refund(self, refund_id, headers):
        return self._request("POST", f"/v1/refunds/{refund_id}/deny", {}, headers)

    # ── DormancyWaiver ───────────────────────────────────────────────────
    def create_dormancy_waiver(self, payload, headers):
        return self._request("POST", "/v1/dormancy-waivers", payload, headers)

    def get_dormancy_waiver(self, waiver_id, headers):
        return self._request("GET", f"/v1/dormancy-waivers/{waiver_id}", headers=headers)

    def list_dormancy_waivers(self, headers, params=None):
        return self._request("GET", "/v1/dormancy-waivers", headers=headers, params=params)

    # ── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/v1/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
