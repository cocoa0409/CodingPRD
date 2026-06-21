"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Organizations + clock ----
    def create_org(self, payload, headers):
        return self._request("POST", "/credentialing-orgs", payload, headers)

    def get_org(self, org_id, headers):
        return self._request("GET", f"/credentialing-orgs/{org_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Payers ----
    def create_payer(self, payload, headers):
        return self._request("POST", "/payers", payload, headers)

    def list_payers(self, headers, params=None):
        return self._request("GET", "/payers", headers=headers, params=params)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    # ---- Sanctions sources ----
    def create_sanctions_source(self, payload, headers):
        return self._request("POST", "/sanctions-sources", payload, headers)

    def list_sanctions_sources(self, headers, params=None):
        return self._request("GET", "/sanctions-sources", headers=headers, params=params)

    def get_sanctions_source(self, source_id, headers):
        return self._request("GET", f"/sanctions-sources/{source_id}", headers=headers)

    # ---- Providers ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def submit_application(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/submit-application", {}, headers)

    def begin_verification(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/begin-verification", {}, headers)

    def finalize_verification(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/finalize-verification", {}, headers)

    def start_recredentialing(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/start-recredentialing", {}, headers)

    # ---- Credential items ----
    def create_credential_item(self, provider_id, payload, headers):
        return self._request("POST", f"/providers/{provider_id}/credential-items", payload, headers)

    def list_credential_items(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/credential-items", headers=headers, params=params)

    def get_credential_item(self, item_id, headers):
        return self._request("GET", f"/credential-items/{item_id}", headers=headers)

    def reverify_credential_item(self, item_id, headers):
        return self._request("POST", f"/credential-items/{item_id}/reverify", {}, headers)

    # ---- Verification requests ----
    def create_verification_request(self, item_id, payload, headers):
        return self._request("POST", f"/credential-items/{item_id}/verification-requests", payload, headers)

    def list_item_verification_requests(self, item_id, headers, params=None):
        return self._request("GET", f"/credential-items/{item_id}/verification-requests", headers=headers, params=params)

    def list_verification_requests(self, headers, params=None):
        return self._request("GET", "/verification-requests", headers=headers, params=params)

    def get_verification_request(self, vr_id, headers):
        return self._request("GET", f"/verification-requests/{vr_id}", headers=headers)

    def complete_verification_request(self, vr_id, payload, headers):
        return self._request("POST", f"/verification-requests/{vr_id}/complete", payload, headers)

    # ---- Sanctions screenings ----
    def create_sanctions_screening(self, provider_id, payload, headers):
        return self._request("POST", f"/providers/{provider_id}/sanctions-screenings", payload, headers)

    def list_provider_sanctions_screenings(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/sanctions-screenings", headers=headers, params=params)

    def list_sanctions_screenings(self, headers, params=None):
        return self._request("GET", "/sanctions-screenings", headers=headers, params=params)

    def get_sanctions_screening(self, screening_id, headers):
        return self._request("GET", f"/sanctions-screenings/{screening_id}", headers=headers)

    def resolve_sanctions_screening(self, screening_id, payload, headers):
        return self._request("POST", f"/sanctions-screenings/{screening_id}/resolve", payload, headers)

    # ---- Peer reviewers ----
    def create_peer_reviewer(self, payload, headers):
        return self._request("POST", "/peer-reviewers", payload, headers)

    def list_peer_reviewers(self, headers, params=None):
        return self._request("GET", "/peer-reviewers", headers=headers, params=params)

    def get_peer_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/peer-reviewers/{reviewer_id}", headers=headers)

    # ---- Credentialing files ----
    def create_credentialing_file(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/credentialing-files", {}, headers)

    def list_provider_credentialing_files(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/credentialing-files", headers=headers, params=params)

    def get_credentialing_file(self, file_id, headers):
        return self._request("GET", f"/credentialing-files/{file_id}", headers=headers)

    def open_review(self, file_id, headers):
        return self._request("POST", f"/credentialing-files/{file_id}/open-review", {}, headers)

    def cast_vote(self, file_id, payload, headers):
        return self._request("POST", f"/credentialing-files/{file_id}/cast-vote", payload, headers)

    def list_file_votes(self, file_id, headers, params=None):
        return self._request("GET", f"/credentialing-files/{file_id}/votes", headers=headers, params=params)

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"/votes/{vote_id}", headers=headers)

    def list_votes(self, headers, params=None):
        return self._request("GET", "/votes", headers=headers, params=params)

    def finalize_file(self, file_id, payload, headers):
        return self._request("POST", f"/credentialing-files/{file_id}/finalize", payload, headers)

    # ---- Payer enrollments ----
    def create_payer_enrollment(self, provider_id, payload, headers):
        return self._request("POST", f"/providers/{provider_id}/payer-enrollments", payload, headers)

    def list_provider_enrollments(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/payer-enrollments", headers=headers, params=params)

    def list_payer_enrollments(self, headers, params=None):
        return self._request("GET", "/payer-enrollments", headers=headers, params=params)

    def get_payer_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/payer-enrollments/{enrollment_id}", headers=headers)

    def submit_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/payer-enrollments/{enrollment_id}/submit", {}, headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/payer-enrollments/{enrollment_id}/activate", {}, headers)

    def terminate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/payer-enrollments/{enrollment_id}/terminate", payload, headers)


api_client = ApiClient()
