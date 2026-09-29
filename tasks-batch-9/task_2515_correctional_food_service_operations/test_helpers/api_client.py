"""One method per endpoint of the correctional food service API.

Every endpoint is mounted under the `/cfs` prefix. Methods return the raw
`requests.Response` so tests can assert HTTP status codes directly.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cfs"


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the correctional food service API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # ------------------------------------------------------------------
    # Service contracts
    # ------------------------------------------------------------------

    def create_service_contract(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/service-contracts", payload, headers)

    def get_service_contract(
        self, contract_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/service-contracts/{contract_id}", None, headers
        )

    def list_service_contracts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-contracts", params, headers)

    def activate_service_contract(
        self, contract_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/service-contracts/{contract_id}/activate", {}, headers
        )

    def reconcile_service_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/service-contracts/{contract_id}/reconcile",
            payload,
            headers,
        )

    def close_service_contract(
        self, contract_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/service-contracts/{contract_id}/close", {}, headers
        )

    def get_performance_summary(
        self, contract_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/service-contracts/{contract_id}/performance-summary",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------

    def create_facility(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def get_facility(
        self, facility_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", None, headers)

    def list_facilities(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/facilities", params, headers)

    def sharps_audit(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/facilities/{facility_id}/sharps-audit", payload, headers
        )

    def get_sharps_summary(
        self, facility_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/facilities/{facility_id}/sharps-summary", None, headers
        )

    def list_facility_production_batches(
        self,
        facility_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/facilities/{facility_id}/production-batches",
            params,
            headers,
        )

    def list_facility_tool_issuances(
        self,
        facility_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/facilities/{facility_id}/tool-issuances", params, headers
        )

    # ------------------------------------------------------------------
    # Menu cycles and components
    # ------------------------------------------------------------------

    def create_menu_cycle(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/menu-cycles", payload, headers)

    def get_menu_cycle(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/menu-cycles/{cycle_id}", None, headers)

    def list_menu_cycles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/menu-cycles", params, headers)

    def add_menu_cycle_item(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/menu-cycles/{cycle_id}/items", payload, headers
        )

    def list_items_of_cycle(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/menu-cycles/{cycle_id}/items", params, headers
        )

    def get_menu_cycle_item(
        self, item_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/menu-cycle-items/{item_id}", None, headers
        )

    def list_menu_cycle_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/menu-cycle-items", params, headers)

    def nutrition_sign_menu_cycle(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/menu-cycles/{cycle_id}/nutrition-sign", {}, headers
        )

    def activate_menu_cycle(
        self, cycle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/menu-cycles/{cycle_id}/activate", {}, headers
        )

    # ------------------------------------------------------------------
    # Inmates
    # ------------------------------------------------------------------

    def create_inmate(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/inmates", payload, headers)

    def get_inmate(self, inmate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/inmates/{inmate_id}", None, headers)

    def list_inmates(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/inmates", params, headers)

    def record_inmate_movement(
        self, inmate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/inmates/{inmate_id}/movement", payload, headers
        )

    # ------------------------------------------------------------------
    # Diet orders
    # ------------------------------------------------------------------

    def create_diet_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/diet-orders", payload, headers)

    def get_diet_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/diet-orders/{order_id}", None, headers)

    def list_diet_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/diet-orders", params, headers)

    def verify_diet_order(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/diet-orders/{order_id}/verify", payload or {}, headers
        )

    def suspend_diet_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/diet-orders/{order_id}/suspend", payload, headers
        )

    def request_reverification(
        self, order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/diet-orders/{order_id}/request-reverification",
            {},
            headers,
        )

    def revoke_diet_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/diet-orders/{order_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Population counts
    # ------------------------------------------------------------------

    def create_population_count(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/population-counts", payload, headers)

    def get_population_count(
        self, count_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/population-counts/{count_id}", None, headers
        )

    def list_population_counts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/population-counts", params, headers)

    # ------------------------------------------------------------------
    # Meal forecasts
    # ------------------------------------------------------------------

    def create_meal_forecast(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/meal-forecasts", payload, headers)

    def get_meal_forecast(
        self, forecast_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/meal-forecasts/{forecast_id}", None, headers
        )

    def list_meal_forecasts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/meal-forecasts", params, headers)

    def lock_meal_forecast(
        self, forecast_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/meal-forecasts/{forecast_id}/lock", {}, headers
        )

    # ------------------------------------------------------------------
    # Production batches and HACCP readings
    # ------------------------------------------------------------------

    def create_production_batch(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/production-batches", payload, headers)

    def get_production_batch(
        self, batch_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/production-batches/{batch_id}", None, headers
        )

    def list_production_batches(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/production-batches", params, headers)

    def post_temperature_log(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/production-batches/{batch_id}/temperature-logs",
            payload,
            headers,
        )

    def list_temperature_logs(
        self,
        batch_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/production-batches/{batch_id}/temperature-logs",
            params,
            headers,
        )

    def advance_stage(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/production-batches/{batch_id}/advance-stage",
            payload,
            headers,
        )

    def qa_decision(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/production-batches/{batch_id}/qa-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Kitchen workers
    # ------------------------------------------------------------------

    def create_inmate_worker(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/inmate-workers", payload, headers)

    def get_inmate_worker(
        self, worker_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/inmate-workers/{worker_id}", None, headers
        )

    def list_inmate_workers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/inmate-workers", params, headers)

    def assign_inmate_worker(
        self, worker_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/inmate-workers/{worker_id}/assign", payload, headers
        )

    # ------------------------------------------------------------------
    # Tool issuances
    # ------------------------------------------------------------------

    def create_tool_issuance(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tool-issuances", payload, headers)

    def get_tool_issuance(
        self, issuance_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/tool-issuances/{issuance_id}", None, headers
        )

    def list_tool_issuances(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/tool-issuances", params, headers)

    def return_tool_issuance(
        self, issuance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/tool-issuances/{issuance_id}/return", payload, headers
        )

    def declare_tool_unaccounted(
        self, issuance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/tool-issuances/{issuance_id}/declare-unaccounted",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Contraband incidents
    # ------------------------------------------------------------------

    def create_contraband_incident(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/contraband-incidents", payload, headers)

    def get_contraband_incident(
        self, incident_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/contraband-incidents/{incident_id}", None, headers
        )

    def list_contraband_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/contraband-incidents", params, headers)

    def disposition_contraband_incident(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/contraband-incidents/{incident_id}/disposition",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Meal service records
    # ------------------------------------------------------------------

    def create_meal_service_record(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/meal-service-records", payload, headers
        )

    def get_meal_service_record(
        self, record_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/meal-service-records/{record_id}", None, headers
        )

    def list_meal_service_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/meal-service-records", params, headers)

    def patch_meal_service_record(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{PREFIX}/meal-service-records/{record_id}", payload, headers
        )

    def close_meal_service_record(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/meal-service-records/{record_id}/close",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Menu substitutions
    # ------------------------------------------------------------------

    def create_menu_substitution(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/menu-substitutions", payload, headers)

    def get_menu_substitution(
        self, substitution_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/menu-substitutions/{substitution_id}", None, headers
        )

    def list_menu_substitutions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/menu-substitutions", params, headers)

    def decide_menu_substitution(
        self, substitution_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/menu-substitutions/{substitution_id}/decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Grievances
    # ------------------------------------------------------------------

    def create_grievance(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/grievances", payload, headers)

    def get_grievance(
        self, grievance_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/grievances/{grievance_id}", None, headers)

    def list_grievances(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/grievances", params, headers)

    def route_grievance(
        self, grievance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/grievances/{grievance_id}/route", payload, headers
        )

    def complete_grievance_branch(
        self, grievance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/grievances/{grievance_id}/complete-branch",
            payload,
            headers,
        )

    def respond_grievance(
        self, grievance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/grievances/{grievance_id}/respond", payload, headers
        )

    # ------------------------------------------------------------------
    # Raw helpers for probing arbitrary paths (unknown-id sweeps)
    # ------------------------------------------------------------------

    def get_path(
        self, path: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}{path}", params, headers)
