"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles envelope transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- LicenseBoard ----
    def create_license_board(self, payload, headers):
        return self._request("POST", "/license-boards", payload, headers)

    def get_license_board(self, board_id, headers):
        return self._request("GET", f"/license-boards/{board_id}", headers=headers)

    def create_requirement(self, board_id, payload, headers):
        return self._request(
            "POST", f"/license-boards/{board_id}/requirements", payload, headers
        )

    def list_board_requirements(self, board_id, headers, params=None):
        return self._request(
            "GET", f"/license-boards/{board_id}/requirements", headers=headers, params=params
        )

    def get_credit_requirement(self, requirement_id, headers):
        return self._request(
            "GET", f"/credit-requirements/{requirement_id}", headers=headers
        )

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def accredit_provider(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/accredit", payload, headers
        )

    def suspend_provider(self, provider_id, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/suspend", headers=headers
        )

    def reinstate_provider(self, provider_id, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/reinstate", headers=headers
        )

    def revoke_provider(self, provider_id, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/revoke", headers=headers
        )

    # ---- Course ----
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_provider_courses(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/providers/{provider_id}/courses", headers=headers, params=params
        )

    # ---- Licensee ----
    def create_licensee(self, payload, headers):
        return self._request("POST", "/licensees", payload, headers)

    def get_licensee(self, licensee_id, headers):
        return self._request("GET", f"/licensees/{licensee_id}", headers=headers)

    def list_licensees(self, headers, params=None):
        return self._request("GET", "/licensees", headers=headers, params=params)

    # ---- RenewalCycle ----
    def create_renewal_cycle(self, payload, headers):
        return self._request("POST", "/renewal-cycles", payload, headers)

    def get_renewal_cycle(self, cycle_id, headers):
        return self._request("GET", f"/renewal-cycles/{cycle_id}", headers=headers)

    def list_renewal_cycles(self, headers, params=None):
        return self._request("GET", "/renewal-cycles", headers=headers, params=params)

    def list_licensee_renewal_cycles(self, licensee_id, headers, params=None):
        return self._request(
            "GET", f"/licensees/{licensee_id}/renewal-cycles", headers=headers, params=params
        )

    def get_cycle_reminder(self, cycle_id, headers):
        return self._request(
            "GET", f"/renewal-cycles/{cycle_id}/reminder", headers=headers
        )

    def renew_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/renewal-cycles/{cycle_id}/renew", payload, headers
        )

    # ---- Completion ----
    def create_completion(self, payload, headers):
        return self._request("POST", "/completions", payload, headers)

    def get_completion(self, completion_id, headers):
        return self._request("GET", f"/completions/{completion_id}", headers=headers)

    def list_completions(self, headers, params=None):
        return self._request("GET", "/completions", headers=headers, params=params)

    def list_cycle_completions(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/renewal-cycles/{cycle_id}/completions", headers=headers, params=params
        )

    def verify_completion(self, completion_id, headers):
        return self._request(
            "POST", f"/completions/{completion_id}/verify", headers=headers
        )

    def reject_completion(self, completion_id, headers, payload=None):
        return self._request(
            "POST", f"/completions/{completion_id}/reject", payload or {}, headers
        )

    def resubmit_completion(self, completion_id, headers):
        return self._request(
            "POST", f"/completions/{completion_id}/resubmit", headers=headers
        )

    # ---- Certificate ----
    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/certificates/{certificate_id}", headers=headers
        )

    def list_cycle_certificates(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/renewal-cycles/{cycle_id}/certificate", headers=headers, params=params
        )

    # ---- Audit ----
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def list_cycle_audits(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/renewal-cycles/{cycle_id}/audits", headers=headers, params=params
        )

    def request_attestation(self, audit_id, headers):
        return self._request(
            "POST", f"/audits/{audit_id}/request-attestation", headers=headers
        )

    def submit_attestation(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/audits/{audit_id}/attestations", payload, headers
        )

    def list_audit_attestations(self, audit_id, headers, params=None):
        return self._request(
            "GET", f"/audits/{audit_id}/attestations", headers=headers, params=params
        )

    def decide_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/decide", payload, headers)

    # ---- ReciprocityGrant ----
    def create_reciprocity_grant(self, payload, headers):
        return self._request("POST", "/reciprocity-grants", payload, headers)

    def get_reciprocity_grant(self, grant_id, headers):
        return self._request(
            "GET", f"/reciprocity-grants/{grant_id}", headers=headers
        )

    def list_reciprocity_grants(self, headers, params=None):
        return self._request(
            "GET", "/reciprocity-grants", headers=headers, params=params
        )

    def list_cycle_reciprocity_grants(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/renewal-cycles/{cycle_id}/reciprocity-grants", headers=headers, params=params
        )

    def approve_reciprocity_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/reciprocity-grants/{grant_id}/approve", headers=headers
        )

    def deny_reciprocity_grant(self, grant_id, headers, payload=None):
        return self._request(
            "POST", f"/reciprocity-grants/{grant_id}/deny", payload or {}, headers
        )

    def revoke_reciprocity_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/reciprocity-grants/{grant_id}/revoke", headers=headers
        )

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
