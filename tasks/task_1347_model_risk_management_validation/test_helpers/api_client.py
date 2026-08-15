"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Models ---
    def create_model(self, payload, headers):
        return self._request("POST", "/mrm/models", payload, headers)

    def list_models(self, headers, params=None):
        return self._request("GET", "/mrm/models", headers=headers, params=params)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/mrm/models/{model_id}", headers=headers)

    def approve_model(self, model_id, headers):
        return self._request("POST", f"/mrm/models/{model_id}/approve", {}, headers)

    def retire_model(self, model_id, payload, headers):
        return self._request("POST", f"/mrm/models/{model_id}/retire", payload, headers)

    # --- Documentation ---
    def submit_documentation(self, model_id, payload, headers):
        return self._request("POST", f"/mrm/models/{model_id}/documentations", payload, headers)

    def list_documentations(self, model_id, headers, params=None):
        return self._request("GET", f"/mrm/models/{model_id}/documentations", headers=headers, params=params)

    def decide_documentation(self, model_id, doc_id, payload, headers):
        return self._request(
            "POST", f"/mrm/models/{model_id}/documentations/{doc_id}/decide", payload, headers
        )

    # --- Change requests ---
    def create_change_request(self, model_id, payload, headers):
        return self._request("POST", f"/mrm/models/{model_id}/change-requests", payload, headers)

    def list_change_requests(self, model_id, headers, params=None):
        return self._request("GET", f"/mrm/models/{model_id}/change-requests", headers=headers, params=params)

    def decide_change_request(self, model_id, cr_id, payload, headers):
        return self._request(
            "POST", f"/mrm/models/{model_id}/change-requests/{cr_id}/decide", payload, headers
        )

    # --- Validation engagements ---
    def create_engagement(self, model_id, payload, headers):
        return self._request("POST", f"/mrm/models/{model_id}/validation-engagements", payload, headers)

    def list_engagements(self, model_id, headers, params=None):
        return self._request("GET", f"/mrm/models/{model_id}/validation-engagements", headers=headers, params=params)

    def complete_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/mrm/validation-engagements/{engagement_id}/complete", payload, headers)

    def reopen_engagement(self, engagement_id, headers):
        return self._request("POST", f"/mrm/validation-engagements/{engagement_id}/reopen", {}, headers)

    # --- Findings ---
    def create_finding(self, model_id, payload, headers):
        return self._request("POST", f"/mrm/models/{model_id}/findings", payload, headers)

    def list_findings(self, model_id, headers, params=None):
        return self._request("GET", f"/mrm/models/{model_id}/findings", headers=headers, params=params)

    def close_finding(self, model_id, finding_id, headers):
        return self._request("POST", f"/mrm/models/{model_id}/findings/{finding_id}/close", {}, headers)

    def reopen_finding(self, model_id, finding_id, headers):
        return self._request("POST", f"/mrm/models/{model_id}/findings/{finding_id}/reopen", {}, headers)

    # --- Monitoring ---
    def create_metric(self, model_id, payload, headers):
        return self._request("POST", f"/mrm/models/{model_id}/monitoring-metrics", payload, headers)

    def list_metrics(self, model_id, headers, params=None):
        return self._request("GET", f"/mrm/models/{model_id}/monitoring-metrics", headers=headers, params=params)

    def get_metric(self, metric_id, headers):
        return self._request("GET", f"/mrm/monitoring-metrics/{metric_id}", headers=headers)

    def record_reading(self, metric_id, payload, headers):
        return self._request("POST", f"/mrm/monitoring-metrics/{metric_id}/readings", payload, headers)

    def list_readings(self, metric_id, headers, params=None):
        return self._request("GET", f"/mrm/monitoring-metrics/{metric_id}/readings", headers=headers, params=params)

    def list_breach_events(self, metric_id, headers, params=None):
        return self._request("GET", f"/mrm/monitoring-metrics/{metric_id}/breach-events", headers=headers, params=params)

    def resolve_breach_event(self, breach_event_id, headers):
        return self._request("POST", f"/mrm/breach-events/{breach_event_id}/resolve", {}, headers)

    # --- Vendor transparency ---
    def create_vendor_assessment(self, model_id, payload, headers):
        return self._request("POST", f"/mrm/models/{model_id}/vendor-assessments", payload, headers)

    def list_vendor_assessments(self, model_id, headers, params=None):
        return self._request("GET", f"/mrm/models/{model_id}/vendor-assessments", headers=headers, params=params)

    # --- Board & regulatory reporting ---
    def create_report(self, payload, headers):
        return self._request("POST", "/mrm/regulatory-reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/mrm/regulatory-reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/mrm/regulatory-reports/{report_id}", headers=headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/mrm/regulatory-reports/{report_id}/submit", {}, headers)

    # --- Test-driving logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
