"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Lender ----
    def create_lender(self, payload, headers):
        return self._request("POST", "/lenders", payload, headers)

    def get_lender(self, lender_id, headers):
        return self._request("GET", f"/lenders/{lender_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/loans/_clock/set", payload, headers)

    # ---- PrincipalLimitFactor ----
    def create_plf(self, payload, headers):
        return self._request("POST", "/principal-limit-factors", payload, headers)

    def get_plf(self, plf_id, headers):
        return self._request("GET", f"/principal-limit-factors/{plf_id}", headers=headers)

    def list_plfs(self, headers, params=None):
        return self._request("GET", "/principal-limit-factors", headers=headers, params=params)

    # ---- Borrower ----
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def list_borrowers(self, headers, params=None):
        return self._request("GET", "/borrowers", headers=headers, params=params)

    # ---- Loan ----
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def originate_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/originate", {}, headers)

    def post_accrual(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/post-accrual", payload, headers)

    def payoff_quote(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/payoff-quote", headers=headers, params=params)

    def recompute_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/recompute", {}, headers)

    # ---- Disbursement ----
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    def approve_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/approve", payload, headers)

    def disburse_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/disburse", {}, headers)

    def reject_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/reject", {}, headers)

    def void_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/void", {}, headers)

    # ---- LesaSetAside ----
    def create_lesa(self, payload, headers):
        return self._request("POST", "/lesa-set-asides", payload, headers)

    def get_lesa(self, lesa_id, headers):
        return self._request("GET", f"/lesa-set-asides/{lesa_id}", headers=headers)

    def list_lesas(self, headers, params=None):
        return self._request("GET", "/lesa-set-asides", headers=headers, params=params)

    # ---- PropertyChargePayment ----
    def create_property_charge_payment(self, payload, headers):
        return self._request("POST", "/property-charge-payments", payload, headers)

    def get_property_charge_payment(self, payment_id, headers):
        return self._request("GET", f"/property-charge-payments/{payment_id}", headers=headers)

    def list_property_charge_payments(self, headers, params=None):
        return self._request("GET", "/property-charge-payments", headers=headers, params=params)

    def reverse_property_charge_payment(self, payment_id, headers):
        return self._request("POST", f"/property-charge-payments/{payment_id}/reverse", {}, headers)

    # ---- OccupancyCertification ----
    def create_occupancy_certification(self, payload, headers):
        return self._request("POST", "/occupancy-certifications", payload, headers)

    def get_occupancy_certification(self, cert_id, headers):
        return self._request("GET", f"/occupancy-certifications/{cert_id}", headers=headers)

    def list_occupancy_certifications(self, headers, params=None):
        return self._request("GET", "/occupancy-certifications", headers=headers, params=params)

    def certify_occupancy(self, cert_id, headers):
        return self._request("POST", f"/occupancy-certifications/{cert_id}/certify", {}, headers)

    def mark_delinquent_occupancy(self, cert_id, headers):
        return self._request("POST", f"/occupancy-certifications/{cert_id}/mark-delinquent", {}, headers)

    # ---- MaturityEvent ----
    def create_maturity_event(self, payload, headers):
        return self._request("POST", "/maturity-events", payload, headers)

    def get_maturity_event(self, event_id, headers):
        return self._request("GET", f"/maturity-events/{event_id}", headers=headers)

    def list_maturity_events(self, headers, params=None):
        return self._request("GET", "/maturity-events", headers=headers, params=params)

    def acknowledge_maturity_event(self, event_id, headers):
        return self._request("POST", f"/maturity-events/{event_id}/acknowledge", {}, headers)

    # ---- NonBorrowingSpouseDeferral ----
    def create_nbs_deferral(self, payload, headers):
        return self._request("POST", "/nbs-deferrals", payload, headers)

    def get_nbs_deferral(self, deferral_id, headers):
        return self._request("GET", f"/nbs-deferrals/{deferral_id}", headers=headers)

    def list_nbs_deferrals(self, headers, params=None):
        return self._request("GET", "/nbs-deferrals", headers=headers, params=params)

    def terminate_nbs_deferral(self, deferral_id, headers):
        return self._request("POST", f"/nbs-deferrals/{deferral_id}/terminate", {}, headers)

    # ---- Resolution ----
    def create_resolution(self, payload, headers):
        return self._request("POST", "/resolutions", payload, headers)

    def get_resolution(self, resolution_id, headers):
        return self._request("GET", f"/resolutions/{resolution_id}", headers=headers)

    def list_resolutions(self, headers, params=None):
        return self._request("GET", "/resolutions", headers=headers, params=params)

    def settle_resolution(self, resolution_id, headers):
        return self._request("POST", f"/resolutions/{resolution_id}/settle", {}, headers)

    def cancel_resolution(self, resolution_id, headers):
        return self._request("POST", f"/resolutions/{resolution_id}/cancel", {}, headers)

    # ---- LedgerEntry ----
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/ledger-entries/{ledger_entry_id}", headers=headers)


api_client = ApiClient()
