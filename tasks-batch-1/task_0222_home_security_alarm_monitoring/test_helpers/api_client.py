"""API client: one method per endpoint in the PRD.

Subclasses the framework GenericApiClient, which supplies _request().
GET endpoints pass filter/pagination data via the `params` argument so it
lands in the query string; POST/PATCH pass it as a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- MonitoringPlan -----
    def create_monitoring_plan(self, payload, headers):
        return self._request("POST", "/monitoring-plans", payload, headers)

    def get_monitoring_plan(self, plan_id, headers):
        return self._request("GET", f"/monitoring-plans/{plan_id}", headers=headers)

    def list_monitoring_plans(self, headers, params=None):
        return self._request("GET", "/monitoring-plans", headers=headers, params=params)

    # ----- Account -----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def activate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/activate", {}, headers)

    def change_plan(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/change-plan", payload, headers)

    def request_cancellation(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/request-cancellation", {}, headers)

    def withdraw_cancellation(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/withdraw-cancellation", {}, headers)

    def finalize_cancellation(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/finalize-cancellation", payload, headers)

    # ----- SecuritySystem -----
    def create_system(self, payload, headers):
        return self._request("POST", "/systems", payload, headers)

    def list_systems(self, headers, params=None):
        return self._request("GET", "/systems", headers=headers, params=params)

    def get_system(self, system_id, headers):
        return self._request("GET", f"/systems/{system_id}", headers=headers)

    def patch_system(self, system_id, payload, headers):
        return self._request("PATCH", f"/systems/{system_id}", payload, headers)

    def arm_system(self, system_id, payload, headers):
        return self._request("POST", f"/systems/{system_id}/arm", payload, headers)

    def disarm_system(self, system_id, headers):
        return self._request("POST", f"/systems/{system_id}/disarm", {}, headers)

    def enter_test_mode(self, system_id, headers):
        return self._request("POST", f"/systems/{system_id}/enter-test-mode", {}, headers)

    def exit_test_mode(self, system_id, headers):
        return self._request("POST", f"/systems/{system_id}/exit-test-mode", {}, headers)

    # ----- Sensor -----
    def create_sensor(self, payload, headers):
        return self._request("POST", "/sensors", payload, headers)

    def list_sensors(self, headers, params=None):
        return self._request("GET", "/sensors", headers=headers, params=params)

    def get_sensor(self, sensor_id, headers):
        return self._request("GET", f"/sensors/{sensor_id}", headers=headers)

    def bypass_sensor(self, sensor_id, headers):
        return self._request("POST", f"/sensors/{sensor_id}/bypass", {}, headers)

    def restore_sensor(self, sensor_id, headers):
        return self._request("POST", f"/sensors/{sensor_id}/restore", {}, headers)

    def remove_sensor(self, sensor_id, headers):
        return self._request("POST", f"/sensors/{sensor_id}/remove", {}, headers)

    # ----- AlarmEvent -----
    def create_alarm_event(self, payload, headers):
        return self._request("POST", "/alarm-events", payload, headers)

    def list_alarm_events(self, headers, params=None):
        return self._request("GET", "/alarm-events", headers=headers, params=params)

    def get_alarm_event(self, event_id, headers):
        return self._request("GET", f"/alarm-events/{event_id}", headers=headers)

    def route_alarm_event(self, event_id, headers):
        return self._request("POST", f"/alarm-events/{event_id}/route", {}, headers)

    def dispatch_alarm_event(self, event_id, headers):
        return self._request("POST", f"/alarm-events/{event_id}/dispatch", {}, headers)

    def resolve_alarm_event(self, event_id, payload, headers):
        return self._request("POST", f"/alarm-events/{event_id}/resolve", payload, headers)

    # ----- Dispatch -----
    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/dispatches", headers=headers, params=params)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/dispatches/{dispatch_id}", headers=headers)

    def cancel_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/cancel", {}, headers)

    # ----- Permit -----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers)

    def expire_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/expire", {}, headers)

    # ----- Fine -----
    def list_fines(self, headers, params=None):
        return self._request("GET", "/fines", headers=headers, params=params)

    def get_fine(self, fine_id, headers):
        return self._request("GET", f"/fines/{fine_id}", headers=headers)

    def pay_fine(self, fine_id, headers):
        return self._request("POST", f"/fines/{fine_id}/pay", {}, headers)

    def waive_fine(self, fine_id, headers):
        return self._request("POST", f"/fines/{fine_id}/waive", {}, headers)

    # ----- Logical clock (test-driving) -----
    def set_clock(self, now_utc, headers):
        return self._request("POST", "/_clock/set", {"now_utc": now_utc}, headers)


api_client = ApiClient()
