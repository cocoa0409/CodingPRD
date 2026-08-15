"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The runner SIGKILLs and respawns the server on the same port before
        # every test (per-test-server isolation). A pooled keep-alive
        # connection can then race the respawn ("Remote end closed connection
        # without response"). Sending Connection: close makes every request
        # use a fresh TCP connection, eliminating the stale-pool race.
        self.session.headers["Connection"] = "close"

    # --- SubscriptionPlan ---
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/ag-drone/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/ag-drone/subscription-plans/{plan_id}",
                             headers=headers)

    def list_subscription_plans(self, headers, params=None):
        return self._request("GET", "/ag-drone/subscription-plans",
                             headers=headers, params=params)

    # --- Grower ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/ag-drone/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/ag-drone/growers/{grower_id}", headers=headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/ag-drone/growers", headers=headers, params=params)

    def patch_grower(self, grower_id, payload, headers):
        return self._request("PATCH", f"/ag-drone/growers/{grower_id}", payload, headers)

    def suspend_grower(self, grower_id, headers):
        return self._request("POST", f"/ag-drone/growers/{grower_id}/suspend",
                             headers=headers)

    def reinstate_grower(self, grower_id, headers):
        return self._request("POST", f"/ag-drone/growers/{grower_id}/reinstate",
                             headers=headers)

    def terminate_grower(self, grower_id, headers):
        return self._request("POST", f"/ag-drone/growers/{grower_id}/terminate",
                             headers=headers)

    def run_invoice(self, grower_id, payload, headers):
        return self._request("POST", f"/ag-drone/growers/{grower_id}/invoice",
                             payload, headers)

    # --- Field ---
    def create_field(self, grower_id, payload, headers):
        return self._request("POST", f"/ag-drone/growers/{grower_id}/fields",
                             payload, headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/ag-drone/fields/{field_id}", headers=headers)

    def list_fields(self, grower_id, headers, params=None):
        return self._request("GET", f"/ag-drone/growers/{grower_id}/fields",
                             headers=headers, params=params)

    # --- PilotProfile ---
    def create_pilot(self, payload, headers):
        return self._request("POST", "/ag-drone/pilots", payload, headers)

    def get_pilot(self, pilot_id, headers):
        return self._request("GET", f"/ag-drone/pilots/{pilot_id}", headers=headers)

    def list_pilots(self, headers, params=None):
        return self._request("GET", "/ag-drone/pilots", headers=headers, params=params)

    # --- AirspaceAuthorization ---
    def create_authorization(self, payload, headers):
        return self._request("POST", "/ag-drone/airspace-authorizations",
                             payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET",
                             f"/ag-drone/airspace-authorizations/{authorization_id}",
                             headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/ag-drone/airspace-authorizations",
                             headers=headers, params=params)

    def revoke_authorization(self, authorization_id, headers):
        return self._request(
            "POST", f"/ag-drone/airspace-authorizations/{authorization_id}/revoke",
            headers=headers)

    # --- FlightMission ---
    def create_mission(self, field_id, payload, headers):
        return self._request("POST", f"/ag-drone/fields/{field_id}/missions",
                             payload, headers)

    def get_mission(self, mission_id, headers):
        return self._request("GET", f"/ag-drone/missions/{mission_id}", headers=headers)

    def list_field_missions(self, field_id, headers, params=None):
        return self._request("GET", f"/ag-drone/fields/{field_id}/missions",
                             headers=headers, params=params)

    def list_missions(self, headers, params=None):
        return self._request("GET", "/ag-drone/missions", headers=headers, params=params)

    def authorize_mission(self, mission_id, headers):
        return self._request("POST", f"/ag-drone/missions/{mission_id}/authorize",
                             headers=headers)

    def launch_mission(self, mission_id, headers):
        return self._request("POST", f"/ag-drone/missions/{mission_id}/launch",
                             headers=headers)

    def capture_mission(self, mission_id, payload, headers):
        return self._request("POST", f"/ag-drone/missions/{mission_id}/capture",
                             payload, headers)

    def abort_weather_mission(self, mission_id, payload, headers):
        return self._request("POST", f"/ag-drone/missions/{mission_id}/abort-weather",
                             payload, headers)

    def complete_mission(self, mission_id, payload, headers):
        return self._request("POST", f"/ag-drone/missions/{mission_id}/complete",
                             payload, headers)

    def cancel_mission(self, mission_id, headers):
        return self._request("POST", f"/ag-drone/missions/{mission_id}/cancel",
                             headers=headers)

    def replan_mission(self, mission_id, payload, headers):
        return self._request("POST", f"/ag-drone/missions/{mission_id}/replan",
                             payload, headers)

    # --- ImageryDeliverable ---
    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/ag-drone/deliverables/{deliverable_id}",
                             headers=headers)

    def list_mission_deliverables(self, mission_id, headers, params=None):
        return self._request("GET", f"/ag-drone/missions/{mission_id}/deliverables",
                             headers=headers, params=params)

    def process_deliverable(self, deliverable_id, payload, headers):
        return self._request("POST", f"/ag-drone/deliverables/{deliverable_id}/process",
                             payload, headers)

    def deliver_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/ag-drone/deliverables/{deliverable_id}/deliver",
                             headers=headers)

    # --- ScoutingAlert ---
    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/ag-drone/alerts/{alert_id}", headers=headers)

    def list_field_alerts(self, field_id, headers, params=None):
        return self._request("GET", f"/ag-drone/fields/{field_id}/alerts",
                             headers=headers, params=params)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/ag-drone/alerts", headers=headers, params=params)

    def claim_alert(self, alert_id, headers):
        return self._request("POST", f"/ag-drone/alerts/{alert_id}/claim",
                             headers=headers)

    def review_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/ag-drone/alerts/{alert_id}/review",
                             payload, headers)

    def release_alert(self, alert_id, headers):
        return self._request("POST", f"/ag-drone/alerts/{alert_id}/release",
                             headers=headers)

    # --- SprayMissionRecord ---
    def get_spray_record(self, mission_id, headers):
        return self._request("GET", f"/ag-drone/missions/{mission_id}/spray-record",
                             headers=headers)

    # --- InsuranceClaim ---
    def create_claim(self, grower_id, payload, headers):
        return self._request("POST", f"/ag-drone/growers/{grower_id}/claims",
                             payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/ag-drone/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/ag-drone/claims", headers=headers, params=params)

    def list_grower_claims(self, grower_id, headers, params=None):
        return self._request("GET", f"/ag-drone/growers/{grower_id}/claims",
                             headers=headers, params=params)

    def open_claim_review(self, claim_id, headers):
        return self._request("POST", f"/ag-drone/claims/{claim_id}/open-review",
                             headers=headers)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/ag-drone/claims/{claim_id}/approve",
                             payload, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/ag-drone/claims/{claim_id}/deny",
                             headers=headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/ag-drone/claims/{claim_id}/pay",
                             headers=headers)

    # --- Logical clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/ag-drone/_clock/set_current_utc",
                             payload, headers)


api_client = ApiClient()
