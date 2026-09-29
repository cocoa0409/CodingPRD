"""One method per endpoint of PRD §4.

"Every endpoint below is served at the root of the service; there is no version
or product path prefix", so `API_PREFIX` is the empty string.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = ""


class ApiClient(GenericApiClient):
    """Endpoint methods for the Airline Catering & Inflight Meal Production API."""

    # ------------------------------------------------------------------
    # The deterministic logical clock (PRD §2.4)
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: Any, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        """The clock call with an arbitrary body, for shape probes."""
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------------
    # Airlines (PRD §3.1)
    # ------------------------------------------------------------------

    def create_airline(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/airlines", payload, headers)

    def list_airlines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/airlines", headers=headers, params=params
        )

    def get_airline(self, airline_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/airlines/{airline_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Meal specifications (PRD §3.1)
    # ------------------------------------------------------------------

    def create_meal_specification(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/meal-specifications", payload, headers
        )

    def amend_meal_specification(
        self, spec_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/meal-specifications/{spec_id}", payload, headers
        )

    def list_meal_specifications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/meal-specifications", headers=headers, params=params
        )

    def get_meal_specification(self, spec_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/meal-specifications/{spec_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Trucks and stands (PRD §3.7)
    # ------------------------------------------------------------------

    def create_truck(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/trucks", payload, headers)

    def amend_truck(
        self, truck_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/trucks/{truck_id}", payload, headers
        )

    def list_trucks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/trucks", headers=headers, params=params
        )

    def get_truck(self, truck_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/trucks/{truck_id}", headers=headers)

    def create_stand(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/stands", payload, headers)

    def amend_stand(
        self, stand_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/stands/{stand_id}", payload, headers
        )

    def list_stands(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/stands", headers=headers, params=params
        )

    def get_stand(self, stand_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/stands/{stand_id}", headers=headers)

    # ------------------------------------------------------------------
    # Flights (PRD §3.2, §3.4, §3.8)
    # ------------------------------------------------------------------

    def create_flight(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/flights", payload, headers)

    def update_pax_counts(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/flights/{flight_id}/pax-counts", payload, headers
        )

    def retime_flight(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/flights/{flight_id}/schedule", payload, headers
        )

    def lock_counts(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/flights/{flight_id}/lock-counts", payload, headers
        )

    def record_delay(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/flights/{flight_id}/delays", payload, headers
        )

    def cancel_flight(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/flights/{flight_id}/cancel", payload, headers
        )

    def list_flights(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/flights", headers=headers, params=params
        )

    def get_flight(self, flight_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/flights/{flight_id}", headers=headers
        )

    def get_cost_report(self, flight_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/flights/{flight_id}/cost-report", headers=headers
        )

    # ------------------------------------------------------------------
    # Special meal orders (PRD §3.3)
    # ------------------------------------------------------------------

    def create_special_meal_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/special-meal-orders", payload, headers
        )

    def change_special_meal_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/special-meal-orders/{order_id}/changes",
            payload,
            headers,
        )

    def list_special_meal_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/special-meal-orders", headers=headers, params=params
        )

    def get_special_meal_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/special-meal-orders/{order_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Production plan and batches (PRD §3.4, §3.5)
    # ------------------------------------------------------------------

    def cut_production_plan(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/flights/{flight_id}/production-plan",
            payload,
            headers,
        )

    def start_batch(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/production-batches/{batch_id}/start", payload, headers
        )

    def record_haccp_check(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-batches/{batch_id}/haccp-checks",
            payload,
            headers,
        )

    def complete_batch(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-batches/{batch_id}/complete",
            payload,
            headers,
        )

    def release_batch(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-batches/{batch_id}/release",
            payload,
            headers,
        )

    def list_production_batches(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/production-batches", headers=headers, params=params
        )

    def get_production_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/production-batches/{batch_id}", headers=headers
        )

    def list_haccp_checks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/haccp-checks", headers=headers, params=params
        )

    def get_haccp_check(self, check_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/haccp-checks/{check_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Carts and cart items (PRD §3.6)
    # ------------------------------------------------------------------

    def create_cart(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/carts", payload, headers)

    def load_cart_item(
        self, cart_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/carts/{cart_id}/items", payload, headers
        )

    def void_cart_item(self, cart_id: str, cart_item_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"{API_PREFIX}/carts/{cart_id}/items/{cart_item_id}",
            headers=headers,
        )

    def complete_cart_build(
        self, cart_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/carts/{cart_id}/build-completion", payload, headers
        )

    def seal_cart(
        self, cart_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/carts/{cart_id}/seals", payload, headers
        )

    def list_carts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/carts", headers=headers, params=params
        )

    def get_cart(self, cart_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/carts/{cart_id}", headers=headers)

    def list_cart_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/cart-items", headers=headers, params=params
        )

    def get_cart_item(self, cart_item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/cart-items/{cart_item_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Loading manifests (PRD §3.6)
    # ------------------------------------------------------------------

    def open_loading_manifest(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/flights/{flight_id}/loading-manifests",
            payload,
            headers,
        )

    def issue_loading_manifest(
        self, manifest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/loading-manifests/{manifest_id}/issue",
            payload,
            headers,
        )

    def list_loading_manifests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/loading-manifests", headers=headers, params=params
        )

    def get_loading_manifest(self, manifest_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/loading-manifests/{manifest_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Delivery runs (PRD §3.7)
    # ------------------------------------------------------------------

    def create_delivery_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/delivery-runs", payload, headers)

    def record_run_event(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/delivery-runs/{run_id}/events", payload, headers
        )

    def create_recovery_run(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/delivery-runs/{run_id}/recovery-runs",
            payload,
            headers,
        )

    def list_delivery_runs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/delivery-runs", headers=headers, params=params
        )

    def get_delivery_run(self, run_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/delivery-runs/{run_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Uplift reconciliation and disposition (PRD §3.9)
    # ------------------------------------------------------------------

    def create_uplift_record(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/flights/{flight_id}/uplift-records", payload, headers
        )

    def record_dispositions(
        self, uplift_record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/uplift-records/{uplift_record_id}/dispositions",
            payload,
            headers,
        )

    def list_uplift_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/uplift-records", headers=headers, params=params
        )

    def get_uplift_record(self, uplift_record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/uplift-records/{uplift_record_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Waste manifests (PRD §3.9)
    # ------------------------------------------------------------------

    def create_waste_manifest(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/waste-manifests", payload, headers)

    def transition_waste_manifest(
        self, waste_manifest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/waste-manifests/{waste_manifest_id}/transitions",
            payload,
            headers,
        )

    def list_waste_manifests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/waste-manifests", headers=headers, params=params
        )

    def get_waste_manifest(self, waste_manifest_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/waste-manifests/{waste_manifest_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # The audit docket (PRD §3.10)
    # ------------------------------------------------------------------

    def create_audit_finding(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/audit-findings", payload, headers)

    def resolve_audit_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/audit-findings/{finding_id}/resolution",
            payload,
            headers,
        )

    def list_audit_findings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/audit-findings", headers=headers, params=params
        )

    def get_audit_finding(self, finding_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/audit-findings/{finding_id}", headers=headers
        )


api_client = ApiClient()
