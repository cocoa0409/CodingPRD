"""API client: one method per endpoint of the hazardous waste TSDF API.

All list methods take an optional `params` dict for pagination and filters so
tests can exercise `limit`, `offset` and the documented filters.
"""

import time
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

# Per-test-server isolation restarts the API on the same port before every test.
# The first call a test makes can therefore be met by a TCP reset left over from
# the previous server process's socket state rather than by a response: the reset
# arrives before the request reaches the API, so re-sending it is safe and asks
# the same question again.
TRANSPORT_ATTEMPTS = 3
TRANSPORT_BACKOFF_SECONDS = 0.25


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        last_error = None
        for attempt in range(TRANSPORT_ATTEMPTS):
            try:
                return super()._request(method, path, payload, headers, params)
            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                time.sleep(TRANSPORT_BACKOFF_SECONDS * (attempt + 1))
        raise last_error

    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Facilities and permits ───────────────────────────────────────────────
    def create_facility(self, payload, headers):
        return self._request("POST", "/tsdf/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers):
        return self._request("GET", f"/tsdf/facilities/{facility_id}", None, headers)

    def list_facilities(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/facilities", None, headers, params=params)

    def request_permit_renewal(self, facility_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/facilities/{facility_id}/permit-renewal-request", payload, headers
        )

    def decide_permit(self, facility_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/facilities/{facility_id}/permit-decision", payload, headers
        )

    def get_financial_assurance_summary(self, facility_id: str, headers):
        return self._request(
            "GET", f"/tsdf/facilities/{facility_id}/financial-assurance-summary", None, headers
        )

    def get_biennial_report(self, facility_id: str, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/tsdf/facilities/{facility_id}/biennial-report", None, headers, params=params
        )

    # ─── Financial assurance instruments ──────────────────────────────────────
    def create_instrument(self, payload, headers):
        return self._request("POST", "/tsdf/financial-assurance-instruments", payload, headers)

    def get_instrument(self, instrument_id: str, headers):
        return self._request(
            "GET", f"/tsdf/financial-assurance-instruments/{instrument_id}", None, headers
        )

    def list_instruments(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/tsdf/financial-assurance-instruments", None, headers, params=params
        )

    def cancel_instrument(self, instrument_id: str, payload, headers):
        return self._request(
            "POST",
            f"/tsdf/financial-assurance-instruments/{instrument_id}/cancel",
            payload,
            headers,
        )

    # ─── Generators ───────────────────────────────────────────────────────────
    def create_generator(self, payload, headers):
        return self._request("POST", "/tsdf/generators", payload, headers)

    def get_generator(self, generator_id: str, headers):
        return self._request("GET", f"/tsdf/generators/{generator_id}", None, headers)

    def list_generators(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/generators", None, headers, params=params)

    def set_generator_status(self, generator_id: str, payload, headers):
        return self._request("POST", f"/tsdf/generators/{generator_id}/status", payload, headers)

    def get_reliability_score(self, generator_id: str, headers):
        return self._request(
            "GET", f"/tsdf/generators/{generator_id}/reliability-score", None, headers
        )

    # ─── Waste profiles ───────────────────────────────────────────────────────
    def create_waste_profile(self, payload, headers):
        return self._request("POST", "/tsdf/waste-profiles", payload, headers)

    def get_waste_profile(self, profile_id: str, headers):
        return self._request("GET", f"/tsdf/waste-profiles/{profile_id}", None, headers)

    def list_waste_profiles(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/waste-profiles", None, headers, params=params)

    def submit_waste_profile(self, profile_id: str, headers, payload=None):
        return self._request(
            "POST", f"/tsdf/waste-profiles/{profile_id}/submit", payload, headers
        )

    def create_profile_sample(self, profile_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/waste-profiles/{profile_id}/samples", payload, headers
        )

    def list_profile_samples(self, profile_id: str, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/tsdf/waste-profiles/{profile_id}/samples", None, headers, params=params
        )

    def decide_waste_profile(self, profile_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/waste-profiles/{profile_id}/decision", payload, headers
        )

    def set_waste_profile_status(self, profile_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/waste-profiles/{profile_id}/status", payload, headers
        )

    def list_profile_manifest_lines(self, profile_id: str, headers, params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/tsdf/waste-profiles/{profile_id}/manifest-lines",
            None,
            headers,
            params=params,
        )

    # ─── Storage units ────────────────────────────────────────────────────────
    def create_storage_unit(self, payload, headers):
        return self._request("POST", "/tsdf/storage-units", payload, headers)

    def get_storage_unit(self, unit_id: str, headers):
        return self._request("GET", f"/tsdf/storage-units/{unit_id}", None, headers)

    def list_storage_units(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/storage-units", None, headers, params=params)

    def set_storage_unit_status(self, unit_id: str, payload, headers):
        return self._request("POST", f"/tsdf/storage-units/{unit_id}/status", payload, headers)

    def list_unit_containers(self, unit_id: str, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/tsdf/storage-units/{unit_id}/containers", None, headers, params=params
        )

    # ─── Manifests ────────────────────────────────────────────────────────────
    def create_manifest(self, payload, headers):
        return self._request("POST", "/tsdf/manifests", payload, headers)

    def get_manifest(self, manifest_id: str, headers):
        return self._request("GET", f"/tsdf/manifests/{manifest_id}", None, headers)

    def list_manifests(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/manifests", None, headers, params=params)

    def list_manifest_lines(self, manifest_id: str, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/tsdf/manifests/{manifest_id}/lines", None, headers, params=params
        )

    def receive_manifest(self, manifest_id: str, payload, headers):
        return self._request("POST", f"/tsdf/manifests/{manifest_id}/receive", payload, headers)

    def resolve_manifest_discrepancy(self, manifest_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/manifests/{manifest_id}/discrepancy-resolution", payload, headers
        )

    def certify_manifest(self, manifest_id: str, payload, headers):
        return self._request("POST", f"/tsdf/manifests/{manifest_id}/certify", payload, headers)

    # ─── Containers ───────────────────────────────────────────────────────────
    def create_container(self, payload, headers):
        return self._request("POST", "/tsdf/containers", payload, headers)

    def get_container(self, container_id: str, headers):
        return self._request("GET", f"/tsdf/containers/{container_id}", None, headers)

    def list_containers(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/containers", None, headers, params=params)

    def set_container_custody_state(self, container_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/containers/{container_id}/custody-state", payload, headers
        )

    def set_container_compliance_state(self, container_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/containers/{container_id}/compliance-state", payload, headers
        )

    # ─── Treatment batches ────────────────────────────────────────────────────
    def create_treatment_batch(self, payload, headers):
        return self._request("POST", "/tsdf/treatment-batches", payload, headers)

    def get_treatment_batch(self, batch_id: str, headers):
        return self._request("GET", f"/tsdf/treatment-batches/{batch_id}", None, headers)

    def list_treatment_batches(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/treatment-batches", None, headers, params=params)

    def batch_operation(self, batch_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/treatment-batches/{batch_id}/operations", payload, headers
        )

    def verify_batch_ldr(self, batch_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/treatment-batches/{batch_id}/ldr-verification", payload, headers
        )

    # ─── Inspection events ────────────────────────────────────────────────────
    def create_inspection_event(self, payload, headers):
        return self._request("POST", "/tsdf/inspection-events", payload, headers)

    def get_inspection_event(self, event_id: str, headers):
        return self._request("GET", f"/tsdf/inspection-events/{event_id}", None, headers)

    def list_inspection_events(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/inspection-events", None, headers, params=params)

    # ─── Emission repair orders ───────────────────────────────────────────────
    def get_repair_order(self, order_id: str, headers):
        return self._request("GET", f"/tsdf/emission-repair-orders/{order_id}", None, headers)

    def list_repair_orders(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/emission-repair-orders", None, headers, params=params)

    def repair_order_action(self, order_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/emission-repair-orders/{order_id}/actions", payload, headers
        )

    # ─── Compliance findings ──────────────────────────────────────────────────
    def create_compliance_finding(self, payload, headers):
        return self._request("POST", "/tsdf/compliance-findings", payload, headers)

    def get_compliance_finding(self, finding_id: str, headers):
        return self._request("GET", f"/tsdf/compliance-findings/{finding_id}", None, headers)

    def list_compliance_findings(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/tsdf/compliance-findings", None, headers, params=params)

    def set_compliance_finding_status(self, finding_id: str, payload, headers):
        return self._request(
            "POST", f"/tsdf/compliance-findings/{finding_id}/status", payload, headers
        )


# Shared instance used by fixtures and by the `api` fixture in conftest.py.
api_client = ApiClient()

# Per-test-server isolation restarts the API on the same port between tests, so a
# pooled keep-alive socket left over from the previous server process is already
# dead when the next test reuses it and the read fails with ECONNRESET. Ask for a
# fresh connection on every request; nothing about the requests themselves changes.
api_client.session.headers["Connection"] = "close"
