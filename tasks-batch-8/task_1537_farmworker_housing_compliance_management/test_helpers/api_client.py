"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Housing sites
    # ------------------------------------------------------------------
    def create_housing_site(self, payload, headers):
        return self._request("POST", "/housing-sites", payload, headers)

    def list_housing_sites(self, headers, params=None):
        return self._request("GET", "/housing-sites", headers=headers, params=params)

    def get_housing_site(self, site_id, headers):
        return self._request("GET", f"/housing-sites/{site_id}", headers=headers)

    def update_housing_site(self, site_id, payload, headers):
        return self._request("PUT", f"/housing-sites/{site_id}", payload, headers)

    def get_site_compliance_summary(self, site_id, headers):
        return self._request("GET", f"/housing-sites/{site_id}/compliance-summary",
                             headers=headers)

    # ------------------------------------------------------------------
    # Season windows
    # ------------------------------------------------------------------
    def create_season_window(self, payload, headers):
        return self._request("POST", "/season-windows", payload, headers)

    def list_season_windows(self, headers, params=None):
        return self._request("GET", "/season-windows", headers=headers, params=params)

    def get_season_window(self, window_id, headers):
        return self._request("GET", f"/season-windows/{window_id}", headers=headers)

    def delete_season_window(self, window_id, headers):
        return self._request("DELETE", f"/season-windows/{window_id}", headers=headers)

    # ------------------------------------------------------------------
    # Buildings
    # ------------------------------------------------------------------
    def create_building(self, payload, headers):
        return self._request("POST", "/buildings", payload, headers)

    def list_buildings(self, headers, params=None):
        return self._request("GET", "/buildings", headers=headers, params=params)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/buildings/{building_id}", headers=headers)

    # ------------------------------------------------------------------
    # Housing units
    # ------------------------------------------------------------------
    def create_housing_unit(self, payload, headers):
        return self._request("POST", "/housing-units", payload, headers)

    def list_housing_units(self, headers, params=None):
        return self._request("GET", "/housing-units", headers=headers, params=params)

    def get_housing_unit(self, unit_id, headers):
        return self._request("GET", f"/housing-units/{unit_id}", headers=headers)

    def update_housing_unit(self, unit_id, payload, headers):
        return self._request("PUT", f"/housing-units/{unit_id}", payload, headers)

    def get_unit_availability(self, unit_id, headers):
        return self._request("GET", f"/housing-units/{unit_id}/availability",
                             headers=headers)

    # ------------------------------------------------------------------
    # Unit certifications
    # ------------------------------------------------------------------
    def create_unit_certification(self, payload, headers):
        return self._request("POST", "/unit-certifications", payload, headers)

    def list_unit_certifications(self, headers, params=None):
        return self._request("GET", "/unit-certifications", headers=headers, params=params)

    def get_unit_certification(self, cert_id, headers):
        return self._request("GET", f"/unit-certifications/{cert_id}", headers=headers)

    def update_unit_certification(self, cert_id, payload, headers):
        return self._request("PUT", f"/unit-certifications/{cert_id}", payload, headers)

    # ------------------------------------------------------------------
    # Households
    # ------------------------------------------------------------------
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def update_household(self, household_id, payload, headers):
        return self._request("PUT", f"/households/{household_id}", payload, headers)

    # ------------------------------------------------------------------
    # Household members
    # ------------------------------------------------------------------
    def create_household_member(self, payload, headers):
        return self._request("POST", "/household-members", payload, headers)

    def list_household_members(self, headers, params=None):
        return self._request("GET", "/household-members", headers=headers, params=params)

    def get_household_member(self, member_id, headers):
        return self._request("GET", f"/household-members/{member_id}", headers=headers)

    # ------------------------------------------------------------------
    # Deduction authorizations
    # ------------------------------------------------------------------
    def create_deduction_authorization(self, payload, headers):
        return self._request("POST", "/deduction-authorizations", payload, headers)

    def list_deduction_authorizations(self, headers, params=None):
        return self._request("GET", "/deduction-authorizations",
                             headers=headers, params=params)

    def get_deduction_authorization(self, authorization_id, headers):
        return self._request("GET", f"/deduction-authorizations/{authorization_id}",
                             headers=headers)

    def update_deduction_authorization(self, authorization_id, payload, headers):
        return self._request("PUT", f"/deduction-authorizations/{authorization_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Tenancies
    # ------------------------------------------------------------------
    def create_tenancy(self, payload, headers):
        return self._request("POST", "/tenancies", payload, headers)

    def list_tenancies(self, headers, params=None):
        return self._request("GET", "/tenancies", headers=headers, params=params)

    def get_tenancy(self, tenancy_id, headers):
        return self._request("GET", f"/tenancies/{tenancy_id}", headers=headers)

    def update_tenancy(self, tenancy_id, payload, headers):
        return self._request("PUT", f"/tenancies/{tenancy_id}", payload, headers)

    def create_tenancy_payment(self, tenancy_id, payload, headers):
        return self._request("POST", f"/tenancies/{tenancy_id}/payments",
                             payload, headers)

    def get_tenancy_statement(self, tenancy_id, headers):
        return self._request("GET", f"/tenancies/{tenancy_id}/statement",
                             headers=headers)

    # ------------------------------------------------------------------
    # Charge ledger
    # ------------------------------------------------------------------
    def create_charge_ledger_entry(self, payload, headers):
        return self._request("POST", "/charge-ledger-entries", payload, headers)

    def list_charge_ledger_entries(self, headers, params=None):
        return self._request("GET", "/charge-ledger-entries",
                             headers=headers, params=params)

    def get_charge_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/charge-ledger-entries/{entry_id}",
                             headers=headers)

    def void_charge_ledger_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/charge-ledger-entries/{entry_id}/void",
                             payload, headers)

    # ------------------------------------------------------------------
    # Work orders
    # ------------------------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def update_work_order(self, work_order_id, payload, headers):
        return self._request("PUT", f"/work-orders/{work_order_id}", payload, headers)

    # ------------------------------------------------------------------
    # Pest treatments
    # ------------------------------------------------------------------
    def create_pest_treatment(self, payload, headers):
        return self._request("POST", "/pest-treatments", payload, headers)

    def list_pest_treatments(self, headers, params=None):
        return self._request("GET", "/pest-treatments", headers=headers, params=params)

    def get_pest_treatment(self, treatment_id, headers):
        return self._request("GET", f"/pest-treatments/{treatment_id}", headers=headers)

    def update_pest_treatment(self, treatment_id, payload, headers):
        return self._request("PUT", f"/pest-treatments/{treatment_id}", payload, headers)

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def update_complaint(self, complaint_id, payload, headers):
        return self._request("PUT", f"/complaints/{complaint_id}", payload, headers)

    # ------------------------------------------------------------------
    # Regulatory inspections
    # ------------------------------------------------------------------
    def create_regulatory_inspection(self, payload, headers):
        return self._request("POST", "/regulatory-inspections", payload, headers)

    def list_regulatory_inspections(self, headers, params=None):
        return self._request("GET", "/regulatory-inspections",
                             headers=headers, params=params)

    def get_regulatory_inspection(self, inspection_id, headers):
        return self._request("GET", f"/regulatory-inspections/{inspection_id}",
                             headers=headers)

    def update_regulatory_inspection(self, inspection_id, payload, headers):
        return self._request("PUT", f"/regulatory-inspections/{inspection_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Service referrals
    # ------------------------------------------------------------------
    def create_service_referral(self, payload, headers):
        return self._request("POST", "/service-referrals", payload, headers)

    def list_service_referrals(self, headers, params=None):
        return self._request("GET", "/service-referrals", headers=headers, params=params)

    def get_service_referral(self, referral_id, headers):
        return self._request("GET", f"/service-referrals/{referral_id}", headers=headers)

    def update_service_referral(self, referral_id, payload, headers):
        return self._request("PUT", f"/service-referrals/{referral_id}", payload, headers)


api_client = ApiClient()
