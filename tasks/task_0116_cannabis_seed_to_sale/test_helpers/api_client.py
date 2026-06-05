"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /compliance prefix. The base _request()
method (HTTP verb, envelope handling) is inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/compliance/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- License ----
    def create_license(self, payload, headers):
        return self._request("POST", "/compliance/licenses", payload, headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/compliance/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/compliance/licenses/{license_id}", headers=headers)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/compliance/licenses/{license_id}/suspend", {}, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/compliance/licenses/{license_id}/reinstate", {}, headers)

    def revoke_license(self, license_id, headers):
        return self._request("POST", f"/compliance/licenses/{license_id}/revoke", {}, headers)

    # ---- PlantBatch ----
    def create_plant_batch(self, payload, headers):
        return self._request("POST", "/compliance/plant-batches", payload, headers)

    def list_plant_batches(self, headers, params=None):
        return self._request("GET", "/compliance/plant-batches", headers=headers, params=params)

    def get_plant_batch(self, batch_id, headers):
        return self._request("GET", f"/compliance/plant-batches/{batch_id}", headers=headers)

    def advance_plant_batch(self, batch_id, headers):
        return self._request("POST", f"/compliance/plant-batches/{batch_id}/advance", {}, headers)

    def list_plant_batch_waste_events(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/compliance/plant-batches/{batch_id}/waste-events",
            headers=headers, params=params,
        )

    # ---- Harvest ----
    def create_harvest(self, payload, headers):
        return self._request("POST", "/compliance/harvests", payload, headers)

    def list_harvests(self, headers, params=None):
        return self._request("GET", "/compliance/harvests", headers=headers, params=params)

    def get_harvest(self, harvest_id, headers):
        return self._request("GET", f"/compliance/harvests/{harvest_id}", headers=headers)

    def cure_harvest(self, harvest_id, payload, headers):
        return self._request("POST", f"/compliance/harvests/{harvest_id}/cure", payload, headers)

    def finish_harvest(self, harvest_id, headers):
        return self._request("POST", f"/compliance/harvests/{harvest_id}/finish", {}, headers)

    # ---- Package ----
    def create_package(self, payload, headers):
        return self._request("POST", "/compliance/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/compliance/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/compliance/packages/{package_id}", headers=headers)

    def list_package_lab_results(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/compliance/packages/{package_id}/lab-results",
            headers=headers, params=params,
        )

    def list_package_reconciliation_counts(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/compliance/packages/{package_id}/reconciliation-counts",
            headers=headers, params=params,
        )

    def list_package_waste_events(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/compliance/packages/{package_id}/waste-events",
            headers=headers, params=params,
        )

    def list_package_manifest_lines(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/compliance/packages/{package_id}/manifest-lines",
            headers=headers, params=params,
        )

    def list_package_sale_lines(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/compliance/packages/{package_id}/sale-lines",
            headers=headers, params=params,
        )

    def release_package(self, package_id, headers):
        return self._request("POST", f"/compliance/packages/{package_id}/release", {}, headers)

    def clear_hold(self, package_id, headers):
        return self._request("POST", f"/compliance/packages/{package_id}/clear-hold", {}, headers)

    # ---- LabResult ----
    def create_lab_result(self, payload, headers):
        return self._request("POST", "/compliance/lab-results", payload, headers)

    def list_lab_results(self, headers, params=None):
        return self._request("GET", "/compliance/lab-results", headers=headers, params=params)

    def get_lab_result(self, lab_result_id, headers):
        return self._request("GET", f"/compliance/lab-results/{lab_result_id}", headers=headers)

    # ---- Manifest + lines ----
    def create_manifest(self, payload, headers):
        return self._request("POST", "/compliance/manifests", payload, headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/compliance/manifests", headers=headers, params=params)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/compliance/manifests/{manifest_id}", headers=headers)

    def add_manifest_line(self, manifest_id, payload, headers):
        return self._request("POST", f"/compliance/manifests/{manifest_id}/lines", payload, headers)

    def list_manifest_lines(self, manifest_id, headers, params=None):
        return self._request(
            "GET", f"/compliance/manifests/{manifest_id}/lines",
            headers=headers, params=params,
        )

    def depart_manifest(self, manifest_id, payload, headers):
        return self._request("POST", f"/compliance/manifests/{manifest_id}/depart", payload, headers)

    def recall_manifest(self, manifest_id, headers):
        return self._request("POST", f"/compliance/manifests/{manifest_id}/recall", {}, headers)

    def receive_manifest(self, manifest_id, payload, headers):
        return self._request("POST", f"/compliance/manifests/{manifest_id}/receive", payload, headers)

    def void_manifest(self, manifest_id, headers):
        return self._request("POST", f"/compliance/manifests/{manifest_id}/void", {}, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/compliance/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/compliance/customers/{customer_id}", headers=headers)

    # ---- Sale + lines ----
    def create_sale(self, payload, headers):
        return self._request("POST", "/compliance/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/compliance/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/compliance/sales/{sale_id}", headers=headers)

    def add_sale_line(self, sale_id, payload, headers):
        return self._request("POST", f"/compliance/sales/{sale_id}/lines", payload, headers)

    def list_sale_lines(self, sale_id, headers, params=None):
        return self._request(
            "GET", f"/compliance/sales/{sale_id}/lines",
            headers=headers, params=params,
        )

    def finalize_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/compliance/sales/{sale_id}/finalize", payload, headers)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/compliance/sales/{sale_id}/void", {}, headers)

    # ---- ReconciliationCount ----
    def create_reconciliation_count(self, payload, headers):
        return self._request("POST", "/compliance/reconciliation-counts", payload, headers)

    def list_reconciliation_counts(self, headers, params=None):
        return self._request(
            "GET", "/compliance/reconciliation-counts", headers=headers, params=params,
        )

    # ---- WasteEvent ----
    def create_waste_event(self, payload, headers):
        return self._request("POST", "/compliance/waste-events", payload, headers)

    def list_waste_events(self, headers, params=None):
        return self._request("GET", "/compliance/waste-events", headers=headers, params=params)


api_client = ApiClient()
