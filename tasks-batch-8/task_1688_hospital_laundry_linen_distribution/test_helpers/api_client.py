"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Hospital Linen Distribution API."""

    # --- Logical clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Facilities ---
    def create_facility(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def get_facility_metrics(self, facility_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/facilities/{facility_id}/metrics", headers=headers
        )

    # --- Units ---
    def create_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/units", headers=headers, params=params)

    # --- Linen stocks ---
    def create_linen_stock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/linen-stocks", payload, headers)

    def get_linen_stock(self, stock_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/linen-stocks/{stock_id}", headers=headers)

    def list_linen_stocks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/linen-stocks", headers=headers, params=params)

    def create_stock_adjustment(
        self, stock_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/linen-stocks/{stock_id}/adjustments", payload, headers
        )

    # --- Par levels ---
    def create_par_level(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/par-levels", payload, headers)

    def get_par_level(self, par_level_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/par-levels/{par_level_id}", headers=headers)

    def list_par_levels(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/par-levels", headers=headers, params=params)

    def update_par_level(
        self, par_level_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PUT", f"/par-levels/{par_level_id}", payload, headers)

    # --- Cart exchange runs ---
    def create_cart_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cart-runs", payload, headers)

    def get_cart_run(self, cart_run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cart-runs/{cart_run_id}", headers=headers)

    def list_cart_runs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cart-runs", headers=headers, params=params)

    def complete_cart_run(
        self, cart_run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cart-runs/{cart_run_id}/complete", payload, headers
        )

    def dispute_cart_run(
        self, cart_run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cart-runs/{cart_run_id}/dispute", payload, headers
        )

    def recount_cart_run(
        self, cart_run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cart-runs/{cart_run_id}/recount", payload, headers
        )

    def reconcile_cart_run(self, cart_run_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cart-runs/{cart_run_id}/reconcile", {}, headers
        )

    # --- Soiled manifests ---
    def create_soiled_manifest(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/soiled-manifests", payload, headers)

    def get_soiled_manifest(self, manifest_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/soiled-manifests/{manifest_id}", headers=headers
        )

    def list_soiled_manifests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/soiled-manifests", headers=headers, params=params)

    def return_soiled_manifest(
        self, manifest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/soiled-manifests/{manifest_id}/return", payload, headers
        )

    def reconcile_soiled_manifest(self, manifest_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/soiled-manifests/{manifest_id}/reconcile", {}, headers
        )

    # --- Vendor invoices ---
    def create_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def finalize_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", {}, headers)

    def dispute_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/invoices/{invoice_id}/dispute", payload, headers
        )

    def settle_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/invoices/{invoice_id}/settle", {}, headers)

    # --- Complaints ---
    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def verify_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/complaints/{complaint_id}/verify", {}, headers)

    def reject_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/complaints/{complaint_id}/reject", payload, headers
        )

    def rescind_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/complaints/{complaint_id}/rescind", {}, headers
        )

    # --- Surge events ---
    def create_surge_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/surge-events", payload, headers)

    def get_surge_event(self, surge_event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/surge-events/{surge_event_id}", headers=headers)

    def list_surge_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/surge-events", headers=headers, params=params)

    def activate_surge_event(self, surge_event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/surge-events/{surge_event_id}/activate", {}, headers
        )

    def close_surge_event(self, surge_event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/surge-events/{surge_event_id}/close", {}, headers
        )


api_client = ApiClient()
