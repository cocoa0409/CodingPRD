"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Zones ----
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/zones", headers=headers, params=params)

    # ---- Hosts ----
    def create_host(self, payload, headers):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def list_hosts(self, headers, params=None):
        return self._request("GET", "/hosts", headers=headers, params=params)

    def attest_primary_residence(self, host_id, payload, headers):
        return self._request("POST", f"/hosts/{host_id}/attest-primary-residence", payload, headers)

    # ---- Properties ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ---- Permits ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    def reject_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/reject", {}, headers)

    def activate_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/activate", {}, headers)

    def renew_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/renew", payload, headers)

    def reinstate_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/reinstate", {}, headers)

    # ---- Complaints ----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def dismiss_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/dismiss", {}, headers)

    def uphold_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/uphold", {}, headers)

    # ---- Tax Filings ----
    def create_tax_filing(self, payload, headers):
        return self._request("POST", "/tax-filings", payload, headers)

    def get_tax_filing(self, filing_id, headers):
        return self._request("GET", f"/tax-filings/{filing_id}", headers=headers)

    def list_tax_filings(self, headers, params=None):
        return self._request("GET", "/tax-filings", headers=headers, params=params)

    def file_tax_filing(self, filing_id, headers):
        return self._request("POST", f"/tax-filings/{filing_id}/file", {}, headers)

    def amend_tax_filing(self, filing_id, headers):
        return self._request("POST", f"/tax-filings/{filing_id}/amend", {}, headers)

    def remit_tax_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/tax-filings/{filing_id}/remit", payload, headers)

    # ---- Lottery ----
    def create_lottery_round(self, payload, headers):
        return self._request("POST", "/lottery-rounds", payload, headers)

    def get_lottery_round(self, round_id, headers):
        return self._request("GET", f"/lottery-rounds/{round_id}", headers=headers)

    def list_lottery_rounds(self, headers, params=None):
        return self._request("GET", "/lottery-rounds", headers=headers, params=params)

    def draw_lottery_round(self, round_id, payload, headers):
        return self._request("POST", f"/lottery-rounds/{round_id}/draw", payload, headers)

    # ---- Platforms & listing reports ----
    def create_platform(self, payload, headers):
        return self._request("POST", "/platforms", payload, headers)

    def get_platform(self, platform_id, headers):
        return self._request("GET", f"/platforms/{platform_id}", headers=headers)

    def create_listing_report(self, payload, headers):
        return self._request("POST", "/listing-reports", payload, headers)

    def get_listing_report(self, report_id, headers):
        return self._request("GET", f"/listing-reports/{report_id}", headers=headers)

    def list_listing_reports(self, headers, params=None):
        return self._request("GET", "/listing-reports", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
