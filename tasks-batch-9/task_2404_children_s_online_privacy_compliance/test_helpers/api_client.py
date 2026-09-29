"""API client: one method per endpoint the PRD defines."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the Children's Online Privacy Compliance API."""

    # ---------------------------------------------------------------- services
    def create_online_service(self, payload: dict, headers: dict):
        return self._request("POST", "/online-services", payload, headers)

    def list_online_services(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/online-services", headers=headers, params=params)

    def get_online_service(self, service_id: str, headers: dict):
        return self._request("GET", f"/online-services/{service_id}", headers=headers)

    def run_determination(self, service_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/online-services/{service_id}/determination", payload or {}, headers
        )

    def set_posture(self, service_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/online-services/{service_id}/posture", payload, headers)

    # ------------------------------------------------- service reverse lookups
    def list_service_determination_evidence(
        self, service_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/online-services/{service_id}/determination-evidence",
            headers=headers,
            params=params,
        )

    def list_service_age_screens(
        self, service_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/online-services/{service_id}/age-screens", headers=headers, params=params
        )

    def list_service_parental_notices(
        self, service_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/online-services/{service_id}/parental-notices", headers=headers, params=params
        )

    def list_service_activities(
        self, service_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/online-services/{service_id}/activities", headers=headers, params=params
        )

    def list_service_retention_schedules(
        self, service_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/online-services/{service_id}/retention-schedules",
            headers=headers,
            params=params,
        )

    def list_service_third_party_integrations(
        self, service_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/online-services/{service_id}/third-party-integrations",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------ determination evidence
    def create_determination_evidence(self, payload: dict, headers: dict):
        return self._request("POST", "/determination-evidence", payload, headers)

    # ------------------------------------------------------------- age screens
    def create_age_screen(self, payload: dict, headers: dict):
        return self._request("POST", "/age-screens", payload, headers)

    def set_age_screen_status(self, screen_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/age-screens/{screen_id}/status", payload, headers)

    # --------------------------------------------------------- parental notices
    def create_parental_notice(self, payload: dict, headers: dict):
        return self._request("POST", "/parental-notices", payload, headers)

    def publish_parental_notice(self, notice_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/parental-notices/{notice_id}/publish", payload or {}, headers
        )

    # -------------------------------------------------------------- activities
    def create_activity(self, payload: dict, headers: dict):
        return self._request("POST", "/activities", payload, headers)

    # --------------------------------------------------------- consent requests
    def create_consent_request(self, payload: dict, headers: dict):
        return self._request("POST", "/consent-requests", payload, headers)

    def list_consent_requests(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/consent-requests", headers=headers, params=params)

    def get_consent_request(self, consent_id: str, headers: dict):
        return self._request("GET", f"/consent-requests/{consent_id}", headers=headers)

    def set_consent_request_status(self, consent_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/consent-requests/{consent_id}/status", payload, headers)

    # ------------------------------------------------------ child data records
    def create_child_data_record(self, payload: dict, headers: dict):
        return self._request("POST", "/child-data-records", payload, headers)

    def list_child_data_records(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/child-data-records", headers=headers, params=params)

    def get_child_data_record(self, record_id: str, headers: dict):
        return self._request("GET", f"/child-data-records/{record_id}", headers=headers)

    # ------------------------------------------------- parental rights requests
    def create_parental_rights_request(self, payload: dict, headers: dict):
        return self._request("POST", "/parental-rights-requests", payload, headers)

    def list_parental_rights_requests(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/parental-rights-requests", headers=headers, params=params)

    def get_parental_rights_request(self, request_id: str, headers: dict):
        return self._request("GET", f"/parental-rights-requests/{request_id}", headers=headers)

    def set_parental_rights_request_status(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/parental-rights-requests/{request_id}/status", payload, headers
        )

    # --------------------------------------------------- third-party integrations
    def create_third_party_integration(self, payload: dict, headers: dict):
        return self._request("POST", "/third-party-integrations", payload, headers)

    def set_third_party_integration_status(self, integration_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/third-party-integrations/{integration_id}/status", payload, headers
        )

    # ------------------------------------------------------ retention schedules
    def create_retention_schedule(self, payload: dict, headers: dict):
        return self._request("POST", "/retention-schedules", payload, headers)

    # --------------------------------------------------------- compliance runs
    def create_compliance_run(self, payload: dict, headers: dict):
        return self._request("POST", "/compliance-runs", payload, headers)

    # ------------------------------------------------------ safe harbor programs
    def create_safe_harbor_program(self, payload: dict, headers: dict):
        return self._request("POST", "/safe-harbor-programs", payload, headers)

    # --------------------------------------------------- safe harbor assessments
    def create_safe_harbor_assessment(self, payload: dict, headers: dict):
        return self._request("POST", "/safe-harbor-assessments", payload, headers)

    def list_safe_harbor_assessments(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/safe-harbor-assessments", headers=headers, params=params)

    def get_safe_harbor_assessment(self, assessment_id: str, headers: dict):
        return self._request("GET", f"/safe-harbor-assessments/{assessment_id}", headers=headers)

    def set_safe_harbor_assessment_status(self, assessment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/safe-harbor-assessments/{assessment_id}/status", payload, headers
        )

    def certify_safe_harbor_assessment(
        self, assessment_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/safe-harbor-assessments/{assessment_id}/certify", payload or {}, headers
        )

    # -------------------------------------------------------------- the clock
    def set_current_utc(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -------------------------------------------------------------- raw access
    def raw_get(self, path: str, headers: Dict[str, str], params: Optional[dict] = None):
        """Escape hatch for header-level tests that must omit an auth header."""
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path: str, payload: Any, headers: Dict[str, str]):
        """Escape hatch for header-level tests that must omit an auth header."""
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
