"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------------- #
    # Programs
    # ----------------------------------------------------------------- #
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/api/programs", headers=headers, params=params)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/activate", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/close", {}, headers)

    def create_budget_adjustment(self, program_id, payload, headers):
        return self._request(
            "POST", f"/api/programs/{program_id}/budget-adjustments", payload, headers
        )

    def get_program_report(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}/report", headers=headers)

    def run_escheat_sweep(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/escheat-sweep", {}, headers)

    # ----------------------------------------------------------------- #
    # Offers
    # ----------------------------------------------------------------- #
    def create_offer(self, payload, headers):
        return self._request("POST", "/api/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/api/offers", headers=headers, params=params)

    def publish_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/publish", {}, headers)

    def suspend_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/suspend", {}, headers)

    def close_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/close", {}, headers)

    # ----------------------------------------------------------------- #
    # Claimants
    # ----------------------------------------------------------------- #
    def create_claimant(self, payload, headers):
        return self._request("POST", "/api/claimants", payload, headers)

    def get_claimant(self, claimant_id, headers):
        return self._request("GET", f"/api/claimants/{claimant_id}", headers=headers)

    def list_claimants(self, headers, params=None):
        return self._request("GET", "/api/claimants", headers=headers, params=params)

    def reinstate_claimant(self, claimant_id, payload, headers):
        return self._request("POST", f"/api/claimants/{claimant_id}/reinstate", payload, headers)

    # ----------------------------------------------------------------- #
    # Claims and receipts
    # ----------------------------------------------------------------- #
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def create_receipt(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/receipts", payload, headers)

    def list_claim_receipts(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/api/claims/{claim_id}/receipts", headers=headers, params=params
        )

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/api/receipts/{receipt_id}", headers=headers)

    def validate_receipt(self, receipt_id, headers):
        return self._request("POST", f"/api/receipts/{receipt_id}/validate", {}, headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/submit", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/withdraw", {}, headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/deny", payload, headers)

    def appeal_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/appeal", payload, headers)

    # ----------------------------------------------------------------- #
    # Payouts
    # ----------------------------------------------------------------- #
    def create_payout(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/api/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/api/payouts", headers=headers, params=params)

    def release_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"/api/payouts/{payout_id}/release", payload or {}, headers)

    def clear_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/clear", {}, headers)

    def void_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/void", payload, headers)

    def reissue_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/reissue", {}, headers)

    # ----------------------------------------------------------------- #
    # Virtual cards
    # ----------------------------------------------------------------- #
    def get_virtual_card(self, card_id, headers):
        return self._request("GET", f"/api/virtual-cards/{card_id}", headers=headers)

    def list_virtual_cards(self, headers, params=None):
        return self._request("GET", "/api/virtual-cards", headers=headers, params=params)

    def activate_virtual_card(self, card_id, headers):
        return self._request("POST", f"/api/virtual-cards/{card_id}/activate", {}, headers)

    def spend_virtual_card(self, card_id, payload, headers):
        return self._request("POST", f"/api/virtual-cards/{card_id}/spend", payload, headers)

    # ----------------------------------------------------------------- #
    # Escheat records
    # ----------------------------------------------------------------- #
    def get_escheat_record(self, record_id, headers):
        return self._request("GET", f"/api/escheat-records/{record_id}", headers=headers)

    def list_escheat_records(self, headers, params=None):
        return self._request("GET", "/api/escheat-records", headers=headers, params=params)

    # ----------------------------------------------------------------- #
    # Budget entries (ledger)
    # ----------------------------------------------------------------- #
    def get_budget_entry(self, entry_id, headers):
        return self._request("GET", f"/api/budget-entries/{entry_id}", headers=headers)

    def list_budget_entries(self, headers, params=None):
        return self._request("GET", "/api/budget-entries", headers=headers, params=params)

    # ----------------------------------------------------------------- #
    # Fraud cases
    # ----------------------------------------------------------------- #
    def create_fraud_case(self, payload, headers):
        return self._request("POST", "/api/fraud-cases", payload, headers)

    def get_fraud_case(self, case_id, headers):
        return self._request("GET", f"/api/fraud-cases/{case_id}", headers=headers)

    def list_fraud_cases(self, headers, params=None):
        return self._request("GET", "/api/fraud-cases", headers=headers, params=params)

    def transition_fraud_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/fraud-cases/{case_id}/transition", payload, headers)

    # ----------------------------------------------------------------- #
    # Logical clock (administrative test-driving capability)
    # ----------------------------------------------------------------- #
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
