"""API client: one method per endpoint defined in the PRD.

All paths are full paths from root (the API has no prefix).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Fee plans ---
    def create_fee_plan(self, payload, headers=None):
        return self._request("POST", "/fee-plans", payload, headers=headers)

    def get_fee_plan(self, fee_plan_id, headers):
        return self._request("GET", f"/fee-plans/{fee_plan_id}", headers=headers)

    def list_fee_plans(self, headers, params=None):
        return self._request("GET", "/fee-plans", headers=headers, params=params)

    # --- Merchant onboarding & underwriting ---
    def create_merchant(self, payload, headers=None):
        return self._request("POST", "/merchants", payload, headers=headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/merchants", headers=headers, params=params)

    def list_risk_reviews(self, merchant_id, headers, params=None):
        return self._request("GET", f"/merchants/{merchant_id}/risk-reviews", headers=headers, params=params)

    def approve_risk_review(self, merchant_id, review_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/risk-reviews/{review_id}/approve", payload, headers=headers)

    def reject_risk_review(self, merchant_id, review_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/risk-reviews/{review_id}/reject", payload, headers=headers)

    def suspend_merchant(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/suspend", payload, headers=headers)

    def reinstate_merchant(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/reinstate", payload, headers=headers)

    # --- Charges: authorization / capture / void ---
    def create_charge(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/charges", payload, headers=headers)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    def capture_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/capture", payload, headers=headers)

    def void_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/void", payload, headers=headers)

    # --- Refunds ---
    def create_refund(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/refunds", payload, headers=headers)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refunds(self, charge_id, headers, params=None):
        return self._request("GET", f"/charges/{charge_id}/refunds", headers=headers, params=params)

    def settle_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/refunds/{refund_id}/settle", payload, headers=headers)

    def fail_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/refunds/{refund_id}/fail", payload, headers=headers)

    # --- Disputes ---
    def create_dispute(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/disputes", payload, headers=headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, charge_id, headers, params=None):
        return self._request("GET", f"/charges/{charge_id}/disputes", headers=headers, params=params)

    def acknowledge_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/acknowledge", payload, headers=headers)

    def represent_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/represent", payload, headers=headers)

    def reopen_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/reopen", payload, headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers=headers)

    def accept_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/accept", payload, headers=headers)

    # --- Settlement batches ---
    def create_settlement_batch(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/settlement-batches", payload, headers=headers)

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"/settlement-batches/{batch_id}", headers=headers)

    def list_settlement_batches(self, merchant_id, headers, params=None):
        return self._request("GET", f"/merchants/{merchant_id}/settlement-batches", headers=headers, params=params)

    def settle_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/settlement-batches/{batch_id}/settle", payload, headers=headers)

    def fund_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/settlement-batches/{batch_id}/fund", payload, headers=headers)

    # --- Reserve entries ---
    def list_merchant_reserve_entries(self, merchant_id, headers, params=None):
        return self._request("GET", f"/merchants/{merchant_id}/reserve-entries", headers=headers, params=params)

    def list_batch_reserve_entries(self, batch_id, headers, params=None):
        return self._request("GET", f"/settlement-batches/{batch_id}/reserve-entries", headers=headers, params=params)

    def run_reserve_releases(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/reserve-releases", payload, headers=headers)

    # --- Payouts ---
    def create_payout(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/payouts", payload, headers=headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, merchant_id, headers, params=None):
        return self._request("GET", f"/merchants/{merchant_id}/payouts", headers=headers, params=params)

    def mark_payout_paid(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/mark-paid", payload, headers=headers)

    def return_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/return", payload, headers=headers)

    # --- Ledger ---
    def list_ledger_entries(self, merchant_id, headers, params=None):
        return self._request("GET", f"/merchants/{merchant_id}/ledger-entries", headers=headers, params=params)

    # --- 1099-K tax forms ---
    def generate_tax_1099k(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/tax-1099k", payload, headers=headers)

    def get_tax_1099k(self, form_id, headers):
        return self._request("GET", f"/tax-1099k/{form_id}", headers=headers)

    def list_tax_1099k(self, merchant_id, headers, params=None):
        return self._request("GET", f"/merchants/{merchant_id}/tax-1099k", headers=headers, params=params)

    # --- Webhook events ---
    def emit_webhook_event(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/webhook-events", payload, headers=headers)

    def list_webhook_events(self, merchant_id, headers, params=None):
        return self._request("GET", f"/merchants/{merchant_id}/webhook-events", headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers=headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers=headers)


api_client = ApiClient()
