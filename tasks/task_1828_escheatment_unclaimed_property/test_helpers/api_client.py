"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Owners ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/escheatment/owners", payload, headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/escheatment/owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/escheatment/owners/{owner_id}", headers=headers)

    def list_owner_properties(self, owner_id, headers, params=None):
        return self._request("GET", f"/escheatment/owners/{owner_id}/properties", headers=headers, params=params)

    def list_owner_claims(self, owner_id, headers, params=None):
        return self._request("GET", f"/escheatment/owners/{owner_id}/owner-claims", headers=headers, params=params)

    # --- Dormancy rules ---
    def create_dormancy_rule(self, payload, headers):
        return self._request("POST", "/escheatment/dormancy-rules", payload, headers)

    def list_dormancy_rules(self, headers, params=None):
        return self._request("GET", "/escheatment/dormancy-rules", headers=headers, params=params)

    def get_dormancy_rule(self, rule_id, headers):
        return self._request("GET", f"/escheatment/dormancy-rules/{rule_id}", headers=headers)

    def update_dormancy_rule(self, rule_id, payload, headers):
        return self._request("PUT", f"/escheatment/dormancy-rules/{rule_id}", payload, headers)

    # --- Properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/escheatment/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/escheatment/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/escheatment/properties/{property_id}", headers=headers)

    def reactivate_property(self, property_id, payload, headers):
        return self._request("POST", f"/escheatment/properties/{property_id}/reactivate", payload, headers)

    def create_contact_event(self, property_id, payload, headers):
        return self._request("POST", f"/escheatment/properties/{property_id}/contact-events", payload, headers)

    def list_contact_events(self, property_id, headers, params=None):
        return self._request("GET", f"/escheatment/properties/{property_id}/contact-events", headers=headers, params=params)

    def list_property_line_items(self, property_id, headers, params=None):
        return self._request("GET", f"/escheatment/properties/{property_id}/report-line-items", headers=headers, params=params)

    def list_property_claims(self, property_id, headers, params=None):
        return self._request("GET", f"/escheatment/properties/{property_id}/owner-claims", headers=headers, params=params)

    def escheat_property(self, property_id, headers):
        return self._request("POST", f"/escheatment/properties/{property_id}/escheat", headers=headers)

    # --- Due-diligence letters ---
    def create_letter(self, property_id, headers):
        return self._request("POST", f"/escheatment/properties/{property_id}/due-diligence-letters", headers=headers)

    def list_property_letters(self, property_id, headers, params=None):
        return self._request("GET", f"/escheatment/properties/{property_id}/due-diligence-letters", headers=headers, params=params)

    def get_letter(self, letter_id, headers):
        return self._request("GET", f"/escheatment/due-diligence-letters/{letter_id}", headers=headers)

    def mark_letter_delivered(self, letter_id, headers):
        return self._request("POST", f"/escheatment/due-diligence-letters/{letter_id}/mark-delivered", headers=headers)

    def mark_letter_undeliverable(self, letter_id, headers):
        return self._request("POST", f"/escheatment/due-diligence-letters/{letter_id}/mark-undeliverable", headers=headers)

    def record_letter_response(self, letter_id, payload, headers):
        return self._request("POST", f"/escheatment/due-diligence-letters/{letter_id}/record-response", payload, headers)

    # --- Holder reports ---
    def create_report(self, payload, headers):
        return self._request("POST", "/escheatment/holder-reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/escheatment/holder-reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/escheatment/holder-reports/{report_id}", headers=headers)

    def create_amendment(self, report_id, payload, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/amendments", payload, headers)

    def list_amendments(self, report_id, headers, params=None):
        return self._request("GET", f"/escheatment/holder-reports/{report_id}/amendments", headers=headers, params=params)

    def add_line_item(self, report_id, payload, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/line-items", payload, headers)

    def list_line_items(self, report_id, headers, params=None):
        return self._request("GET", f"/escheatment/holder-reports/{report_id}/line-items", headers=headers, params=params)

    def remove_line_item(self, report_id, line_id, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/line-items/{line_id}/remove", headers=headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/submit", headers=headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/accept", headers=headers)

    def reject_report(self, report_id, payload, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/reject", payload, headers)

    def reopen_report(self, report_id, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/reopen", headers=headers)

    # --- Securities detail ---
    def create_securities_detail(self, property_id, payload, headers):
        return self._request("POST", f"/escheatment/properties/{property_id}/securities-detail", payload, headers)

    def get_securities_detail(self, property_id, headers):
        return self._request("GET", f"/escheatment/properties/{property_id}/securities-detail", headers=headers)

    # --- Liquidation ---
    def create_liquidation_order(self, payload, headers):
        return self._request("POST", "/escheatment/liquidation-orders", payload, headers)

    def get_liquidation_order(self, order_id, headers):
        return self._request("GET", f"/escheatment/liquidation-orders/{order_id}", headers=headers)

    def list_property_liquidation_orders(self, property_id, headers, params=None):
        return self._request("GET", f"/escheatment/properties/{property_id}/liquidation-orders", headers=headers, params=params)

    def execute_liquidation_order(self, order_id, payload, headers):
        return self._request("POST", f"/escheatment/liquidation-orders/{order_id}/execute", payload, headers)

    def settle_liquidation_order(self, order_id, headers):
        return self._request("POST", f"/escheatment/liquidation-orders/{order_id}/settle", headers=headers)

    def cancel_liquidation_order(self, order_id, headers):
        return self._request("POST", f"/escheatment/liquidation-orders/{order_id}/cancel", headers=headers)

    # --- Remittances ---
    def create_remittance(self, report_id, payload, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/remittances", payload, headers)

    def list_remittances(self, report_id, headers, params=None):
        return self._request("GET", f"/escheatment/holder-reports/{report_id}/remittances", headers=headers, params=params)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/escheatment/remittances/{remittance_id}", headers=headers)

    def confirm_remittance(self, remittance_id, headers):
        return self._request("POST", f"/escheatment/remittances/{remittance_id}/confirm", headers=headers)

    def fail_remittance(self, remittance_id, payload, headers):
        return self._request("POST", f"/escheatment/remittances/{remittance_id}/fail", payload, headers)

    def requeue_remittance(self, remittance_id, payload, headers):
        return self._request("POST", f"/escheatment/remittances/{remittance_id}/requeue", payload, headers)

    # --- Owner claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/escheatment/owner-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/escheatment/owner-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/escheatment/owner-claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/escheatment/owner-claims/{claim_id}/start-review", headers=headers)

    def request_claim_info(self, claim_id, payload, headers):
        return self._request("POST", f"/escheatment/owner-claims/{claim_id}/request-info", payload, headers)

    def submit_claim_info(self, claim_id, payload, headers):
        return self._request("POST", f"/escheatment/owner-claims/{claim_id}/submit-info", payload, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/escheatment/owner-claims/{claim_id}/approve", headers=headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/escheatment/owner-claims/{claim_id}/deny", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/escheatment/owner-claims/{claim_id}/pay", headers=headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/escheatment/owner-claims/{claim_id}/withdraw", headers=headers)

    # --- Penalty assessments ---
    def create_penalty_assessment(self, report_id, headers):
        return self._request("POST", f"/escheatment/holder-reports/{report_id}/penalty-assessments", headers=headers)

    def list_penalty_assessments(self, report_id, headers, params=None):
        return self._request("GET", f"/escheatment/holder-reports/{report_id}/penalty-assessments", headers=headers, params=params)

    def get_penalty_assessment(self, assessment_id, headers):
        return self._request("GET", f"/escheatment/penalty-assessments/{assessment_id}", headers=headers)

    def pay_penalty(self, assessment_id, headers):
        return self._request("POST", f"/escheatment/penalty-assessments/{assessment_id}/pay", headers=headers)

    def waive_penalty(self, assessment_id, payload, headers):
        return self._request("POST", f"/escheatment/penalty-assessments/{assessment_id}/waive", payload, headers)

    def dispute_penalty(self, assessment_id, payload, headers):
        return self._request("POST", f"/escheatment/penalty-assessments/{assessment_id}/dispute", payload, headers)

    def uphold_penalty(self, assessment_id, headers):
        return self._request("POST", f"/escheatment/penalty-assessments/{assessment_id}/uphold", headers=headers)

    # --- Audit cases ---
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/escheatment/audit-cases", payload, headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", "/escheatment/audit-cases", headers=headers, params=params)

    def get_audit_case(self, audit_id, headers):
        return self._request("GET", f"/escheatment/audit-cases/{audit_id}", headers=headers)

    def advance_audit_case(self, audit_id, headers):
        return self._request("POST", f"/escheatment/audit-cases/{audit_id}/advance", headers=headers)

    def get_audit_exposure(self, audit_id, headers):
        return self._request("GET", f"/escheatment/audit-cases/{audit_id}/exposure", headers=headers)

    # --- Document records ---
    def create_document_record(self, payload, headers):
        return self._request("POST", "/escheatment/document-records", payload, headers)

    def list_document_records(self, headers, params=None):
        return self._request("GET", "/escheatment/document-records", headers=headers, params=params)

    def get_document_record(self, doc_id, headers):
        return self._request("GET", f"/escheatment/document-records/{doc_id}", headers=headers)

    def purge_document_record(self, doc_id, headers):
        return self._request("POST", f"/escheatment/document-records/{doc_id}/purge", headers=headers)

    # --- Test-driving endpoints ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/escheatment/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_dormancy_sweep(self, headers):
        return self._request("POST", "/escheatment/_sweeps/dormancy", headers=headers)


api_client = ApiClient()
