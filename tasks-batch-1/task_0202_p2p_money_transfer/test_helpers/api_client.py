"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Accounts ─────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def list_account_ledger(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/ledger", headers=headers, params=params)

    def list_account_funding_sources(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/funding-sources", headers=headers, params=params)

    def list_account_recipient_verifications(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/recipient-verifications", headers=headers, params=params)

    def list_account_split_participations(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/split-participations", headers=headers, params=params)

    def freeze_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/freeze", {}, headers)

    # ─── Funding sources ──────────────────────────────────────────────────
    def create_funding_source(self, payload, headers):
        return self._request("POST", "/funding-sources", payload, headers)

    def get_funding_source(self, funding_source_id, headers):
        return self._request("GET", f"/funding-sources/{funding_source_id}", headers=headers)

    def verify_funding_source(self, funding_source_id, payload, headers):
        return self._request("POST", f"/funding-sources/{funding_source_id}/verify", payload, headers)

    def delete_funding_source(self, funding_source_id, headers):
        return self._request("DELETE", f"/funding-sources/{funding_source_id}", headers=headers)

    # ─── Recipient verifications ──────────────────────────────────────────
    def create_recipient_verification(self, payload, headers):
        return self._request("POST", "/recipient-verifications", payload, headers)

    def confirm_recipient_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/recipient-verifications/{verification_id}/confirm", payload, headers)

    # ─── Transfers ────────────────────────────────────────────────────────
    def create_transfer(self, payload, headers):
        return self._request("POST", "/transfers", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/transfers", headers=headers, params=params)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/cancel", {}, headers)

    # ─── Money requests ───────────────────────────────────────────────────
    def create_money_request(self, payload, headers):
        return self._request("POST", "/money-requests", payload, headers)

    def get_money_request(self, money_request_id, headers):
        return self._request("GET", f"/money-requests/{money_request_id}", headers=headers)

    def list_money_requests(self, headers, params=None):
        return self._request("GET", "/money-requests", headers=headers, params=params)

    def pay_money_request(self, money_request_id, payload, headers):
        return self._request("POST", f"/money-requests/{money_request_id}/pay", payload, headers)

    def decline_money_request(self, money_request_id, headers):
        return self._request("POST", f"/money-requests/{money_request_id}/decline", {}, headers)

    def cancel_money_request(self, money_request_id, headers):
        return self._request("POST", f"/money-requests/{money_request_id}/cancel", {}, headers)

    # ─── Split requests ───────────────────────────────────────────────────
    def create_split_request(self, payload, headers):
        return self._request("POST", "/split-requests", payload, headers)

    def get_split_request(self, split_request_id, headers):
        return self._request("GET", f"/split-requests/{split_request_id}", headers=headers)

    def list_split_requests(self, headers, params=None):
        return self._request("GET", "/split-requests", headers=headers, params=params)

    def list_split_participants(self, split_request_id, headers, params=None):
        return self._request("GET", f"/split-requests/{split_request_id}/participants", headers=headers, params=params)

    def pay_split_participant(self, split_request_id, participant_id, payload, headers):
        return self._request("POST", f"/split-requests/{split_request_id}/participants/{participant_id}/pay", payload, headers)

    def forgive_split_participant(self, split_request_id, participant_id, headers):
        return self._request("POST", f"/split-requests/{split_request_id}/participants/{participant_id}/forgive", {}, headers)

    def cancel_split_request(self, split_request_id, headers):
        return self._request("POST", f"/split-requests/{split_request_id}/cancel", {}, headers)

    # ─── Risk holds ───────────────────────────────────────────────────────
    def get_risk_hold(self, risk_hold_id, headers):
        return self._request("GET", f"/risk-holds/{risk_hold_id}", headers=headers)

    def list_risk_holds(self, headers, params=None):
        return self._request("GET", "/risk-holds", headers=headers, params=params)

    def clear_risk_hold(self, risk_hold_id, headers):
        return self._request("POST", f"/risk-holds/{risk_hold_id}/clear", {}, headers)

    def block_risk_hold(self, risk_hold_id, headers):
        return self._request("POST", f"/risk-holds/{risk_hold_id}/block", {}, headers)

    # ─── Disputes ─────────────────────────────────────────────────────────
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def request_info_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/request-info", {}, headers)

    def provide_info_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/provide-info", {}, headers)

    def uphold_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/uphold", {}, headers)

    def deny_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/deny", {}, headers)

    # ─── Reversals (read) ─────────────────────────────────────────────────
    def get_reversal(self, reversal_id, headers):
        return self._request("GET", f"/reversals/{reversal_id}", headers=headers)

    def list_reversals(self, headers, params=None):
        return self._request("GET", "/reversals", headers=headers, params=params)

    # ─── Withdrawals ──────────────────────────────────────────────────────
    def create_withdrawal(self, payload, headers):
        return self._request("POST", "/withdrawals", payload, headers)

    def get_withdrawal(self, withdrawal_id, headers):
        return self._request("GET", f"/withdrawals/{withdrawal_id}", headers=headers)

    def list_withdrawals(self, headers, params=None):
        return self._request("GET", "/withdrawals", headers=headers, params=params)

    def settle_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/withdrawals/{withdrawal_id}/settle", {}, headers)

    def cancel_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/withdrawals/{withdrawal_id}/cancel", {}, headers)

    def fail_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/withdrawals/{withdrawal_id}/fail", {}, headers)

    # ─── Test-driving (clock + ledger seed) ───────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def seed_credit(self, payload, headers):
        return self._request("POST", "/_ledger/seed_credit", payload, headers)


api_client = ApiClient()
