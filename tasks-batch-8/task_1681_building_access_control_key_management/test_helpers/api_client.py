"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Building / clock ---
    def create_building(self, payload, headers):
        return self._request("POST", "/buildings", payload, headers)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/buildings/{building_id}", headers=headers)

    def run_ops(self, building_id, headers):
        return self._request("POST", f"/buildings/{building_id}/run-ops", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- KeyNode ---
    def create_key_node(self, payload, headers):
        return self._request("POST", "/key-nodes", payload, headers)

    def list_key_nodes(self, headers, params=None):
        return self._request("GET", "/key-nodes", headers=headers, params=params)

    def get_key_node(self, key_node_id, headers):
        return self._request("GET", f"/key-nodes/{key_node_id}", headers=headers)

    # --- Door ---
    def create_door(self, payload, headers):
        return self._request("POST", "/doors", payload, headers)

    def list_doors(self, headers, params=None):
        return self._request("GET", "/doors", headers=headers, params=params)

    def get_door(self, door_id, headers):
        return self._request("GET", f"/doors/{door_id}", headers=headers)

    def patch_door(self, door_id, payload, headers):
        return self._request("PATCH", f"/doors/{door_id}", payload, headers)

    def close_door(self, door_id, headers):
        return self._request("POST", f"/doors/{door_id}/close", {}, headers)

    def access_check(self, door_id, payload, headers):
        return self._request("POST", f"/doors/{door_id}/access-checks", payload, headers)

    # --- AccessEvent ---
    def list_access_events(self, headers, params=None):
        return self._request("GET", "/access-events", headers=headers, params=params)

    def get_access_event(self, access_event_id, headers):
        return self._request("GET", f"/access-events/{access_event_id}", headers=headers)

    # --- Person ---
    def create_person(self, payload, headers):
        return self._request("POST", "/persons", payload, headers)

    def list_persons(self, headers, params=None):
        return self._request("GET", "/persons", headers=headers, params=params)

    def get_person(self, person_id, headers):
        return self._request("GET", f"/persons/{person_id}", headers=headers)

    def move_out_person(self, person_id, headers):
        return self._request("POST", f"/persons/{person_id}/move-out", {}, headers)

    def terminate_person(self, person_id, headers):
        return self._request("POST", f"/persons/{person_id}/terminate", {}, headers)

    # --- Credential ---
    def create_credential(self, payload, headers):
        return self._request("POST", "/credentials", payload, headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/credentials", headers=headers, params=params)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def issue_credential(self, credential_id, payload, headers):
        return self._request("POST", f"/credentials/{credential_id}/issue", payload, headers)

    def return_credential(self, credential_id, headers):
        return self._request("POST", f"/credentials/{credential_id}/return", {}, headers)

    def report_lost_credential(self, credential_id, headers):
        return self._request("POST", f"/credentials/{credential_id}/report-lost", {}, headers)

    # --- AccessGroup ---
    def create_access_group(self, payload, headers):
        return self._request("POST", "/access-groups", payload, headers)

    def list_access_groups(self, headers, params=None):
        return self._request("GET", "/access-groups", headers=headers, params=params)

    def get_access_group(self, access_group_id, headers):
        return self._request("GET", f"/access-groups/{access_group_id}", headers=headers)

    def patch_access_group(self, access_group_id, payload, headers):
        return self._request("PATCH", f"/access-groups/{access_group_id}", payload, headers)

    def delete_access_group(self, access_group_id, headers):
        return self._request("DELETE", f"/access-groups/{access_group_id}", headers=headers)

    # --- Incident ---
    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def start_incident_review(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/start-review", {}, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/resolve", payload, headers)

    def dismiss_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/dismiss", {}, headers)

    def reopen_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/reopen", {}, headers)

    # --- RekeyCampaign ---
    def create_rekey_campaign(self, payload, headers):
        return self._request("POST", "/rekey-campaigns", payload, headers)

    def list_rekey_campaigns(self, headers, params=None):
        return self._request("GET", "/rekey-campaigns", headers=headers, params=params)

    def get_rekey_campaign(self, campaign_id, headers):
        return self._request("GET", f"/rekey-campaigns/{campaign_id}", headers=headers)

    def approve_rekey_campaign(self, campaign_id, headers):
        return self._request("POST", f"/rekey-campaigns/{campaign_id}/approve", {}, headers)

    def cancel_rekey_campaign(self, campaign_id, headers):
        return self._request("POST", f"/rekey-campaigns/{campaign_id}/cancel", {}, headers)

    # --- MaintenanceWorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", {}, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    # --- Charge ---
    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def issue_charge(self, charge_id, headers):
        return self._request("POST", f"/charges/{charge_id}/issue", {}, headers)

    def pay_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/pay", payload, headers)

    def void_charge(self, charge_id, headers):
        return self._request("POST", f"/charges/{charge_id}/void", {}, headers)

    # --- ProppedDoorAlert ---
    def list_propped_alerts(self, headers, params=None):
        return self._request("GET", "/propped-alerts", headers=headers, params=params)

    def get_propped_alert(self, alert_id, headers):
        return self._request("GET", f"/propped-alerts/{alert_id}", headers=headers)

    def acknowledge_propped_alert(self, alert_id, headers):
        return self._request("POST", f"/propped-alerts/{alert_id}/acknowledge", {}, headers)

    def resolve_propped_alert(self, alert_id, headers):
        return self._request("POST", f"/propped-alerts/{alert_id}/resolve", {}, headers)


api_client = ApiClient()
