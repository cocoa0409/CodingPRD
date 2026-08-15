"""API client: one method per endpoint declared in PRD section 4.

All paths are mounted under /api per PRD section 4. Methods delegate to the
inherited _request() and return raw requests.Response objects so tests can
assert status codes and envelopes themselves.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Cloth Diaper & Linen Route Service API."""

    # --- Logical clock (PRD 2.5) ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Subscription plans ---
    def create_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/subscription-plans", payload, headers)

    def list_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/subscription-plans", headers=headers, params=params)

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/subscription-plans/{plan_id}", headers=headers)

    # --- Service zones ---
    def create_zone(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/service-zones", payload, headers)

    def list_zones(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/service-zones", headers=headers, params=params)

    def get_zone(self, zone_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/service-zones/{zone_id}", headers=headers)

    # --- Customers ---
    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/customers", payload, headers)

    def list_customers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def customer_event(self, customer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/customers/{customer_id}/events", payload, headers)

    # --- Subscriptions ---
    def create_subscription(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def list_subscriptions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/subscriptions/{subscription_id}", headers=headers)

    def subscription_event(self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/events", payload, headers)

    # --- Service pauses ---
    def create_pause(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/service-pauses", payload, headers)

    def list_pauses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/service-pauses", headers=headers, params=params)

    def get_pause(self, pause_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/service-pauses/{pause_id}", headers=headers)

    def cancel_pause(self, pause_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/service-pauses/{pause_id}/cancel", {}, headers)

    # --- Starter kits ---
    def list_kits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/starter-kits", headers=headers, params=params)

    def get_kit(self, kit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/starter-kits/{kit_id}", headers=headers)

    def kit_event(self, kit_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/starter-kits/{kit_id}/events", payload, headers)

    # --- Routes ---
    def create_route(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/routes", payload, headers)

    def list_routes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/routes", headers=headers, params=params)

    def get_route(self, route_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/routes/{route_id}", headers=headers)

    def sequence_route(self, route_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/routes/{route_id}/sequence", {}, headers)

    def route_event(self, route_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/routes/{route_id}/events", payload, headers)

    # --- Route stops ---
    def create_route_stop(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/route-stops", payload, headers)

    def list_route_stops(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/route-stops/{stop_id}", headers=headers)

    def complete_stop(self, stop_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/route-stops/{stop_id}/complete", payload, headers)

    def route_stop_event(self, stop_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/route-stops/{stop_id}/events", payload, headers)

    # --- Soiled intakes ---
    def create_intake(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/soiled-intakes", payload, headers)

    def list_intakes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/soiled-intakes", headers=headers, params=params)

    def get_intake(self, intake_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/soiled-intakes/{intake_id}", headers=headers)

    def intake_event(self, intake_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/soiled-intakes/{intake_id}/events", payload, headers)

    # --- Wash formulas ---
    def create_formula(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/wash-formulas", payload, headers)

    def list_formulas(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/wash-formulas", headers=headers, params=params)

    def get_formula(self, formula_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/wash-formulas/{formula_id}", headers=headers)

    # --- Wash batches ---
    def create_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/wash-batches", payload, headers)

    def list_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/wash-batches", headers=headers, params=params)

    def get_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/wash-batches/{batch_id}", headers=headers)

    def load_batch(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/wash-batches/{batch_id}/load", payload, headers)

    def batch_event(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/wash-batches/{batch_id}/events", payload, headers)

    # --- Inventory pools ---
    def create_pool(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/inventory-pools", payload, headers)

    def list_pools(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/inventory-pools", headers=headers, params=params)

    def get_pool(self, pool_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/inventory-pools/{pool_id}", headers=headers)

    def pool_adjustment(self, pool_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/inventory-pools/{pool_id}/adjustments", payload, headers)

    # --- Inventory swaps ---
    def create_swap(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/inventory-swaps", payload, headers)

    def list_swaps(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/inventory-swaps", headers=headers, params=params)

    def get_swap(self, swap_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/inventory-swaps/{swap_id}", headers=headers)

    def approve_swap(self, swap_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/inventory-swaps/{swap_id}/approve", payload, headers)

    def swap_event(self, swap_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/inventory-swaps/{swap_id}/events", payload, headers)

    # --- Lost / damaged item cases ---
    def create_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/lost-item-cases", payload, headers)

    def list_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/lost-item-cases", headers=headers, params=params)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/lost-item-cases/{case_id}", headers=headers)

    def case_event(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/lost-item-cases/{case_id}/events", payload, headers)

    # --- Invoices ---
    def generate_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/invoices/generate", payload, headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def invoice_event(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/invoices/{invoice_id}/events", payload, headers)


api_client = ApiClient()
