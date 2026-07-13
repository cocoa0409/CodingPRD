"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ServiceConnection ----
    def create_connection(self, payload, headers):
        return self._request("POST", "/service-connections", payload, headers)

    def list_connections(self, headers, params=None):
        return self._request("GET", "/service-connections", headers=headers, params=params)

    def get_connection(self, connection_id, headers):
        return self._request("GET", f"/service-connections/{connection_id}", headers=headers)

    def restore_connection(self, connection_id, headers):
        return self._request("POST", f"/service-connections/{connection_id}/restore", {}, headers)

    # ---- BackflowDevice ----
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/devices", headers=headers, params=params)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def remove_device(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/remove", {}, headers)

    # ---- Tester ----
    def create_tester(self, payload, headers):
        return self._request("POST", "/testers", payload, headers)

    def list_testers(self, headers, params=None):
        return self._request("GET", "/testers", headers=headers, params=params)

    def get_tester(self, tester_id, headers):
        return self._request("GET", f"/testers/{tester_id}", headers=headers)

    def suspend_tester(self, tester_id, headers):
        return self._request("POST", f"/testers/{tester_id}/suspend", {}, headers)

    def reinstate_tester(self, tester_id, headers):
        return self._request("POST", f"/testers/{tester_id}/reinstate", {}, headers)

    # ---- TestAppointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/test-appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/test-appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/test-appointments/{appointment_id}", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/test-appointments/{appointment_id}/cancel", {}, headers)

    # ---- TestReport ----
    def create_report(self, payload, headers):
        return self._request("POST", "/test-reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/test-reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/test-reports/{report_id}", headers=headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/test-reports/{report_id}/accept", {}, headers)

    def reject_report(self, report_id, payload, headers):
        return self._request("POST", f"/test-reports/{report_id}/reject", payload, headers)

    # ---- HazardSurvey ----
    def create_survey(self, payload, headers):
        return self._request("POST", "/hazard-surveys", payload, headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/hazard-surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/hazard-surveys/{survey_id}", headers=headers)

    def finalize_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/hazard-surveys/{survey_id}/finalize", payload, headers)

    # ---- ShutoffNotice ----
    def create_notice(self, payload, headers):
        return self._request("POST", "/shutoff-notices", payload, headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/shutoff-notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/shutoff-notices/{notice_id}", headers=headers)

    def rescind_notice(self, notice_id, headers):
        return self._request("POST", f"/shutoff-notices/{notice_id}/rescind", {}, headers)

    def enforce_notice(self, notice_id, headers):
        return self._request("POST", f"/shutoff-notices/{notice_id}/enforce", {}, headers)

    # ---- RepairOrder ----
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def get_repair_order(self, order_id, headers):
        return self._request("GET", f"/repair-orders/{order_id}", headers=headers)

    def complete_repair_order(self, order_id, payload, headers):
        return self._request("POST", f"/repair-orders/{order_id}/complete", payload, headers)

    def cancel_repair_order(self, order_id, headers):
        return self._request("POST", f"/repair-orders/{order_id}/cancel", {}, headers)

    # ---- Reminder ----
    def generate_reminders(self, headers):
        return self._request("POST", "/reminders/generate", {}, headers)

    def list_reminders(self, headers, params=None):
        return self._request("GET", "/reminders", headers=headers, params=params)

    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/reminders/{reminder_id}", headers=headers)

    # ---- Utility reporting ----
    def utility_report(self, headers, params=None):
        return self._request("GET", "/utility-report", headers=headers, params=params)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
