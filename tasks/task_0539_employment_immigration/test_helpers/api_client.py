"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Employer ----
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    # ---- PrevailingWageDetermination ----
    def create_pwd(self, payload, headers):
        return self._request("POST", "/prevailing-wage-determinations", payload, headers)

    def get_pwd(self, pwd_id, headers):
        return self._request("GET", f"/prevailing-wage-determinations/{pwd_id}", headers=headers)

    def list_pwds(self, headers, params=None):
        return self._request("GET", "/prevailing-wage-determinations", headers=headers, params=params)

    def transition_pwd(self, pwd_id, payload, headers):
        return self._request("POST", f"/prevailing-wage-determinations/{pwd_id}/transitions", payload, headers)

    # ---- PermCase ----
    def create_perm_case(self, payload, headers):
        return self._request("POST", "/perm-cases", payload, headers)

    def get_perm_case(self, perm_case_id, headers):
        return self._request("GET", f"/perm-cases/{perm_case_id}", headers=headers)

    def list_perm_cases(self, headers, params=None):
        return self._request("GET", "/perm-cases", headers=headers, params=params)

    def transition_perm_case(self, perm_case_id, payload, headers):
        return self._request("POST", f"/perm-cases/{perm_case_id}/transitions", payload, headers)

    # ---- RecruitmentStep ----
    def create_recruitment_step(self, payload, headers):
        return self._request("POST", "/recruitment-steps", payload, headers)

    def get_recruitment_step(self, step_id, headers):
        return self._request("GET", f"/recruitment-steps/{step_id}", headers=headers)

    def list_recruitment_steps(self, headers, params=None):
        return self._request("GET", "/recruitment-steps", headers=headers, params=params)

    # ---- LCA ----
    def create_lca(self, payload, headers):
        return self._request("POST", "/lcas", payload, headers)

    def get_lca(self, lca_id, headers):
        return self._request("GET", f"/lcas/{lca_id}", headers=headers)

    def list_lcas(self, headers, params=None):
        return self._request("GET", "/lcas", headers=headers, params=params)

    def patch_lca(self, lca_id, payload, headers):
        return self._request("PATCH", f"/lcas/{lca_id}", payload, headers)

    def transition_lca(self, lca_id, payload, headers):
        return self._request("POST", f"/lcas/{lca_id}/transitions", payload, headers)

    def audit_paf(self, lca_id, headers):
        return self._request("POST", f"/lcas/{lca_id}/audit-paf", {}, headers)

    # ---- Beneficiary ----
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}", headers=headers)

    # ---- CapProgram ----
    def create_cap_program(self, payload, headers):
        return self._request("POST", "/cap-programs", payload, headers)

    def get_cap_program(self, cap_id, headers):
        return self._request("GET", f"/cap-programs/{cap_id}", headers=headers)

    def run_lottery(self, cap_id, headers):
        return self._request("POST", f"/cap-programs/{cap_id}/run-lottery", {}, headers)

    # ---- H1BRegistration ----
    def create_registration(self, payload, headers):
        return self._request("POST", "/h1b-registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/h1b-registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/h1b-registrations", headers=headers, params=params)

    def transition_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/h1b-registrations/{registration_id}/transitions", payload, headers)

    # ---- H1BPetition ----
    def create_h1b_petition(self, payload, headers):
        return self._request("POST", "/h1b-petitions", payload, headers)

    def get_h1b_petition(self, petition_id, headers):
        return self._request("GET", f"/h1b-petitions/{petition_id}", headers=headers)

    def list_h1b_petitions(self, headers, params=None):
        return self._request("GET", "/h1b-petitions", headers=headers, params=params)

    def transition_h1b_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/h1b-petitions/{petition_id}/transitions", payload, headers)

    # ---- I140Petition ----
    def create_i140_petition(self, payload, headers):
        return self._request("POST", "/i140-petitions", payload, headers)

    def get_i140_petition(self, petition_id, headers):
        return self._request("GET", f"/i140-petitions/{petition_id}", headers=headers)

    def list_i140_petitions(self, headers, params=None):
        return self._request("GET", "/i140-petitions", headers=headers, params=params)

    def transition_i140_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/i140-petitions/{petition_id}/transitions", payload, headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
