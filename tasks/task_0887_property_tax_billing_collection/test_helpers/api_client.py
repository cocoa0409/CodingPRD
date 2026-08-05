"""API client: one method per endpoint defined in the PRD (Section 4).

All paths carry the /property-tax prefix. GET query filters are passed via the
`params` argument (the framework routes GET payload to query params).
"""
from prd_bench_local_runner.testing import GenericApiClient

P = "/property-tax"


class ApiClient(GenericApiClient):
    # ----- Logical clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc", payload, headers)

    # ----- TaxYear -----
    def create_tax_year(self, payload, headers):
        return self._request("POST", f"{P}/tax-years", payload, headers)

    def get_tax_year(self, tax_year_id, headers):
        return self._request("GET", f"{P}/tax-years/{tax_year_id}", headers=headers)

    # ----- EscrowAgent -----
    def create_escrow_agent(self, payload, headers):
        return self._request("POST", f"{P}/escrow-agents", payload, headers)

    # ----- Parcel -----
    def create_parcel(self, payload, headers):
        return self._request("POST", f"{P}/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"{P}/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", f"{P}/parcels", headers=headers, params=params)

    # ----- TaxBill -----
    def create_tax_bill(self, payload, headers):
        return self._request("POST", f"{P}/tax-bills", payload, headers)

    def get_tax_bill(self, bill_id, headers):
        return self._request("GET", f"{P}/tax-bills/{bill_id}", headers=headers)

    def list_tax_bills(self, headers, params=None):
        return self._request("GET", f"{P}/tax-bills", headers=headers, params=params)

    def get_payoff(self, bill_id, headers, params=None):
        return self._request("GET", f"{P}/tax-bills/{bill_id}/payoff", headers=headers, params=params)

    def list_ledger_entries(self, bill_id, headers, params=None):
        return self._request("GET", f"{P}/tax-bills/{bill_id}/ledger-entries", headers=headers, params=params)

    # ----- Installment -----
    def get_installment(self, installment_id, headers):
        return self._request("GET", f"{P}/installments/{installment_id}", headers=headers)

    def list_installments(self, headers, params=None):
        return self._request("GET", f"{P}/installments", headers=headers, params=params)

    # ----- TaxReliefApplication -----
    def create_relief_application(self, payload, headers):
        return self._request("POST", f"{P}/relief-applications", payload, headers)

    def get_relief_application(self, app_id, headers):
        return self._request("GET", f"{P}/relief-applications/{app_id}", headers=headers)

    def list_relief_applications(self, headers, params=None):
        return self._request("GET", f"{P}/relief-applications", headers=headers, params=params)

    def review_relief(self, app_id, headers):
        return self._request("POST", f"{P}/relief-applications/{app_id}/review", {}, headers)

    def request_info_relief(self, app_id, headers):
        return self._request("POST", f"{P}/relief-applications/{app_id}/request-info", {}, headers)

    def resubmit_relief(self, app_id, headers):
        return self._request("POST", f"{P}/relief-applications/{app_id}/resubmit", {}, headers)

    def decide_relief(self, app_id, payload, headers):
        return self._request("POST", f"{P}/relief-applications/{app_id}/decide", payload, headers)

    # ----- Payment -----
    def create_payment(self, payload, headers):
        return self._request("POST", f"{P}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{P}/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", f"{P}/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"{P}/payments/{payment_id}/reverse", {}, headers)

    # ----- Refund -----
    def create_refund(self, payload, headers):
        return self._request("POST", f"{P}/refunds", payload, headers)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"{P}/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", f"{P}/refunds", headers=headers, params=params)

    def decide_refund(self, refund_id, payload, headers):
        return self._request("POST", f"{P}/refunds/{refund_id}/decide", payload, headers)

    # ----- TaxSaleReferral -----
    def create_referral(self, payload, headers):
        return self._request("POST", f"{P}/tax-sale-referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{P}/tax-sale-referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{P}/tax-sale-referrals", headers=headers, params=params)

    def redeem_referral(self, referral_id, headers):
        return self._request("POST", f"{P}/tax-sale-referrals/{referral_id}/redeem", {}, headers)

    def sell_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{P}/tax-sale-referrals/{referral_id}/sell", payload or {}, headers)


api_client = ApiClient()
