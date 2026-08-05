"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Aquifer ----
    def create_aquifer(self, payload, headers):
        return self._request("POST", "/aquifers", payload, headers)

    def get_aquifer(self, aquifer_id, headers):
        return self._request("GET", f"/aquifers/{aquifer_id}", headers=headers)

    # ---- Applicant ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ---- Driller ----
    def create_driller(self, payload, headers):
        return self._request("POST", "/drillers", payload, headers)

    def get_driller(self, driller_id, headers):
        return self._request("GET", f"/drillers/{driller_id}", headers=headers)

    def suspend_driller(self, driller_id, headers):
        return self._request("POST", f"/drillers/{driller_id}/suspend", {}, headers)

    # ---- Well ----
    def create_well(self, payload, headers):
        return self._request("POST", "/wells", payload, headers)

    def get_well(self, well_id, headers):
        return self._request("GET", f"/wells/{well_id}", headers=headers)

    def list_wells(self, headers, params=None):
        return self._request("GET", "/wells", headers=headers, params=params)

    def deactivate_well(self, well_id, headers):
        return self._request("POST", f"/wells/{well_id}/deactivate", {}, headers)

    def reactivate_well(self, well_id, headers):
        return self._request("POST", f"/wells/{well_id}/reactivate", {}, headers)

    # ---- ConstructionPermit ----
    def create_construction_permit(self, payload, headers):
        return self._request("POST", "/construction-permits", payload, headers)

    def get_construction_permit(self, permit_id, headers):
        return self._request("GET", f"/construction-permits/{permit_id}", headers=headers)

    def list_construction_permits(self, headers, params=None):
        return self._request("GET", "/construction-permits", headers=headers, params=params)

    def pay_permit(self, permit_id, headers):
        return self._request("POST", f"/construction-permits/{permit_id}/pay", {}, headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/construction-permits/{permit_id}/approve", {}, headers)

    def deny_permit(self, permit_id, headers):
        return self._request("POST", f"/construction-permits/{permit_id}/deny", {}, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/construction-permits/{permit_id}/issue", {}, headers)

    # ---- DrillerLog ----
    def create_driller_log(self, payload, headers):
        return self._request("POST", "/driller-logs", payload, headers)

    def get_driller_log(self, log_id, headers):
        return self._request("GET", f"/driller-logs/{log_id}", headers=headers)

    def list_driller_logs(self, headers, params=None):
        return self._request("GET", "/driller-logs", headers=headers, params=params)

    # ---- WaterSample ----
    def create_water_sample(self, payload, headers):
        return self._request("POST", "/water-samples", payload, headers)

    def get_water_sample(self, sample_id, headers):
        return self._request("GET", f"/water-samples/{sample_id}", headers=headers)

    def list_water_samples(self, headers, params=None):
        return self._request("GET", "/water-samples", headers=headers, params=params)

    def receive_sample(self, sample_id, headers):
        return self._request("POST", f"/water-samples/{sample_id}/receive", {}, headers)

    def begin_analysis(self, sample_id, headers):
        return self._request("POST", f"/water-samples/{sample_id}/begin-analysis", {}, headers)

    def invalidate_sample(self, sample_id, headers):
        return self._request("POST", f"/water-samples/{sample_id}/invalidate", {}, headers)

    # ---- SampleResult ----
    def create_sample_result(self, payload, headers):
        return self._request("POST", "/sample-results", payload, headers)

    def get_sample_result(self, result_id, headers):
        return self._request("GET", f"/sample-results/{result_id}", headers=headers)

    def list_sample_results(self, headers, params=None):
        return self._request("GET", "/sample-results", headers=headers, params=params)

    # ---- Advisory ----
    def create_advisory(self, payload, headers):
        return self._request("POST", "/advisories", payload, headers)

    def get_advisory(self, advisory_id, headers):
        return self._request("GET", f"/advisories/{advisory_id}", headers=headers)

    def list_advisories(self, headers, params=None):
        return self._request("GET", "/advisories", headers=headers, params=params)

    def lift_advisory(self, advisory_id, headers):
        return self._request("POST", f"/advisories/{advisory_id}/lift", {}, headers)

    # ---- ContaminationCase ----
    def create_contamination_case(self, payload, headers):
        return self._request("POST", "/contamination-cases", payload, headers)

    def get_contamination_case(self, case_id, headers):
        return self._request("GET", f"/contamination-cases/{case_id}", headers=headers)

    def list_contamination_cases(self, headers, params=None):
        return self._request("GET", "/contamination-cases", headers=headers, params=params)

    def transition_case(self, case_id, payload, headers):
        return self._request("POST", f"/contamination-cases/{case_id}/transition", payload, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/contamination-cases/{case_id}/close", payload, headers)

    # ---- AbandonmentPermit ----
    def create_abandonment_permit(self, payload, headers):
        return self._request("POST", "/abandonment-permits", payload, headers)

    def get_abandonment_permit(self, permit_id, headers):
        return self._request("GET", f"/abandonment-permits/{permit_id}", headers=headers)

    def list_abandonment_permits(self, headers, params=None):
        return self._request("GET", "/abandonment-permits", headers=headers, params=params)

    def approve_abandonment(self, permit_id, headers):
        return self._request("POST", f"/abandonment-permits/{permit_id}/approve", {}, headers)

    def deny_abandonment(self, permit_id, headers):
        return self._request("POST", f"/abandonment-permits/{permit_id}/deny", {}, headers)

    def complete_abandonment(self, permit_id, headers):
        return self._request("POST", f"/abandonment-permits/{permit_id}/complete", {}, headers)

    # ---- RealEstateTestRequirement ----
    def create_real_estate_requirement(self, payload, headers):
        return self._request("POST", "/real-estate-requirements", payload, headers)

    def get_real_estate_requirement(self, req_id, headers):
        return self._request("GET", f"/real-estate-requirements/{req_id}", headers=headers)

    def list_real_estate_requirements(self, headers, params=None):
        return self._request("GET", "/real-estate-requirements", headers=headers, params=params)

    def link_sample(self, req_id, payload, headers):
        return self._request("POST", f"/real-estate-requirements/{req_id}/link-sample", payload, headers)

    def certify_requirement(self, req_id, headers):
        return self._request("POST", f"/real-estate-requirements/{req_id}/certify", {}, headers)

    def waive_requirement(self, req_id, payload, headers):
        return self._request("POST", f"/real-estate-requirements/{req_id}/waive", payload, headers)

    # ---- Clock / Ops (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def expiry_sweep(self, headers):
        return self._request("POST", "/_ops/expiry-sweep", {}, headers)


api_client = ApiClient()
