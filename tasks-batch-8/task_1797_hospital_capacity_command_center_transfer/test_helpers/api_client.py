"""API client: one method per endpoint defined in the PRD."""
import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        """Retry transport-level failures on a fresh connection.

        Under per-test-server isolation the server is killed and respawned on
        the same port between tests; the session's pooled keep-alive
        connection can then be stale, surfacing as ConnectionError /
        ChunkedEncodingError on the next request. The broken connection is
        discarded by urllib3, so a retry opens a fresh socket to the live
        server. Assertion semantics are untouched.
        """
        last_exc = None
        for _ in range(4):
            try:
                return super()._request(
                    method, path, payload=payload, headers=headers,
                    params=params)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError) as exc:
                last_exc = exc
                self.session.close()
        raise last_exc

    # ------------------------------------------------------------------
    # Test-driving: logical clock and sweeps
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/cc/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/cc/_sweeps/run", {}, headers)

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/cc/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/cc/facilities/{facility_id}", headers=headers)

    def get_facility_load_score(self, facility_id, headers):
        return self._request("GET", f"/cc/facilities/{facility_id}/load-score",
                             headers=headers)

    def get_bed_candidates(self, facility_id, transfer_request_id, headers):
        return self._request(
            "GET", f"/cc/facilities/{facility_id}/bed-candidates",
            headers=headers, params={"transfer_request_id": transfer_request_id})

    # ------------------------------------------------------------------
    # Diversions
    # ------------------------------------------------------------------
    def create_diversion(self, facility_id, payload, headers):
        return self._request("POST", f"/cc/facilities/{facility_id}/diversions",
                             payload, headers)

    def list_diversions(self, facility_id, headers, params=None):
        return self._request("GET", f"/cc/facilities/{facility_id}/diversions",
                             headers=headers, params=params)

    def lift_diversion(self, diversion_id, headers):
        return self._request("POST", f"/cc/diversions/{diversion_id}/lift",
                             {}, headers)

    # ------------------------------------------------------------------
    # Beds
    # ------------------------------------------------------------------
    def create_bed(self, facility_id, payload, headers):
        return self._request("POST", f"/cc/facilities/{facility_id}/beds",
                             payload, headers)

    def list_beds(self, facility_id, headers, params=None):
        return self._request("GET", f"/cc/facilities/{facility_id}/beds",
                             headers=headers, params=params)

    def get_bed(self, bed_id, headers):
        return self._request("GET", f"/cc/beds/{bed_id}", headers=headers)

    def set_bed_status(self, bed_id, payload, headers):
        return self._request("POST", f"/cc/beds/{bed_id}/status", payload, headers)

    def list_bed_admissions(self, bed_id, headers, params=None):
        return self._request("GET", f"/cc/beds/{bed_id}/admissions",
                             headers=headers, params=params)

    def list_bed_holds_for_bed(self, bed_id, headers, params=None):
        return self._request("GET", f"/cc/beds/{bed_id}/bed-holds",
                             headers=headers, params=params)

    def list_bed_transfer_requests(self, bed_id, headers, params=None):
        return self._request("GET", f"/cc/beds/{bed_id}/transfer-requests",
                             headers=headers, params=params)

    def list_bed_assignments_for_bed(self, bed_id, headers, params=None):
        return self._request("GET", f"/cc/beds/{bed_id}/bed-assignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Physicians
    # ------------------------------------------------------------------
    def create_physician(self, facility_id, payload, headers):
        return self._request("POST", f"/cc/facilities/{facility_id}/physicians",
                             payload, headers)

    def list_physicians(self, facility_id, headers, params=None):
        return self._request("GET", f"/cc/facilities/{facility_id}/physicians",
                             headers=headers, params=params)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/cc/physicians/{physician_id}", headers=headers)

    def set_physician_status(self, physician_id, payload, headers):
        return self._request("POST", f"/cc/physicians/{physician_id}/status",
                             payload, headers)

    def list_physician_transfer_requests(self, physician_id, headers, params=None):
        return self._request("GET", f"/cc/physicians/{physician_id}/transfer-requests",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Admissions
    # ------------------------------------------------------------------
    def create_admission(self, facility_id, payload, headers):
        return self._request("POST", f"/cc/facilities/{facility_id}/admissions",
                             payload, headers)

    def list_admissions(self, facility_id, headers, params=None):
        return self._request("GET", f"/cc/facilities/{facility_id}/admissions",
                             headers=headers, params=params)

    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/cc/admissions/{admission_id}", headers=headers)

    def mark_pending_discharge(self, admission_id, payload, headers):
        return self._request("POST", f"/cc/admissions/{admission_id}/pending-discharge",
                             payload, headers)

    def confirm_discharge(self, admission_id, headers):
        return self._request("POST", f"/cc/admissions/{admission_id}/confirm-discharge",
                             {}, headers)

    def rescind_pending_discharge(self, admission_id, headers):
        return self._request(
            "POST", f"/cc/admissions/{admission_id}/rescind-pending-discharge",
            {}, headers)

    def list_admission_boarding_records(self, admission_id, headers, params=None):
        return self._request("GET", f"/cc/admissions/{admission_id}/boarding-records",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Transfer requests
    # ------------------------------------------------------------------
    def create_transfer_request(self, facility_id, payload, headers):
        return self._request("POST", f"/cc/facilities/{facility_id}/transfer-requests",
                             payload, headers)

    def list_transfer_requests(self, facility_id, headers, params=None):
        return self._request("GET", f"/cc/facilities/{facility_id}/transfer-requests",
                             headers=headers, params=params)

    def get_transfer_request(self, request_id, headers):
        return self._request("GET", f"/cc/transfer-requests/{request_id}",
                             headers=headers)

    def dispatch_consult(self, request_id, payload, headers):
        return self._request("POST", f"/cc/transfer-requests/{request_id}/consult",
                             payload, headers)

    def consult_response(self, request_id, payload, headers):
        return self._request(
            "POST", f"/cc/transfer-requests/{request_id}/consult-response",
            payload, headers)

    def cancel_transfer_request(self, request_id, headers):
        return self._request("POST", f"/cc/transfer-requests/{request_id}/cancel",
                             {}, headers)

    def rebalance_transfer_request(self, request_id, payload, headers):
        return self._request("POST", f"/cc/transfer-requests/{request_id}/rebalance",
                             payload, headers)

    # ------------------------------------------------------------------
    # Bed holds
    # ------------------------------------------------------------------
    def create_bed_hold(self, request_id, payload, headers):
        return self._request("POST", f"/cc/transfer-requests/{request_id}/bed-holds",
                             payload, headers)

    def list_bed_holds_for_request(self, request_id, headers, params=None):
        return self._request("GET", f"/cc/transfer-requests/{request_id}/bed-holds",
                             headers=headers, params=params)

    def get_bed_hold(self, hold_id, headers):
        return self._request("GET", f"/cc/bed-holds/{hold_id}", headers=headers)

    def extend_bed_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/cc/bed-holds/{hold_id}/extend",
                             payload, headers)

    def release_bed_hold(self, hold_id, headers):
        return self._request("POST", f"/cc/bed-holds/{hold_id}/release", {}, headers)

    def list_bed_assignments_for_hold(self, hold_id, headers, params=None):
        return self._request("GET", f"/cc/bed-holds/{hold_id}/bed-assignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Bed assignments
    # ------------------------------------------------------------------
    def create_bed_assignment(self, request_id, payload, headers):
        return self._request(
            "POST", f"/cc/transfer-requests/{request_id}/bed-assignments",
            payload, headers)

    def list_bed_assignments_for_request(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/cc/transfer-requests/{request_id}/bed-assignments",
            headers=headers, params=params)

    def complete_bed_assignment(self, assignment_id, headers):
        return self._request("POST", f"/cc/bed-assignments/{assignment_id}/complete",
                             {}, headers)

    # ------------------------------------------------------------------
    # Boarding records and huddles
    # ------------------------------------------------------------------
    def create_boarding_record(self, facility_id, payload, headers):
        return self._request("POST", f"/cc/facilities/{facility_id}/boarding-records",
                             payload, headers)

    def list_boarding_records(self, facility_id, headers, params=None):
        return self._request("GET", f"/cc/facilities/{facility_id}/boarding-records",
                             headers=headers, params=params)

    def get_boarding_record(self, record_id, headers):
        return self._request("GET", f"/cc/boarding-records/{record_id}",
                             headers=headers)

    def heartbeat_boarding_record(self, record_id, payload, headers):
        return self._request("POST", f"/cc/boarding-records/{record_id}/heartbeat",
                             payload, headers)

    def offer_boarding_record(self, record_id, headers):
        return self._request("POST", f"/cc/boarding-records/{record_id}/offer",
                             {}, headers)

    def place_boarding_record(self, record_id, headers):
        return self._request("POST", f"/cc/boarding-records/{record_id}/place",
                             {}, headers)

    def leave_ama_boarding_record(self, record_id, headers):
        return self._request("POST", f"/cc/boarding-records/{record_id}/leave-ama",
                             {}, headers)

    def create_huddle(self, record_id, headers):
        return self._request("POST", f"/cc/boarding-records/{record_id}/huddles",
                             {}, headers)

    def list_huddles(self, record_id, headers, params=None):
        return self._request("GET", f"/cc/boarding-records/{record_id}/huddles",
                             headers=headers, params=params)

    def resolve_huddle(self, huddle_id, payload, headers):
        return self._request("POST", f"/cc/huddles/{huddle_id}/resolve",
                             payload, headers)

    # ------------------------------------------------------------------
    # Capacity forecasts
    # ------------------------------------------------------------------
    def create_capacity_forecast(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/cc/facilities/{facility_id}/capacity-forecasts",
            payload, headers)

    def list_capacity_forecasts(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/cc/facilities/{facility_id}/capacity-forecasts",
            headers=headers, params=params)

    def get_capacity_forecast(self, forecast_id, headers):
        return self._request("GET", f"/cc/capacity-forecasts/{forecast_id}",
                             headers=headers)

    def publish_capacity_forecast(self, forecast_id, headers):
        return self._request("POST", f"/cc/capacity-forecasts/{forecast_id}/publish",
                             {}, headers)


api_client = ApiClient()
