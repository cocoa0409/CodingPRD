"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- infra / test-driving ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_tick(self, headers):
        return self._request("POST", "/_tick/run", {}, headers)

    def ingest_incident(self, payload, headers):
        return self._request("POST", "/_integration/ingest_incident", payload, headers)

    # ---- Contact ----
    def create_contact(self, payload, headers):
        return self._request("POST", "/contacts", payload, headers)

    def get_contact(self, contact_id, headers, params=None):
        return self._request("GET", f"/contacts/{contact_id}", headers=headers, params=params)

    def add_channel(self, contact_id, payload, headers):
        return self._request("POST", f"/contacts/{contact_id}/channels", payload, headers)

    def list_channels(self, contact_id, headers, params=None):
        return self._request("GET", f"/contacts/{contact_id}/channels", headers=headers, params=params)

    def confirm_channel(self, channel_id, payload, headers):
        return self._request("POST", f"/channels/{channel_id}/confirm", payload, headers)

    def opt_out_channel(self, channel_id, headers):
        return self._request("POST", f"/channels/{channel_id}/opt-out", {}, headers)

    # ---- Group ----
    def create_group(self, payload, headers):
        return self._request("POST", "/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/groups/{group_id}", headers=headers)

    def close_group(self, group_id, headers):
        return self._request("POST", f"/groups/{group_id}/close", {}, headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    # ---- Template ----
    def create_template(self, payload, headers):
        return self._request("POST", "/templates", payload, headers)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/templates/{template_id}", headers=headers)

    def publish_template(self, template_id, headers):
        return self._request("POST", f"/templates/{template_id}/publish", {}, headers)

    # ---- Alert ----
    def create_alert(self, payload, headers):
        return self._request("POST", "/alerts", payload, headers)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/alerts/{alert_id}", headers=headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/alerts", headers=headers, params=params)

    def add_localization(self, alert_id, payload, headers):
        return self._request("POST", f"/alerts/{alert_id}/localizations", payload, headers)

    def list_localizations(self, alert_id, headers, params=None):
        return self._request("GET", f"/alerts/{alert_id}/localizations", headers=headers, params=params)

    def submit_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/submit", {}, headers)

    def approve_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/approve", {}, headers)

    def reject_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/alerts/{alert_id}/reject", payload, headers)

    def preview_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/preview", {}, headers)

    def dispatch_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/alerts/{alert_id}/dispatch", payload, headers)

    def cancel_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/cancel", {}, headers)

    def close_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/close", {}, headers)

    # ---- Notification ----
    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/notifications/{notification_id}", headers=headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/notifications", headers=headers, params=params)

    def delivery_report(self, notification_id, payload, headers):
        return self._request("POST", f"/notifications/{notification_id}/delivery-report", payload, headers)

    def acknowledge_notification(self, notification_id, headers):
        return self._request("POST", f"/notifications/{notification_id}/acknowledge", {}, headers)

    # ---- Gateway ----
    def create_gateway(self, payload, headers):
        return self._request("POST", "/gateways", payload, headers)

    def get_gateway(self, gateway_id, headers):
        return self._request("GET", f"/gateways/{gateway_id}", headers=headers)

    def toggle_gateway(self, gateway_id, payload, headers):
        return self._request("POST", f"/gateways/{gateway_id}/toggle", payload, headers)

    def create_maintenance_window(self, gateway_id, payload, headers):
        return self._request("POST", f"/gateways/{gateway_id}/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, gateway_id, headers, params=None):
        return self._request("GET", f"/gateways/{gateway_id}/maintenance-windows", headers=headers, params=params)

    # ---- Drill ----
    def create_drill(self, payload, headers):
        return self._request("POST", "/drills", payload, headers)

    def get_drill(self, drill_id, headers):
        return self._request("GET", f"/drills/{drill_id}", headers=headers)

    def list_drills(self, headers, params=None):
        return self._request("GET", "/drills", headers=headers, params=params)

    def cancel_drill(self, drill_id, headers):
        return self._request("POST", f"/drills/{drill_id}/cancel", {}, headers)


api_client = ApiClient()
