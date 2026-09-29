"""API client: one method per endpoint declared in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/carriage"


class ApiClient(GenericApiClient):
    # ---------------- Distributors ----------------
    def create_distributor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/distributors", payload, headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/distributors", headers=headers, params=params)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"{PREFIX}/distributors/{distributor_id}", headers=headers)

    def patch_distributor(self, distributor_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/distributors/{distributor_id}", payload, headers)

    def credit_review(self, distributor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/distributors/{distributor_id}/credit-review", payload, headers
        )

    # ---------------- Carriage agreements ----------------
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def patch_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/agreements/{agreement_id}", payload, headers)

    def agreement_lifecycle(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/lifecycle", payload, headers
        )

    def agreement_renewal(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/renewal", payload, headers
        )

    def get_settlement_summary(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/agreements/{agreement_id}/settlement-summary", headers=headers
        )

    # ---------------- Rate card ----------------
    def create_rate_card_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-card-entries", payload, headers)

    def list_rate_card_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rate-card-entries", headers=headers, params=params)

    def get_rate_card_entry(self, rate_card_entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rate-card-entries/{rate_card_entry_id}", headers=headers
        )

    # ---------------- MFN clauses ----------------
    def create_mfn_clause(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mfn-clauses", payload, headers)

    def list_mfn_clauses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/mfn-clauses", headers=headers, params=params)

    def get_mfn_clause(self, mfn_clause_id, headers):
        return self._request("GET", f"{PREFIX}/mfn-clauses/{mfn_clause_id}", headers=headers)

    def reset_mfn_clause(self, mfn_clause_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/mfn-clauses/{mfn_clause_id}/reset", payload, headers
        )

    # ---------------- Subscriber reports ----------------
    def create_subscriber_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriber-reports", payload, headers)

    def list_subscriber_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/subscriber-reports", headers=headers, params=params)

    def get_subscriber_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/subscriber-reports/{report_id}", headers=headers)

    def review_subscriber_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriber-reports/{report_id}/review", payload, headers
        )

    # ---------------- Audit engagements & findings ----------------
    def create_audit_engagement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audit-engagements", payload, headers)

    def list_audit_engagements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/audit-engagements", headers=headers, params=params)

    def get_audit_engagement(self, engagement_id, headers):
        return self._request("GET", f"{PREFIX}/audit-engagements/{engagement_id}", headers=headers)

    def audit_engagement_lifecycle(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audit-engagements/{engagement_id}/lifecycle", payload, headers
        )

    def create_audit_finding(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audit-engagements/{engagement_id}/findings", payload, headers
        )

    def list_audit_findings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/audit-findings", headers=headers, params=params)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"{PREFIX}/audit-findings/{finding_id}", headers=headers)

    # ---------------- Content titles ----------------
    def create_content_title(self, payload, headers):
        return self._request("POST", f"{PREFIX}/content-titles", payload, headers)

    def list_content_titles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/content-titles", headers=headers, params=params)

    def get_content_title(self, title_id, headers):
        return self._request("GET", f"{PREFIX}/content-titles/{title_id}", headers=headers)

    def set_title_rights_status(self, title_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/content-titles/{title_id}/rights-status", payload, headers
        )

    # ---------------- Rights windows ----------------
    def create_rights_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rights-windows", payload, headers)

    def list_rights_windows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rights-windows", headers=headers, params=params)

    def get_rights_window(self, window_id, headers):
        return self._request("GET", f"{PREFIX}/rights-windows/{window_id}", headers=headers)

    def rights_window_lifecycle(self, window_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rights-windows/{window_id}/lifecycle", payload, headers
        )

    # ---------------- Blackout rules ----------------
    def create_blackout_rule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/blackout-rules", payload, headers)

    def list_blackout_rules(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/blackout-rules", headers=headers, params=params)

    def get_blackout_rule(self, blackout_rule_id, headers):
        return self._request("GET", f"{PREFIX}/blackout-rules/{blackout_rule_id}", headers=headers)

    def blackout_rule_lifecycle(self, blackout_rule_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/blackout-rules/{blackout_rule_id}/lifecycle", payload, headers
        )

    # ---------------- Marketing commitments ----------------
    def create_marketing_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/marketing-commitments", payload, headers)

    def list_marketing_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/marketing-commitments", headers=headers, params=params
        )

    def get_marketing_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/marketing-commitments/{commitment_id}", headers=headers
        )

    def earn_marketing_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/marketing-commitments/{commitment_id}/earn", payload, headers
        )

    # ---------------- Invoices ----------------
    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def invoice_lifecycle(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/lifecycle", payload, headers
        )

    # ---------------- Renewal analyses ----------------
    def create_renewal_analysis(self, payload, headers):
        return self._request("POST", f"{PREFIX}/renewal-analyses", payload, headers)

    def list_renewal_analyses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/renewal-analyses", headers=headers, params=params)

    def get_renewal_analysis(self, analysis_id, headers):
        return self._request("GET", f"{PREFIX}/renewal-analyses/{analysis_id}", headers=headers)

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
