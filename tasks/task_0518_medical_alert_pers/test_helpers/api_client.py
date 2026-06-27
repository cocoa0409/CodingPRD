"""API client: one method per endpoint defined in the PRD (Section 4).

Subclasses GenericApiClient; the base _request() handles HTTP plumbing. All paths are
mounted under the /pers prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/pers/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- MonitoringPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/pers/monitoring-plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/pers/monitoring-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/pers/monitoring-plans/{plan_id}", headers=headers)

    def archive_plan(self, plan_id, headers):
        return self._request("POST", f"/pers/monitoring-plans/{plan_id}/archive", headers=headers)

    # ---- Subscriber ----
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/pers/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/pers/subscribers/{subscriber_id}", headers=headers)

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/pers/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/pers/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/pers/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/pers/contracts/{contract_id}/activate", headers=headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/pers/contracts/{contract_id}/suspend", headers=headers)

    def reinstate_contract(self, contract_id, headers):
        return self._request("POST", f"/pers/contracts/{contract_id}/reinstate", headers=headers)

    def request_cancellation(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/pers/contracts/{contract_id}/request-cancellation", payload, headers
        )

    def finalize_cancellation(self, contract_id, headers):
        return self._request(
            "POST", f"/pers/contracts/{contract_id}/finalize-cancellation", headers=headers
        )

    def mark_past_due(self, contract_id, headers):
        return self._request(
            "POST", f"/pers/contracts/{contract_id}/billing/mark-past-due", headers=headers
        )

    def record_payment(self, contract_id, headers):
        return self._request(
            "POST", f"/pers/contracts/{contract_id}/billing/record-payment", headers=headers
        )

    def write_off(self, contract_id, headers):
        return self._request(
            "POST", f"/pers/contracts/{contract_id}/billing/write-off", headers=headers
        )

    def list_contract_devices(self, contract_id, headers):
        return self._request("GET", f"/pers/contracts/{contract_id}/devices", headers=headers)

    def list_contract_equipment_returns(self, contract_id, headers):
        return self._request(
            "GET", f"/pers/contracts/{contract_id}/equipment-returns", headers=headers
        )

    # ---- Device ----
    def create_device(self, payload, headers):
        return self._request("POST", "/pers/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/pers/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/pers/devices", headers=headers, params=params)

    def enroll_device(self, device_id, headers):
        return self._request("POST", f"/pers/devices/{device_id}/enroll", headers=headers)

    def submit_test(self, device_id, payload, headers):
        return self._request("POST", f"/pers/devices/{device_id}/tests", payload, headers)

    def list_tests(self, device_id, headers):
        return self._request("GET", f"/pers/devices/{device_id}/tests", headers=headers)

    # ---- EmergencyContact ----
    def create_contact(self, payload, headers):
        return self._request("POST", "/pers/emergency-contacts", payload, headers)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"/pers/emergency-contacts/{contact_id}", headers=headers)

    def list_contacts(self, headers, params=None):
        return self._request("GET", "/pers/emergency-contacts", headers=headers, params=params)

    def update_contact(self, contact_id, payload, headers):
        return self._request(
            "PATCH", f"/pers/emergency-contacts/{contact_id}", payload, headers
        )

    # ---- AlarmEvent + DispatchAction ----
    def raise_alarm(self, device_id, payload, headers):
        return self._request("POST", f"/pers/devices/{device_id}/alarms", payload, headers)

    def get_alarm(self, alarm_id, headers):
        return self._request("GET", f"/pers/alarms/{alarm_id}", headers=headers)

    def list_alarms(self, headers, params=None):
        return self._request("GET", "/pers/alarms", headers=headers, params=params)

    def list_device_alarms(self, device_id, headers):
        return self._request("GET", f"/pers/devices/{device_id}/alarms", headers=headers)

    def assign_alarm(self, alarm_id, headers):
        return self._request("POST", f"/pers/alarms/{alarm_id}/assign", headers=headers)

    def create_dispatch_action(self, alarm_id, payload, headers):
        return self._request(
            "POST", f"/pers/alarms/{alarm_id}/dispatch-actions", payload, headers
        )

    def list_dispatch_actions_for_alarm(self, alarm_id, headers):
        return self._request(
            "GET", f"/pers/alarms/{alarm_id}/dispatch-actions", headers=headers
        )

    def get_dispatch_action(self, action_id, headers):
        return self._request("GET", f"/pers/dispatch-actions/{action_id}", headers=headers)

    def list_dispatch_actions(self, headers, params=None):
        return self._request("GET", "/pers/dispatch-actions", headers=headers, params=params)

    # ---- EquipmentReturn ----
    def get_equipment_return(self, return_id, headers):
        return self._request("GET", f"/pers/equipment-returns/{return_id}", headers=headers)

    def list_equipment_returns(self, headers, params=None):
        return self._request("GET", "/pers/equipment-returns", headers=headers, params=params)

    def send_kit(self, return_id, headers):
        return self._request("POST", f"/pers/equipment-returns/{return_id}/send-kit", headers=headers)

    def mark_received(self, return_id, headers):
        return self._request(
            "POST", f"/pers/equipment-returns/{return_id}/mark-received", headers=headers
        )

    def inspect_return(self, return_id, payload, headers):
        return self._request(
            "POST", f"/pers/equipment-returns/{return_id}/inspect", payload, headers
        )

    def close_return(self, return_id, headers):
        return self._request("POST", f"/pers/equipment-returns/{return_id}/close", headers=headers)

    # ---- AgentShift ----
    def create_shift(self, payload, headers):
        return self._request("POST", "/pers/agent-shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/pers/agent-shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/pers/agent-shifts", headers=headers, params=params)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/pers/agent-shifts/{shift_id}/cancel", headers=headers)

    # ---- MonitoringHold ----
    def create_hold(self, payload, headers):
        return self._request("POST", "/pers/monitoring-holds", payload, headers)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/pers/monitoring-holds/{hold_id}", headers=headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/pers/monitoring-holds", headers=headers, params=params)

    def list_device_holds(self, device_id, headers):
        return self._request("GET", f"/pers/devices/{device_id}/monitoring-holds", headers=headers)

    def cancel_hold(self, hold_id, headers):
        return self._request("POST", f"/pers/monitoring-holds/{hold_id}/cancel", headers=headers)


api_client = ApiClient()
