"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Varieties
    # ------------------------------------------------------------------
    def create_variety(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/varieties", payload, headers)

    def list_varieties(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/varieties", headers=headers, params=params)

    def get_variety(self, variety_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/varieties/{variety_id}", headers=headers)

    def release_variety(self, variety_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/varieties/{variety_id}/release", payload or {}, headers)

    def retire_variety(self, variety_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/varieties/{variety_id}/retire", payload or {}, headers)

    def brand_register_variety(self, variety_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/varieties/{variety_id}/brand-register", payload, headers)

    def brand_renew_variety(self, variety_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/varieties/{variety_id}/brand-renew", payload, headers)

    def brand_abandon_variety(self, variety_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/varieties/{variety_id}/brand-abandon", payload or {}, headers)

    # ------------------------------------------------------------------
    # Protection filings
    # ------------------------------------------------------------------
    def create_protection_filing(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/protection-filings", payload, headers)

    def list_protection_filings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/protection-filings", headers=headers, params=params)

    def get_protection_filing(self, filing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/protection-filings/{filing_id}", headers=headers)

    def file_protection_filing(self, filing_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/protection-filings/{filing_id}/file", payload or {}, headers)

    def grant_protection_filing(self, filing_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/protection-filings/{filing_id}/grant", payload or {}, headers)

    def schedule_annuity(self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/protection-filings/{filing_id}/schedule-annuity", payload, headers)

    def pay_annuity(self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/protection-filings/{filing_id}/pay-annuity", payload, headers)

    def lapse_protection_filing(self, filing_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/protection-filings/{filing_id}/lapse", payload or {}, headers)

    def abandon_protection_filing(self, filing_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/protection-filings/{filing_id}/abandon", payload or {}, headers)

    # ------------------------------------------------------------------
    # Trial sites
    # ------------------------------------------------------------------
    def create_trial_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/trial-sites", payload, headers)

    def list_trial_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/trial-sites", headers=headers, params=params)

    def get_trial_site(self, trial_site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/trial-sites/{trial_site_id}", headers=headers)

    # ------------------------------------------------------------------
    # Variety trials
    # ------------------------------------------------------------------
    def create_variety_trial(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/variety-trials", payload, headers)

    def list_variety_trials(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/variety-trials", headers=headers, params=params)

    def get_variety_trial(self, trial_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/variety-trials/{trial_id}", headers=headers)

    def plant_variety_trial(self, trial_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/variety-trials/{trial_id}/plant", payload or {}, headers)

    def evaluate_variety_trial(self, trial_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/variety-trials/{trial_id}/evaluate", payload, headers)

    def certify_variety_trial(self, trial_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/variety-trials/{trial_id}/certify", payload or {}, headers)

    # ------------------------------------------------------------------
    # Propagators
    # ------------------------------------------------------------------
    def create_propagator(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/propagators", payload, headers)

    def list_propagators(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/propagators", headers=headers, params=params)

    def get_propagator(self, propagator_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/propagators/{propagator_id}", headers=headers)

    # ------------------------------------------------------------------
    # Propagator agreements
    # ------------------------------------------------------------------
    def create_propagator_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/propagator-agreements", payload, headers)

    def list_propagator_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/propagator-agreements", headers=headers, params=params)

    def get_propagator_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/propagator-agreements/{agreement_id}", headers=headers)

    def countersign_agreement(self, agreement_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/propagator-agreements/{agreement_id}/countersign", payload or {}, headers)

    def suspend_agreement(self, agreement_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/propagator-agreements/{agreement_id}/suspend", payload or {}, headers)

    def reinstate_agreement(self, agreement_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/propagator-agreements/{agreement_id}/reinstate", payload or {}, headers)

    def terminate_agreement(self, agreement_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/propagator-agreements/{agreement_id}/terminate", payload or {}, headers)

    # ------------------------------------------------------------------
    # Production quotas
    # ------------------------------------------------------------------
    def create_production_quota(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/production-quotas", payload, headers)

    def list_production_quotas(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/production-quotas", headers=headers, params=params)

    def get_production_quota(self, quota_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/production-quotas/{quota_id}", headers=headers)

    # ------------------------------------------------------------------
    # Tag orders
    # ------------------------------------------------------------------
    def create_tag_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/tag-orders", payload, headers)

    def list_tag_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/tag-orders", headers=headers, params=params)

    def get_tag_order(self, tag_order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/tag-orders/{tag_order_id}", headers=headers)

    def issue_tag_order(self, tag_order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/tag-orders/{tag_order_id}/issue", payload or {}, headers)

    def reconcile_tag_order(self, tag_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/tag-orders/{tag_order_id}/reconcile", payload, headers)

    def void_tag_order(self, tag_order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/tag-orders/{tag_order_id}/void", payload or {}, headers)

    # ------------------------------------------------------------------
    # Royalty reports and line items
    # ------------------------------------------------------------------
    def create_royalty_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/royalty-reports", payload, headers)

    def list_royalty_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/royalty-reports", headers=headers, params=params)

    def get_royalty_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/royalty-reports/{report_id}", headers=headers)

    def create_royalty_line_item(self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/royalty-reports/{report_id}/line-items", payload, headers)

    def list_royalty_line_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/royalty-line-items", headers=headers, params=params)

    def get_royalty_line_item(self, line_item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/royalty-line-items/{line_item_id}", headers=headers)

    def submit_royalty_report(self, report_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/royalty-reports/{report_id}/submit", payload or {}, headers)

    def accept_royalty_report(self, report_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/royalty-reports/{report_id}/accept", payload or {}, headers)

    def dispute_royalty_report(self, report_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/royalty-reports/{report_id}/dispute", payload or {}, headers)

    def revise_royalty_report(self, report_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/royalty-reports/{report_id}/revise", payload or {}, headers)

    def settle_royalty_report(self, report_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/royalty-reports/{report_id}/settle", payload or {}, headers)

    def reverse_royalty_report(self, report_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/royalty-reports/{report_id}/reverse", payload or {}, headers)

    # ------------------------------------------------------------------
    # Sublicense grants
    # ------------------------------------------------------------------
    def create_sublicense_grant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sublicense-grants", payload, headers)

    def list_sublicense_grants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/sublicense-grants", headers=headers, params=params)

    def get_sublicense_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sublicense-grants/{grant_id}", headers=headers)

    def activate_sublicense_grant(self, grant_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/sublicense-grants/{grant_id}/activate", payload or {}, headers)

    def revoke_sublicense_grant(self, grant_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/sublicense-grants/{grant_id}/revoke", payload or {}, headers)

    # ------------------------------------------------------------------
    # Surveillance cases and genetic tests
    # ------------------------------------------------------------------
    def create_surveillance_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/surveillance-cases", payload, headers)

    def list_surveillance_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/surveillance-cases", headers=headers, params=params)

    def get_surveillance_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/surveillance-cases/{case_id}", headers=headers)

    def sample_surveillance_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/surveillance-cases/{case_id}/sample", payload, headers)

    def create_genetic_test(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/surveillance-cases/{case_id}/genetic-tests", payload, headers)

    def list_genetic_tests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/genetic-tests", headers=headers, params=params)

    def get_genetic_test(self, test_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/genetic-tests/{test_id}", headers=headers)

    def conclude_testing(self, case_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/surveillance-cases/{case_id}/conclude-testing", payload or {}, headers)

    def resolve_surveillance_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/surveillance-cases/{case_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Audit engagements
    # ------------------------------------------------------------------
    def create_audit_engagement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/audit-engagements", payload, headers)

    def list_audit_engagements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-engagements", headers=headers, params=params)

    def get_audit_engagement(self, engagement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/audit-engagements/{engagement_id}", headers=headers)

    def finalize_audit_engagement(self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/audit-engagements/{engagement_id}/finalize", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
