"""One client method per endpoint in PRD section 4.

Every method returns the raw `requests.Response` so that tests can assert on
the HTTP status as well as the envelope body.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_FIELD, CLOCK_PATH


class CaApiClient(GenericApiClient):
    """Typed access to the certificate authority operations API."""

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.6)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request("POST", CLOCK_PATH, {CLOCK_FIELD: current_utc}, headers)

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------------
    # Certificate profiles (PRD 3.1)
    # ------------------------------------------------------------------
    def create_profile(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/ca/certificate-profiles", payload, headers)

    def list_profiles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/ca/certificate-profiles", headers=headers, params=params
        )

    def get_profile(self, profile_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/certificate-profiles/{profile_id}", headers=headers
        )

    def activate_profile(self, profile_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/certificate-profiles/{profile_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def publish_crl(self, profile_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/ca/certificate-profiles/{profile_id}/crl-publications",
            payload,
            headers,
        )

    def list_crl_publications(
        self, profile_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/ca/certificate-profiles/{profile_id}/crl-publications",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Subscribers (PRD 3.2)
    # ------------------------------------------------------------------
    def create_subscriber(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/ca/subscribers", payload, headers)

    def list_subscribers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/ca/subscribers", headers=headers, params=params)

    def get_subscriber(self, subscriber_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ca/subscribers/{subscriber_id}", headers=headers)

    def amend_subscriber(self, subscriber_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/ca/subscribers/{subscriber_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Organization vetting (PRD 3.3)
    # ------------------------------------------------------------------
    def open_vetting(self, subscriber_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/ca/subscribers/{subscriber_id}/organization-vettings",
            payload,
            headers,
        )

    def list_vettings(
        self, subscriber_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/ca/subscribers/{subscriber_id}/organization-vettings",
            headers=headers,
            params=params,
        )

    def get_vetting(self, vetting_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/organization-vettings/{vetting_id}", headers=headers
        )

    def record_check(self, vetting_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/organization-vettings/{vetting_id}/checks", payload, headers
        )

    def approve_vetting(self, vetting_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/organization-vettings/{vetting_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Domain control validation (PRD 3.4)
    # ------------------------------------------------------------------
    def create_authorization(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/ca/domain-authorizations", payload, headers)

    def list_authorizations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/ca/domain-authorizations", headers=headers, params=params
        )

    def get_authorization(self, authorization_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/domain-authorizations/{authorization_id}", headers=headers
        )

    def validate_authorization(
        self, authorization_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/ca/domain-authorizations/{authorization_id}/validate",
            payload,
            headers,
        )

    def invalidate_authorization(
        self, authorization_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/ca/domain-authorizations/{authorization_id}/invalidate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Certificate requests (PRD 3.5)
    # ------------------------------------------------------------------
    def create_request(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/ca/certificate-requests", payload, headers)

    def list_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/ca/certificate-requests", headers=headers, params=params
        )

    def get_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/certificate-requests/{request_id}", headers=headers
        )

    def submit_request(self, request_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/certificate-requests/{request_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def return_request(self, request_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/certificate-requests/{request_id}/return", payload, headers
        )

    def reject_request(self, request_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/certificate-requests/{request_id}/reject", payload, headers
        )

    def clear_validation(self, request_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/certificate-requests/{request_id}/clear-validation",
            payload if payload is not None else {},
            headers,
        )

    def issue_certificate(self, request_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/certificate-requests/{request_id}/issue", payload, headers
        )

    # ------------------------------------------------------------------
    # Certificates and CT submissions (PRD 3.7)
    # ------------------------------------------------------------------
    def list_certificates(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/ca/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/certificates/{certificate_id}", headers=headers
        )

    def submit_ct_log(self, certificate_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/certificates/{certificate_id}/ct-submissions", payload, headers
        )

    def list_ct_submissions(
        self, certificate_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/ca/certificates/{certificate_id}/ct-submissions",
            headers=headers,
            params=params,
        )

    def activate_certificate(
        self, certificate_id: str, headers: Dict[str, str], payload=None
    ):
        return self._request(
            "POST",
            f"/ca/certificates/{certificate_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # HSM partitions and key ceremonies (PRD 3.6)
    # ------------------------------------------------------------------
    def create_partition(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/ca/hsm-partitions", payload, headers)

    def list_partitions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/ca/hsm-partitions", headers=headers, params=params)

    def get_partition(self, partition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/hsm-partitions/{partition_id}", headers=headers
        )

    def schedule_ceremony(self, partition_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/hsm-partitions/{partition_id}/key-ceremonies", payload, headers
        )

    def list_ceremonies(
        self, partition_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/ca/hsm-partitions/{partition_id}/key-ceremonies",
            headers=headers,
            params=params,
        )

    def get_ceremony(self, ceremony_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/key-ceremonies/{ceremony_id}", headers=headers
        )

    def witness_ceremony(self, ceremony_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/key-ceremonies/{ceremony_id}/witness",
            payload if payload is not None else {},
            headers,
        )

    def attest_ceremony(self, ceremony_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/key-ceremonies/{ceremony_id}/attest",
            payload if payload is not None else {},
            headers,
        )

    def revoke_attestation(self, ceremony_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/ca/key-ceremonies/{ceremony_id}/revoke-attestation",
            payload,
            headers,
        )

    def abort_ceremony(self, ceremony_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/key-ceremonies/{ceremony_id}/abort", payload, headers
        )

    # ------------------------------------------------------------------
    # Revocation (PRD 3.8)
    # ------------------------------------------------------------------
    def raise_revocation(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/ca/revocation-requests", payload, headers)

    def list_revocations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/ca/revocation-requests", headers=headers, params=params
        )

    def get_revocation(self, revocation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/revocation-requests/{revocation_id}", headers=headers
        )

    def execute_revocation(
        self, revocation_id: str, headers: Dict[str, str], payload=None
    ):
        return self._request(
            "POST",
            f"/ca/revocation-requests/{revocation_id}/execute",
            payload if payload is not None else {},
            headers,
        )

    def deny_revocation(self, revocation_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/revocation-requests/{revocation_id}/deny", payload, headers
        )

    # ------------------------------------------------------------------
    # Misissuance incidents (PRD 3.9)
    # ------------------------------------------------------------------
    def create_incident(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/ca/misissuance-incidents", payload, headers)

    def list_incidents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/ca/misissuance-incidents", headers=headers, params=params
        )

    def get_incident(self, incident_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/misissuance-incidents/{incident_id}", headers=headers
        )

    def disclose_incident(self, incident_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/misissuance-incidents/{incident_id}/disclose", payload, headers
        )

    def create_incident_communication(
        self, incident_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/ca/misissuance-incidents/{incident_id}/communications",
            payload,
            headers,
        )

    def list_incident_communications(
        self, incident_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/ca/misissuance-incidents/{incident_id}/communications",
            headers=headers,
            params=params,
        )

    def mass_revoke(self, incident_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/misissuance-incidents/{incident_id}/mass-revoke",
            payload if payload is not None else {},
            headers,
        )

    def close_incident(self, incident_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/misissuance-incidents/{incident_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Root program audits (PRD 3.9)
    # ------------------------------------------------------------------
    def create_audit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/ca/root-program-audits", payload, headers)

    def list_audits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/ca/root-program-audits", headers=headers, params=params
        )

    def get_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ca/root-program-audits/{audit_id}", headers=headers
        )

    def record_finding(self, audit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/ca/root-program-audits/{audit_id}/findings", payload, headers
        )

    def opine_audit(self, audit_id: str, headers: Dict[str, str], payload=None):
        return self._request(
            "POST",
            f"/ca/root-program-audits/{audit_id}/opine",
            payload if payload is not None else {},
            headers,
        )

    def create_audit_communication(
        self, audit_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/ca/root-program-audits/{audit_id}/communications",
            payload,
            headers,
        )

    def list_audit_communications(
        self, audit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/ca/root-program-audits/{audit_id}/communications",
            headers=headers,
            params=params,
        )
