"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- plants ---
    def create_plant(self, payload: Dict, headers: Dict):
        return self._request("POST", "/plants", payload, headers)

    def get_plant(self, plant_id: str, headers: Dict):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    def run_ops(self, plant_id: str, headers: Dict):
        return self._request("POST", f"/plants/{plant_id}/run-ops", {}, headers)

    # --- boilers ---
    def create_boiler(self, plant_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/plants/{plant_id}/boilers", payload, headers)

    def get_boiler(self, plant_id: str, boiler_id: str, headers: Dict):
        return self._request(
            "GET", f"/plants/{plant_id}/boilers/{boiler_id}", headers=headers
        )

    def list_boilers(self, plant_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/plants/{plant_id}/boilers", headers=headers, params=params
        )

    def warm_boiler(self, plant_id: str, boiler_id: str, headers: Dict):
        return self._request(
            "POST", f"/plants/{plant_id}/boilers/{boiler_id}/warm", {}, headers
        )

    def bring_boiler_online(self, plant_id: str, boiler_id: str, headers: Dict):
        return self._request(
            "POST", f"/plants/{plant_id}/boilers/{boiler_id}/bring-online", {}, headers
        )

    def bank_boiler(self, plant_id: str, boiler_id: str, headers: Dict):
        return self._request(
            "POST", f"/plants/{plant_id}/boilers/{boiler_id}/bank", {}, headers
        )

    def shutdown_boiler(self, plant_id: str, boiler_id: str, headers: Dict):
        return self._request(
            "POST", f"/plants/{plant_id}/boilers/{boiler_id}/shutdown", {}, headers
        )

    def reset_boiler(self, plant_id: str, boiler_id: str, headers: Dict):
        return self._request(
            "POST", f"/plants/{plant_id}/boilers/{boiler_id}/reset", {}, headers
        )

    def decommission_boiler(self, plant_id: str, boiler_id: str, headers: Dict):
        return self._request(
            "POST", f"/plants/{plant_id}/boilers/{boiler_id}/decommission", {}, headers
        )

    # --- operators ---
    def create_operator(self, plant_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/plants/{plant_id}/operators", payload, headers)

    def get_operator(self, plant_id: str, operator_id: str, headers: Dict):
        return self._request(
            "GET", f"/plants/{plant_id}/operators/{operator_id}", headers=headers
        )

    def list_operators(self, plant_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/plants/{plant_id}/operators", headers=headers, params=params
        )

    def renew_license(self, plant_id: str, operator_id: str, new_license_expires_on: str,
                      headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/operators/{operator_id}/renew-license",
            {"new_license_expires_on": new_license_expires_on},
            headers,
        )

    def revoke_license(self, plant_id: str, operator_id: str, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/operators/{operator_id}/revoke-license",
            {},
            headers,
        )

    # --- boiler log entries ---
    def create_log_entry(self, plant_id: str, boiler_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/boilers/{boiler_id}/log-entries",
            payload,
            headers,
        )

    def get_log_entry(self, plant_id: str, boiler_id: str, entry_id: str, headers: Dict):
        return self._request(
            "GET",
            f"/plants/{plant_id}/boilers/{boiler_id}/log-entries/{entry_id}",
            headers=headers,
        )

    def list_log_entries(self, plant_id: str, boiler_id: str, headers: Dict,
                         params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/plants/{plant_id}/boilers/{boiler_id}/log-entries",
            headers=headers,
            params=params,
        )

    def verify_log_entry(self, plant_id: str, boiler_id: str, entry_id: str,
                         expected_boiler_version, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/boilers/{boiler_id}/log-entries/{entry_id}/verify",
            {"expected_boiler_version": expected_boiler_version},
            headers,
        )

    def void_log_entry(self, plant_id: str, boiler_id: str, entry_id: str, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/boilers/{boiler_id}/log-entries/{entry_id}/void",
            {},
            headers,
        )

    # --- chemistry logs ---
    def create_chemistry_log(self, plant_id: str, boiler_id: str, payload: Dict,
                             headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/boilers/{boiler_id}/chemistry-logs",
            payload,
            headers,
        )

    def get_chemistry_log(self, plant_id: str, boiler_id: str, log_id: str, headers: Dict):
        return self._request(
            "GET",
            f"/plants/{plant_id}/boilers/{boiler_id}/chemistry-logs/{log_id}",
            headers=headers,
        )

    def list_chemistry_logs(self, plant_id: str, boiler_id: str, headers: Dict,
                            params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/plants/{plant_id}/boilers/{boiler_id}/chemistry-logs",
            headers=headers,
            params=params,
        )

    def void_chemistry_log(self, plant_id: str, boiler_id: str, log_id: str, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/boilers/{boiler_id}/chemistry-logs/{log_id}/void",
            {},
            headers,
        )

    # --- inspections ---
    def create_inspection(self, plant_id: str, boiler_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/boilers/{boiler_id}/inspections",
            payload,
            headers,
        )

    def get_inspection(self, plant_id: str, boiler_id: str, inspection_id: str,
                       headers: Dict):
        return self._request(
            "GET",
            f"/plants/{plant_id}/boilers/{boiler_id}/inspections/{inspection_id}",
            headers=headers,
        )

    def list_inspections(self, plant_id: str, boiler_id: str, headers: Dict,
                         params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/plants/{plant_id}/boilers/{boiler_id}/inspections",
            headers=headers,
            params=params,
        )

    def record_inspection_outcome(self, plant_id: str, boiler_id: str,
                                  inspection_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/boilers/{boiler_id}/inspections/{inspection_id}/record-outcome",
            payload,
            headers,
        )

    def post_certificate(self, plant_id: str, boiler_id: str, inspection_id: str,
                         headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/boilers/{boiler_id}/inspections/{inspection_id}/post",
            {},
            headers,
        )

    # --- steam traps ---
    def create_steam_trap(self, plant_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/plants/{plant_id}/steam-traps", payload, headers)

    def get_steam_trap(self, plant_id: str, trap_id: str, headers: Dict):
        return self._request(
            "GET", f"/plants/{plant_id}/steam-traps/{trap_id}", headers=headers
        )

    def list_steam_traps(self, plant_id: str, headers: Dict,
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/plants/{plant_id}/steam-traps", headers=headers, params=params
        )

    def survey_steam_trap(self, plant_id: str, trap_id: str, condition: str, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/steam-traps/{trap_id}/survey",
            {"condition": condition},
            headers,
        )

    def get_loss_projection(self, plant_id: str, trap_id: str, headers: Dict):
        return self._request(
            "GET",
            f"/plants/{plant_id}/steam-traps/{trap_id}/loss-projection",
            headers=headers,
        )

    # --- load dispatches ---
    def create_load_dispatch(self, plant_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/plants/{plant_id}/load-dispatches", payload, headers
        )

    def get_load_dispatch(self, plant_id: str, dispatch_id: str, headers: Dict):
        return self._request(
            "GET", f"/plants/{plant_id}/load-dispatches/{dispatch_id}", headers=headers
        )

    def list_load_dispatches(self, plant_id: str, headers: Dict,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/plants/{plant_id}/load-dispatches", headers=headers, params=params
        )

    def cancel_load_dispatch(self, plant_id: str, dispatch_id: str, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/load-dispatches/{dispatch_id}/cancel",
            {},
            headers,
        )

    # --- incidents ---
    def create_incident(self, plant_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/plants/{plant_id}/incidents", payload, headers)

    def get_incident(self, plant_id: str, incident_id: str, headers: Dict):
        return self._request(
            "GET", f"/plants/{plant_id}/incidents/{incident_id}", headers=headers
        )

    def list_incidents(self, plant_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/plants/{plant_id}/incidents", headers=headers, params=params
        )

    def acknowledge_incident(self, plant_id: str, incident_id: str, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/incidents/{incident_id}/acknowledge",
            {},
            headers,
        )

    def mitigate_incident(self, plant_id: str, incident_id: str, headers: Dict):
        return self._request(
            "POST",
            f"/plants/{plant_id}/incidents/{incident_id}/mitigate",
            {},
            headers,
        )

    def close_incident(self, plant_id: str, incident_id: str, resolution_notes,
                       headers: Dict):
        payload = {} if resolution_notes is None else {"resolution_notes": resolution_notes}
        return self._request(
            "POST",
            f"/plants/{plant_id}/incidents/{incident_id}/close",
            payload,
            headers,
        )

    # --- fuel deliveries ---
    def create_fuel_delivery(self, plant_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/plants/{plant_id}/fuel-deliveries", payload, headers
        )

    def get_fuel_delivery(self, plant_id: str, delivery_id: str, headers: Dict):
        return self._request(
            "GET", f"/plants/{plant_id}/fuel-deliveries/{delivery_id}", headers=headers
        )

    def list_fuel_deliveries(self, plant_id: str, headers: Dict,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/plants/{plant_id}/fuel-deliveries", headers=headers, params=params
        )


api_client = ApiClient()
