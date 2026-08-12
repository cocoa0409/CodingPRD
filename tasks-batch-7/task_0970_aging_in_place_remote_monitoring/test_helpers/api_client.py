"""API client: one method per endpoint defined in PRD section 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Aging In Place Monitoring API (all under /v1)."""

    # --- Logical clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- Seniors ---
    def create_senior(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/seniors", payload, headers)

    def get_senior(self, senior_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/v1/seniors/{senior_id}", headers=headers)

    def list_seniors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/v1/seniors", headers=headers, params=params)

    def get_senior_dashboard(self, senior_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/seniors/{senior_id}/dashboard", headers=headers
        )

    # --- Subscription plans ---
    def create_subscription_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/v1/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/subscription-plans/{plan_id}", headers=headers
        )

    def list_subscription_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/subscription-plans", headers=headers, params=params
        )

    # --- Subscriptions ---
    def create_subscription(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/subscriptions", payload, headers)

    def get_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/subscriptions", headers=headers, params=params
        )

    def activate_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/subscriptions/{subscription_id}/activate", {}, headers
        )

    def record_payment(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/v1/subscriptions/{subscription_id}/record-payment",
            payload,
            headers,
        )

    def change_plan(
        self, subscription_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/v1/subscriptions/{subscription_id}/change-plan",
            payload,
            headers,
        )

    def resume_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/subscriptions/{subscription_id}/resume", {}, headers
        )

    def cancel_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/subscriptions/{subscription_id}/cancel", {}, headers
        )

    # --- Sensor kits ---
    def create_sensor_kit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/sensor-kits", payload, headers)

    def get_sensor_kit(self, kit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/v1/sensor-kits/{kit_id}", headers=headers)

    def list_sensor_kits(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/v1/sensor-kits", headers=headers, params=params)

    def ship_sensor_kit(self, kit_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/sensor-kits/{kit_id}/ship", {}, headers
        )

    def mark_sensor_kit_delivered(self, kit_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/sensor-kits/{kit_id}/mark-delivered", {}, headers
        )

    # --- Devices ---
    def get_device(self, device_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/v1/devices/{device_id}", headers=headers)

    def list_devices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/v1/devices", headers=headers, params=params)

    def decommission_device(self, device_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/devices/{device_id}/decommission", {}, headers
        )

    # --- Telemetry / sensor events ---
    def ingest_telemetry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/telemetry", payload, headers)

    def get_sensor_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/sensor-events/{event_id}", headers=headers
        )

    def list_sensor_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/sensor-events", headers=headers, params=params
        )

    # --- Installers ---
    def create_installer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/installers", payload, headers)

    def get_installer(self, installer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/v1/installers/{installer_id}", headers=headers)

    def list_installers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/v1/installers", headers=headers, params=params)

    # --- Install appointments ---
    def create_install_appointment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/v1/install-appointments", payload, headers)

    def get_install_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/install-appointments/{appointment_id}", headers=headers
        )

    def list_install_appointments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/install-appointments", headers=headers, params=params
        )

    def confirm_install_appointment(
        self, appointment_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/v1/install-appointments/{appointment_id}/confirm",
            {},
            headers,
        )

    def complete_install_appointment(
        self, appointment_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/v1/install-appointments/{appointment_id}/complete",
            {},
            headers,
        )

    def cancel_install_appointment(
        self, appointment_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/v1/install-appointments/{appointment_id}/cancel",
            {},
            headers,
        )

    def reschedule_install_appointment(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/v1/install-appointments/{appointment_id}/reschedule",
            payload,
            headers,
        )

    # --- Caregivers ---
    def create_caregiver(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/caregivers", payload, headers)

    def get_caregiver(self, caregiver_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/v1/caregivers/{caregiver_id}", headers=headers)

    def list_caregivers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/v1/caregivers", headers=headers, params=params)

    # --- Contact tree entries ---
    def create_contact_tree_entry(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/v1/contact-tree-entries", payload, headers)

    def get_contact_tree_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/contact-tree-entries/{entry_id}", headers=headers
        )

    def list_contact_tree_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/contact-tree-entries", headers=headers, params=params
        )

    def update_contact_tree_entry(
        self, entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/v1/contact-tree-entries/{entry_id}", payload, headers
        )

    def delete_contact_tree_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/v1/contact-tree-entries/{entry_id}", headers=headers
        )

    # --- Alerts ---
    def create_alert(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/alerts", payload, headers)

    def get_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/v1/alerts/{alert_id}", headers=headers)

    def list_alerts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/v1/alerts", headers=headers, params=params)

    def acknowledge_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/alerts/{alert_id}/acknowledge", {}, headers
        )

    def resolve_alert(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/v1/alerts/{alert_id}/resolve", payload, headers
        )

    def mark_false_alarm(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/v1/alerts/{alert_id}/mark-false-alarm", payload, headers
        )

    def reopen_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/v1/alerts/{alert_id}/reopen", {}, headers)

    # --- Alert notifications ---
    def get_alert_notification(self, notification_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/alert-notifications/{notification_id}", headers=headers
        )

    def list_alert_notifications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/alert-notifications", headers=headers, params=params
        )

    # --- Medication schedules ---
    def create_medication_schedule(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/v1/medication-schedules", payload, headers)

    def get_medication_schedule(self, schedule_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/medication-schedules/{schedule_id}", headers=headers
        )

    def list_medication_schedules(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/medication-schedules", headers=headers, params=params
        )

    def end_medication_schedule(self, schedule_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/medication-schedules/{schedule_id}/end", {}, headers
        )

    # --- Dose events ---
    def get_dose_event(self, dose_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/v1/dose-events/{dose_id}", headers=headers)

    def list_dose_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/v1/dose-events", headers=headers, params=params)

    def confirm_dose_event(self, dose_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/dose-events/{dose_id}/confirm", {}, headers
        )

    # --- Check-ins ---
    def create_check_in(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/v1/check-ins", payload, headers)

    def get_check_in(self, checkin_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/v1/check-ins/{checkin_id}", headers=headers)

    def list_check_ins(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/v1/check-ins", headers=headers, params=params)

    # --- Wellness reports ---
    def create_wellness_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/v1/wellness-reports", payload, headers)

    def get_wellness_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/v1/wellness-reports/{report_id}", headers=headers
        )

    def list_wellness_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/v1/wellness-reports", headers=headers, params=params
        )

    def regenerate_wellness_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/v1/wellness-reports/{report_id}/regenerate",
            payload,
            headers,
        )

    def deliver_wellness_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/v1/wellness-reports/{report_id}/deliver", {}, headers
        )


api_client = ApiClient()
