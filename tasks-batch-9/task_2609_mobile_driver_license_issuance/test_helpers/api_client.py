"""One typed method per published endpoint of the mDL issuance API.

Every method returns the raw response so tests can assert on the status line
as well as the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class MdlApiClient(GenericApiClient):
    """Client covering the whole /mdl surface."""

    # ------------------------------------------------------------------
    # Interoperability profiles and trust list distribution
    # ------------------------------------------------------------------
    def create_interop_profile(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdl/interop-profiles", payload, headers)

    def get_interop_profile(self, profile_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdl/interop-profiles/{profile_id}", None, headers
        )

    def list_profile_trust_list_snapshots(
        self,
        profile_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/mdl/interop-profiles/{profile_id}/trust-list-snapshots",
            params,
            headers,
        )

    def create_trust_list_snapshot(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/mdl/trust-list-snapshots", payload, headers)

    # ------------------------------------------------------------------
    # Holders
    # ------------------------------------------------------------------
    def create_holder(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdl/holders", payload, headers)

    def get_holder(self, holder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdl/holders/{holder_id}", None, headers)

    def patch_physical_credential(
        self, holder_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/mdl/holders/{holder_id}/physical-credential", payload, headers
        )

    def change_holder_address(
        self, holder_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/holders/{holder_id}/address-change", payload, headers
        )

    def list_holder_devices(
        self,
        holder_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/mdl/holders/{holder_id}/devices", params, headers
        )

    def list_holder_proofing_sessions(
        self,
        holder_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/mdl/holders/{holder_id}/proofing-sessions", params, headers
        )

    # ------------------------------------------------------------------
    # Identity proofing
    # ------------------------------------------------------------------
    def create_proofing_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdl/proofing-sessions", payload, headers)

    def get_proofing_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdl/proofing-sessions/{session_id}", None, headers
        )

    def add_proofing_evidence(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/proofing-sessions/{session_id}/evidence", payload, headers
        )

    def list_proofing_evidence(
        self,
        session_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/mdl/proofing-sessions/{session_id}/evidence", params, headers
        )

    def get_assurance_preview(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/mdl/proofing-sessions/{session_id}/assurance-preview",
            None,
            headers,
        )

    def submit_proofing_session(
        self,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/mdl/proofing-sessions/{session_id}/submit", payload or {}, headers
        )

    def adjudicate_proofing_session(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/proofing-sessions/{session_id}/adjudicate", payload, headers
        )

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    def create_device(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdl/devices", payload, headers)

    def get_device(self, device_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdl/devices/{device_id}", None, headers)

    def attest_device(
        self, device_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/devices/{device_id}/attest", payload, headers
        )

    def report_device_lost(
        self,
        device_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/mdl/devices/{device_id}/report-lost", payload or {}, headers
        )

    def recover_device(
        self, device_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/devices/{device_id}/recover", payload, headers
        )

    def wipe_device(
        self,
        device_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/mdl/devices/{device_id}/wipe", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Digital credentials
    # ------------------------------------------------------------------
    def create_credential(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdl/credentials", payload, headers)

    def get_credential(self, credential_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdl/credentials/{credential_id}", None, headers)

    def list_credentials(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/mdl/credentials", params, headers)

    def activate_credential(
        self, credential_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/credentials/{credential_id}/activate", payload, headers
        )

    def renew_credential(
        self, credential_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/credentials/{credential_id}/renew", payload, headers
        )

    def revoke_credential(
        self, credential_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/credentials/{credential_id}/revoke", payload, headers
        )

    def list_revocation_entries(
        self,
        credential_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/mdl/credentials/{credential_id}/revocation-entries", params, headers
        )

    def get_revocation_status(self, credential_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdl/credentials/{credential_id}/revocation-status", None, headers
        )

    def list_credential_deliveries(
        self,
        credential_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/mdl/credentials/{credential_id}/deliveries", params, headers
        )

    # ------------------------------------------------------------------
    # Update orders and deliveries
    # ------------------------------------------------------------------
    def get_update_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdl/update-orders/{order_id}", None, headers)

    def list_update_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/mdl/update-orders", params, headers)

    def list_order_deliveries(
        self,
        order_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/mdl/update-orders/{order_id}/deliveries", params, headers
        )

    def deliver_update(
        self, delivery_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/update-deliveries/{delivery_id}/deliver", payload, headers
        )

    def fail_update(
        self, delivery_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/update-deliveries/{delivery_id}/fail", payload, headers
        )

    # ------------------------------------------------------------------
    # Verifiers
    # ------------------------------------------------------------------
    def create_verifier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdl/verifiers", payload, headers)

    def get_verifier(self, verifier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdl/verifiers/{verifier_id}", None, headers)

    def decide_verifier_trust(
        self, verifier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/verifiers/{verifier_id}/trust-decision", payload, headers
        )

    def attest_retention(
        self, verifier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/mdl/verifiers/{verifier_id}/retention-attestation",
            payload,
            headers,
        )

    def get_exposure_index(self, verifier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdl/verifiers/{verifier_id}/exposure-index", None, headers
        )

    def get_invoice(self, verifier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdl/verifiers/{verifier_id}/invoice", None, headers
        )

    def list_verifier_reader_apps(
        self,
        verifier_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/mdl/verifiers/{verifier_id}/reader-apps", params, headers
        )

    def list_verifier_log_entries(
        self,
        verifier_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/mdl/verifiers/{verifier_id}/presentation-log-entries",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Reader applications
    # ------------------------------------------------------------------
    def create_reader_app(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdl/reader-apps", payload, headers)

    def decide_reader_listing(
        self, reader_app_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/reader-apps/{reader_app_id}/list-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Presentation sessions
    # ------------------------------------------------------------------
    def create_presentation_session(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/mdl/presentation-sessions", payload, headers)

    def get_presentation_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/mdl/presentation-sessions/{session_id}", None, headers
        )

    def list_presentation_sessions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/mdl/presentation-sessions", params, headers)

    def consent_presentation(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mdl/presentation-sessions/{session_id}/consent", payload, headers
        )

    def disclose_presentation(
        self,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/mdl/presentation-sessions/{session_id}/disclose",
            payload or {},
            headers,
        )

    def void_presentation_billing(
        self,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/mdl/presentation-sessions/{session_id}/void-billing",
            payload or {},
            headers,
        )

    def list_presentation_log_entries(
        self,
        session_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/mdl/presentation-sessions/{session_id}/log-entries", params, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/mdl/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )
