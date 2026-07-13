"""API client: one method per PHA endpoint. Subclasses the framework client."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Applicants & household ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/pha/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/pha/applicants/{applicant_id}", headers=headers)

    def add_member(self, applicant_id, payload, headers):
        return self._request("POST", f"/pha/applicants/{applicant_id}/members", payload, headers)

    def list_members(self, applicant_id, headers, params=None):
        return self._request("GET", f"/pha/applicants/{applicant_id}/members", headers=headers, params=params)

    def create_preference_claim(self, applicant_id, payload, headers):
        return self._request("POST", f"/pha/applicants/{applicant_id}/preference-claims", payload, headers)

    def list_preference_claims(self, applicant_id, headers, params=None):
        return self._request("GET", f"/pha/applicants/{applicant_id}/preference-claims", headers=headers, params=params)

    def verify_preference_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/pha/preference-claims/{claim_id}/verify", payload, headers)

    def revoke_preference_claim(self, claim_id, headers):
        return self._request("POST", f"/pha/preference-claims/{claim_id}/revoke", {}, headers)

    def list_applicant_waitlist_entries(self, applicant_id, headers, params=None):
        return self._request("GET", f"/pha/applicants/{applicant_id}/waitlist-entries", headers=headers, params=params)

    # ---- Waitlists ----
    def create_waitlist(self, payload, headers):
        return self._request("POST", "/pha/waitlists", payload, headers)

    def get_waitlist(self, waitlist_id, headers):
        return self._request("GET", f"/pha/waitlists/{waitlist_id}", headers=headers)

    def create_entry(self, waitlist_id, payload, headers):
        return self._request("POST", f"/pha/waitlists/{waitlist_id}/entries", payload, headers)

    def list_entries(self, waitlist_id, headers, params=None):
        return self._request("GET", f"/pha/waitlists/{waitlist_id}/entries", headers=headers, params=params)

    def lottery_draw(self, waitlist_id, headers):
        return self._request("POST", f"/pha/waitlists/{waitlist_id}/lottery-draw", {}, headers)

    def purge_waitlist(self, waitlist_id, headers):
        return self._request("POST", f"/pha/waitlists/{waitlist_id}/purge", {}, headers)

    # ---- Units ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/pha/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/pha/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/pha/units", headers=headers, params=params)

    # ---- Offers ----
    def create_offer(self, payload, headers):
        return self._request("POST", "/pha/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/pha/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/pha/offers", headers=headers, params=params)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/pha/offers/{offer_id}/accept", {}, headers)

    def refuse_offer(self, offer_id, headers):
        return self._request("POST", f"/pha/offers/{offer_id}/refuse", {}, headers)

    # ---- Tenancies ----
    def get_tenancy(self, tenancy_id, headers):
        return self._request("GET", f"/pha/tenancies/{tenancy_id}", headers=headers)

    def list_tenancies(self, headers, params=None):
        return self._request("GET", "/pha/tenancies", headers=headers, params=params)

    # ---- Certifications ----
    def create_certification(self, tenancy_id, payload, headers):
        return self._request("POST", f"/pha/tenancies/{tenancy_id}/certifications", payload, headers)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/pha/certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/pha/certifications", headers=headers, params=params)

    def finalize_certification(self, cert_id, headers):
        return self._request("POST", f"/pha/certifications/{cert_id}/finalize", {}, headers)

    def hud_submit(self, cert_id, headers):
        return self._request("POST", f"/pha/certifications/{cert_id}/hud-submit", {}, headers)

    def hud_result(self, cert_id, payload, headers):
        return self._request("POST", f"/pha/certifications/{cert_id}/hud-result", payload, headers)

    # ---- Interim changes ----
    def create_interim_change(self, tenancy_id, payload, headers):
        return self._request("POST", f"/pha/tenancies/{tenancy_id}/interim-changes", payload, headers)

    def list_interim_changes(self, tenancy_id, headers, params=None):
        return self._request("GET", f"/pha/tenancies/{tenancy_id}/interim-changes", headers=headers, params=params)

    def process_interim_change(self, interim_change_id, payload, headers):
        return self._request("POST", f"/pha/interim-changes/{interim_change_id}/process", payload, headers)

    # ---- Grievances / eviction ----
    def create_grievance(self, tenancy_id, payload, headers):
        return self._request("POST", f"/pha/tenancies/{tenancy_id}/grievances", payload, headers)

    def list_grievances(self, tenancy_id, headers, params=None):
        return self._request("GET", f"/pha/tenancies/{tenancy_id}/grievances", headers=headers, params=params)

    def decide_grievance(self, grievance_id, payload, headers):
        return self._request("POST", f"/pha/grievances/{grievance_id}/decide", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/pha/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
