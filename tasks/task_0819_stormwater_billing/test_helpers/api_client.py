"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    # ---- Parcels ----
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def get_fee_quote(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}/fee-quote", headers=headers)

    # ---- Impervious Measurements ----
    def create_measurement(self, payload, headers):
        return self._request("POST", "/impervious-measurements", payload, headers)

    def get_measurement(self, measurement_id, headers):
        return self._request("GET", f"/impervious-measurements/{measurement_id}", headers=headers)

    def list_measurements(self, headers, params=None):
        return self._request("GET", "/impervious-measurements", headers=headers, params=params)

    # ---- Exemptions ----
    def create_exemption(self, payload, headers):
        return self._request("POST", "/exemptions", payload, headers)

    def get_exemption(self, exemption_id, headers):
        return self._request("GET", f"/exemptions/{exemption_id}", headers=headers)

    def list_exemptions(self, headers, params=None):
        return self._request("GET", "/exemptions", headers=headers, params=params)

    def decide_exemption(self, exemption_id, payload, headers):
        return self._request("POST", f"/exemptions/{exemption_id}/decision", payload, headers)

    # ---- BMP Credits ----
    def create_bmp_credit(self, payload, headers):
        return self._request("POST", "/bmp-credits", payload, headers)

    def get_bmp_credit(self, credit_id, headers):
        return self._request("GET", f"/bmp-credits/{credit_id}", headers=headers)

    def list_bmp_credits(self, headers, params=None):
        return self._request("GET", "/bmp-credits", headers=headers, params=params)

    # ---- Credit Inspections ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/credit-inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/credit-inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/credit-inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/credit-inspections/{inspection_id}/complete", payload, headers)

    # ---- Bills ----
    def create_bill(self, payload, headers):
        return self._request("POST", "/bills", payload, headers)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def list_bills(self, headers, params=None):
        return self._request("GET", "/bills", headers=headers, params=params)

    def void_bill(self, bill_id, headers):
        return self._request("POST", f"/bills/{bill_id}/void", {}, headers)

    # ---- Appeals ----
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def review_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/review", {}, headers)

    def remeasure_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/remeasure", {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ---- Payments ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", {}, headers)

    # ---- Fund Ledger ----
    def get_fund_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/fund-ledger/{entry_id}", headers=headers)

    def list_fund_ledger(self, headers, params=None):
        return self._request("GET", "/fund-ledger", headers=headers, params=params)

    # ---- Periodic cycle ----
    def run_billing_cycle(self, headers):
        return self._request("POST", "/billing/run-cycle", {}, headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
