"""API client: one method per endpoint defined in the Residential Parking
Permit Zone PRD (§4). Subclasses GenericApiClient; the base _request() handles
the envelope and transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Zone ----
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def suspend_zone(self, zone_id, headers):
        return self._request("POST", f"/zones/{zone_id}/suspend", {}, headers)

    def reactivate_zone(self, zone_id, headers):
        return self._request("POST", f"/zones/{zone_id}/reactivate", {}, headers)

    def run_expiry(self, zone_id, headers):
        return self._request("POST", f"/zones/{zone_id}/run-expiry", {}, headers)

    # ---- Household ----
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    # ---- Vehicle ----
    def create_vehicle(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ---- ProofSubmission ----
    def create_proof_submission(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/proof-submissions", payload, headers)

    def get_proof_submission(self, proof_id, headers):
        return self._request("GET", f"/proof-submissions/{proof_id}", headers=headers)

    def list_proof_submissions(self, headers, params=None):
        return self._request("GET", "/proof-submissions", headers=headers, params=params)

    def review_proof_submission(self, proof_id, payload, headers):
        return self._request("POST", f"/proof-submissions/{proof_id}/review", payload, headers)

    # ---- PermitApplication ----
    def create_permit_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers)

    def get_permit_application(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}", headers=headers)

    def list_permit_applications(self, headers, params=None):
        return self._request("GET", "/permit-applications", headers=headers, params=params)

    def review_permit_application(self, application_id, headers):
        return self._request("POST", f"/permit-applications/{application_id}/review", {}, headers)

    def approve_permit_application(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/approve", payload, headers)

    def waitlist_permit_application(self, application_id, headers):
        return self._request("POST", f"/permit-applications/{application_id}/waitlist", {}, headers)

    def deny_permit_application(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/deny", payload, headers)

    # ---- Permit ----
    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def renew_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/renew", {}, headers)

    def renew_approve_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/renew-approve", payload, headers)

    def transfer_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/transfer", payload, headers)

    def refund_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/refund", payload, headers)

    def revoke_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", payload, headers)

    # ---- VisitorPass ----
    def create_visitor_pass(self, payload, headers):
        return self._request("POST", "/visitor-passes", payload, headers)

    def get_visitor_pass(self, pass_id, headers):
        return self._request("GET", f"/visitor-passes/{pass_id}", headers=headers)

    def list_visitor_passes(self, headers, params=None):
        return self._request("GET", "/visitor-passes", headers=headers, params=params)

    def cancel_visitor_pass(self, pass_id, headers):
        return self._request("POST", f"/visitor-passes/{pass_id}/cancel", {}, headers)

    # ---- WaitlistEntry ----
    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    # ---- Citation ----
    def create_citation(self, payload, headers):
        return self._request("POST", "/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/citations", headers=headers, params=params)

    def pay_citation(self, citation_id, headers):
        return self._request("POST", f"/citations/{citation_id}/pay", {}, headers)

    def dispute_citation(self, citation_id, headers):
        return self._request("POST", f"/citations/{citation_id}/dispute", {}, headers)

    def adjudicate_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/adjudicate", payload, headers)

    # ---- Complaint ----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", payload, headers)


api_client = ApiClient()
