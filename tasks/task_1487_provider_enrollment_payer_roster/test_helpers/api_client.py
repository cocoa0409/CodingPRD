"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under /api (PRD §2).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- practice groups & providers ---
    def create_practice_group(self, payload, headers):
        return self._request("POST", "/api/practice-groups", payload, headers)

    def get_practice_group(self, group_id, headers):
        return self._request("GET", f"/api/practice-groups/{group_id}", headers=headers)

    def create_provider(self, group_id, payload, headers):
        return self._request(
            "POST", f"/api/practice-groups/{group_id}/providers", payload, headers
        )

    def list_group_providers(self, group_id, headers, params=None):
        return self._request(
            "GET", f"/api/practice-groups/{group_id}/providers",
            headers=headers, params=params,
        )

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/api/providers/{provider_id}", headers=headers)

    def terminate_provider(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/api/providers/{provider_id}/terminate", payload, headers
        )

    def get_provider_caqh_profile(self, provider_id, headers):
        return self._request(
            "GET", f"/api/providers/{provider_id}/caqh-profile", headers=headers
        )

    def list_provider_roster_lines(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/api/providers/{provider_id}/roster-lines",
            headers=headers, params=params,
        )

    # --- payers ---
    def create_payer(self, payload, headers):
        return self._request("POST", "/api/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/api/payers/{payer_id}", headers=headers)

    # --- CAQH ---
    def attest_caqh_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/api/caqh-profiles/{profile_id}/attest", headers=headers
        )

    # --- enrollment applications ---
    def create_enrollment_application(self, payload, headers):
        return self._request("POST", "/api/enrollment-applications", payload, headers)

    def get_enrollment_application(self, application_id, headers):
        return self._request(
            "GET", f"/api/enrollment-applications/{application_id}", headers=headers
        )

    def list_enrollment_applications(self, headers, params=None):
        return self._request(
            "GET", "/api/enrollment-applications", headers=headers, params=params
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/enrollment-applications/{application_id}/submit",
            headers=headers,
        )

    def request_info_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/api/enrollment-applications/{application_id}/request-info",
            payload, headers,
        )

    def resubmit_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/enrollment-applications/{application_id}/resubmit",
            headers=headers,
        )

    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/enrollment-applications/{application_id}/approve",
            headers=headers,
        )

    def reject_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/api/enrollment-applications/{application_id}/reject",
            payload, headers,
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/enrollment-applications/{application_id}/withdraw",
            headers=headers,
        )

    # --- enrollment records ---
    def get_enrollment_record(self, record_id, headers):
        return self._request(
            "GET", f"/api/enrollment-records/{record_id}", headers=headers
        )

    def list_enrollment_records(self, headers, params=None):
        return self._request(
            "GET", "/api/enrollment-records", headers=headers, params=params
        )

    def terminate_enrollment_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/api/enrollment-records/{record_id}/terminate",
            payload, headers,
        )

    def revalidate_enrollment_record(self, record_id, headers):
        return self._request(
            "POST", f"/api/enrollment-records/{record_id}/revalidate", headers=headers
        )

    # --- delegation agreements ---
    def create_delegation_agreement(self, payload, headers):
        return self._request("POST", "/api/delegation-agreements", payload, headers)

    def get_delegation_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/api/delegation-agreements/{agreement_id}", headers=headers
        )

    def list_delegation_agreements(self, headers, params=None):
        return self._request(
            "GET", "/api/delegation-agreements", headers=headers, params=params
        )

    def terminate_delegation_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/api/delegation-agreements/{agreement_id}/terminate",
            headers=headers,
        )

    # --- roster files & lines ---
    def create_roster_file(self, payload, headers):
        return self._request("POST", "/api/roster-files", payload, headers)

    def get_roster_file(self, roster_file_id, headers):
        return self._request("GET", f"/api/roster-files/{roster_file_id}", headers=headers)

    def list_roster_files(self, headers, params=None):
        return self._request("GET", "/api/roster-files", headers=headers, params=params)

    def list_roster_lines(self, roster_file_id, headers, params=None):
        return self._request(
            "GET", f"/api/roster-files/{roster_file_id}/lines",
            headers=headers, params=params,
        )

    def confirm_roster_line(self, roster_file_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"/api/roster-files/{roster_file_id}/lines/{line_id}/confirm",
            payload, headers,
        )

    def reject_roster_line(self, roster_file_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"/api/roster-files/{roster_file_id}/lines/{line_id}/reject",
            payload, headers,
        )

    def resolve_roster_line(self, roster_file_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"/api/roster-files/{roster_file_id}/lines/{line_id}/resolve",
            payload, headers,
        )

    def reconcile_roster_file(self, roster_file_id, headers):
        return self._request(
            "POST", f"/api/roster-files/{roster_file_id}/reconcile", headers=headers
        )

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def reverse_recoupment(self, claim_id, headers):
        return self._request(
            "POST", f"/api/claims/{claim_id}/reverse-recoupment", headers=headers
        )

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
