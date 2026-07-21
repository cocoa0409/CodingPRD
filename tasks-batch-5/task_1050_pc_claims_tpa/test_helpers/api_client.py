"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- ClientAccount ----
    def create_client_account(self, payload, headers):
        return self._request("POST", "/client-accounts", payload, headers)

    def get_client_account(self, account_id, headers):
        return self._request("GET", f"/client-accounts/{account_id}", headers=headers)

    def list_client_accounts(self, headers, params=None):
        return self._request("GET", "/client-accounts", headers=headers, params=params)

    # ---- Policy ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    # ---- Adjuster ----
    def create_adjuster(self, payload, headers):
        return self._request("POST", "/adjusters", payload, headers)

    def get_adjuster(self, adjuster_id, headers):
        return self._request("GET", f"/adjusters/{adjuster_id}", headers=headers)

    def list_adjusters(self, headers, params=None):
        return self._request("GET", "/adjusters", headers=headers, params=params)

    # ---- Vendor ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def transition_claim(self, claim_id, to_status, headers, **extra):
        body = {"to_status": to_status}
        body.update(extra)
        return self._request("POST", f"/claims/{claim_id}/transition", body, headers)

    def get_claim_financials(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}/financials", headers=headers)

    # ---- Assignment ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def transition_assignment(self, assignment_id, to_status, headers, **extra):
        body = {"to_status": to_status}
        body.update(extra)
        return self._request("POST", f"/assignments/{assignment_id}/transition", body, headers)

    # ---- ReserveChange ----
    def create_reserve_change(self, payload, headers):
        return self._request("POST", "/reserve-changes", payload, headers)

    def get_reserve_change(self, reserve_change_id, headers):
        return self._request("GET", f"/reserve-changes/{reserve_change_id}", headers=headers)

    def list_reserve_changes(self, headers, params=None):
        return self._request("GET", "/reserve-changes", headers=headers, params=params)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def transition_payment(self, payment_id, to_status, headers, **extra):
        body = {"to_status": to_status}
        body.update(extra)
        return self._request("POST", f"/payments/{payment_id}/transition", body, headers)

    # ---- VendorInvoice ----
    def create_vendor_invoice(self, payload, headers):
        return self._request("POST", "/vendor-invoices", payload, headers)

    def get_vendor_invoice(self, invoice_id, headers):
        return self._request("GET", f"/vendor-invoices/{invoice_id}", headers=headers)

    def list_vendor_invoices(self, headers, params=None):
        return self._request("GET", "/vendor-invoices", headers=headers, params=params)

    def transition_vendor_invoice(self, invoice_id, to_status, headers, **extra):
        body = {"to_status": to_status}
        body.update(extra)
        return self._request("POST", f"/vendor-invoices/{invoice_id}/transition", body, headers)

    # ---- LitigationCase ----
    def create_litigation_case(self, payload, headers):
        return self._request("POST", "/litigation-cases", payload, headers)

    def get_litigation_case(self, case_id, headers):
        return self._request("GET", f"/litigation-cases/{case_id}", headers=headers)

    def list_litigation_cases(self, headers, params=None):
        return self._request("GET", "/litigation-cases", headers=headers, params=params)

    def transition_litigation_case(self, case_id, to_status, headers, **extra):
        body = {"to_status": to_status}
        body.update(extra)
        return self._request("POST", f"/litigation-cases/{case_id}/transition", body, headers)

    # ---- SubrogationCase ----
    def create_subrogation_case(self, payload, headers):
        return self._request("POST", "/subrogation-cases", payload, headers)

    def get_subrogation_case(self, case_id, headers):
        return self._request("GET", f"/subrogation-cases/{case_id}", headers=headers)

    def list_subrogation_cases(self, headers, params=None):
        return self._request("GET", "/subrogation-cases", headers=headers, params=params)

    def transition_subrogation_case(self, case_id, to_status, headers, **extra):
        body = {"to_status": to_status}
        body.update(extra)
        return self._request("POST", f"/subrogation-cases/{case_id}/transition", body, headers)

    # ---- SiuReferral ----
    def create_siu_referral(self, payload, headers):
        return self._request("POST", "/siu-referrals", payload, headers)

    def get_siu_referral(self, referral_id, headers):
        return self._request("GET", f"/siu-referrals/{referral_id}", headers=headers)

    def list_siu_referrals(self, headers, params=None):
        return self._request("GET", "/siu-referrals", headers=headers, params=params)

    def transition_siu_referral(self, referral_id, to_status, headers, **extra):
        body = {"to_status": to_status}
        body.update(extra)
        return self._request("POST", f"/siu-referrals/{referral_id}/transition", body, headers)

    # ---- BordereauReport ----
    def create_bordereau_report(self, payload, headers):
        return self._request("POST", "/bordereau-reports", payload, headers)

    def get_bordereau_report(self, report_id, headers):
        return self._request("GET", f"/bordereau-reports/{report_id}", headers=headers)

    def list_bordereau_reports(self, headers, params=None):
        return self._request("GET", "/bordereau-reports", headers=headers, params=params)


api_client = ApiClient()
