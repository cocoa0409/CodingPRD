"""API client: one method per endpoint defined in the PRD §4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- ServiceTerritory ---
    def create_territory(self, payload, headers):
        return self._request("POST", "/gas-ops/territories", payload, headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", "/gas-ops/territories", headers=headers, params=params)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"/gas-ops/territories/{territory_id}", headers=headers)

    def list_territory_incidents(self, territory_id, headers, params=None):
        return self._request("GET", f"/gas-ops/territories/{territory_id}/incidents",
                             headers=headers, params=params)

    # --- FieldTechnician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/gas-ops/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/gas-ops/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/gas-ops/technicians/{technician_id}", headers=headers)

    def create_shift(self, technician_id, payload, headers):
        return self._request("POST", f"/gas-ops/technicians/{technician_id}/shifts",
                             payload, headers)

    def list_shifts(self, technician_id, headers, params=None):
        return self._request("GET", f"/gas-ops/technicians/{technician_id}/shifts",
                             headers=headers, params=params)

    def list_technician_dispatches(self, technician_id, headers, params=None):
        return self._request("GET", f"/gas-ops/technicians/{technician_id}/dispatches",
                             headers=headers, params=params)

    def list_technician_readings(self, technician_id, headers, params=None):
        return self._request("GET", f"/gas-ops/technicians/{technician_id}/atmospheric-readings",
                             headers=headers, params=params)

    def list_technician_make_safe_actions(self, technician_id, headers, params=None):
        return self._request("GET", f"/gas-ops/technicians/{technician_id}/make-safe-actions",
                             headers=headers, params=params)

    # --- RepairCrew ---
    def create_repair_crew(self, payload, headers):
        return self._request("POST", "/gas-ops/repair-crews", payload, headers)

    def list_repair_crews(self, headers, params=None):
        return self._request("GET", "/gas-ops/repair-crews", headers=headers, params=params)

    def get_repair_crew(self, crew_id, headers):
        return self._request("GET", f"/gas-ops/repair-crews/{crew_id}", headers=headers)

    def list_crew_work_orders(self, crew_id, headers, params=None):
        return self._request("GET", f"/gas-ops/repair-crews/{crew_id}/repair-work-orders",
                             headers=headers, params=params)

    # --- EmergencyCall ---
    def create_emergency_call(self, payload, headers):
        return self._request("POST", "/gas-ops/emergency-calls", payload, headers)

    def list_emergency_calls(self, headers, params=None):
        return self._request("GET", "/gas-ops/emergency-calls", headers=headers, params=params)

    def get_emergency_call(self, call_id, headers):
        return self._request("GET", f"/gas-ops/emergency-calls/{call_id}", headers=headers)

    # --- GasIncident ---
    def list_incidents(self, headers, params=None):
        return self._request("GET", "/gas-ops/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/gas-ops/incidents/{incident_id}", headers=headers)

    def triage_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/triage",
                             payload, headers)

    def reclassify_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/reclassify-priority",
                             payload, headers)

    def close_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/close",
                             payload or {}, headers)

    def merge_incident(self, target_incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{target_incident_id}/merge-duplicate",
                             payload, headers)

    def set_entry_status(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/entry-status",
                             payload, headers)

    # --- ResponseClockPause ---
    def create_pause(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/response-clock-pauses",
                             payload, headers)

    def end_pause(self, pause_id, headers):
        return self._request("POST", f"/gas-ops/response-clock-pauses/{pause_id}/end",
                             {}, headers)

    def list_pauses(self, incident_id, headers, params=None):
        return self._request("GET", f"/gas-ops/incidents/{incident_id}/response-clock-pauses",
                             headers=headers, params=params)

    # --- DispatchAssignment ---
    def create_dispatch(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/dispatches",
                             payload, headers)

    def list_incident_dispatches(self, incident_id, headers, params=None):
        return self._request("GET", f"/gas-ops/incidents/{incident_id}/dispatches",
                             headers=headers, params=params)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/gas-ops/dispatches/{dispatch_id}", headers=headers)

    def arrive_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/gas-ops/dispatches/{dispatch_id}/arrive", {}, headers)

    def clear_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/gas-ops/dispatches/{dispatch_id}/clear", {}, headers)

    def cancel_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/gas-ops/dispatches/{dispatch_id}/cancel",
                             payload, headers)

    def preempt_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/gas-ops/dispatches/{dispatch_id}/preempt",
                             payload, headers)

    # --- AtmosphericReading / MakeSafeAction ---
    def create_reading(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/atmospheric-readings",
                             payload, headers)

    def list_readings(self, incident_id, headers, params=None):
        return self._request("GET", f"/gas-ops/incidents/{incident_id}/atmospheric-readings",
                             headers=headers, params=params)

    def create_make_safe_action(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/make-safe-actions",
                             payload, headers)

    def list_make_safe_actions(self, incident_id, headers, params=None):
        return self._request("GET", f"/gas-ops/incidents/{incident_id}/make-safe-actions",
                             headers=headers, params=params)

    def complete_make_safe(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/make-safe/complete",
                             payload, headers)

    # --- Premise entry ---
    def create_entry_authorization(self, incident_id, payload, headers):
        return self._request("POST",
                             f"/gas-ops/incidents/{incident_id}/premise-entry-authorizations",
                             payload, headers)

    def list_entry_authorizations(self, incident_id, headers, params=None):
        return self._request("GET",
                             f"/gas-ops/incidents/{incident_id}/premise-entry-authorizations",
                             headers=headers, params=params)

    # --- ShutoffOrder ---
    def create_shutoff_order(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/shutoff-orders",
                             payload, headers)

    def list_shutoff_orders(self, incident_id, headers, params=None):
        return self._request("GET", f"/gas-ops/incidents/{incident_id}/shutoff-orders",
                             headers=headers, params=params)

    def get_shutoff_order(self, shutoff_id, headers):
        return self._request("GET", f"/gas-ops/shutoff-orders/{shutoff_id}", headers=headers)

    def authorize_shutoff(self, shutoff_id, headers):
        return self._request("POST", f"/gas-ops/shutoff-orders/{shutoff_id}/authorize",
                             {}, headers)

    def decline_shutoff(self, shutoff_id, headers, payload=None):
        return self._request("POST", f"/gas-ops/shutoff-orders/{shutoff_id}/decline",
                             payload or {}, headers)

    def execute_shutoff(self, shutoff_id, headers):
        return self._request("POST", f"/gas-ops/shutoff-orders/{shutoff_id}/execute",
                             {}, headers)

    def restore_shutoff(self, shutoff_id, headers):
        return self._request("POST", f"/gas-ops/shutoff-orders/{shutoff_id}/restore",
                             {}, headers)

    # --- ResponsibilityDetermination ---
    def create_determination(self, incident_id, payload, headers):
        return self._request("POST",
                             f"/gas-ops/incidents/{incident_id}/responsibility-determinations",
                             payload, headers)

    def list_determinations(self, incident_id, headers, params=None):
        return self._request("GET",
                             f"/gas-ops/incidents/{incident_id}/responsibility-determinations",
                             headers=headers, params=params)

    def get_determination(self, determination_id, headers):
        return self._request("GET",
                             f"/gas-ops/responsibility-determinations/{determination_id}",
                             headers=headers)

    def finalize_determination(self, determination_id, headers):
        return self._request("POST",
                             f"/gas-ops/responsibility-determinations/{determination_id}/finalize",
                             {}, headers)

    # --- RepairWorkOrder ---
    def create_work_order(self, incident_id, headers, payload=None):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/repair-work-orders",
                             payload or {}, headers)

    def list_work_orders(self, incident_id, headers, params=None):
        return self._request("GET", f"/gas-ops/incidents/{incident_id}/repair-work-orders",
                             headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/gas-ops/repair-work-orders/{work_order_id}",
                             headers=headers)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/gas-ops/repair-work-orders/{work_order_id}/schedule",
                             payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/gas-ops/repair-work-orders/{work_order_id}/start",
                             {}, headers)

    def hold_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/gas-ops/repair-work-orders/{work_order_id}/hold",
                             payload or {}, headers)

    def resume_work_order(self, work_order_id, headers):
        return self._request("POST", f"/gas-ops/repair-work-orders/{work_order_id}/resume",
                             {}, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/gas-ops/repair-work-orders/{work_order_id}/complete",
                             payload, headers)

    def cancel_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/gas-ops/repair-work-orders/{work_order_id}/cancel",
                             payload or {}, headers)

    # --- RegulatoryReport ---
    def create_report(self, payload, headers):
        return self._request("POST", "/gas-ops/regulatory-reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/gas-ops/regulatory-reports", headers=headers,
                             params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/gas-ops/regulatory-reports/{report_id}",
                             headers=headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/gas-ops/regulatory-reports/{report_id}/submit",
                             {}, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/gas-ops/regulatory-reports/{report_id}/accept",
                             {}, headers)

    def reject_report(self, report_id, payload, headers):
        return self._request("POST", f"/gas-ops/regulatory-reports/{report_id}/reject",
                             payload, headers)

    def regenerate_report(self, report_id, headers):
        return self._request("POST", f"/gas-ops/regulatory-reports/{report_id}/regenerate",
                             {}, headers)

    # --- PublicNotification ---
    def create_notification(self, incident_id, payload, headers):
        return self._request("POST", f"/gas-ops/incidents/{incident_id}/public-notifications",
                             payload, headers)

    def list_notifications(self, incident_id, headers, params=None):
        return self._request("GET", f"/gas-ops/incidents/{incident_id}/public-notifications",
                             headers=headers, params=params)

    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/gas-ops/public-notifications/{notification_id}",
                             headers=headers)

    def issue_notification(self, notification_id, headers):
        return self._request("POST", f"/gas-ops/public-notifications/{notification_id}/issue",
                             {}, headers)

    def retract_notification(self, notification_id, headers, payload=None):
        return self._request("POST",
                             f"/gas-ops/public-notifications/{notification_id}/retract",
                             payload or {}, headers)

    def discard_notification(self, notification_id, headers):
        return self._request("POST",
                             f"/gas-ops/public-notifications/{notification_id}/discard",
                             {}, headers)


api_client = ApiClient()
