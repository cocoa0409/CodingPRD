"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/pyro/_clock/set_current_utc", payload, headers)

    # --- Operators ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/pyro/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/pyro/operators/{operator_id}", headers=headers)

    def suspend_operator(self, operator_id, payload, headers):
        return self._request("POST", f"/pyro/operators/{operator_id}/suspend", payload, headers)

    def create_crew_member(self, operator_id, payload, headers):
        return self._request("POST", f"/pyro/operators/{operator_id}/crew-members", payload, headers)

    def list_crew_members(self, operator_id, headers, params=None):
        return self._request("GET", f"/pyro/operators/{operator_id}/crew-members", headers=headers, params=params)

    # --- Displays ---
    def create_display(self, payload, headers):
        return self._request("POST", "/pyro/displays", payload, headers)

    def get_display(self, display_id, headers):
        return self._request("GET", f"/pyro/displays/{display_id}", headers=headers)

    def list_displays(self, headers, params=None):
        return self._request("GET", "/pyro/displays", headers=headers, params=params)

    def standby_confirm(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/standby-confirm", payload, headers)

    def ready_display(self, display_id, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/ready", {}, headers)

    def go_no_go(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/go-no-go", payload, headers)

    def complete_show(self, display_id, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/complete-show", {}, headers)

    def cancel_display(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/cancel", payload, headers)

    # --- Site plans ---
    def create_site_plan(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/site-plans", payload, headers)

    def list_site_plans(self, display_id, headers, params=None):
        return self._request("GET", f"/pyro/displays/{display_id}/site-plans", headers=headers, params=params)

    # --- Permit applications ---
    def create_permit_application(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/permit-applications", payload, headers)

    def list_display_permit_applications(self, display_id, headers, params=None):
        return self._request("GET", f"/pyro/displays/{display_id}/permit-applications", headers=headers, params=params)

    def get_permit_application(self, application_id, headers):
        return self._request("GET", f"/pyro/permit-applications/{application_id}", headers=headers)

    def list_permit_applications(self, headers, params=None):
        return self._request("GET", "/pyro/permit-applications", headers=headers, params=params)

    def approve_permit(self, application_id, payload, headers):
        return self._request("POST", f"/pyro/permit-applications/{application_id}/approve", payload, headers)

    def deny_permit(self, application_id, payload, headers):
        return self._request("POST", f"/pyro/permit-applications/{application_id}/deny", payload, headers)

    def request_info_permit(self, application_id, payload, headers):
        return self._request("POST", f"/pyro/permit-applications/{application_id}/request-info", payload, headers)

    def resubmit_permit(self, application_id, payload, headers):
        return self._request("POST", f"/pyro/permit-applications/{application_id}/resubmit", payload, headers)

    # --- Magazines / batches / movements ---
    def create_magazine(self, payload, headers):
        return self._request("POST", "/pyro/magazines", payload, headers)

    def get_magazine(self, magazine_id, headers):
        return self._request("GET", f"/pyro/magazines/{magazine_id}", headers=headers)

    def list_magazines(self, headers, params=None):
        return self._request("GET", "/pyro/magazines", headers=headers, params=params)

    def create_batch(self, magazine_id, payload, headers):
        return self._request("POST", f"/pyro/magazines/{magazine_id}/batches", payload, headers)

    def list_batches(self, magazine_id, headers, params=None):
        return self._request("GET", f"/pyro/magazines/{magazine_id}/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/pyro/batches/{batch_id}", headers=headers)

    def quarantine_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/pyro/batches/{batch_id}/quarantine", payload, headers)

    def create_movement(self, batch_id, payload, headers):
        return self._request("POST", f"/pyro/batches/{batch_id}/movements", payload, headers)

    def list_batch_movements(self, batch_id, headers, params=None):
        return self._request("GET", f"/pyro/batches/{batch_id}/movements", headers=headers, params=params)

    def list_display_movements(self, display_id, headers, params=None):
        return self._request("GET", f"/pyro/displays/{display_id}/movements", headers=headers, params=params)

    # --- Weather ---
    def create_weather_reading(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/weather-readings", payload, headers)

    def list_weather_readings(self, display_id, headers, params=None):
        return self._request("GET", f"/pyro/displays/{display_id}/weather-readings", headers=headers, params=params)

    # --- Security posts ---
    def create_security_post(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/security-posts", payload, headers)

    def list_security_posts(self, display_id, headers, params=None):
        return self._request("GET", f"/pyro/displays/{display_id}/security-posts", headers=headers, params=params)

    def assign_guard(self, post_id, payload, headers):
        return self._request("POST", f"/pyro/security-posts/{post_id}/assign", payload, headers)

    # --- Misfires ---
    def create_misfire(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/misfires", payload, headers)

    def list_display_misfires(self, display_id, headers, params=None):
        return self._request("GET", f"/pyro/displays/{display_id}/misfires", headers=headers, params=params)

    def list_batch_misfires(self, batch_id, headers, params=None):
        return self._request("GET", f"/pyro/batches/{batch_id}/misfires", headers=headers, params=params)

    def dispose_misfire(self, misfire_id, payload, headers):
        return self._request("POST", f"/pyro/misfires/{misfire_id}/dispose", payload, headers)

    # --- Sweeps ---
    def create_sweep(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/sweeps", payload, headers)

    def list_sweeps(self, display_id, headers, params=None):
        return self._request("GET", f"/pyro/displays/{display_id}/sweeps", headers=headers, params=params)

    def verify_sweep(self, sweep_id, payload, headers):
        return self._request("POST", f"/pyro/sweeps/{sweep_id}/verify", payload, headers)

    # --- Incidents ---
    def create_incident(self, display_id, payload, headers):
        return self._request("POST", f"/pyro/displays/{display_id}/incidents", payload, headers)

    def list_incidents(self, display_id, headers, params=None):
        return self._request("GET", f"/pyro/displays/{display_id}/incidents", headers=headers, params=params)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/pyro/incidents/{incident_id}/close", payload, headers)


api_client = ApiClient()
