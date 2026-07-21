"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ───
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Merchant ───
    def create_merchant(self, payload, headers):
        return self._request("POST", "/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def activate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/activate", headers=headers)

    def suspend_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/suspend", headers=headers)

    def reactivate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/reactivate", headers=headers)

    def close_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/close", headers=headers)

    # ─── CardProgram ───
    def create_card_program(self, payload, headers):
        return self._request("POST", "/card-programs", payload, headers)

    def get_card_program(self, program_id, headers):
        return self._request("GET", f"/card-programs/{program_id}", headers=headers)

    def list_card_programs(self, headers, params=None):
        return self._request("GET", "/card-programs", headers=headers, params=params)

    def activate_card_program(self, program_id, headers):
        return self._request("POST", f"/card-programs/{program_id}/activate", headers=headers)

    def pause_card_program(self, program_id, headers):
        return self._request("POST", f"/card-programs/{program_id}/pause", headers=headers)

    def resume_card_program(self, program_id, headers):
        return self._request("POST", f"/card-programs/{program_id}/resume", headers=headers)

    def retire_card_program(self, program_id, headers):
        return self._request("POST", f"/card-programs/{program_id}/retire", headers=headers)

    def run_maintenance(self, program_id, headers):
        return self._request("POST", f"/card-programs/{program_id}/run-maintenance", headers=headers)

    # ─── IncentiveCampaign ───
    def create_incentive_campaign(self, payload, headers):
        return self._request("POST", "/incentive-campaigns", payload, headers)

    def get_incentive_campaign(self, campaign_id, headers):
        return self._request("GET", f"/incentive-campaigns/{campaign_id}", headers=headers)

    def list_incentive_campaigns(self, headers, params=None):
        return self._request("GET", "/incentive-campaigns", headers=headers, params=params)

    # ─── CardBatch ───
    def create_card_batch(self, payload, headers):
        return self._request("POST", "/card-batches", payload, headers)

    def get_card_batch(self, batch_id, headers):
        return self._request("GET", f"/card-batches/{batch_id}", headers=headers)

    def list_card_batches(self, headers, params=None):
        return self._request("GET", "/card-batches", headers=headers, params=params)

    def commit_card_batch(self, batch_id, headers):
        return self._request("POST", f"/card-batches/{batch_id}/commit", headers=headers)

    def cancel_card_batch(self, batch_id, headers):
        return self._request("POST", f"/card-batches/{batch_id}/cancel", headers=headers)

    # ─── GiftCard ───
    def get_gift_card(self, card_id, headers):
        return self._request("GET", f"/gift-cards/{card_id}", headers=headers)

    def get_gift_card_balance(self, card_id, headers):
        return self._request("GET", f"/gift-cards/{card_id}/balance", headers=headers)

    def list_gift_cards(self, headers, params=None):
        return self._request("GET", "/gift-cards", headers=headers, params=params)

    def activate_gift_card(self, card_id, headers):
        return self._request("POST", f"/gift-cards/{card_id}/activate", headers=headers)

    def redeem_gift_card(self, card_id, payload, headers):
        return self._request("POST", f"/gift-cards/{card_id}/redeem", payload, headers)

    def reload_gift_card(self, card_id, payload, headers):
        return self._request("POST", f"/gift-cards/{card_id}/reload", payload, headers)

    # ─── LedgerEntry ───
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # ─── FraudHold ───
    def open_fraud_hold(self, payload, headers):
        return self._request("POST", "/fraud-holds", payload, headers)

    def get_fraud_hold(self, hold_id, headers):
        return self._request("GET", f"/fraud-holds/{hold_id}", headers=headers)

    def list_fraud_holds(self, headers, params=None):
        return self._request("GET", "/fraud-holds", headers=headers, params=params)

    def clear_fraud_hold(self, hold_id, headers):
        return self._request("POST", f"/fraud-holds/{hold_id}/clear", headers=headers)

    def confirm_fraud_hold(self, hold_id, headers):
        return self._request("POST", f"/fraud-holds/{hold_id}/confirm", headers=headers)

    # ─── VelocityRule ───
    def create_velocity_rule(self, payload, headers):
        return self._request("POST", "/velocity-rules", payload, headers)

    def get_velocity_rule(self, rule_id, headers):
        return self._request("GET", f"/velocity-rules/{rule_id}", headers=headers)

    def list_velocity_rules(self, headers, params=None):
        return self._request("GET", "/velocity-rules", headers=headers, params=params)

    # ─── SettlementBatch ───
    def open_settlement_batch(self, payload, headers):
        return self._request("POST", "/settlement-batches", payload, headers)

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"/settlement-batches/{batch_id}", headers=headers)

    def list_settlement_batches(self, headers, params=None):
        return self._request("GET", "/settlement-batches", headers=headers, params=params)

    def finalize_settlement_batch(self, batch_id, headers):
        return self._request("POST", f"/settlement-batches/{batch_id}/finalize", headers=headers)

    def cancel_settlement_batch(self, batch_id, headers):
        return self._request("POST", f"/settlement-batches/{batch_id}/cancel", headers=headers)

    # ─── EscheatReport ───
    def create_escheat_report(self, payload, headers):
        return self._request("POST", "/escheat-reports", payload, headers)

    def get_escheat_report(self, report_id, headers):
        return self._request("GET", f"/escheat-reports/{report_id}", headers=headers)

    def list_escheat_reports(self, headers, params=None):
        return self._request("GET", "/escheat-reports", headers=headers, params=params)

    def remit_escheat_report(self, report_id, headers):
        return self._request("POST", f"/escheat-reports/{report_id}/remit", headers=headers)


api_client = ApiClient()
