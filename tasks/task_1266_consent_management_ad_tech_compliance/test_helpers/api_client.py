"""API client: one method per endpoint defined in the PRD (59 endpoints under /v1)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Properties & clock ---
    def create_property(self, payload, headers):
        return self._request("POST", "/v1/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/v1/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/v1/properties/{property_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- Jurisdiction policies ---
    def create_jurisdiction_policy(self, payload, headers):
        return self._request("POST", "/v1/jurisdiction-policies", payload, headers)

    def list_jurisdiction_policies(self, headers, params=None):
        return self._request("GET", "/v1/jurisdiction-policies", headers=headers, params=params)

    def get_jurisdiction_policy(self, policy_id, headers):
        return self._request("GET", f"/v1/jurisdiction-policies/{policy_id}", headers=headers)

    def update_jurisdiction_policy(self, policy_id, payload, headers):
        return self._request("PUT", f"/v1/jurisdiction-policies/{policy_id}", payload, headers)

    # --- Banner configs ---
    def create_banner_config(self, payload, headers):
        return self._request("POST", "/v1/banner-configs", payload, headers)

    def list_banner_configs(self, headers, params=None):
        return self._request("GET", "/v1/banner-configs", headers=headers, params=params)

    def get_banner_config(self, config_id, headers):
        return self._request("GET", f"/v1/banner-configs/{config_id}", headers=headers)

    def publish_banner_config(self, config_id, payload, headers):
        return self._request("POST", f"/v1/banner-configs/{config_id}/publish", payload, headers)

    def archive_banner_config(self, config_id, headers):
        return self._request("POST", f"/v1/banner-configs/{config_id}/archive", headers=headers)

    # --- Vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/v1/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/v1/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/v1/vendors/{vendor_id}", headers=headers)

    def approve_vendor(self, vendor_id, headers):
        return self._request("POST", f"/v1/vendors/{vendor_id}/approve", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/v1/vendors/{vendor_id}/suspend", headers=headers)

    # --- Tag rules ---
    def create_tag_rule(self, payload, headers):
        return self._request("POST", "/v1/tag-rules", payload, headers)

    def list_tag_rules(self, headers, params=None):
        return self._request("GET", "/v1/tag-rules", headers=headers, params=params)

    def get_tag_rule(self, rule_id, headers):
        return self._request("GET", f"/v1/tag-rules/{rule_id}", headers=headers)

    def update_tag_rule(self, rule_id, payload, headers):
        return self._request("PUT", f"/v1/tag-rules/{rule_id}", payload, headers)

    # --- Visitors ---
    def create_visitor(self, payload, headers):
        return self._request("POST", "/v1/visitors", payload, headers)

    def list_visitors(self, headers, params=None):
        return self._request("GET", "/v1/visitors", headers=headers, params=params)

    def get_visitor(self, visitor_id, headers):
        return self._request("GET", f"/v1/visitors/{visitor_id}", headers=headers)

    def attest_age(self, visitor_id, payload, headers):
        return self._request("POST", f"/v1/visitors/{visitor_id}/age-attestation", payload, headers)

    def create_gpc_signal(self, visitor_id, payload, headers):
        return self._request("POST", f"/v1/visitors/{visitor_id}/gpc-signals", payload, headers)

    def list_gpc_signals(self, visitor_id, headers, params=None):
        return self._request("GET", f"/v1/visitors/{visitor_id}/gpc-signals", headers=headers, params=params)

    # --- Consent records ---
    def get_consent_preview(self, visitor_id, headers, params=None):
        return self._request("GET", f"/v1/visitors/{visitor_id}/consent-preview", headers=headers, params=params)

    def create_consent_record(self, visitor_id, payload, headers):
        return self._request("POST", f"/v1/visitors/{visitor_id}/consent-records", payload, headers)

    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/v1/consent-records", headers=headers, params=params)

    def list_visitor_consent_records(self, visitor_id, headers, params=None):
        return self._request("GET", f"/v1/visitors/{visitor_id}/consent-records", headers=headers, params=params)

    def get_consent_record(self, record_id, headers):
        return self._request("GET", f"/v1/consent-records/{record_id}", headers=headers)

    def withdraw_consent_record(self, record_id, headers):
        return self._request("POST", f"/v1/consent-records/{record_id}/withdraw", headers=headers)

    def regrant_consent_record(self, record_id, headers):
        return self._request("POST", f"/v1/consent-records/{record_id}/regrant", headers=headers)

    # --- Do-not-sell ---
    def create_do_not_sell_request(self, visitor_id, payload, headers):
        return self._request("POST", f"/v1/visitors/{visitor_id}/do-not-sell-requests", payload, headers)

    def list_visitor_do_not_sell_requests(self, visitor_id, headers, params=None):
        return self._request("GET", f"/v1/visitors/{visitor_id}/do-not-sell-requests", headers=headers, params=params)

    def list_do_not_sell_requests(self, headers, params=None):
        return self._request("GET", "/v1/do-not-sell-requests", headers=headers, params=params)

    def get_do_not_sell_request(self, request_id, headers):
        return self._request("GET", f"/v1/do-not-sell-requests/{request_id}", headers=headers)

    def update_do_not_sell_request(self, request_id, payload, headers):
        return self._request("PUT", f"/v1/do-not-sell-requests/{request_id}", payload, headers)

    def propagate_do_not_sell_request(self, request_id, headers):
        return self._request("POST", f"/v1/do-not-sell-requests/{request_id}/propagate", headers=headers)

    def list_request_propagations(self, request_id, headers, params=None):
        return self._request("GET", f"/v1/do-not-sell-requests/{request_id}/propagations", headers=headers, params=params)

    def list_vendor_propagations(self, headers, params=None):
        return self._request("GET", "/v1/vendor-propagations", headers=headers, params=params)

    def get_vendor_propagation(self, propagation_id, headers):
        return self._request("GET", f"/v1/vendor-propagations/{propagation_id}", headers=headers)

    def update_vendor_propagation(self, propagation_id, payload, headers):
        return self._request("PUT", f"/v1/vendor-propagations/{propagation_id}", payload, headers)

    # --- Tag audit scans & findings ---
    def create_tag_audit_scan(self, payload, headers):
        return self._request("POST", "/v1/tag-audit-scans", payload, headers)

    def list_tag_audit_scans(self, headers, params=None):
        return self._request("GET", "/v1/tag-audit-scans", headers=headers, params=params)

    def get_tag_audit_scan(self, scan_id, headers):
        return self._request("GET", f"/v1/tag-audit-scans/{scan_id}", headers=headers)

    def run_tag_audit_scan(self, scan_id, payload, headers):
        return self._request("POST", f"/v1/tag-audit-scans/{scan_id}/run", payload, headers)

    def list_scan_findings(self, scan_id, headers, params=None):
        return self._request("GET", f"/v1/tag-audit-scans/{scan_id}/findings", headers=headers, params=params)

    def list_vendor_tracker_findings(self, vendor_id, headers, params=None):
        return self._request("GET", f"/v1/vendors/{vendor_id}/tracker-findings", headers=headers, params=params)

    def update_tracker_finding(self, finding_id, payload, headers):
        return self._request("PUT", f"/v1/tracker-findings/{finding_id}", payload, headers)

    # --- Regulatory sweeps ---
    def create_regulatory_sweep(self, payload, headers):
        return self._request("POST", "/v1/regulatory-sweeps", payload, headers)

    def list_regulatory_sweeps(self, headers, params=None):
        return self._request("GET", "/v1/regulatory-sweeps", headers=headers, params=params)

    def get_regulatory_sweep(self, sweep_id, headers):
        return self._request("GET", f"/v1/regulatory-sweeps/{sweep_id}", headers=headers)

    def begin_evidence_collection(self, sweep_id, headers):
        return self._request("POST", f"/v1/regulatory-sweeps/{sweep_id}/begin-evidence-collection", headers=headers)

    def respond_regulatory_sweep(self, sweep_id, headers):
        return self._request("POST", f"/v1/regulatory-sweeps/{sweep_id}/respond", headers=headers)

    def escalate_regulatory_sweep(self, sweep_id, headers):
        return self._request("POST", f"/v1/regulatory-sweeps/{sweep_id}/escalate", headers=headers)

    def close_regulatory_sweep(self, sweep_id, headers):
        return self._request("POST", f"/v1/regulatory-sweeps/{sweep_id}/close", headers=headers)


api_client = ApiClient()
