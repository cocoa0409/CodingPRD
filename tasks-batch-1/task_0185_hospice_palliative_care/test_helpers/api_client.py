"""API client: one method per endpoint defined in the hospice & palliative care PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Provider -------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/hospice/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/hospice/providers/{provider_id}", headers=headers)

    def get_cap_summary(self, provider_id, headers):
        return self._request("GET", f"/hospice/providers/{provider_id}/cap-summary", headers=headers)

    def settle_cap(self, provider_id, headers):
        return self._request("POST", f"/hospice/providers/{provider_id}/settle-cap", {}, headers)

    def list_provider_elections(self, provider_id, headers, params=None):
        return self._request("GET", f"/hospice/providers/{provider_id}/elections", headers=headers, params=params)

    # ---- Physician ------------------------------------------------------
    def create_physician(self, payload, headers):
        return self._request("POST", "/hospice/physicians", payload, headers)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/hospice/physicians/{physician_id}", headers=headers)

    # ---- Election -------------------------------------------------------
    def create_election(self, payload, headers):
        return self._request("POST", "/hospice/elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/hospice/elections/{election_id}", headers=headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/hospice/elections", headers=headers, params=params)

    def revoke_election(self, election_id, payload, headers):
        return self._request("POST", f"/hospice/elections/{election_id}/revoke", payload, headers)

    def discharge_election(self, election_id, payload, headers):
        return self._request("POST", f"/hospice/elections/{election_id}/discharge", payload, headers)

    # ---- BenefitPeriod --------------------------------------------------
    def list_election_benefit_periods(self, election_id, headers, params=None):
        return self._request("GET", f"/hospice/elections/{election_id}/benefit-periods", headers=headers, params=params)

    def get_benefit_period(self, period_id, headers):
        return self._request("GET", f"/hospice/benefit-periods/{period_id}", headers=headers)

    def list_benefit_periods(self, headers, params=None):
        return self._request("GET", "/hospice/benefit-periods", headers=headers, params=params)

    # ---- Certification --------------------------------------------------
    def create_certification(self, payload, headers):
        return self._request("POST", "/hospice/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/hospice/certifications/{certification_id}", headers=headers)

    def list_election_certifications(self, election_id, headers, params=None):
        return self._request("GET", f"/hospice/elections/{election_id}/certifications", headers=headers, params=params)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/hospice/certifications", headers=headers, params=params)

    # ---- CarePlan -------------------------------------------------------
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/hospice/care-plans", payload, headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/hospice/care-plans/{care_plan_id}", headers=headers)

    def list_election_care_plans(self, election_id, headers, params=None):
        return self._request("GET", f"/hospice/elections/{election_id}/care-plans", headers=headers, params=params)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/hospice/care-plans", headers=headers, params=params)

    # ---- CareDay --------------------------------------------------------
    def create_care_day(self, payload, headers):
        return self._request("POST", "/hospice/care-days", payload, headers)

    def get_care_day(self, care_day_id, headers):
        return self._request("GET", f"/hospice/care-days/{care_day_id}", headers=headers)

    def list_election_care_days(self, election_id, headers, params=None):
        return self._request("GET", f"/hospice/elections/{election_id}/care-days", headers=headers, params=params)

    def list_care_days(self, headers, params=None):
        return self._request("GET", "/hospice/care-days", headers=headers, params=params)

    # ---- CoverageItem ---------------------------------------------------
    def create_coverage_item(self, payload, headers):
        return self._request("POST", "/hospice/coverage-items", payload, headers)

    def get_coverage_item(self, coverage_item_id, headers):
        return self._request("GET", f"/hospice/coverage-items/{coverage_item_id}", headers=headers)

    def list_election_coverage_items(self, election_id, headers, params=None):
        return self._request("GET", f"/hospice/elections/{election_id}/coverage-items", headers=headers, params=params)

    def list_care_plan_coverage_items(self, care_plan_id, headers, params=None):
        return self._request("GET", f"/hospice/care-plans/{care_plan_id}/coverage-items", headers=headers, params=params)

    # ---- BereavementCase ------------------------------------------------
    def create_bereavement_case(self, payload, headers):
        return self._request("POST", "/hospice/bereavement-cases", payload, headers)

    def get_bereavement_case(self, bereavement_id, headers):
        return self._request("GET", f"/hospice/bereavement-cases/{bereavement_id}", headers=headers)

    def close_bereavement_case(self, bereavement_id, headers):
        return self._request("POST", f"/hospice/bereavement-cases/{bereavement_id}/close", {}, headers)

    def list_election_bereavement_cases(self, election_id, headers, params=None):
        return self._request("GET", f"/hospice/elections/{election_id}/bereavement-cases", headers=headers, params=params)

    # ---- Test-driving clock ---------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
