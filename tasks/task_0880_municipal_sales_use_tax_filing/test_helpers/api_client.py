"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/tax/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"/tax/jurisdictions/{jurisdiction_id}", headers=headers
        )

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/tax/jurisdictions", headers=headers, params=params)

    # --- Taxpayers ---
    def create_taxpayer(self, payload, headers):
        return self._request("POST", "/tax/taxpayers", payload, headers)

    def get_taxpayer(self, taxpayer_id, headers):
        return self._request("GET", f"/tax/taxpayers/{taxpayer_id}", headers=headers)

    def list_taxpayers(self, headers, params=None):
        return self._request("GET", "/tax/taxpayers", headers=headers, params=params)

    def activate_taxpayer(self, taxpayer_id, headers):
        return self._request(
            "POST", f"/tax/taxpayers/{taxpayer_id}/activate", {}, headers
        )

    def suspend_taxpayer(self, taxpayer_id, payload, headers):
        return self._request(
            "POST", f"/tax/taxpayers/{taxpayer_id}/suspend", payload, headers
        )

    # --- Returns ---
    def create_return(self, payload, headers):
        return self._request("POST", "/tax/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/tax/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/tax/returns", headers=headers, params=params)

    def file_return(self, return_id, headers):
        return self._request("POST", f"/tax/returns/{return_id}/file", {}, headers)

    def amend_return(self, return_id, payload, headers):
        return self._request("POST", f"/tax/returns/{return_id}/amend", payload, headers)

    # --- Exemption Certificates ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/tax/exemption-certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/tax/exemption-certificates/{certificate_id}", headers=headers
        )

    def list_certificates(self, headers, params=None):
        return self._request(
            "GET", "/tax/exemption-certificates", headers=headers, params=params
        )

    # --- Remittances ---
    def create_remittance(self, payload, headers):
        return self._request("POST", "/tax/remittances", payload, headers)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/tax/remittances/{remittance_id}", headers=headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/tax/remittances", headers=headers, params=params)

    def apply_remittance(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/tax/remittances/{remittance_id}/apply", payload, headers
        )

    # --- Audits ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/tax/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/tax/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/tax/audits", headers=headers, params=params)

    def close_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/tax/audits/{audit_id}/close", payload, headers)

    # --- Assessments ---
    def create_assessment(self, payload, headers):
        return self._request("POST", "/tax/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/tax/assessments/{assessment_id}", headers=headers
        )

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/tax/assessments", headers=headers, params=params)

    # --- Appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/tax/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/tax/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/tax/appeals", headers=headers, params=params)

    def request_info_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/tax/appeals/{appeal_id}/request-info", payload, headers
        )

    def respond_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/tax/appeals/{appeal_id}/respond", payload, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/tax/appeals/{appeal_id}/decide", payload, headers
        )

    # --- Refund Claims ---
    def create_refund_claim(self, payload, headers):
        return self._request("POST", "/tax/refund-claims", payload, headers)

    def get_refund_claim(self, refund_id, headers):
        return self._request("GET", f"/tax/refund-claims/{refund_id}", headers=headers)

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", "/tax/refund-claims", headers=headers, params=params)

    def approve_refund_claim(self, refund_id, headers):
        return self._request(
            "POST", f"/tax/refund-claims/{refund_id}/approve", {}, headers
        )

    def deny_refund_claim(self, refund_id, payload, headers):
        return self._request(
            "POST", f"/tax/refund-claims/{refund_id}/deny", payload, headers
        )


api_client = ApiClient()
