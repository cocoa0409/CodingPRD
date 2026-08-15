"""API client: one method per endpoint defined in the PRD (mounted under /septic-ops)."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/septic-ops"


def _company(cid):
    return f"{BASE}/installer-companies/{cid}"


def _customer(cid, cuid):
    return f"{_company(cid)}/customers/{cuid}"


def _site(cid, cuid, sid):
    return f"{_customer(cid, cuid)}/sites/{sid}"


def _installation(cid, cuid, sid, iid):
    return f"{_site(cid, cuid, sid)}/installations/{iid}"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Installer companies
    # ------------------------------------------------------------------
    def create_installer_company(self, payload, headers):
        return self._request("POST", f"{BASE}/installer-companies", payload, headers)

    def list_installer_companies(self, headers, params=None):
        return self._request("GET", f"{BASE}/installer-companies", headers=headers, params=params)

    def get_installer_company(self, cid, headers):
        return self._request("GET", f"{_company(cid)}", headers=headers)

    # ------------------------------------------------------------------
    # Staff registries
    # ------------------------------------------------------------------
    def create_soil_scientist(self, cid, payload, headers):
        return self._request("POST", f"{_company(cid)}/soil-scientists", payload, headers)

    def list_soil_scientists(self, cid, headers, params=None):
        return self._request("GET", f"{_company(cid)}/soil-scientists", headers=headers, params=params)

    def get_soil_scientist(self, cid, ssid, headers):
        return self._request("GET", f"{_company(cid)}/soil-scientists/{ssid}", headers=headers)

    def create_system_designer(self, cid, payload, headers):
        return self._request("POST", f"{_company(cid)}/system-designers", payload, headers)

    def list_system_designers(self, cid, headers, params=None):
        return self._request("GET", f"{_company(cid)}/system-designers", headers=headers, params=params)

    def get_system_designer(self, cid, dsid, headers):
        return self._request("GET", f"{_company(cid)}/system-designers/{dsid}", headers=headers)

    def create_inspector(self, cid, payload, headers):
        return self._request("POST", f"{_company(cid)}/inspectors", payload, headers)

    def list_inspectors(self, cid, headers, params=None):
        return self._request("GET", f"{_company(cid)}/inspectors", headers=headers, params=params)

    def get_inspector(self, cid, iid, headers):
        return self._request("GET", f"{_company(cid)}/inspectors/{iid}", headers=headers)

    def create_health_officer(self, cid, payload, headers):
        return self._request("POST", f"{_company(cid)}/health-officers", payload, headers)

    def list_health_officers(self, cid, headers, params=None):
        return self._request("GET", f"{_company(cid)}/health-officers", headers=headers, params=params)

    def get_health_officer(self, cid, hid, headers):
        return self._request("GET", f"{_company(cid)}/health-officers/{hid}", headers=headers)

    def create_project_manager(self, cid, payload, headers):
        return self._request("POST", f"{_company(cid)}/project-managers", payload, headers)

    def list_project_managers(self, cid, headers, params=None):
        return self._request("GET", f"{_company(cid)}/project-managers", headers=headers, params=params)

    def get_project_manager(self, cid, pmid, headers):
        return self._request("GET", f"{_company(cid)}/project-managers/{pmid}", headers=headers)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, cid, payload, headers):
        return self._request("POST", f"{_company(cid)}/customers", payload, headers)

    def list_customers(self, cid, headers, params=None):
        return self._request("GET", f"{_company(cid)}/customers", headers=headers, params=params)

    def get_customer(self, cid, cuid, headers):
        return self._request("GET", f"{_customer(cid, cuid)}", headers=headers)

    # ------------------------------------------------------------------
    # Sites and site lifecycle
    # ------------------------------------------------------------------
    def create_site(self, cid, cuid, payload, headers):
        return self._request("POST", f"{_customer(cid, cuid)}/sites", payload, headers)

    def list_sites(self, cid, cuid, headers, params=None):
        return self._request("GET", f"{_customer(cid, cuid)}/sites", headers=headers, params=params)

    def get_site(self, cid, cuid, sid, headers):
        return self._request("GET", f"{_site(cid, cuid, sid)}", headers=headers)

    def advance_site_clock(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/clock/advance", payload, headers)

    def freeze_site(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/freeze", payload, headers)

    def close_site(self, cid, cuid, sid, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/close", {}, headers)

    # ------------------------------------------------------------------
    # Soil evaluations
    # ------------------------------------------------------------------
    def create_soil_evaluation(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/soil-evaluations", payload, headers)

    def list_soil_evaluations(self, cid, cuid, sid, headers, params=None):
        return self._request("GET", f"{_site(cid, cuid, sid)}/soil-evaluations", headers=headers, params=params)

    def get_soil_evaluation(self, cid, cuid, sid, eid, headers):
        return self._request("GET", f"{_site(cid, cuid, sid)}/soil-evaluations/{eid}", headers=headers)

    def void_soil_evaluation(self, cid, cuid, sid, eid, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/soil-evaluations/{eid}/void", {}, headers)

    # ------------------------------------------------------------------
    # Percolation tests
    # ------------------------------------------------------------------
    def create_percolation_test(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/percolation-tests", payload, headers)

    def list_percolation_tests(self, cid, cuid, sid, headers, params=None):
        return self._request("GET", f"{_site(cid, cuid, sid)}/percolation-tests", headers=headers, params=params)

    def get_percolation_test(self, cid, cuid, sid, ptid, headers):
        return self._request("GET", f"{_site(cid, cuid, sid)}/percolation-tests/{ptid}", headers=headers)

    def void_percolation_test(self, cid, cuid, sid, ptid, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/percolation-tests/{ptid}/void", {}, headers)

    # ------------------------------------------------------------------
    # System designs
    # ------------------------------------------------------------------
    def create_design(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/designs", payload, headers)

    def list_designs(self, cid, cuid, sid, headers, params=None):
        return self._request("GET", f"{_site(cid, cuid, sid)}/designs", headers=headers, params=params)

    def get_design(self, cid, cuid, sid, did, headers):
        return self._request("GET", f"{_site(cid, cuid, sid)}/designs/{did}", headers=headers)

    def submit_design(self, cid, cuid, sid, did, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/designs/{did}/submit", {}, headers)

    def decide_design(self, cid, cuid, sid, did, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/designs/{did}/decide", payload, headers)

    def revise_design(self, cid, cuid, sid, did, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/designs/{did}/revise", payload, headers)

    def withdraw_design(self, cid, cuid, sid, did, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/designs/{did}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Permits
    # ------------------------------------------------------------------
    def create_permit(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/permits", payload, headers)

    def list_permits(self, cid, cuid, sid, headers, params=None):
        return self._request("GET", f"{_site(cid, cuid, sid)}/permits", headers=headers, params=params)

    def get_permit(self, cid, cuid, sid, pid, headers):
        return self._request("GET", f"{_site(cid, cuid, sid)}/permits/{pid}", headers=headers)

    def suspend_permit(self, cid, cuid, sid, pid, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/permits/{pid}/suspend", {}, headers)

    def reinstate_permit(self, cid, cuid, sid, pid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/permits/{pid}/reinstate", payload, headers)

    def revoke_permit(self, cid, cuid, sid, pid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/permits/{pid}/revoke", payload, headers)

    # ------------------------------------------------------------------
    # Installations
    # ------------------------------------------------------------------
    def create_installation(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/installations", payload, headers)

    def list_installations(self, cid, cuid, sid, headers, params=None):
        return self._request("GET", f"{_site(cid, cuid, sid)}/installations", headers=headers, params=params)

    def get_installation(self, cid, cuid, sid, iid, headers):
        return self._request("GET", f"{_installation(cid, cuid, sid, iid)}", headers=headers)

    def advance_installation(self, cid, cuid, sid, iid, headers):
        return self._request("POST", f"{_installation(cid, cuid, sid, iid)}/advance", {}, headers)

    def remediate_installation(self, cid, cuid, sid, iid, headers):
        return self._request("POST", f"{_installation(cid, cuid, sid, iid)}/remediate", {}, headers)

    def abandon_installation(self, cid, cuid, sid, iid, headers):
        return self._request("POST", f"{_installation(cid, cuid, sid, iid)}/abandon", {}, headers)

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def create_inspection(self, cid, cuid, sid, iid, payload, headers):
        return self._request("POST", f"{_installation(cid, cuid, sid, iid)}/inspections", payload, headers)

    def list_inspections(self, cid, cuid, sid, iid, headers, params=None):
        return self._request("GET", f"{_installation(cid, cuid, sid, iid)}/inspections", headers=headers, params=params)

    def get_inspection(self, cid, cuid, sid, iid, inspid, headers):
        return self._request("GET", f"{_installation(cid, cuid, sid, iid)}/inspections/{inspid}", headers=headers)

    def decide_inspection(self, cid, cuid, sid, iid, inspid, payload, headers):
        return self._request(
            "POST", f"{_installation(cid, cuid, sid, iid)}/inspections/{inspid}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Material verifications
    # ------------------------------------------------------------------
    def create_material_verification(self, cid, cuid, sid, iid, payload, headers):
        return self._request(
            "POST", f"{_installation(cid, cuid, sid, iid)}/material-verifications", payload, headers
        )

    def list_material_verifications(self, cid, cuid, sid, iid, headers, params=None):
        return self._request(
            "GET", f"{_installation(cid, cuid, sid, iid)}/material-verifications", headers=headers, params=params
        )

    def get_material_verification(self, cid, cuid, sid, iid, mvid, headers):
        return self._request(
            "GET", f"{_installation(cid, cuid, sid, iid)}/material-verifications/{mvid}", headers=headers
        )

    def verify_material(self, cid, cuid, sid, iid, mvid, headers):
        return self._request(
            "POST", f"{_installation(cid, cuid, sid, iid)}/material-verifications/{mvid}/verify", {}, headers
        )

    # ------------------------------------------------------------------
    # Variance requests
    # ------------------------------------------------------------------
    def create_variance_request(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/variance-requests", payload, headers)

    def list_variance_requests(self, cid, cuid, sid, headers, params=None):
        return self._request("GET", f"{_site(cid, cuid, sid)}/variance-requests", headers=headers, params=params)

    def get_variance_request(self, cid, cuid, sid, vid, headers):
        return self._request("GET", f"{_site(cid, cuid, sid)}/variance-requests/{vid}", headers=headers)

    def decide_variance_request(self, cid, cuid, sid, vid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/variance-requests/{vid}/decide", payload, headers)

    def withdraw_variance_request(self, cid, cuid, sid, vid, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/variance-requests/{vid}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Maintenance contracts and visits
    # ------------------------------------------------------------------
    def create_maintenance_contract(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/maintenance-contracts", payload, headers)

    def list_maintenance_contracts(self, cid, cuid, sid, headers, params=None):
        return self._request(
            "GET", f"{_site(cid, cuid, sid)}/maintenance-contracts", headers=headers, params=params
        )

    def get_maintenance_contract(self, cid, cuid, sid, mcid, headers):
        return self._request("GET", f"{_site(cid, cuid, sid)}/maintenance-contracts/{mcid}", headers=headers)

    def renew_maintenance_contract(self, cid, cuid, sid, mcid, payload, headers):
        return self._request(
            "POST", f"{_site(cid, cuid, sid)}/maintenance-contracts/{mcid}/renew", payload, headers
        )

    def cancel_maintenance_contract(self, cid, cuid, sid, mcid, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/maintenance-contracts/{mcid}/cancel", {}, headers)

    def record_visit(self, cid, cuid, sid, mcid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/maintenance-contracts/{mcid}/visits", payload, headers)

    def list_visits(self, cid, cuid, sid, mcid, headers, params=None):
        return self._request(
            "GET", f"{_site(cid, cuid, sid)}/maintenance-contracts/{mcid}/visits", headers=headers, params=params
        )

    def get_visit(self, cid, cuid, sid, mcid, vid, headers):
        return self._request(
            "GET", f"{_site(cid, cuid, sid)}/maintenance-contracts/{mcid}/visits/{vid}", headers=headers
        )

    # ------------------------------------------------------------------
    # Homeowner education
    # ------------------------------------------------------------------
    def deliver_education_record(self, cid, cuid, payload, headers):
        return self._request("POST", f"{_customer(cid, cuid)}/education-records", payload, headers)

    # ------------------------------------------------------------------
    # Repair cases
    # ------------------------------------------------------------------
    def create_repair_case(self, cid, cuid, sid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/repair-cases", payload, headers)

    def list_repair_cases(self, cid, cuid, sid, headers, params=None):
        return self._request("GET", f"{_site(cid, cuid, sid)}/repair-cases", headers=headers, params=params)

    def get_repair_case(self, cid, cuid, sid, rid, headers):
        return self._request("GET", f"{_site(cid, cuid, sid)}/repair-cases/{rid}", headers=headers)

    def triage_repair_case(self, cid, cuid, sid, rid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/repair-cases/{rid}/triage", payload, headers)

    def begin_remediation(self, cid, cuid, sid, rid, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/repair-cases/{rid}/begin-remediation", {}, headers)

    def resolve_repair_case(self, cid, cuid, sid, rid, payload, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/repair-cases/{rid}/resolve", payload, headers)

    def close_repair_case(self, cid, cuid, sid, rid, headers):
        return self._request("POST", f"{_site(cid, cuid, sid)}/repair-cases/{rid}/close", {}, headers)

    # ------------------------------------------------------------------
    # Flat alias read surface
    # ------------------------------------------------------------------
    def list_soil_scientists_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/soil-scientists", headers=headers, params=params)

    def get_soil_scientist_flat(self, ssid, headers):
        return self._request("GET", f"{BASE}/soil-scientists/{ssid}", headers=headers)

    def list_scientist_soil_evaluations(self, ssid, headers, params=None):
        return self._request("GET", f"{BASE}/soil-scientists/{ssid}/soil-evaluations", headers=headers, params=params)

    def list_scientist_percolation_tests(self, ssid, headers, params=None):
        return self._request("GET", f"{BASE}/soil-scientists/{ssid}/percolation-tests", headers=headers, params=params)

    def list_system_designers_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/system-designers", headers=headers, params=params)

    def get_system_designer_flat(self, dsid, headers):
        return self._request("GET", f"{BASE}/system-designers/{dsid}", headers=headers)

    def list_designer_designs(self, dsid, headers, params=None):
        return self._request("GET", f"{BASE}/system-designers/{dsid}/designs", headers=headers, params=params)

    def list_inspectors_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/inspectors", headers=headers, params=params)

    def get_inspector_flat(self, iid, headers):
        return self._request("GET", f"{BASE}/inspectors/{iid}", headers=headers)

    def list_inspector_inspections(self, iid, headers, params=None):
        return self._request("GET", f"{BASE}/inspectors/{iid}/inspections", headers=headers, params=params)

    def list_health_officers_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/health-officers", headers=headers, params=params)

    def get_health_officer_flat(self, hid, headers):
        return self._request("GET", f"{BASE}/health-officers/{hid}", headers=headers)

    def list_officer_variance_requests(self, hid, headers, params=None):
        return self._request("GET", f"{BASE}/health-officers/{hid}/variance-requests", headers=headers, params=params)

    def list_project_managers_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/project-managers", headers=headers, params=params)

    def get_project_manager_flat(self, pmid, headers):
        return self._request("GET", f"{BASE}/project-managers/{pmid}", headers=headers)

    def list_manager_material_verifications(self, pmid, headers, params=None):
        return self._request(
            "GET", f"{BASE}/project-managers/{pmid}/material-verifications", headers=headers, params=params
        )

    def list_customers_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/customers", headers=headers, params=params)

    def get_customer_flat(self, cuid, headers):
        return self._request("GET", f"{BASE}/customers/{cuid}", headers=headers)

    def list_sites_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/sites", headers=headers, params=params)

    def get_site_flat(self, sid, headers):
        return self._request("GET", f"{BASE}/sites/{sid}", headers=headers)

    def list_soil_evaluations_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/soil-evaluations", headers=headers, params=params)

    def get_soil_evaluation_flat(self, eid, headers):
        return self._request("GET", f"{BASE}/soil-evaluations/{eid}", headers=headers)

    def list_percolation_tests_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/percolation-tests", headers=headers, params=params)

    def get_percolation_test_flat(self, ptid, headers):
        return self._request("GET", f"{BASE}/percolation-tests/{ptid}", headers=headers)

    def list_designs_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/designs", headers=headers, params=params)

    def get_design_flat(self, did, headers):
        return self._request("GET", f"{BASE}/designs/{did}", headers=headers)

    def list_design_permits(self, did, headers, params=None):
        return self._request("GET", f"{BASE}/designs/{did}/permits", headers=headers, params=params)

    def list_design_variance_requests(self, did, headers, params=None):
        return self._request("GET", f"{BASE}/designs/{did}/variance-requests", headers=headers, params=params)

    def list_design_repair_cases(self, did, headers, params=None):
        return self._request("GET", f"{BASE}/designs/{did}/repair-cases", headers=headers, params=params)

    def list_permits_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/permits", headers=headers, params=params)

    def get_permit_flat(self, pid, headers):
        return self._request("GET", f"{BASE}/permits/{pid}", headers=headers)

    def list_permit_installations(self, pid, headers, params=None):
        return self._request("GET", f"{BASE}/permits/{pid}/installations", headers=headers, params=params)

    def list_installations_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/installations", headers=headers, params=params)

    def get_installation_flat(self, iid, headers):
        return self._request("GET", f"{BASE}/installations/{iid}", headers=headers)

    def list_installation_maintenance_contracts(self, iid, headers, params=None):
        return self._request(
            "GET", f"{BASE}/installations/{iid}/maintenance-contracts", headers=headers, params=params
        )

    def list_installation_repair_cases(self, iid, headers, params=None):
        return self._request("GET", f"{BASE}/installations/{iid}/repair-cases", headers=headers, params=params)

    def list_inspections_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/inspections", headers=headers, params=params)

    def get_inspection_flat(self, inspid, headers):
        return self._request("GET", f"{BASE}/inspections/{inspid}", headers=headers)

    def list_material_verifications_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/material-verifications", headers=headers, params=params)

    def get_material_verification_flat(self, mvid, headers):
        return self._request("GET", f"{BASE}/material-verifications/{mvid}", headers=headers)

    def list_variance_requests_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/variance-requests", headers=headers, params=params)

    def get_variance_request_flat(self, vid, headers):
        return self._request("GET", f"{BASE}/variance-requests/{vid}", headers=headers)

    def list_maintenance_contracts_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/maintenance-contracts", headers=headers, params=params)

    def get_maintenance_contract_flat(self, mcid, headers):
        return self._request("GET", f"{BASE}/maintenance-contracts/{mcid}", headers=headers)

    def list_contract_visits_flat(self, mcid, headers, params=None):
        return self._request("GET", f"{BASE}/maintenance-contracts/{mcid}/visits", headers=headers, params=params)

    def list_visits_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/visits", headers=headers, params=params)

    def get_visit_flat(self, vid, headers):
        return self._request("GET", f"{BASE}/visits/{vid}", headers=headers)

    def list_repair_cases_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/repair-cases", headers=headers, params=params)

    def get_repair_case_flat(self, rid, headers):
        return self._request("GET", f"{BASE}/repair-cases/{rid}", headers=headers)


api_client = ApiClient()
