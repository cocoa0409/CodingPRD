"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Driver ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/eld/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/eld/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/eld/drivers", headers=headers, params=params)

    def update_driver(self, driver_id, payload, headers):
        return self._request("PATCH", f"/eld/drivers/{driver_id}", payload, headers)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/eld/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/eld/vehicles/{vehicle_id}", headers=headers)

    def update_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"/eld/vehicles/{vehicle_id}", payload, headers)

    # --- ELDDevice ---
    def create_device(self, payload, headers):
        return self._request("POST", "/eld/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/eld/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/eld/devices", headers=headers, params=params)

    def login_device(self, device_id, headers):
        return self._request("POST", f"/eld/devices/{device_id}/login", {}, headers)

    def logout_device(self, device_id, headers):
        return self._request("POST", f"/eld/devices/{device_id}/logout", {}, headers)

    def flag_malfunction(self, device_id, headers):
        return self._request("POST", f"/eld/devices/{device_id}/flag-malfunction", {}, headers)

    def clear_malfunction(self, device_id, headers):
        return self._request("POST", f"/eld/devices/{device_id}/clear-malfunction", {}, headers)

    # --- DutyStatusEvent ---
    def create_duty_event(self, payload, headers):
        return self._request("POST", "/eld/duty-events", payload, headers)

    def get_duty_event(self, event_id, headers):
        return self._request("GET", f"/eld/duty-events/{event_id}", headers=headers)

    def list_duty_events(self, headers, params=None):
        return self._request("GET", "/eld/duty-events", headers=headers, params=params)

    def mark_error_duty_event(self, event_id, payload, headers):
        return self._request("POST", f"/eld/duty-events/{event_id}/mark-error", payload, headers)

    # --- DailyLog ---
    def create_daily_log(self, payload, headers):
        return self._request("POST", "/eld/daily-logs", payload, headers)

    def get_daily_log(self, log_id, headers):
        return self._request("GET", f"/eld/daily-logs/{log_id}", headers=headers)

    def list_daily_logs(self, headers, params=None):
        return self._request("GET", "/eld/daily-logs", headers=headers, params=params)

    def certify_daily_log(self, log_id, headers):
        return self._request("POST", f"/eld/daily-logs/{log_id}/certify", {}, headers)

    # --- HOSViolation ---
    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/eld/hos-violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/eld/hos-violations", headers=headers, params=params)

    def acknowledge_violation(self, violation_id, headers):
        return self._request("POST", f"/eld/hos-violations/{violation_id}/acknowledge", {}, headers)

    def reopen_violation(self, violation_id, headers):
        return self._request("POST", f"/eld/hos-violations/{violation_id}/reopen", {}, headers)

    def resolve_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/eld/hos-violations/{violation_id}/resolve", payload, headers)

    # --- AdverseConditionsClaim ---
    def create_adverse_claim(self, payload, headers):
        return self._request("POST", "/eld/adverse-claims", payload, headers)

    def get_adverse_claim(self, claim_id, headers):
        return self._request("GET", f"/eld/adverse-claims/{claim_id}", headers=headers)

    def list_adverse_claims(self, headers, params=None):
        return self._request("GET", "/eld/adverse-claims", headers=headers, params=params)

    def approve_adverse_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/eld/adverse-claims/{claim_id}/approve", payload, headers)

    def reject_adverse_claim(self, claim_id, headers):
        return self._request("POST", f"/eld/adverse-claims/{claim_id}/reject", {}, headers)

    # --- PersonalConveyanceSegment ---
    def get_pc_segment(self, segment_id, headers):
        return self._request("GET", f"/eld/pc-segments/{segment_id}", headers=headers)

    def list_pc_segments(self, headers, params=None):
        return self._request("GET", "/eld/pc-segments", headers=headers, params=params)

    # --- Test-driving clock control ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
