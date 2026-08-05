"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Logical clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----- Jurisdiction -----
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # ----- Operator -----
    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", "/operators", headers=headers, params=params)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}", headers=headers)

    def activate_operator(self, operator_id, headers):
        return self._request("POST", f"/operators/{operator_id}/activate", {}, headers)

    def suspend_operator(self, operator_id, headers, payload=None):
        return self._request("POST", f"/operators/{operator_id}/suspend", payload or {}, headers)

    def reinstate_operator(self, operator_id, headers):
        return self._request("POST", f"/operators/{operator_id}/reinstate", {}, headers)

    def revoke_operator(self, operator_id, headers):
        return self._request("POST", f"/operators/{operator_id}/revoke", {}, headers)

    def close_operator(self, operator_id, headers):
        return self._request("POST", f"/operators/{operator_id}/close", {}, headers)

    def record_lien(self, operator_id, payload, headers):
        return self._request("POST", f"/operators/{operator_id}/liens", payload, headers)

    def list_operator_liens(self, operator_id, headers, params=None):
        return self._request("GET", f"/operators/{operator_id}/liens", headers=headers, params=params)

    def list_operator_properties(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}/properties", headers=headers)

    def list_operator_ota_agreements(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}/ota-agreements", headers=headers)

    def list_operator_returns(self, operator_id, headers, params=None):
        return self._request("GET", f"/operators/{operator_id}/returns", headers=headers, params=params)

    def list_operator_audits(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}/audits", headers=headers)

    def list_operator_refund_claims(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}/refund-claims", headers=headers)

    def list_operator_ledger_entries(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}/ledger-entries", headers=headers)

    # ----- Property -----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # ----- OTA platform & agreement -----
    def create_ota_platform(self, payload, headers):
        return self._request("POST", "/ota-platforms", payload, headers)

    def get_ota_platform(self, platform_id, headers):
        return self._request("GET", f"/ota-platforms/{platform_id}", headers=headers)

    def create_ota_agreement(self, payload, headers):
        return self._request("POST", "/ota-agreements", payload, headers)

    def list_ota_agreements(self, headers, params=None):
        return self._request("GET", "/ota-agreements", headers=headers, params=params)

    def get_ota_agreement(self, agreement_id, headers):
        return self._request("GET", f"/ota-agreements/{agreement_id}", headers=headers)

    def activate_ota_agreement(self, agreement_id, headers):
        return self._request("POST", f"/ota-agreements/{agreement_id}/activate", {}, headers)

    def terminate_ota_agreement(self, agreement_id, headers):
        return self._request("POST", f"/ota-agreements/{agreement_id}/terminate", {}, headers)

    # ----- Tax return -----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def file_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/file", {}, headers)

    def amend_return(self, return_id, headers, payload=None):
        return self._request("POST", f"/returns/{return_id}/amend", payload or {}, headers)

    def list_return_exemptions(self, return_id, headers, params=None):
        return self._request("GET", f"/returns/{return_id}/exemptions", headers=headers, params=params)

    def list_return_remittances(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}/remittances", headers=headers)

    # ----- Exemption claim -----
    def create_exemption(self, payload, headers):
        return self._request("POST", "/exemptions", payload, headers)

    def get_exemption(self, exemption_id, headers):
        return self._request("GET", f"/exemptions/{exemption_id}", headers=headers)

    def verify_exemption(self, exemption_id, headers):
        return self._request("POST", f"/exemptions/{exemption_id}/verify", {}, headers)

    def reject_exemption(self, exemption_id, headers):
        return self._request("POST", f"/exemptions/{exemption_id}/reject", {}, headers)

    # ----- Remittance -----
    def create_remittance(self, payload, headers):
        return self._request("POST", "/remittances", payload, headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/remittances", headers=headers, params=params)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/remittances/{remittance_id}", headers=headers)

    def clear_remittance(self, remittance_id, headers):
        return self._request("POST", f"/remittances/{remittance_id}/clear", {}, headers)

    def reverse_remittance(self, remittance_id, headers):
        return self._request("POST", f"/remittances/{remittance_id}/reverse", {}, headers)

    # ----- Audit & assessment -----
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def begin_fieldwork(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/begin-fieldwork", {}, headers)

    def propose_assessment(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/assessments", payload, headers)

    def list_audit_assessments(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}/assessments", headers=headers)

    def record_response(self, audit_id, headers, payload=None):
        return self._request("POST", f"/audits/{audit_id}/record-response", payload or {}, headers)

    def reopen_fieldwork(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/reopen-fieldwork", {}, headers)

    def close_no_change(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/close-no-change", {}, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def issue_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/issue", {}, headers)

    def submit_appeal(self, assessment_id, payload, headers):
        return self._request("POST", f"/assessments/{assessment_id}/appeals", payload, headers)

    def list_assessment_appeals(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}/appeals", headers=headers)

    # ----- Appeal -----
    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def begin_review(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/begin-review", {}, headers)

    def request_info(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/request-info", {}, headers)

    def provide_info(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/provide-info", {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ----- Refund claim -----
    def create_refund_claim(self, payload, headers):
        return self._request("POST", "/refund-claims", payload, headers)

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", "/refund-claims", headers=headers, params=params)

    def get_refund_claim(self, refund_id, headers):
        return self._request("GET", f"/refund-claims/{refund_id}", headers=headers)

    def approve_refund(self, refund_id, headers):
        return self._request("POST", f"/refund-claims/{refund_id}/approve", {}, headers)

    def deny_refund(self, refund_id, headers):
        return self._request("POST", f"/refund-claims/{refund_id}/deny", {}, headers)

    def pay_refund(self, refund_id, headers):
        return self._request("POST", f"/refund-claims/{refund_id}/pay", {}, headers)


api_client = ApiClient()
