"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- actors / config ----
    def create_landlord(self, payload, headers):
        return self._request("POST", "/rent-board/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/rent-board/landlords/{landlord_id}", headers=headers)

    def create_tenant(self, payload, headers):
        return self._request("POST", "/rent-board/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/rent-board/tenants/{tenant_id}", headers=headers)

    def create_hearing_officer(self, payload, headers):
        return self._request("POST", "/rent-board/hearing-officers", payload, headers)

    def get_hearing_officer(self, officer_id, headers):
        return self._request("GET", f"/rent-board/hearing-officers/{officer_id}", headers=headers)

    def create_aga_determination(self, payload, headers):
        return self._request("POST", "/rent-board/aga-determinations", payload, headers)

    def list_aga_determinations(self, headers, params=None):
        return self._request("GET", "/rent-board/aga-determinations", headers=headers, params=params)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- units ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/rent-board/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/rent-board/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/rent-board/units", headers=headers, params=params)

    def create_registration(self, unit_id, payload, headers):
        return self._request("POST", f"/rent-board/units/{unit_id}/registrations", payload, headers)

    def list_registrations(self, unit_id, headers, params=None):
        return self._request("GET", f"/rent-board/units/{unit_id}/registrations", headers=headers, params=params)

    def create_rent_adjustment(self, unit_id, payload, headers):
        return self._request("POST", f"/rent-board/units/{unit_id}/rent-adjustments", payload, headers)

    def list_unit_exemptions(self, unit_id, headers, params=None):
        return self._request("GET", f"/rent-board/units/{unit_id}/exemptions", headers=headers, params=params)

    # ---- tenancies ----
    def create_tenancy(self, payload, headers):
        return self._request("POST", "/rent-board/tenancies", payload, headers)

    def get_tenancy(self, tenancy_id, headers):
        return self._request("GET", f"/rent-board/tenancies/{tenancy_id}", headers=headers)

    def list_tenancies(self, headers, params=None):
        return self._request("GET", "/rent-board/tenancies", headers=headers, params=params)

    def end_tenancy(self, tenancy_id, payload, headers):
        return self._request("POST", f"/rent-board/tenancies/{tenancy_id}/end", payload, headers)

    # ---- petitions ----
    def create_petition(self, payload, headers):
        return self._request("POST", "/rent-board/petitions", payload, headers)

    def submit_petition(self, petition_id, headers, payload=None):
        return self._request("POST", f"/rent-board/petitions/{petition_id}/submit", payload or {}, headers)

    def review_petition(self, petition_id, headers, payload=None):
        return self._request("POST", f"/rent-board/petitions/{petition_id}/review", payload or {}, headers)

    def request_revision_petition(self, petition_id, headers, payload=None):
        return self._request("POST", f"/rent-board/petitions/{petition_id}/request-revision", payload or {}, headers)

    def schedule_hearing(self, petition_id, payload, headers):
        return self._request("POST", f"/rent-board/petitions/{petition_id}/hearings", payload, headers)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/rent-board/petitions/{petition_id}", headers=headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/rent-board/petitions", headers=headers, params=params)

    # ---- hearings ----
    def decide_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/rent-board/hearings/{hearing_id}/decide", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/rent-board/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/rent-board/hearings", headers=headers, params=params)

    # ---- service claims ----
    def create_service_claim(self, payload, headers):
        return self._request("POST", "/rent-board/service-claims", payload, headers)

    def investigate_service_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/rent-board/service-claims/{claim_id}/investigate", payload or {}, headers)

    def decide_service_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/rent-board/service-claims/{claim_id}/decide", payload, headers)

    def restore_service_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/rent-board/service-claims/{claim_id}/restore", payload or {}, headers)

    def get_service_claim(self, claim_id, headers):
        return self._request("GET", f"/rent-board/service-claims/{claim_id}", headers=headers)

    def list_service_claims(self, headers, params=None):
        return self._request("GET", "/rent-board/service-claims", headers=headers, params=params)

    # ---- buyouts ----
    def create_buyout(self, payload, headers):
        return self._request("POST", "/rent-board/buyouts", payload, headers)

    def file_buyout(self, buyout_id, payload, headers):
        return self._request("POST", f"/rent-board/buyouts/{buyout_id}/file", payload, headers)

    def rescind_buyout(self, buyout_id, headers, payload=None):
        return self._request("POST", f"/rent-board/buyouts/{buyout_id}/rescind", payload or {}, headers)

    def complete_buyout(self, buyout_id, headers, payload=None):
        return self._request("POST", f"/rent-board/buyouts/{buyout_id}/complete", payload or {}, headers)

    def get_buyout(self, buyout_id, headers):
        return self._request("GET", f"/rent-board/buyouts/{buyout_id}", headers=headers)

    def list_buyouts(self, headers, params=None):
        return self._request("GET", "/rent-board/buyouts", headers=headers, params=params)

    # ---- exemptions ----
    def create_exemption(self, payload, headers):
        return self._request("POST", "/rent-board/exemptions", payload, headers)

    def decide_exemption(self, exemption_id, payload, headers):
        return self._request("POST", f"/rent-board/exemptions/{exemption_id}/decide", payload, headers)

    # ---- penalties ----
    def create_penalty(self, payload, headers):
        return self._request("POST", "/rent-board/penalties", payload, headers)

    def confirm_penalty(self, penalty_id, headers, payload=None):
        return self._request("POST", f"/rent-board/penalties/{penalty_id}/confirm", payload or {}, headers)

    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"/rent-board/penalties/{penalty_id}", headers=headers)

    def list_penalties(self, headers, params=None):
        return self._request("GET", "/rent-board/penalties", headers=headers, params=params)


api_client = ApiClient()
