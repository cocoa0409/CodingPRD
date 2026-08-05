"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- StaffUser ----
    def create_staff_user(self, payload, headers):
        return self._request("POST", "/staff-users", payload, headers)

    def get_staff_user(self, staff_user_id, headers):
        return self._request("GET", f"/staff-users/{staff_user_id}", headers=headers)

    def transition_staff_user(self, staff_user_id, action, headers):
        return self._request(
            "POST", f"/staff-users/{staff_user_id}/transition", {"action": action}, headers
        )

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    # ---- JobOpening ----
    def create_job_opening(self, payload, headers):
        return self._request("POST", "/job-openings", payload, headers)

    def get_job_opening(self, opening_id, headers):
        return self._request("GET", f"/job-openings/{opening_id}", headers=headers)

    def list_job_openings(self, headers, params=None):
        return self._request("GET", "/job-openings", headers=headers, params=params)

    def transition_job_opening(self, opening_id, action, headers):
        return self._request(
            "POST", f"/job-openings/{opening_id}/transition", {"action": action}, headers
        )

    # ---- Candidate ----
    def create_candidate(self, payload, headers):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/candidates", headers=headers, params=params)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def advance_application(self, application_id, action, headers):
        return self._request(
            "POST", f"/applications/{application_id}/advance", {"action": action}, headers
        )

    # ---- SiteVisit ----
    def create_site_visit(self, payload, headers):
        return self._request("POST", "/site-visits", payload, headers)

    def get_site_visit(self, site_visit_id, headers):
        return self._request("GET", f"/site-visits/{site_visit_id}", headers=headers)

    def list_site_visits(self, headers, params=None):
        return self._request("GET", "/site-visits", headers=headers, params=params)

    def transition_site_visit(self, site_visit_id, action, headers):
        return self._request(
            "POST", f"/site-visits/{site_visit_id}/transition", {"action": action}, headers
        )

    # ---- Offer ----
    def create_offer(self, payload, headers):
        return self._request("POST", "/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def transition_offer(self, offer_id, action, headers):
        return self._request(
            "POST", f"/offers/{offer_id}/transition", {"action": action}, headers
        )

    def revise_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/revise", payload, headers)

    # ---- Placement ----
    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def transition_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/transition", payload, headers
        )

    def create_relocation_expense(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/relocation-expenses", payload, headers
        )

    def list_relocation_expenses(self, placement_id, headers, params=None):
        return self._request(
            "GET", f"/placements/{placement_id}/relocation-expenses",
            headers=headers, params=params,
        )

    # ---- CredentialingFile / CredentialItem ----
    def get_credentialing_file(self, credentialing_file_id, headers):
        return self._request(
            "GET", f"/credentialing-files/{credentialing_file_id}", headers=headers
        )

    def list_credentialing_files(self, headers, params=None):
        return self._request("GET", "/credentialing-files", headers=headers, params=params)

    def create_credential_item(self, credentialing_file_id, payload, headers):
        return self._request(
            "POST", f"/credentialing-files/{credentialing_file_id}/items", payload, headers
        )

    def list_credential_items(self, credentialing_file_id, headers, params=None):
        return self._request(
            "GET", f"/credentialing-files/{credentialing_file_id}/items",
            headers=headers, params=params,
        )

    def transition_credential_item(self, credential_item_id, action, headers):
        return self._request(
            "POST", f"/credential-items/{credential_item_id}/transition",
            {"action": action}, headers,
        )

    # ---- GuaranteeClaim ----
    def create_guarantee_claim(self, payload, headers):
        return self._request("POST", "/guarantee-claims", payload, headers)

    def get_guarantee_claim(self, guarantee_claim_id, headers):
        return self._request(
            "GET", f"/guarantee-claims/{guarantee_claim_id}", headers=headers
        )

    def list_guarantee_claims(self, headers, params=None):
        return self._request("GET", "/guarantee-claims", headers=headers, params=params)

    def transition_guarantee_claim(self, guarantee_claim_id, payload, headers):
        return self._request(
            "POST", f"/guarantee-claims/{guarantee_claim_id}/transition", payload, headers
        )


api_client = ApiClient()
