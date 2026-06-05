"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- TaxAccount ---
    def create_tax_account(self, payload, headers=None):
        return self._request("POST", "/collections/tax-accounts", payload, headers=headers)

    def get_tax_account(self, account_id, headers):
        return self._request("GET", f"/collections/tax-accounts/{account_id}", headers=headers)

    def list_tax_accounts(self, headers, params=None):
        return self._request("GET", "/collections/tax-accounts", headers=headers, params=params)

    def recompute_account(self, account_id, headers):
        return self._request("POST", f"/collections/tax-accounts/{account_id}/recompute", {}, headers=headers)

    def sweep_expired_csed(self, account_id, headers):
        return self._request("POST", f"/collections/tax-accounts/{account_id}/sweep-expired-csed", {}, headers=headers)

    # --- TaxPeriod ---
    def create_tax_period(self, payload, headers=None):
        return self._request("POST", "/collections/tax-periods", payload, headers=headers)

    def get_tax_period(self, period_id, headers):
        return self._request("GET", f"/collections/tax-periods/{period_id}", headers=headers)

    def list_tax_periods(self, headers, params=None):
        return self._request("GET", "/collections/tax-periods", headers=headers, params=params)

    # --- CsedSuspension ---
    def create_csed_suspension(self, payload, headers=None):
        return self._request("POST", "/collections/csed-suspensions", payload, headers=headers)

    def close_csed_suspension(self, suspension_id, payload, headers):
        return self._request("POST", f"/collections/csed-suspensions/{suspension_id}/close", payload, headers=headers)

    def get_csed_suspension(self, suspension_id, headers):
        return self._request("GET", f"/collections/csed-suspensions/{suspension_id}", headers=headers)

    def list_csed_suspensions(self, headers, params=None):
        return self._request("GET", "/collections/csed-suspensions", headers=headers, params=params)

    # --- InstallmentAgreement ---
    def create_agreement(self, payload, headers=None):
        return self._request("POST", "/collections/installment-agreements", payload, headers=headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/collections/installment-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/collections/installment-agreements", headers=headers, params=params)

    def approve_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/collections/installment-agreements/{agreement_id}/approve", payload, headers=headers)

    def reject_agreement(self, agreement_id, headers):
        return self._request("POST", f"/collections/installment-agreements/{agreement_id}/reject", {}, headers=headers)

    def record_missed_debit(self, agreement_id, headers):
        return self._request("POST", f"/collections/installment-agreements/{agreement_id}/record-missed-debit", {}, headers=headers)

    # --- Payment ---
    def create_payment(self, payload, headers=None):
        return self._request("POST", "/collections/payments", payload, headers=headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/collections/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/collections/payments", headers=headers, params=params)

    # --- OfferInCompromise ---
    def create_offer(self, payload, headers=None):
        return self._request("POST", "/collections/offers", payload, headers=headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/collections/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/collections/offers", headers=headers, params=params)

    def begin_evaluation(self, offer_id, headers):
        return self._request("POST", f"/collections/offers/{offer_id}/begin-evaluation", {}, headers=headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/collections/offers/{offer_id}/accept", payload, headers=headers)

    def reject_offer(self, offer_id, headers):
        return self._request("POST", f"/collections/offers/{offer_id}/reject", {}, headers=headers)

    # --- FederalTaxLien ---
    def create_lien(self, payload, headers=None):
        return self._request("POST", "/collections/liens", payload, headers=headers)

    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/collections/liens/{lien_id}", headers=headers)

    def list_liens(self, headers, params=None):
        return self._request("GET", "/collections/liens", headers=headers, params=params)

    def request_lien_release(self, lien_id, headers):
        return self._request("POST", f"/collections/liens/{lien_id}/request-release", {}, headers=headers)

    def approve_lien_release(self, lien_id, headers):
        return self._request("POST", f"/collections/liens/{lien_id}/approve-release", {}, headers=headers)

    def withdraw_lien(self, lien_id, headers):
        return self._request("POST", f"/collections/liens/{lien_id}/withdraw", {}, headers=headers)

    # --- CncDetermination ---
    def create_cnc(self, payload, headers=None):
        return self._request("POST", "/collections/cnc-determinations", payload, headers=headers)

    def get_cnc(self, cnc_id, headers):
        return self._request("GET", f"/collections/cnc-determinations/{cnc_id}", headers=headers)

    def list_cnc(self, headers, params=None):
        return self._request("GET", "/collections/cnc-determinations", headers=headers, params=params)

    def revoke_cnc(self, cnc_id, headers):
        return self._request("POST", f"/collections/cnc-determinations/{cnc_id}/revoke", {}, headers=headers)

    # --- AccountEvent ---
    def create_account_event(self, payload, headers=None):
        return self._request("POST", "/collections/account-events", payload, headers=headers)

    def get_account_event(self, event_id, headers):
        return self._request("GET", f"/collections/account-events/{event_id}", headers=headers)

    def list_account_events(self, headers, params=None):
        return self._request("GET", "/collections/account-events", headers=headers, params=params)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
