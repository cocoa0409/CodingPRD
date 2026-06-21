"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Clock (test-driving) ----------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------- Service ----------
    def create_service(self, payload, headers):
        return self._request("POST", "/services", payload, headers)

    def list_services(self, headers, params=None):
        return self._request("GET", "/services", headers=headers, params=params)

    def get_service(self, service_id, headers):
        return self._request("GET", f"/services/{service_id}", headers=headers)

    def get_budget_summary(self, service_id, headers):
        return self._request(
            "GET", f"/services/{service_id}/budget-summary", headers=headers
        )

    def list_service_incidents(self, service_id, headers, params=None):
        return self._request(
            "GET", f"/services/{service_id}/incidents", headers=headers, params=params
        )

    def list_service_maintenance_windows(self, service_id, headers, params=None):
        return self._request(
            "GET",
            f"/services/{service_id}/maintenance-windows",
            headers=headers,
            params=params,
        )

    def list_service_escalation_policies(self, service_id, headers, params=None):
        return self._request(
            "GET",
            f"/services/{service_id}/escalation-policies",
            headers=headers,
            params=params,
        )

    def list_service_on_call_schedules(self, service_id, headers, params=None):
        return self._request(
            "GET",
            f"/services/{service_id}/on-call-schedules",
            headers=headers,
            params=params,
        )

    # ---------- Responder ----------
    def create_responder(self, payload, headers):
        return self._request("POST", "/responders", payload, headers)

    def get_responder(self, responder_id, headers):
        return self._request("GET", f"/responders/{responder_id}", headers=headers)

    # ---------- OnCallSchedule + ScheduleShift ----------
    def create_on_call_schedule(self, payload, headers):
        return self._request("POST", "/on-call-schedules", payload, headers)

    def get_on_call_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/on-call-schedules/{schedule_id}", headers=headers
        )

    def create_schedule_shift(self, payload, headers):
        return self._request("POST", "/schedule-shifts", payload, headers)

    def list_schedule_shifts(self, headers, params=None):
        return self._request(
            "GET", "/schedule-shifts", headers=headers, params=params
        )

    def get_schedule_shift(self, shift_id, headers):
        return self._request("GET", f"/schedule-shifts/{shift_id}", headers=headers)

    # ---------- EscalationPolicy + EscalationTier ----------
    def create_escalation_policy(self, payload, headers):
        return self._request("POST", "/escalation-policies", payload, headers)

    def get_escalation_policy(self, policy_id, headers):
        return self._request(
            "GET", f"/escalation-policies/{policy_id}", headers=headers
        )

    def list_policy_incidents(self, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/escalation-policies/{policy_id}/incidents",
            headers=headers,
            params=params,
        )

    def create_escalation_tier(self, payload, headers):
        return self._request("POST", "/escalation-tiers", payload, headers)

    def list_escalation_tiers(self, headers, params=None):
        return self._request(
            "GET", "/escalation-tiers", headers=headers, params=params
        )

    def get_escalation_tier(self, tier_id, headers):
        return self._request("GET", f"/escalation-tiers/{tier_id}", headers=headers)

    # ---------- MaintenanceWindow ----------
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/maintenance-windows", payload, headers)

    def get_maintenance_window(self, window_id, headers):
        return self._request(
            "GET", f"/maintenance-windows/{window_id}", headers=headers
        )

    def activate_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/activate", {}, headers
        )

    def end_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/end", {}, headers
        )

    def cancel_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/cancel", {}, headers
        )

    # ---------- Incident ----------
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def acknowledge_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/acknowledge", {}, headers
        )

    def resolve_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/resolve", {}, headers
        )

    def escalate_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incidents/{incident_id}/escalate", payload, headers
        )

    def list_incident_page_attempts(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/page-attempts",
            headers=headers,
            params=params,
        )

    def list_page_attempts(self, headers, params=None):
        return self._request(
            "GET", "/page-attempts", headers=headers, params=params
        )

    def get_page_attempt(self, page_attempt_id, headers):
        return self._request(
            "GET", f"/page-attempts/{page_attempt_id}", headers=headers
        )

    # ---------- WarRoom + WarRoomMessage ----------
    def create_war_room(self, payload, headers):
        return self._request("POST", "/war-rooms", payload, headers)

    def get_war_room(self, war_room_id, headers):
        return self._request("GET", f"/war-rooms/{war_room_id}", headers=headers)

    def list_incident_war_rooms(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/war-rooms",
            headers=headers,
            params=params,
        )

    def close_war_room(self, war_room_id, headers):
        return self._request(
            "POST", f"/war-rooms/{war_room_id}/close", {}, headers
        )

    def create_war_room_message(self, war_room_id, payload, headers):
        return self._request(
            "POST", f"/war-rooms/{war_room_id}/messages", payload, headers
        )

    def list_war_room_messages(self, war_room_id, headers, params=None):
        return self._request(
            "GET",
            f"/war-rooms/{war_room_id}/messages",
            headers=headers,
            params=params,
        )

    # ---------- Postmortem + ActionItem ----------
    def create_postmortem(self, payload, headers):
        return self._request("POST", "/postmortems", payload, headers)

    def get_postmortem(self, postmortem_id, headers):
        return self._request("GET", f"/postmortems/{postmortem_id}", headers=headers)

    def list_incident_postmortems(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"/incidents/{incident_id}/postmortems",
            headers=headers,
            params=params,
        )

    def submit_postmortem(self, postmortem_id, headers):
        return self._request(
            "POST", f"/postmortems/{postmortem_id}/submit", {}, headers
        )

    def return_postmortem(self, postmortem_id, headers):
        return self._request(
            "POST", f"/postmortems/{postmortem_id}/return", {}, headers
        )

    def publish_postmortem(self, postmortem_id, headers):
        return self._request(
            "POST", f"/postmortems/{postmortem_id}/publish", {}, headers
        )

    def create_action_item(self, payload, headers):
        return self._request("POST", "/action-items", payload, headers)

    def get_action_item(self, action_item_id, headers):
        return self._request(
            "GET", f"/action-items/{action_item_id}", headers=headers
        )

    def list_postmortem_action_items(self, postmortem_id, headers, params=None):
        return self._request(
            "GET",
            f"/postmortems/{postmortem_id}/action-items",
            headers=headers,
            params=params,
        )

    def list_action_items(self, headers, params=None):
        return self._request(
            "GET", "/action-items", headers=headers, params=params
        )

    def start_action_item(self, action_item_id, headers):
        return self._request(
            "POST", f"/action-items/{action_item_id}/start", {}, headers
        )

    def complete_action_item(self, action_item_id, headers):
        return self._request(
            "POST", f"/action-items/{action_item_id}/complete", {}, headers
        )

    def cancel_action_item(self, action_item_id, headers):
        return self._request(
            "POST", f"/action-items/{action_item_id}/cancel", {}, headers
        )


api_client = ApiClient()
