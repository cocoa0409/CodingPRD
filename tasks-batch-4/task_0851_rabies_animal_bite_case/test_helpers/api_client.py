"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Owners ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/api/v1/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/api/v1/owners/{owner_id}", headers=headers)

    # ---- Animals ----
    def create_animal(self, payload, headers):
        return self._request("POST", "/api/v1/animals", payload, headers)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/api/v1/animals/{animal_id}", headers=headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/api/v1/animals", headers=headers, params=params)

    def capture_animal(self, animal_id, headers):
        return self._request("POST", f"/api/v1/animals/{animal_id}/capture", headers=headers)

    def disposition_animal(self, animal_id, payload, headers):
        return self._request("POST", f"/api/v1/animals/{animal_id}/disposition", payload, headers)

    # ---- Bite cases ----
    def create_bite_case(self, payload, headers):
        return self._request("POST", "/api/v1/bite-cases", payload, headers)

    def get_bite_case(self, case_id, headers):
        return self._request("GET", f"/api/v1/bite-cases/{case_id}", headers=headers)

    def list_bite_cases(self, headers, params=None):
        return self._request("GET", "/api/v1/bite-cases", headers=headers, params=params)

    def close_bite_case(self, case_id, headers):
        return self._request("POST", f"/api/v1/bite-cases/{case_id}/close", headers=headers)

    # ---- Quarantine facilities ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/api/v1/quarantine-facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/api/v1/quarantine-facilities/{facility_id}", headers=headers)

    # ---- Quarantine orders ----
    def create_quarantine_order(self, case_id, payload, headers):
        return self._request("POST", f"/api/v1/bite-cases/{case_id}/quarantine-orders", payload, headers)

    def get_quarantine_order(self, order_id, headers):
        return self._request("GET", f"/api/v1/quarantine-orders/{order_id}", headers=headers)

    def list_quarantine_orders(self, headers, params=None):
        return self._request("GET", "/api/v1/quarantine-orders", headers=headers, params=params)

    def complete_quarantine_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/quarantine-orders/{order_id}/complete", payload, headers)

    def breach_quarantine_order(self, order_id, headers):
        return self._request("POST", f"/api/v1/quarantine-orders/{order_id}/breach", headers=headers)

    def convert_quarantine_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/quarantine-orders/{order_id}/convert-to-specimen", payload, headers)

    # ---- Specimens & lab results ----
    def create_specimen(self, case_id, payload, headers):
        return self._request("POST", f"/api/v1/bite-cases/{case_id}/specimens", payload, headers)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/api/v1/specimens/{specimen_id}", headers=headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/api/v1/specimens", headers=headers, params=params)

    def report_result(self, specimen_id, payload, headers):
        return self._request("POST", f"/api/v1/specimens/{specimen_id}/report-result", payload, headers)

    # ---- PEP recommendations ----
    def create_pep_recommendation(self, case_id, payload, headers):
        return self._request("POST", f"/api/v1/bite-cases/{case_id}/pep-recommendations", payload, headers)

    def list_pep_recommendations(self, case_id, headers, params=None):
        return self._request("GET", f"/api/v1/bite-cases/{case_id}/pep-recommendations", headers=headers, params=params)

    def administer_dose(self, pep_id, payload, headers):
        return self._request("POST", f"/api/v1/pep-recommendations/{pep_id}/administer-dose", payload, headers)

    def discontinue_pep(self, pep_id, headers):
        return self._request("POST", f"/api/v1/pep-recommendations/{pep_id}/discontinue", headers=headers)

    # ---- Citations ----
    def create_citation(self, payload, headers):
        return self._request("POST", "/api/v1/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/api/v1/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/api/v1/citations", headers=headers, params=params)

    def contest_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/api/v1/citations/{citation_id}/contest", payload, headers)

    def resolve_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/api/v1/citations/{citation_id}/resolve", payload, headers)

    def pay_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/api/v1/citations/{citation_id}/pay", payload, headers)

    # ---- Surveillance & wildlife ----
    def create_surveillance_region(self, payload, headers):
        return self._request("POST", "/api/v1/surveillance-regions", payload, headers)

    def get_surveillance_region(self, region_id, headers):
        return self._request("GET", f"/api/v1/surveillance-regions/{region_id}", headers=headers)

    def create_wildlife_report(self, region_id, payload, headers):
        return self._request("POST", f"/api/v1/surveillance-regions/{region_id}/wildlife-exposure-reports", payload, headers)

    def list_wildlife_reports(self, region_id, headers, params=None):
        return self._request("GET", f"/api/v1/surveillance-regions/{region_id}/wildlife-exposure-reports", headers=headers, params=params)

    # ---- Test-driving: logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
