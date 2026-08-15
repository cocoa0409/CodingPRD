"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (BankAdmin) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Card accounts ---
    def create_card_account(self, payload, headers):
        return self._request("POST", "/card-accounts", payload, headers)

    def get_card_account(self, account_id, headers):
        return self._request("GET", f"/card-accounts/{account_id}", headers=headers)

    def list_account_transactions(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/card-accounts/{account_id}/transactions",
            headers=headers, params=params,
        )

    # --- Card transactions ---
    def create_card_transaction(self, payload, headers):
        return self._request("POST", "/card-transactions", payload, headers)

    # --- Dispute cases ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def classify_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/classify", payload, headers)

    def reclassify_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/reclassify", payload, headers)

    def grant_provisional_credit(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/grant-provisional-credit", {}, headers,
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", {}, headers)

    # --- Chargebacks ---
    def create_chargeback(self, payload, headers):
        return self._request("POST", "/chargebacks", payload, headers)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/chargebacks/{chargeback_id}", headers=headers)

    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/chargebacks", headers=headers, params=params)

    def list_case_chargebacks(self, dispute_id, headers, params=None):
        return self._request(
            "GET", f"/disputes/{dispute_id}/chargebacks", headers=headers, params=params,
        )

    def create_representment(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/chargebacks/{chargeback_id}/representments", payload, headers,
        )

    def list_representments(self, chargeback_id, headers, params=None):
        return self._request(
            "GET", f"/chargebacks/{chargeback_id}/representments",
            headers=headers, params=params,
        )

    def review_representment(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/chargebacks/{chargeback_id}/review-representment",
            payload, headers,
        )

    def escalate_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/chargebacks/{chargeback_id}/escalate", payload, headers,
        )

    def withdraw_chargeback(self, chargeback_id, headers):
        return self._request(
            "POST", f"/chargebacks/{chargeback_id}/withdraw", {}, headers,
        )

    # --- Provisional credits ---
    def reverse_provisional_credit(self, credit_id, headers):
        return self._request(
            "POST", f"/provisional-credits/{credit_id}/reverse", {}, headers,
        )

    def reinstate_provisional_credit(self, credit_id, headers):
        return self._request(
            "POST", f"/provisional-credits/{credit_id}/reinstate", {}, headers,
        )

    def list_case_provisional_credits(self, dispute_id, headers, params=None):
        return self._request(
            "GET", f"/disputes/{dispute_id}/provisional-credits",
            headers=headers, params=params,
        )

    # --- Notifications ---
    def list_case_notifications(self, dispute_id, headers, params=None):
        return self._request(
            "GET", f"/disputes/{dispute_id}/notifications",
            headers=headers, params=params,
        )

    # --- Loss recovery ledger ---
    def create_loss_recovery(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/loss-recoveries", payload, headers,
        )

    def list_loss_recoveries(self, dispute_id, headers, params=None):
        return self._request(
            "GET", f"/disputes/{dispute_id}/loss-recoveries",
            headers=headers, params=params,
        )


api_client = ApiClient()
