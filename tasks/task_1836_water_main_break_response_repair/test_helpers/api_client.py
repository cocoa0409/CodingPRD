"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- PipeSegment ---
    def create_pipe_segment(self, payload, headers):
        return self._request("POST", "/pipe-segments", payload, headers)

    def get_pipe_segment(self, segment_id, headers):
        return self._request("GET", f"/pipe-segments/{segment_id}", headers=headers)

    def list_segment_valves(self, segment_id, headers, params=None):
        return self._request(
            "GET", f"/pipe-segments/{segment_id}/valves", headers=headers, params=params
        )

    def list_segment_pressure_anomalies(self, segment_id, headers, params=None):
        return self._request(
            "GET",
            f"/pipe-segments/{segment_id}/pressure-anomalies",
            headers=headers,
            params=params,
        )

    def list_segment_break_reports(self, segment_id, headers, params=None):
        return self._request(
            "GET",
            f"/pipe-segments/{segment_id}/break-reports",
            headers=headers,
            params=params,
        )

    def program_replacement(self, segment_id, headers):
        return self._request(
            "POST", f"/pipe-segments/{segment_id}/program-replacement", headers=headers
        )

    def mark_replaced(self, segment_id, headers):
        return self._request(
            "POST", f"/pipe-segments/{segment_id}/mark-replaced", headers=headers
        )

    # --- Valve ---
    def create_valve(self, payload, headers):
        return self._request("POST", "/valves", payload, headers)

    # --- PressureAnomaly ---
    def create_pressure_anomaly(self, payload, headers):
        return self._request("POST", "/pressure-anomalies", payload, headers)

    # --- BreakReport ---
    def create_break_report(self, payload, headers):
        return self._request("POST", "/break-reports", payload, headers)

    def get_break_report(self, break_id, headers):
        return self._request("GET", f"/break-reports/{break_id}", headers=headers)

    def confirm_break_report(self, break_id, payload, headers):
        return self._request(
            "POST", f"/break-reports/{break_id}/confirm", payload, headers
        )

    def false_alarm_break_report(self, break_id, headers):
        return self._request(
            "POST", f"/break-reports/{break_id}/false-alarm", headers=headers
        )

    def correlate_break_report(self, break_id, payload, headers):
        return self._request(
            "POST", f"/break-reports/{break_id}/correlate", payload, headers
        )

    def close_break_report(self, break_id, headers):
        return self._request("POST", f"/break-reports/{break_id}/close", headers=headers)

    def list_break_isolation_events(self, break_id, headers, params=None):
        return self._request(
            "GET",
            f"/break-reports/{break_id}/isolation-events",
            headers=headers,
            params=params,
        )

    def list_break_pressure_anomalies(self, break_id, headers, params=None):
        return self._request(
            "GET",
            f"/break-reports/{break_id}/pressure-anomalies",
            headers=headers,
            params=params,
        )

    def list_break_work_orders(self, break_id, headers, params=None):
        return self._request(
            "GET", f"/break-reports/{break_id}/work-orders", headers=headers, params=params
        )

    def list_break_advisories(self, break_id, headers, params=None):
        return self._request(
            "GET", f"/break-reports/{break_id}/advisories", headers=headers, params=params
        )

    def list_break_traffic_permits(self, break_id, headers, params=None):
        return self._request(
            "GET",
            f"/break-reports/{break_id}/traffic-permits",
            headers=headers,
            params=params,
        )

    def list_break_damage_claims(self, break_id, headers, params=None):
        return self._request(
            "GET",
            f"/break-reports/{break_id}/damage-claims",
            headers=headers,
            params=params,
        )

    # --- IsolationEvent ---
    def create_isolation_event(self, payload, headers):
        return self._request("POST", "/isolation-events", payload, headers)

    def execute_isolation_event(self, isolation_id, headers):
        return self._request(
            "POST", f"/isolation-events/{isolation_id}/execute", headers=headers
        )

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def dispatch_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/dispatch", payload, headers
        )

    def arrive_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/arrive", headers=headers
        )

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/complete", payload, headers
        )

    def cancel_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/cancel", headers=headers
        )

    # --- BoilWaterAdvisory / WaterQualityTest ---
    def create_boil_water_advisory(self, payload, headers):
        return self._request("POST", "/boil-water-advisories", payload, headers)

    def get_boil_water_advisory(self, advisory_id, headers):
        return self._request(
            "GET", f"/boil-water-advisories/{advisory_id}", headers=headers
        )

    def lift_boil_water_advisory(self, advisory_id, headers):
        return self._request(
            "POST", f"/boil-water-advisories/{advisory_id}/lift", headers=headers
        )

    def create_water_quality_test(self, payload, headers):
        return self._request("POST", "/water-quality-tests", payload, headers)

    def list_advisory_tests(self, advisory_id, headers, params=None):
        return self._request(
            "GET",
            f"/boil-water-advisories/{advisory_id}/tests",
            headers=headers,
            params=params,
        )

    # --- RestorationJob ---
    def get_restoration_job(self, job_id, headers):
        return self._request("GET", f"/restoration-jobs/{job_id}", headers=headers)

    def list_restoration_jobs(self, headers, params=None):
        return self._request("GET", "/restoration-jobs", headers=headers, params=params)

    def schedule_restoration_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/restoration-jobs/{job_id}/schedule", payload, headers
        )

    def complete_restoration_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/restoration-jobs/{job_id}/complete", payload, headers
        )

    # --- TrafficPermit ---
    def create_traffic_permit(self, payload, headers):
        return self._request("POST", "/traffic-permits", payload, headers)

    def approve_traffic_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/traffic-permits/{permit_id}/approve", headers=headers
        )

    # --- DamageClaim ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def approve_damage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/approve", payload, headers
        )

    def deny_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/deny", headers=headers)

    def pay_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/pay", headers=headers)

    def void_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/void", headers=headers)

    # --- Test-driving / checkpoint ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_ops_checkpoint(self, headers):
        return self._request("POST", "/ops-runs", headers=headers)


api_client = ApiClient()
