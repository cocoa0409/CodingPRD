"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint methods for the Card Issuing Program API."""

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/issuing/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- CardProgram ----
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/issuing/programs", payload, headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/issuing/programs", headers=headers, params=params)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/programs/{program_id}", headers=headers)

    def update_program(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PUT", f"/issuing/programs/{program_id}", payload, headers)

    def publish_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/programs/{program_id}/publish", {}, headers)

    def sunset_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/programs/{program_id}/sunset", {}, headers)

    def cancel_sunset_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/programs/{program_id}/cancel_sunset", {}, headers)

    def terminate_program(self, program_id: str, termination_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/programs/{program_id}/terminate",
            {"termination_reason": termination_reason}, headers,
        )

    def get_program_economics(self, program_id: str, month: str, headers: Dict[str, str],
                               variant: Optional[str] = None):
        params: Dict[str, Any] = {"month": month}
        if variant is not None:
            params["variant"] = variant
        return self._request(
            "GET", f"/issuing/programs/{program_id}/economics",
            headers=headers, params=params,
        )

    # ---- BinRange ----
    def create_bin_range(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/issuing/programs/{program_id}/bin-ranges", payload, headers)

    def list_bin_ranges(self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/programs/{program_id}/bin-ranges",
                             headers=headers, params=params)

    def get_bin_range(self, bin_range_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/bin-ranges/{bin_range_id}", headers=headers)

    def freeze_bin_range(self, bin_range_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/bin-ranges/{bin_range_id}/freeze", {}, headers)

    def unfreeze_bin_range(self, bin_range_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/bin-ranges/{bin_range_id}/unfreeze", {}, headers)

    def retire_bin_range(self, bin_range_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/bin-ranges/{bin_range_id}/retire", {}, headers)

    def list_bin_range_cards(self, bin_range_id: str, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/bin-ranges/{bin_range_id}/cards",
                             headers=headers, params=params)

    # ---- ProductionVendor ----
    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/issuing/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/vendors/{vendor_id}", headers=headers)

    def list_vendor_batches(self, vendor_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/vendors/{vendor_id}/production-batches",
                             headers=headers, params=params)

    # ---- ProductionBatch ----
    def create_production_batch(self, program_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"/issuing/programs/{program_id}/production-batches",
                             payload, headers)

    def list_production_batches(self, program_id: str, headers: Dict[str, str],
                                 params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/programs/{program_id}/production-batches",
                             headers=headers, params=params)

    def get_production_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/production-batches/{batch_id}", headers=headers)

    def submit_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/production-batches/{batch_id}/submit", {}, headers)

    def start_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/production-batches/{batch_id}/start", {}, headers)

    def mark_batch_shipped(self, batch_id: str, fulfilled_card_count: int,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/production-batches/{batch_id}/mark_shipped",
            {"fulfilled_card_count": fulfilled_card_count}, headers,
        )

    def mark_batch_delivered(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/production-batches/{batch_id}/mark_delivered",
                             {}, headers)

    def cancel_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/production-batches/{batch_id}/cancel", {}, headers)

    def mark_batch_failed(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/production-batches/{batch_id}/mark_failed",
                             {}, headers)

    # ---- CardAccount ----
    def create_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/issuing/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/issuing/accounts", headers=headers, params=params)

    def list_program_accounts(self, program_id: str, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/programs/{program_id}/accounts",
                             headers=headers, params=params)

    def update_account(self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PUT", f"/issuing/accounts/{account_id}", payload, headers)

    def activate_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/accounts/{account_id}/activate", {}, headers)

    def suspend_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/accounts/{account_id}/suspend", {}, headers)

    def resume_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/accounts/{account_id}/resume", {}, headers)

    def close_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/accounts/{account_id}/close", {}, headers)

    def fund_account(self, account_id: str, amount_cents: int, headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/accounts/{account_id}/fund",
            {"amount_cents": amount_cents}, headers,
        )

    # ---- Card ----
    def issue_card(self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/issuing/accounts/{account_id}/cards", payload, headers)

    def get_card(self, card_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/cards/{card_id}", headers=headers)

    def list_account_cards(self, account_id: str, headers: Dict[str, str],
                            params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/accounts/{account_id}/cards",
                             headers=headers, params=params)

    def list_cards(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/issuing/cards", headers=headers, params=params)

    def activate_card(self, card_id: str, activation_token: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/cards/{card_id}/activate",
            {"activation_token": activation_token}, headers,
        )

    def suspend_card(self, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/cards/{card_id}/suspend", {}, headers)

    def resume_card(self, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/cards/{card_id}/resume", {}, headers)

    def cancel_card(self, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/cards/{card_id}/cancel", {}, headers)

    def mark_card_compromised(self, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/cards/{card_id}/mark_compromised", {}, headers)

    def set_pin(self, card_id: str, new_pin: str, headers: Dict[str, str],
                 current_pin: Optional[str] = None):
        payload: Dict[str, Any] = {"new_pin": new_pin}
        if current_pin is not None:
            payload["current_pin"] = current_pin
        return self._request("POST", f"/issuing/cards/{card_id}/pin", payload, headers)

    def pin_reset_request(self, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/cards/{card_id}/pin_reset_request", {}, headers)

    def pin_block(self, card_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/cards/{card_id}/pin_block", {}, headers)

    def create_authorization(self, card_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/issuing/cards/{card_id}/authorizations",
                             payload, headers)

    def list_card_authorizations(self, card_id: str, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/cards/{card_id}/authorizations",
                             headers=headers, params=params)

    def list_card_activation_tokens(self, card_id: str, headers: Dict[str, str],
                                     params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/cards/{card_id}/activation-tokens",
                             headers=headers, params=params)

    # ---- Settlement / AuthorizationEvent reads ----
    def settle_authorization(self, auth_event_id: str, settled_amount_cents: int,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/authorization-events/{auth_event_id}/settle",
            {"settled_amount_cents": settled_amount_cents}, headers,
        )

    def get_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/settlements/{settlement_id}", headers=headers)

    def list_card_settlements(self, card_id: str, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/cards/{card_id}/settlements",
                             headers=headers, params=params)

    def get_authorization_event(self, auth_event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/authorization-events/{auth_event_id}",
                             headers=headers)

    def list_authorization_event_settlements(self, auth_event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/issuing/authorization-events/{auth_event_id}/settlements",
            headers=headers,
        )

    def list_account_authorization_events(self, account_id: str, headers: Dict[str, str],
                                          params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/accounts/{account_id}/authorization-events",
                             headers=headers, params=params)

    def list_account_settlements(self, account_id: str, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/accounts/{account_id}/settlements",
                             headers=headers, params=params)

    def list_program_authorization_events(self, program_id: str, headers: Dict[str, str],
                                          params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/programs/{program_id}/authorization-events",
                             headers=headers, params=params)

    # ---- AuthorizationRule ----
    def create_authorization_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/issuing/authorization-rules", payload, headers)

    def get_authorization_rule(self, rule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/authorization-rules/{rule_id}", headers=headers)

    def list_authorization_rules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/issuing/authorization-rules",
                             headers=headers, params=params)

    def update_authorization_rule(self, rule_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("PUT", f"/issuing/authorization-rules/{rule_id}", payload, headers)

    def activate_authorization_rule(self, rule_id: str, expected_rule_version: int,
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/authorization-rules/{rule_id}/activate",
            {"expected_rule_version": expected_rule_version}, headers,
        )

    def activate_authorization_rule_raw(self, rule_id: str, payload: Dict[str, Any],
                                         headers: Dict[str, str]):
        """Low-level activate for OCC-negative tests (caller crafts the payload)."""
        return self._request(
            "POST", f"/issuing/authorization-rules/{rule_id}/activate", payload, headers,
        )

    def retire_authorization_rule(self, rule_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/authorization-rules/{rule_id}/retire",
                             {}, headers)

    def list_rule_authorization_events(self, rule_id: str, headers: Dict[str, str],
                                       params: Optional[Dict] = None):
        return self._request(
            "GET", f"/issuing/authorization-rules/{rule_id}/authorization-events",
            headers=headers, params=params,
        )

    # ---- Mandate ----
    def create_mandate(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/issuing/mandates", payload, headers)

    def get_mandate(self, mandate_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/mandates/{mandate_id}", headers=headers)

    def list_mandates(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/issuing/mandates", headers=headers, params=params)

    def retire_mandate(self, mandate_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/mandates/{mandate_id}/retire", {}, headers)

    # ---- MandateAck ----
    def create_mandate_ack(self, mandate_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/issuing/mandates/{mandate_id}/acks",
                             payload, headers)

    def list_mandate_acks(self, mandate_id: str, headers: Dict[str, str],
                          params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/mandates/{mandate_id}/acks",
                             headers=headers, params=params)

    def get_mandate_ack(self, mandate_id: str, ack_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/mandates/{mandate_id}/acks/{ack_id}",
                             headers=headers)

    def submit_mandate_ack(self, mandate_id: str, ack_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/mandates/{mandate_id}/acks/{ack_id}/submit", {}, headers,
        )

    def return_mandate_ack(self, mandate_id: str, ack_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/mandates/{mandate_id}/acks/{ack_id}/return", {}, headers,
        )

    def verify_mandate_ack(self, mandate_id: str, ack_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/mandates/{mandate_id}/acks/{ack_id}/verify", {}, headers,
        )

    def reject_mandate_ack(self, mandate_id: str, ack_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/issuing/mandates/{mandate_id}/acks/{ack_id}/reject", {}, headers,
        )

    def list_program_mandate_acks(self, program_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/programs/{program_id}/mandate-acks",
                             headers=headers, params=params)

    # ---- ReissueCampaign ----
    def create_reissue_campaign(self, program_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"/issuing/programs/{program_id}/reissue-campaigns",
                             payload, headers)

    def list_reissue_campaigns(self, program_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/programs/{program_id}/reissue-campaigns",
                             headers=headers, params=params)

    def get_reissue_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/reissue-campaigns/{campaign_id}",
                             headers=headers)

    def list_campaign_cards(self, campaign_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/reissue-campaigns/{campaign_id}/cards",
                             headers=headers, params=params)

    def schedule_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/reissue-campaigns/{campaign_id}/schedule",
                             {}, headers)

    def cancel_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/reissue-campaigns/{campaign_id}/cancel",
                             {}, headers)

    # ---- ConversionJob ----
    def create_conversion_job(self, program_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"/issuing/programs/{program_id}/conversion-jobs",
                             payload, headers)

    def list_conversion_jobs(self, program_id: str, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", f"/issuing/programs/{program_id}/conversion-jobs",
                             headers=headers, params=params)

    def get_conversion_job(self, job_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/issuing/conversion-jobs/{job_id}", headers=headers)

    def cancel_conversion_job(self, job_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/issuing/conversion-jobs/{job_id}/cancel",
                             {}, headers)


api_client = ApiClient()
