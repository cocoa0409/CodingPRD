"""API client: one method per endpoint defined in the Vital Records PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    # --- Certifier ---
    def create_certifier(self, payload, headers):
        return self._request("POST", "/certifiers", payload, headers)

    def get_certifier(self, certifier_id, headers):
        return self._request("GET", f"/certifiers/{certifier_id}", headers=headers)

    # --- VitalEvent ---
    def create_vital_event(self, payload, headers):
        return self._request("POST", "/vital-events", payload, headers)

    def get_vital_event(self, event_id, headers):
        return self._request("GET", f"/vital-events/{event_id}", headers=headers)

    def list_vital_events(self, headers, params=None):
        return self._request("GET", "/vital-events", headers=headers, params=params)

    def file_vital_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/vital-events/{event_id}/file", payload or {}, headers,
        )

    def register_vital_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/vital-events/{event_id}/register", payload or {}, headers,
        )

    def return_vital_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/vital-events/{event_id}/return", payload or {}, headers,
        )

    def void_vital_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/vital-events/{event_id}/void", payload or {}, headers,
        )

    # --- MedicalCertification ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/certifications", payload, headers)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def certify_certification(self, cert_id, headers, payload=None):
        return self._request(
            "POST", f"/certifications/{cert_id}/certify", payload or {}, headers,
        )

    # --- Amendment ---
    def create_amendment(self, payload, headers):
        return self._request("POST", "/amendments", payload, headers)

    def get_amendment(self, amendment_id, headers):
        return self._request("GET", f"/amendments/{amendment_id}", headers=headers)

    def list_amendments(self, headers, params=None):
        return self._request("GET", "/amendments", headers=headers, params=params)

    def submit_amendment(self, amendment_id, headers, payload=None):
        return self._request(
            "POST", f"/amendments/{amendment_id}/submit", payload or {}, headers,
        )

    def approve_amendment(self, amendment_id, payload, headers):
        return self._request(
            "POST", f"/amendments/{amendment_id}/approve", payload, headers,
        )

    def reject_amendment(self, amendment_id, headers, payload=None):
        return self._request(
            "POST", f"/amendments/{amendment_id}/reject", payload or {}, headers,
        )

    # --- PaternityAcknowledgment ---
    def create_paternity(self, payload, headers):
        return self._request("POST", "/paternity-acknowledgments", payload, headers)

    def get_paternity(self, pa_id, headers):
        return self._request(
            "GET", f"/paternity-acknowledgments/{pa_id}", headers=headers,
        )

    def list_paternity(self, headers, params=None):
        return self._request(
            "GET", "/paternity-acknowledgments", headers=headers, params=params,
        )

    def acknowledge_paternity(self, pa_id, headers, payload=None):
        return self._request(
            "POST", f"/paternity-acknowledgments/{pa_id}/acknowledge",
            payload or {}, headers,
        )

    def rescind_paternity(self, pa_id, headers, payload=None):
        return self._request(
            "POST", f"/paternity-acknowledgments/{pa_id}/rescind",
            payload or {}, headers,
        )

    def finalize_paternity(self, pa_id, headers, payload=None):
        return self._request(
            "POST", f"/paternity-acknowledgments/{pa_id}/finalize",
            payload or {}, headers,
        )

    # --- CertifiedCopyRequest ---
    def create_copy_request(self, payload, headers):
        return self._request("POST", "/certified-copy-requests", payload, headers)

    def get_copy_request(self, copy_id, headers):
        return self._request(
            "GET", f"/certified-copy-requests/{copy_id}", headers=headers,
        )

    def list_copy_requests(self, headers, params=None):
        return self._request(
            "GET", "/certified-copy-requests", headers=headers, params=params,
        )

    def verify_id_copy_request(self, copy_id, headers, payload=None):
        return self._request(
            "POST", f"/certified-copy-requests/{copy_id}/verify-id",
            payload or {}, headers,
        )

    def issue_copy_request(self, copy_id, payload, headers):
        return self._request(
            "POST", f"/certified-copy-requests/{copy_id}/issue", payload, headers,
        )

    def deny_copy_request(self, copy_id, headers, payload=None):
        return self._request(
            "POST", f"/certified-copy-requests/{copy_id}/deny",
            payload or {}, headers,
        )

    # --- ApostilleRequest ---
    def create_apostille(self, payload, headers):
        return self._request("POST", "/apostille-requests", payload, headers)

    def get_apostille(self, apostille_id, headers):
        return self._request(
            "GET", f"/apostille-requests/{apostille_id}", headers=headers,
        )

    def list_apostilles(self, headers, params=None):
        return self._request(
            "GET", "/apostille-requests", headers=headers, params=params,
        )

    def authenticate_apostille(self, apostille_id, headers, payload=None):
        return self._request(
            "POST", f"/apostille-requests/{apostille_id}/authenticate",
            payload or {}, headers,
        )

    def reject_apostille(self, apostille_id, headers, payload=None):
        return self._request(
            "POST", f"/apostille-requests/{apostille_id}/reject",
            payload or {}, headers,
        )

    # --- DelayedRegistrationPacket ---
    def create_packet(self, payload, headers):
        return self._request("POST", "/delayed-registration-packets", payload, headers)

    def get_packet(self, packet_id, headers):
        return self._request(
            "GET", f"/delayed-registration-packets/{packet_id}", headers=headers,
        )

    def list_packets(self, headers, params=None):
        return self._request(
            "GET", "/delayed-registration-packets", headers=headers, params=params,
        )

    def accept_packet(self, packet_id, headers, payload=None):
        return self._request(
            "POST", f"/delayed-registration-packets/{packet_id}/accept",
            payload or {}, headers,
        )

    def return_packet(self, packet_id, headers, payload=None):
        return self._request(
            "POST", f"/delayed-registration-packets/{packet_id}/return",
            payload or {}, headers,
        )

    # --- StatisticsReport ---
    def create_report(self, payload, headers):
        return self._request("POST", "/statistics-reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request(
            "GET", f"/statistics-reports/{report_id}", headers=headers,
        )

    def list_reports(self, headers, params=None):
        return self._request(
            "GET", "/statistics-reports", headers=headers, params=params,
        )


api_client = ApiClient()
