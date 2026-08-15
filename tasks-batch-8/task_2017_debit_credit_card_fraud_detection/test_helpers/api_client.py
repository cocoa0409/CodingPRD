"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- rule sets ----
    def create_rule_set(self, payload, headers):
        return self._request("POST", "/fraudops/rule-sets", payload, headers)

    def list_rule_sets(self, headers, params=None):
        return self._request("GET", "/fraudops/rule-sets", headers=headers, params=params)

    def get_rule_set(self, ruleset_id, headers):
        return self._request("GET", f"/fraudops/rule-sets/{ruleset_id}", headers=headers)

    def update_rule_set(self, ruleset_id, payload, headers):
        return self._request("PUT", f"/fraudops/rule-sets/{ruleset_id}", payload, headers)

    def activate_rule_set(self, ruleset_id, headers):
        return self._request("POST", f"/fraudops/rule-sets/{ruleset_id}/activate", headers=headers)

    def retire_rule_set(self, ruleset_id, headers):
        return self._request("POST", f"/fraudops/rule-sets/{ruleset_id}/retire", headers=headers)

    def get_rule_set_metrics(self, ruleset_id, headers):
        return self._request("GET", f"/fraudops/rule-sets/{ruleset_id}/metrics", headers=headers)

    # ---- accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/fraudops/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/fraudops/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/fraudops/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/fraudops/accounts/{account_id}/suspend", headers=headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/fraudops/accounts/{account_id}/reinstate", headers=headers)

    # ---- cards ----
    def create_card(self, payload, headers):
        return self._request("POST", "/fraudops/cards", payload, headers)

    def list_cards(self, headers, params=None):
        return self._request("GET", "/fraudops/cards", headers=headers, params=params)

    def get_card(self, card_id, headers):
        return self._request("GET", f"/fraudops/cards/{card_id}", headers=headers)

    def block_card(self, card_id, payload, headers):
        return self._request("POST", f"/fraudops/cards/{card_id}/block", payload, headers)

    def unblock_card(self, card_id, headers):
        return self._request("POST", f"/fraudops/cards/{card_id}/unblock", headers=headers)

    def list_card_travel_notices(self, card_id, headers, params=None):
        return self._request("GET", f"/fraudops/cards/{card_id}/travel-notices", headers=headers, params=params)

    # ---- auth transactions ----
    def create_auth_transaction(self, payload, headers):
        return self._request("POST", "/fraudops/auth-transactions", payload, headers)

    def list_auth_transactions(self, headers, params=None):
        return self._request("GET", "/fraudops/auth-transactions", headers=headers, params=params)

    def get_auth_transaction(self, txn_id, headers):
        return self._request("GET", f"/fraudops/auth-transactions/{txn_id}", headers=headers)

    # ---- fraud alerts ----
    def create_fraud_alert(self, payload, headers):
        return self._request("POST", "/fraudops/fraud-alerts", payload, headers)

    def list_fraud_alerts(self, headers, params=None):
        return self._request("GET", "/fraudops/fraud-alerts", headers=headers, params=params)

    def get_fraud_alert(self, alert_id, headers):
        return self._request("GET", f"/fraudops/fraud-alerts/{alert_id}", headers=headers)

    def claim_fraud_alert(self, alert_id, headers):
        return self._request("POST", f"/fraudops/fraud-alerts/{alert_id}/claim", headers=headers)

    def resolve_fraud_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/fraudops/fraud-alerts/{alert_id}/resolve", payload, headers)

    def respond_fraud_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/fraudops/fraud-alerts/{alert_id}/respond", payload, headers)

    def reopen_fraud_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/fraudops/fraud-alerts/{alert_id}/reopen", payload, headers)

    # ---- verification contacts ----
    def create_verification_contact(self, payload, headers):
        return self._request("POST", "/fraudops/verification-contacts", payload, headers)

    def list_verification_contacts(self, headers, params=None):
        return self._request("GET", "/fraudops/verification-contacts", headers=headers, params=params)

    def get_verification_contact(self, contact_id, headers):
        return self._request("GET", f"/fraudops/verification-contacts/{contact_id}", headers=headers)

    def complete_verification_contact(self, contact_id, payload, headers):
        return self._request("POST", f"/fraudops/verification-contacts/{contact_id}/complete", payload, headers)

    # ---- compromised card events ----
    def create_compromised_card_event(self, payload, headers):
        return self._request("POST", "/fraudops/compromised-card-events", payload, headers)

    def list_compromised_card_events(self, headers, params=None):
        return self._request("GET", "/fraudops/compromised-card-events", headers=headers, params=params)

    def get_compromised_card_event(self, event_id, headers):
        return self._request("GET", f"/fraudops/compromised-card-events/{event_id}", headers=headers)

    def confirm_compromised_card_event(self, event_id, headers):
        return self._request("POST", f"/fraudops/compromised-card-events/{event_id}/confirm", headers=headers)

    # ---- reissue decisions ----
    def list_reissue_decisions(self, headers, params=None):
        return self._request("GET", "/fraudops/reissue-decisions", headers=headers, params=params)

    def get_reissue_decision(self, decision_id, headers):
        return self._request("GET", f"/fraudops/reissue-decisions/{decision_id}", headers=headers)

    def decide_reissue_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/fraudops/reissue-decisions/{decision_id}/decide", payload, headers)

    # ---- travel notices ----
    def create_travel_notice(self, payload, headers):
        return self._request("POST", "/fraudops/travel-notices", payload, headers)

    def get_travel_notice(self, notice_id, headers):
        return self._request("GET", f"/fraudops/travel-notices/{notice_id}", headers=headers)

    def cancel_travel_notice(self, notice_id, headers):
        return self._request("POST", f"/fraudops/travel-notices/{notice_id}/cancel", headers=headers)

    # ---- chargeback cases ----
    def create_chargeback_case(self, payload, headers):
        return self._request("POST", "/fraudops/chargeback-cases", payload, headers)

    def list_chargeback_cases(self, headers, params=None):
        return self._request("GET", "/fraudops/chargeback-cases", headers=headers, params=params)

    def get_chargeback_case(self, case_id, headers):
        return self._request("GET", f"/fraudops/chargeback-cases/{case_id}", headers=headers)

    def post_provisional_credit(self, case_id, headers):
        return self._request("POST", f"/fraudops/chargeback-cases/{case_id}/post-provisional-credit", headers=headers)

    def file_representment(self, case_id, headers):
        return self._request("POST", f"/fraudops/chargeback-cases/{case_id}/representment", headers=headers)

    def resolve_chargeback_case(self, case_id, payload, headers):
        return self._request("POST", f"/fraudops/chargeback-cases/{case_id}/resolve", payload, headers)

    def withdraw_chargeback_case(self, case_id, headers):
        return self._request("POST", f"/fraudops/chargeback-cases/{case_id}/withdraw", headers=headers)

    # ---- loss entries ----
    def create_loss_entry(self, payload, headers):
        return self._request("POST", "/fraudops/loss-entries", payload, headers)

    def list_loss_entries(self, headers, params=None):
        return self._request("GET", "/fraudops/loss-entries", headers=headers, params=params)

    def get_loss_entry(self, loss_id, headers):
        return self._request("GET", f"/fraudops/loss-entries/{loss_id}", headers=headers)

    def book_loss_entry(self, loss_id, headers):
        return self._request("POST", f"/fraudops/loss-entries/{loss_id}/book", headers=headers)

    def finalize_loss_entry(self, loss_id, payload, headers):
        return self._request("POST", f"/fraudops/loss-entries/{loss_id}/finalize", payload, headers)

    def write_off_loss_entry(self, loss_id, headers):
        return self._request("POST", f"/fraudops/loss-entries/{loss_id}/write-off", headers=headers)

    # ---- recovery filings ----
    def create_recovery_filing(self, payload, headers):
        return self._request("POST", "/fraudops/recovery-filings", payload, headers)

    def list_recovery_filings(self, headers, params=None):
        return self._request("GET", "/fraudops/recovery-filings", headers=headers, params=params)

    def get_recovery_filing(self, filing_id, headers):
        return self._request("GET", f"/fraudops/recovery-filings/{filing_id}", headers=headers)

    def mark_filing_outcome(self, filing_id, payload, headers):
        return self._request("POST", f"/fraudops/recovery-filings/{filing_id}/mark-outcome", payload, headers)

    # ---- fraud rings / memberships ----
    def detect_fraud_ring(self, payload, headers):
        return self._request("POST", "/fraudops/fraud-rings/detect", payload, headers)

    def list_fraud_rings(self, headers, params=None):
        return self._request("GET", "/fraudops/fraud-rings", headers=headers, params=params)

    def get_fraud_ring(self, ring_id, headers):
        return self._request("GET", f"/fraudops/fraud-rings/{ring_id}", headers=headers)

    def confirm_fraud_ring(self, ring_id, headers):
        return self._request("POST", f"/fraudops/fraud-rings/{ring_id}/confirm", headers=headers)

    def dismiss_fraud_ring(self, ring_id, headers):
        return self._request("POST", f"/fraudops/fraud-rings/{ring_id}/dismiss", headers=headers)

    def list_ring_memberships(self, headers, params=None):
        return self._request("GET", "/fraudops/ring-memberships", headers=headers, params=params)

    def get_ring_membership(self, membership_id, headers):
        return self._request("GET", f"/fraudops/ring-memberships/{membership_id}", headers=headers)


api_client = ApiClient()
