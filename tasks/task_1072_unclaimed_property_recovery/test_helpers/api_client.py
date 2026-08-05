"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Holder ----
    def create_holder(self, payload, headers):
        return self._request("POST", "/holders", payload, headers)

    def get_holder(self, holder_id, headers):
        return self._request("GET", f"/holders/{holder_id}", headers=headers)

    # ---- PropertyType ----
    def create_property_type(self, payload, headers):
        return self._request("POST", "/property-types", payload, headers)

    def get_property_type(self, pt_id, headers):
        return self._request("GET", f"/property-types/{pt_id}", headers=headers)

    # ---- StateAccount ----
    def create_state_account(self, payload, headers):
        return self._request("POST", "/state-accounts", payload, headers)

    def get_state_account(self, account_id, headers):
        return self._request("GET", f"/state-accounts/{account_id}", headers=headers)

    # ---- Owner ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ---- RecoveryFirm ----
    def create_recovery_firm(self, payload, headers):
        return self._request("POST", "/recovery-firms", payload, headers)

    def get_recovery_firm(self, firm_id, headers):
        return self._request("GET", f"/recovery-firms/{firm_id}", headers=headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def evaluate_dormancy(self, property_id, headers):
        return self._request("POST", f"/properties/{property_id}/evaluate-dormancy", {}, headers)

    def create_notice(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/notices", payload, headers)

    def list_notices(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/notices", headers=headers, params=params)

    def record_response(self, notice_id, headers):
        return self._request("POST", f"/due-diligence-notices/{notice_id}/record-response", {}, headers)

    # ---- HolderReport ----
    def create_report(self, payload, headers):
        return self._request("POST", "/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def add_property(self, report_id, payload, headers):
        return self._request("POST", f"/reports/{report_id}/add-property", payload, headers)

    def submit_report(self, report_id, payload, headers):
        return self._request("POST", f"/reports/{report_id}/submit", payload, headers)

    def begin_review(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/begin-review", {}, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/accept", {}, headers)

    def reject_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/reject", {}, headers)

    def revise_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/revise", {}, headers)

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def examine_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/examine", {}, headers)

    def request_evidence(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/request-evidence", {}, headers)

    def upload_evidence(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/evidence", payload, headers)

    def list_evidence(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/evidence", headers=headers, params=params)

    def review_evidence(self, claim_id, doc_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/evidence/{doc_id}/review", payload, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/pay", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/void", {}, headers)

    # ---- AuditCase ----
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/audit-cases", payload, headers)

    def get_audit_case(self, case_id, headers):
        return self._request("GET", f"/audit-cases/{case_id}", headers=headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", "/audit-cases", headers=headers, params=params)

    def request_info(self, case_id, headers):
        return self._request("POST", f"/audit-cases/{case_id}/request-info", {}, headers)

    def provide_info(self, case_id, headers):
        return self._request("POST", f"/audit-cases/{case_id}/provide-info", {}, headers)

    def close_clean(self, case_id, headers):
        return self._request("POST", f"/audit-cases/{case_id}/close-clean", {}, headers)

    def close_assess(self, case_id, payload, headers):
        return self._request("POST", f"/audit-cases/{case_id}/close-assess", payload, headers)

    # ---- LedgerEntry ----
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)


api_client = ApiClient()
