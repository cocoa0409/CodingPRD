"""API client: one method per endpoint defined in the Hazmat Tier II PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/epcra/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/epcra/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/epcra/facilities/{facility_id}", headers=headers)

    def link_emergency_response_plan(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/epcra/facilities/{facility_id}/emergency-response-plan", payload, headers
        )

    def list_facility_tier_ii_filings(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/epcra/facilities/{facility_id}/tier-ii-filings", headers=headers, params=params
        )

    def list_facility_permits(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/epcra/facilities/{facility_id}/permits", headers=headers, params=params
        )

    def list_facility_inspections(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/epcra/facilities/{facility_id}/inspections", headers=headers, params=params
        )

    def list_facility_compliance_cases(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/epcra/facilities/{facility_id}/compliance-cases", headers=headers, params=params
        )

    def list_facility_risk_management_plans(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/epcra/facilities/{facility_id}/risk-management-plans", headers=headers, params=params
        )

    # --- Chemicals (global catalog) ---
    def create_chemical(self, payload, headers):
        return self._request("POST", "/epcra/chemicals", payload, headers)

    def list_chemicals(self, headers, params=None):
        return self._request("GET", "/epcra/chemicals", headers=headers, params=params)

    def get_chemical(self, chemical_id, headers):
        return self._request("GET", f"/epcra/chemicals/{chemical_id}", headers=headers)

    # --- Chemical Inventories ---
    def create_chemical_inventory(self, payload, headers):
        return self._request("POST", "/epcra/chemical-inventories", payload, headers)

    def list_chemical_inventories(self, headers, params=None):
        return self._request("GET", "/epcra/chemical-inventories", headers=headers, params=params)

    def get_chemical_inventory(self, inventory_id, headers):
        return self._request("GET", f"/epcra/chemical-inventories/{inventory_id}", headers=headers)

    def retire_chemical_inventory(self, inventory_id, headers):
        return self._request(
            "POST", f"/epcra/chemical-inventories/{inventory_id}/retire", {}, headers
        )

    # --- Tier II Filings ---
    def create_tier_ii_filing(self, payload, headers):
        return self._request("POST", "/epcra/tier-ii-filings", payload, headers)

    def submit_tier_ii_filing(self, filing_id, headers):
        return self._request("POST", f"/epcra/tier-ii-filings/{filing_id}/submit", {}, headers)

    def review_tier_ii_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/epcra/tier-ii-filings/{filing_id}/review", payload, headers)

    def pay_tier_ii_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/epcra/tier-ii-filings/{filing_id}/pay", payload, headers)

    # --- SDS repository ---
    def create_sds(self, payload, headers):
        return self._request("POST", "/epcra/sds", payload, headers)

    def list_sds(self, headers, params=None):
        return self._request("GET", "/epcra/sds", headers=headers, params=params)

    def get_sds(self, sds_id, headers):
        return self._request("GET", f"/epcra/sds/{sds_id}", headers=headers)

    # --- Release Notifications ---
    def create_release_notification(self, payload, headers):
        return self._request("POST", "/epcra/release-notifications", payload, headers)

    def list_release_notifications(self, headers, params=None):
        return self._request("GET", "/epcra/release-notifications", headers=headers, params=params)

    def get_release_notification(self, release_id, headers):
        return self._request("GET", f"/epcra/release-notifications/{release_id}", headers=headers)

    def report_release_notification(self, release_id, payload, headers):
        return self._request(
            "POST", f"/epcra/release-notifications/{release_id}/report", payload, headers
        )

    def remediate_release_notification(self, release_id, payload, headers):
        return self._request(
            "POST", f"/epcra/release-notifications/{release_id}/remediation", payload, headers
        )

    def list_release_lepc_notices(self, release_id, headers, params=None):
        return self._request(
            "GET", f"/epcra/release-notifications/{release_id}/lepc-notices", headers=headers, params=params
        )

    # --- LEPC Notices ---
    def create_lepc_notice(self, payload, headers):
        return self._request("POST", "/epcra/lepc-notices", payload, headers)

    def acknowledge_lepc_notice(self, notice_id, headers):
        return self._request("POST", f"/epcra/lepc-notices/{notice_id}/acknowledge", {}, headers)

    # --- Permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/epcra/permits", payload, headers)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/epcra/inspections", payload, headers)

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/epcra/inspections/{inspection_id}/start", {}, headers)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/epcra/inspections/{inspection_id}/complete", payload, headers
        )

    # --- Compliance Cases ---
    def create_compliance_case(self, payload, headers):
        return self._request("POST", "/epcra/compliance-cases", payload, headers)

    def review_compliance_case(self, case_id, headers):
        return self._request("POST", f"/epcra/compliance-cases/{case_id}/review", {}, headers)

    def resolve_compliance_case(self, case_id, payload, headers):
        return self._request("POST", f"/epcra/compliance-cases/{case_id}/resolve", payload, headers)

    # --- Risk Management Plans ---
    def create_risk_management_plan(self, payload, headers):
        return self._request("POST", "/epcra/risk-management-plans", payload, headers)

    def resubmit_risk_management_plan(self, rmp_id, payload, headers):
        return self._request(
            "POST", f"/epcra/risk-management-plans/{rmp_id}/resubmit", payload, headers
        )


api_client = ApiClient()
