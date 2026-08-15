"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- substations ---
    def create_substation(self, payload, headers):
        return self._request("POST", "/substations", payload, headers)

    def list_substations(self, headers, params=None):
        return self._request("GET", "/substations", headers=headers, params=params)

    def decommission_substation(self, substation_id, headers):
        return self._request("POST", f"/substations/{substation_id}/decommission", {}, headers)

    # --- asset class policies ---
    def create_asset_class_policy(self, payload, headers):
        return self._request("POST", "/asset-class-policies", payload, headers)

    def list_asset_class_policies(self, headers, params=None):
        return self._request("GET", "/asset-class-policies", headers=headers, params=params)

    # --- assets ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def get_asset_forecast(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}/forecast", headers=headers)

    def decommission_asset(self, asset_id, headers):
        return self._request("POST", f"/assets/{asset_id}/decommission", {}, headers)

    # --- outage windows ---
    def create_outage_window(self, payload, headers):
        return self._request("POST", "/outage-windows", payload, headers)

    def list_outage_windows(self, headers, params=None):
        return self._request("GET", "/outage-windows", headers=headers, params=params)

    def get_outage_window(self, window_id, headers):
        return self._request("GET", f"/outage-windows/{window_id}", headers=headers)

    def approve_outage_window(self, window_id, headers):
        return self._request("POST", f"/outage-windows/{window_id}/approve", {}, headers)

    def reject_outage_window(self, window_id, headers):
        return self._request("POST", f"/outage-windows/{window_id}/reject", {}, headers)

    def cancel_outage_window(self, window_id, headers):
        return self._request("POST", f"/outage-windows/{window_id}/cancel", {}, headers)

    def begin_switching(self, window_id, headers):
        return self._request("POST", f"/outage-windows/{window_id}/begin-switching", {}, headers)

    def clear_outage_window(self, window_id, headers):
        return self._request("POST", f"/outage-windows/{window_id}/clear", {}, headers)

    def restore_outage_window(self, window_id, headers):
        return self._request("POST", f"/outage-windows/{window_id}/restore", {}, headers)

    # --- switching steps ---
    def create_switching_step(self, window_id, payload, headers):
        return self._request("POST", f"/outage-windows/{window_id}/switching-steps", payload, headers)

    def list_switching_steps(self, window_id, headers, params=None):
        return self._request("GET", f"/outage-windows/{window_id}/switching-steps", headers=headers, params=params)

    def execute_switching_step(self, step_id, headers):
        return self._request("POST", f"/switching-steps/{step_id}/execute", {}, headers)

    def verify_switching_step(self, step_id, headers):
        return self._request("POST", f"/switching-steps/{step_id}/verify", {}, headers)

    # --- test events ---
    def create_test_event(self, payload, headers):
        return self._request("POST", "/test-events", payload, headers)

    def list_test_events(self, headers, params=None):
        return self._request("GET", "/test-events", headers=headers, params=params)

    def get_test_event(self, event_id, headers):
        return self._request("GET", f"/test-events/{event_id}", headers=headers)

    def submit_test_event(self, event_id, headers):
        return self._request("POST", f"/test-events/{event_id}/submit", {}, headers)

    def review_test_event(self, event_id, payload, headers):
        return self._request("POST", f"/test-events/{event_id}/review", payload, headers)

    # --- defects ---
    def create_defect(self, payload, headers):
        return self._request("POST", "/defects", payload, headers)

    def list_defects(self, headers, params=None):
        return self._request("GET", "/defects", headers=headers, params=params)

    def get_defect(self, defect_id, headers):
        return self._request("GET", f"/defects/{defect_id}", headers=headers)

    def defer_defect(self, defect_id, payload, headers):
        return self._request("POST", f"/defects/{defect_id}/defer", payload, headers)

    # --- work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/schedule", payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", {}, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def verify_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/verify", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    # --- spare units and reservations ---
    def create_spare_unit(self, payload, headers):
        return self._request("POST", "/spare-units", payload, headers)

    def list_spare_units(self, headers, params=None):
        return self._request("GET", "/spare-units", headers=headers, params=params)

    def get_spare_unit(self, unit_id, headers):
        return self._request("GET", f"/spare-units/{unit_id}", headers=headers)

    def decommission_spare_unit(self, unit_id, headers):
        return self._request("POST", f"/spare-units/{unit_id}/decommission", {}, headers)

    def list_spare_unit_reservations(self, unit_id, headers, params=None):
        return self._request("GET", f"/spare-units/{unit_id}/reservations", headers=headers, params=params)

    def create_spare_reservation(self, payload, headers):
        return self._request("POST", "/spare-reservations", payload, headers)

    def list_spare_reservations(self, headers, params=None):
        return self._request("GET", "/spare-reservations", headers=headers, params=params)

    def get_spare_reservation(self, reservation_id, headers):
        return self._request("GET", f"/spare-reservations/{reservation_id}", headers=headers)

    def cancel_spare_reservation(self, reservation_id, headers):
        return self._request("POST", f"/spare-reservations/{reservation_id}/cancel", {}, headers)

    def deploy_spare_reservation(self, reservation_id, headers):
        return self._request("POST", f"/spare-reservations/{reservation_id}/deploy", {}, headers)

    def return_spare_reservation(self, reservation_id, headers):
        return self._request("POST", f"/spare-reservations/{reservation_id}/return", {}, headers)

    # --- relay settings ---
    def create_relay_setting(self, payload, headers):
        return self._request("POST", "/relay-settings", payload, headers)

    def list_relay_settings(self, headers, params=None):
        return self._request("GET", "/relay-settings", headers=headers, params=params)

    def get_relay_setting(self, setting_id, headers):
        return self._request("GET", f"/relay-settings/{setting_id}", headers=headers)

    def submit_relay_setting(self, setting_id, headers):
        return self._request("POST", f"/relay-settings/{setting_id}/submit", {}, headers)

    def verify_relay_setting(self, setting_id, headers):
        return self._request("POST", f"/relay-settings/{setting_id}/verify", {}, headers)

    def reject_relay_setting(self, setting_id, payload, headers):
        return self._request("POST", f"/relay-settings/{setting_id}/reject", payload, headers)

    def activate_relay_setting(self, setting_id, payload, headers):
        return self._request("POST", f"/relay-settings/{setting_id}/activate", payload, headers)

    # --- technicians and certifications ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def deactivate_technician(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/deactivate", {}, headers)

    def create_certification(self, technician_id, payload, headers):
        return self._request("POST", f"/technicians/{technician_id}/certifications", payload, headers)

    def list_certifications(self, technician_id, headers, params=None):
        return self._request("GET", f"/technicians/{technician_id}/certifications", headers=headers, params=params)

    def revoke_certification(self, certification_id, headers):
        return self._request("POST", f"/certifications/{certification_id}/revoke", {}, headers)

    # --- environmental inspections ---
    def create_environmental_inspection(self, substation_id, payload, headers):
        return self._request("POST", f"/substations/{substation_id}/environmental-inspections", payload, headers)

    def list_environmental_inspections(self, headers, params=None):
        return self._request("GET", "/environmental-inspections", headers=headers, params=params)

    def get_environmental_inspection(self, inspection_id, headers):
        return self._request("GET", f"/environmental-inspections/{inspection_id}", headers=headers)

    def complete_environmental_inspection(self, inspection_id, headers):
        return self._request("POST", f"/environmental-inspections/{inspection_id}/complete", {}, headers)

    def close_environmental_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/environmental-inspections/{inspection_id}/close", payload, headers)


api_client = ApiClient()
