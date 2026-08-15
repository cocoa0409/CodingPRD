"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Registry ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/v1/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/v1/owners/{owner_id}", headers=headers)

    def create_verifier(self, payload, headers):
        return self._request("POST", "/v1/verifiers", payload, headers)

    def get_verifier(self, verifier_id, headers):
        return self._request("GET", f"/v1/verifiers/{verifier_id}", headers=headers)

    # --- Reporting cycles ---
    def create_reporting_cycle(self, payload, headers):
        return self._request("POST", "/v1/reporting-cycles", payload, headers)

    def get_reporting_cycle(self, cycle_id, headers):
        return self._request("GET", f"/v1/reporting-cycles/{cycle_id}", headers=headers)

    def patch_reporting_cycle(self, cycle_id, payload, headers):
        return self._request("PATCH", f"/v1/reporting-cycles/{cycle_id}", payload, headers)

    def open_reporting_cycle(self, cycle_id, headers):
        return self._request("POST", f"/v1/reporting-cycles/{cycle_id}/open", {}, headers)

    def close_filing(self, cycle_id, headers):
        return self._request("POST", f"/v1/reporting-cycles/{cycle_id}/close-filing", {}, headers)

    # --- Buildings ---
    def create_building(self, payload, headers):
        return self._request("POST", "/v1/buildings", payload, headers)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/v1/buildings/{building_id}", headers=headers)

    def list_buildings(self, headers, params=None):
        return self._request("GET", "/v1/buildings", headers=headers, params=params)

    def patch_building(self, building_id, payload, headers):
        return self._request("PATCH", f"/v1/buildings/{building_id}", payload, headers)

    def archive_building(self, building_id, headers):
        return self._request("POST", f"/v1/buildings/{building_id}/archive", {}, headers)

    def get_compliance_summary(self, building_id, cycle_id, headers):
        return self._request(
            "GET",
            f"/v1/buildings/{building_id}/compliance-summary",
            headers=headers,
            params={"cycle_id": cycle_id},
        )

    # --- Tenant units ---
    def create_tenant_unit(self, building_id, payload, headers):
        return self._request("POST", f"/v1/buildings/{building_id}/tenant-units", payload, headers)

    def list_tenant_units(self, headers, params=None):
        return self._request("GET", "/v1/tenant-units", headers=headers, params=params)

    def get_tenant_unit(self, unit_id, headers):
        return self._request("GET", f"/v1/tenant-units/{unit_id}", headers=headers)

    def patch_tenant_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/v1/tenant-units/{unit_id}", payload, headers)

    # --- Consent grants ---
    def create_consent_grant(self, unit_id, headers):
        return self._request("POST", f"/v1/tenant-units/{unit_id}/consent-grants", {}, headers)

    def grant_consent(self, grant_id, payload, headers):
        return self._request("POST", f"/v1/consent-grants/{grant_id}/grant", payload, headers)

    def deny_consent(self, grant_id, headers):
        return self._request("POST", f"/v1/consent-grants/{grant_id}/deny", {}, headers)

    def revoke_consent(self, grant_id, headers):
        return self._request("POST", f"/v1/consent-grants/{grant_id}/revoke", {}, headers)

    def list_consent_grants(self, headers, params=None):
        return self._request("GET", "/v1/consent-grants", headers=headers, params=params)

    def get_consent_grant(self, grant_id, headers):
        return self._request("GET", f"/v1/consent-grants/{grant_id}", headers=headers)

    # --- Utility accounts ---
    def create_utility_account(self, building_id, payload, headers):
        return self._request("POST", f"/v1/buildings/{building_id}/utility-accounts", payload, headers)

    def list_utility_accounts(self, headers, params=None):
        return self._request("GET", "/v1/utility-accounts", headers=headers, params=params)

    def get_utility_account(self, account_id, headers):
        return self._request("GET", f"/v1/utility-accounts/{account_id}", headers=headers)

    # --- Usage records ---
    def create_usage_record(self, account_id, payload, headers):
        return self._request("POST", f"/v1/utility-accounts/{account_id}/usage-records", payload, headers)

    def void_usage_record(self, record_id, payload, headers):
        return self._request("POST", f"/v1/usage-records/{record_id}/void", payload, headers)

    def list_usage_records(self, headers, params=None):
        return self._request("GET", "/v1/usage-records", headers=headers, params=params)

    def get_usage_record(self, record_id, headers):
        return self._request("GET", f"/v1/usage-records/{record_id}", headers=headers)

    # --- Benchmark reports ---
    def create_benchmark_report(self, payload, headers):
        return self._request("POST", "/v1/benchmark-reports", payload, headers)

    def get_benchmark_report(self, report_id, headers):
        return self._request("GET", f"/v1/benchmark-reports/{report_id}", headers=headers)

    def list_benchmark_reports(self, headers, params=None):
        return self._request("GET", "/v1/benchmark-reports", headers=headers, params=params)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/v1/benchmark-reports/{report_id}/submit", {}, headers)

    def certify_report(self, report_id, headers):
        return self._request("POST", f"/v1/benchmark-reports/{report_id}/certify", {}, headers)

    # --- Verification records ---
    def create_verification_record(self, report_id, payload, headers):
        return self._request(
            "POST", f"/v1/benchmark-reports/{report_id}/verification-records", payload, headers
        )

    def sign_off_verification(self, record_id, headers):
        return self._request("POST", f"/v1/verification-records/{record_id}/sign-off", {}, headers)

    def reject_verification(self, record_id, payload, headers):
        return self._request("POST", f"/v1/verification-records/{record_id}/reject", payload, headers)

    def list_verification_records(self, headers, params=None):
        return self._request("GET", "/v1/verification-records", headers=headers, params=params)

    def get_verification_record(self, record_id, headers):
        return self._request("GET", f"/v1/verification-records/{record_id}", headers=headers)

    # --- Anomaly flags ---
    def create_anomaly_flag(self, report_id, payload, headers):
        return self._request("POST", f"/v1/benchmark-reports/{report_id}/anomaly-flags", payload, headers)

    def list_anomaly_flags(self, headers, params=None):
        return self._request("GET", "/v1/anomaly-flags", headers=headers, params=params)

    def get_anomaly_flag(self, flag_id, headers):
        return self._request("GET", f"/v1/anomaly-flags/{flag_id}", headers=headers)

    def resolve_anomaly_flag(self, flag_id, payload, headers):
        return self._request("POST", f"/v1/anomaly-flags/{flag_id}/resolve", payload, headers)

    def waive_anomaly_flag(self, flag_id, payload, headers):
        return self._request("POST", f"/v1/anomaly-flags/{flag_id}/waive", payload, headers)

    # --- Fine assessments ---
    def list_fine_assessments(self, headers, params=None):
        return self._request("GET", "/v1/fine-assessments", headers=headers, params=params)

    def get_fine_assessment(self, fine_id, headers):
        return self._request("GET", f"/v1/fine-assessments/{fine_id}", headers=headers)

    def notice_fine(self, fine_id, headers):
        return self._request("POST", f"/v1/fine-assessments/{fine_id}/notice", {}, headers)

    def pay_fine(self, fine_id, payload, headers):
        return self._request("POST", f"/v1/fine-assessments/{fine_id}/pay", payload, headers)

    def waive_fine(self, fine_id, payload, headers):
        return self._request("POST", f"/v1/fine-assessments/{fine_id}/waive", payload, headers)

    # --- Exemption requests ---
    def create_exemption_request(self, building_id, payload, headers):
        return self._request("POST", f"/v1/buildings/{building_id}/exemption-requests", payload, headers)

    def list_exemption_requests(self, headers, params=None):
        return self._request("GET", "/v1/exemption-requests", headers=headers, params=params)

    def get_exemption_request(self, request_id, headers):
        return self._request("GET", f"/v1/exemption-requests/{request_id}", headers=headers)

    def start_exemption_review(self, request_id, headers):
        return self._request("POST", f"/v1/exemption-requests/{request_id}/start-review", {}, headers)

    def decide_exemption(self, request_id, payload, headers):
        return self._request("POST", f"/v1/exemption-requests/{request_id}/decide", payload, headers)

    def appeal_exemption(self, request_id, payload, headers):
        return self._request("POST", f"/v1/exemption-requests/{request_id}/appeal", payload, headers)

    # --- Disclosure publications ---
    def create_disclosure_publication(self, cycle_id, headers):
        return self._request(
            "POST", f"/v1/reporting-cycles/{cycle_id}/disclosure-publications", {}, headers
        )

    def publish_disclosure(self, publication_id, headers):
        return self._request(
            "POST", f"/v1/disclosure-publications/{publication_id}/publish", {}, headers
        )

    def list_disclosure_publications(self, headers, params=None):
        return self._request("GET", "/v1/disclosure-publications", headers=headers, params=params)

    def get_disclosure_publication(self, publication_id, headers):
        return self._request(
            "GET", f"/v1/disclosure-publications/{publication_id}", headers=headers
        )

    # --- Test-driving clock ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
