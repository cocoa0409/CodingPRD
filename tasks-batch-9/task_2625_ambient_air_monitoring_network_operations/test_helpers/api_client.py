"""One method per endpoint declared in PRD 4."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed facade over the ambient air monitoring API."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----------------------------------------------------------- pollutants
    def create_pollutant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/pollutants", payload, headers)

    def get_pollutant(self, pollutant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pollutants/{pollutant_id}", None, headers)

    def list_pollutant_reference_methods(
        self, pollutant_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/pollutants/{pollutant_id}/reference-methods", params, headers
        )

    # ----------------------------------------------------- reference methods
    def create_reference_method(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/reference-methods", payload, headers)

    def change_designation(
        self, method_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reference-methods/{method_id}/designation", payload, headers
        )

    def get_reference_method(self, method_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reference-methods/{method_id}", None, headers)

    # ------------------------------------------------------------- networks
    def create_network(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/monitoring-networks", payload, headers)

    def get_network(self, network_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/monitoring-networks/{network_id}", None, headers)

    def list_network_assessments(
        self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/monitoring-networks/{network_id}/assessments", params, headers
        )

    def list_network_certification_packages(
        self, network_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/monitoring-networks/{network_id}/certification-packages",
            params,
            headers,
        )

    # ---------------------------------------------------------------- sites
    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/monitoring-sites", payload, headers)

    def approve_siting(self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/monitoring-sites/{site_id}/siting-approval", payload, headers
        )

    def commence_operations(
        self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/monitoring-sites/{site_id}/commence-operations", payload, headers
        )

    def reinstate_site(self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/monitoring-sites/{site_id}/reinstate", payload, headers
        )

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/monitoring-sites/{site_id}", None, headers)

    def list_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/monitoring-sites", params, headers)

    # ------------------------------------------------------------- monitors
    def create_monitor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/monitors", payload, headers)

    def approve_monitor(
        self, monitor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/monitors/{monitor_id}/approve", payload, headers)

    def commission_monitor(
        self, monitor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/monitors/{monitor_id}/commission", payload, headers)

    def set_service_status(
        self, monitor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/monitors/{monitor_id}/service-status", payload, headers
        )

    def create_qc_event(
        self, monitor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/monitors/{monitor_id}/qc-events", payload, headers)

    def get_monitor(self, monitor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/monitors/{monitor_id}", None, headers)

    def list_monitors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/monitors", params, headers)

    def list_monitor_qc_events(
        self, monitor_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/monitors/{monitor_id}/qc-events", params, headers)

    # ---------------------------------------------------------- data batches
    def create_data_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/data-batches", payload, headers)

    def bulk_ingest(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/data-batches/bulk-ingest", payload, headers)

    def bulk_validate(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/data-batches/bulk-validate", payload, headers)

    def begin_validation(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/data-batches/{batch_id}/begin-validation", payload, headers
        )

    def create_invalidation(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/data-batches/{batch_id}/invalidations", payload, headers
        )

    def withdraw_invalidation(
        self, invalidation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/data-invalidations/{invalidation_id}/withdraw", payload, headers
        )

    def validate_batch(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/data-batches/{batch_id}/validate", payload, headers)

    def invalidate_batch(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/data-batches/{batch_id}/invalidate", payload, headers)

    def reopen_batch(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/data-batches/{batch_id}/reopen", payload, headers)

    def get_data_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/data-batches/{batch_id}", None, headers)

    def list_data_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/data-batches", params, headers)

    def list_batch_invalidations(
        self, batch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/data-batches/{batch_id}/invalidations", params, headers
        )

    def list_batch_exclusions(
        self, batch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/data-batches/{batch_id}/exclusions", params, headers)

    # ------------------------------------------------------- demonstrations
    def create_demonstration(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/exceptional-event-demonstrations", payload, headers)

    def create_exclusion(
        self, demonstration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/exceptional-event-demonstrations/{demonstration_id}/exclusions",
            payload,
            headers,
        )

    def submit_demonstration(
        self, demonstration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/exceptional-event-demonstrations/{demonstration_id}/submit",
            payload,
            headers,
        )

    def request_demonstration_info(
        self, demonstration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/exceptional-event-demonstrations/{demonstration_id}/request-info",
            payload,
            headers,
        )

    def decide_demonstration(
        self, demonstration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/exceptional-event-demonstrations/{demonstration_id}/determination",
            payload,
            headers,
        )

    def get_demonstration(self, demonstration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/exceptional-event-demonstrations/{demonstration_id}", None, headers
        )

    def list_demonstrations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/exceptional-event-demonstrations", params, headers)

    def list_demonstration_exclusions(
        self, demonstration_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/exceptional-event-demonstrations/{demonstration_id}/exclusions",
            params,
            headers,
        )

    # --------------------------------------------------------- design values
    def create_design_value(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/design-values", payload, headers)

    def finalize_design_value(
        self, design_value_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/design-values/{design_value_id}/finalize", payload, headers
        )

    def get_design_value(self, design_value_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/design-values/{design_value_id}", None, headers)

    def list_design_values(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/design-values", params, headers)

    # -------------------------------------------------- certification packages
    def create_package(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/certification-packages", payload, headers)

    def submit_package(self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/certification-packages/{package_id}/submit", payload, headers
        )

    def certify_package(
        self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/certification-packages/{package_id}/certify", payload, headers
        )

    def reject_package(self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/certification-packages/{package_id}/reject", payload, headers
        )

    def get_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/certification-packages/{package_id}", None, headers)

    def list_packages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/certification-packages", params, headers)

    # ----------------------------------------------------------- assessments
    def create_assessment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/network-assessments", payload, headers)

    def submit_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/network-assessments/{assessment_id}/submit", payload, headers
        )

    def decide_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/network-assessments/{assessment_id}/decision", payload, headers
        )

    def get_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/network-assessments/{assessment_id}", None, headers)

    # ------------------------------------------------------ change requests
    def create_change_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/site-change-requests", payload, headers)

    def submit_change_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/site-change-requests/{request_id}/submit", payload, headers
        )

    def decide_change_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/site-change-requests/{request_id}/decision", payload, headers
        )

    def get_change_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/site-change-requests/{request_id}", None, headers)

    def list_change_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/site-change-requests", params, headers)
