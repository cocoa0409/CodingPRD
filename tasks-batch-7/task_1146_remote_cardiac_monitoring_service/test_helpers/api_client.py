"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/v1/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/v1/patients/{patient_id}", headers=headers)

    # --- Physicians ---
    def create_physician(self, payload, headers):
        return self._request("POST", "/v1/physicians", payload, headers)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/v1/physicians/{physician_id}", headers=headers)

    # --- Technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/v1/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/v1/technicians/{technician_id}", headers=headers)

    # --- Devices ---
    def create_device(self, payload, headers):
        return self._request("POST", "/v1/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/v1/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/v1/devices", headers=headers, params=params)

    # --- Monitoring orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/v1/monitoring-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/v1/monitoring-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/v1/monitoring-orders", headers=headers, params=params)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/v1/monitoring-orders/{order_id}/cancel", {}, headers)

    # --- Enrollments ---
    def create_enrollment(self, order_id, payload, headers):
        return self._request("POST", f"/v1/monitoring-orders/{order_id}/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/v1/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/v1/enrollments/{enrollment_id}", headers=headers)

    def complete_education(self, enrollment_id, payload, headers):
        return self._request("POST", f"/v1/enrollments/{enrollment_id}/complete-education", payload, headers)

    def activate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/v1/enrollments/{enrollment_id}/activate", payload, headers)

    def retry_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/v1/enrollments/{enrollment_id}/retry", payload, headers)

    def abort_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/v1/enrollments/{enrollment_id}/abort", {}, headers)

    # --- Episodes ---
    def list_episodes(self, headers, params=None):
        return self._request("GET", "/v1/episodes", headers=headers, params=params)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/v1/episodes/{episode_id}", headers=headers)

    def complete_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/v1/episodes/{episode_id}/complete", payload, headers)

    def resume_episode(self, episode_id, headers):
        return self._request("POST", f"/v1/episodes/{episode_id}/resume", {}, headers)

    def list_suspension_intervals(self, episode_id, headers, params=None):
        return self._request("GET", f"/v1/episodes/{episode_id}/suspension-intervals", headers=headers, params=params)

    # --- Transmissions ---
    def ingest_transmission(self, episode_id, payload, headers):
        return self._request("POST", f"/v1/episodes/{episode_id}/transmissions", payload, headers)

    def list_transmissions(self, episode_id, headers, params=None):
        return self._request("GET", f"/v1/episodes/{episode_id}/transmissions", headers=headers, params=params)

    def reprocess_transmission(self, transmission_id, payload, headers):
        return self._request("POST", f"/v1/transmissions/{transmission_id}/reprocess", payload, headers)

    # --- Arrhythmia alerts ---
    def raise_alert(self, episode_id, payload, headers):
        return self._request("POST", f"/v1/episodes/{episode_id}/alerts", payload, headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/v1/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/v1/alerts/{alert_id}", headers=headers)

    def acknowledge_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/alerts/{alert_id}/acknowledge", {}, headers)

    def release_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/alerts/{alert_id}/release", {}, headers)

    def triage_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/v1/alerts/{alert_id}/triage", payload, headers)

    def notify_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/alerts/{alert_id}/notify", {}, headers)

    def escalate_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/alerts/{alert_id}/escalate", {}, headers)

    def close_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/v1/alerts/{alert_id}/close", payload, headers)

    # --- Notification attempts ---
    def list_notification_attempts(self, headers, params=None):
        return self._request("GET", "/v1/notification-attempts", headers=headers, params=params)

    def get_notification_attempt(self, attempt_id, headers):
        return self._request("GET", f"/v1/notification-attempts/{attempt_id}", headers=headers)

    def acknowledge_notification_attempt(self, attempt_id, headers):
        return self._request("POST", f"/v1/notification-attempts/{attempt_id}/acknowledge", {}, headers)

    # --- Diagnostic reports ---
    def create_report(self, episode_id, payload, headers):
        return self._request("POST", f"/v1/episodes/{episode_id}/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/v1/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/v1/reports/{report_id}", headers=headers)

    def finalize_report(self, report_id, headers):
        return self._request("POST", f"/v1/reports/{report_id}/finalize", {}, headers)

    def amend_report(self, report_id, payload, headers):
        return self._request("POST", f"/v1/reports/{report_id}/amend", payload, headers)

    # --- Billing periods ---
    def generate_billing_periods(self, episode_id, headers):
        return self._request("POST", f"/v1/episodes/{episode_id}/billing-periods/generate", {}, headers)

    def list_billing_periods(self, headers, params=None):
        return self._request("GET", "/v1/billing-periods", headers=headers, params=params)

    def get_billing_period(self, period_id, headers):
        return self._request("GET", f"/v1/billing-periods/{period_id}", headers=headers)

    def submit_billing_period(self, period_id, headers):
        return self._request("POST", f"/v1/billing-periods/{period_id}/submit", {}, headers)

    def propose_adjustment(self, period_id, payload, headers):
        return self._request("POST", f"/v1/billing-periods/{period_id}/propose-adjustment", payload, headers)

    def approve_adjustment(self, period_id, headers):
        return self._request("POST", f"/v1/billing-periods/{period_id}/approve-adjustment", {}, headers)

    # --- Return shipments ---
    def create_return_shipment(self, episode_id, headers):
        return self._request("POST", f"/v1/episodes/{episode_id}/return-shipments", {}, headers)

    def list_return_shipments(self, headers, params=None):
        return self._request("GET", "/v1/return-shipments", headers=headers, params=params)

    def get_return_shipment(self, shipment_id, headers):
        return self._request("GET", f"/v1/return-shipments/{shipment_id}", headers=headers)

    def mark_shipment_received(self, shipment_id, headers):
        return self._request("POST", f"/v1/return-shipments/{shipment_id}/mark-received", {}, headers)

    # --- Compliance events ---
    def list_compliance_events(self, headers, params=None):
        return self._request("GET", "/v1/compliance-events", headers=headers, params=params)

    def get_compliance_event(self, event_id, headers):
        return self._request("GET", f"/v1/compliance-events/{event_id}", headers=headers)

    def resolve_compliance_event(self, event_id, payload, headers):
        return self._request("POST", f"/v1/compliance-events/{event_id}/resolve", payload, headers)

    # --- Test-driving operations ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/v1/_ops/run-daily-sweep", {}, headers)


api_client = ApiClient()
