"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # State plans
    # ------------------------------------------------------------------
    def create_state_plan(self, payload, headers):
        return self._request("POST", "/state-plans", payload, headers)

    def get_state_plan(self, plan_id, headers):
        return self._request("GET", f"/state-plans/{plan_id}", headers=headers)

    def list_state_plans(self, headers, params=None):
        return self._request("GET", "/state-plans", headers=headers, params=params)

    def activate_state_plan(self, plan_id, headers):
        return self._request("POST", f"/state-plans/{plan_id}/activate", None, headers)

    # ------------------------------------------------------------------
    # Stations
    # ------------------------------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def get_compliance_summary(self, station_id, headers):
        return self._request(
            "GET", f"/stations/{station_id}/compliance-summary", headers=headers
        )

    def run_log_review(self, station_id, headers):
        return self._request(
            "POST", f"/stations/{station_id}/run-log-review", None, headers
        )

    def create_public_file_document(self, station_id, payload, headers):
        return self._request(
            "POST", f"/stations/{station_id}/public-file-documents", payload, headers
        )

    # ------------------------------------------------------------------
    # Relay rules
    # ------------------------------------------------------------------
    def create_relay_rule(self, payload, headers):
        return self._request("POST", "/relay-rules", payload, headers)

    def get_relay_rule(self, rule_id, headers):
        return self._request("GET", f"/relay-rules/{rule_id}", headers=headers)

    def list_relay_rules(self, headers, params=None):
        return self._request("GET", "/relay-rules", headers=headers, params=params)

    def retire_relay_rule(self, rule_id, headers):
        return self._request("POST", f"/relay-rules/{rule_id}/retire", None, headers)

    # ------------------------------------------------------------------
    # EAS devices
    # ------------------------------------------------------------------
    def create_device(self, payload, headers):
        return self._request("POST", "/eas-devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/eas-devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/eas-devices", headers=headers, params=params)

    def readiness_check_device(self, device_id, payload, headers):
        return self._request(
            "POST", f"/eas-devices/{device_id}/readiness-check", payload, headers
        )

    def decommission_device(self, device_id, headers):
        return self._request(
            "POST", f"/eas-devices/{device_id}/decommission", None, headers
        )

    # ------------------------------------------------------------------
    # Monitoring assignments
    # ------------------------------------------------------------------
    def create_monitoring_assignment(self, payload, headers):
        return self._request("POST", "/monitoring-assignments", payload, headers)

    def get_monitoring_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/monitoring-assignments/{assignment_id}", headers=headers
        )

    def list_monitoring_assignments(self, headers, params=None):
        return self._request(
            "GET", "/monitoring-assignments", headers=headers, params=params
        )

    def record_receipt(self, assignment_id, headers):
        return self._request(
            "POST",
            f"/monitoring-assignments/{assignment_id}/record-receipt",
            None,
            headers,
        )

    def decommission_assignment(self, assignment_id, headers):
        return self._request(
            "POST",
            f"/monitoring-assignments/{assignment_id}/decommission",
            None,
            headers,
        )

    def reinstate_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/monitoring-assignments/{assignment_id}/reinstate", None, headers
        )

    # ------------------------------------------------------------------
    # Equipment outages
    # ------------------------------------------------------------------
    def create_equipment_outage(self, payload, headers):
        return self._request("POST", "/equipment-outages", payload, headers)

    def get_equipment_outage(self, outage_id, headers):
        return self._request("GET", f"/equipment-outages/{outage_id}", headers=headers)

    def list_equipment_outages(self, headers, params=None):
        return self._request("GET", "/equipment-outages", headers=headers, params=params)

    def start_repair(self, outage_id, headers):
        return self._request(
            "POST", f"/equipment-outages/{outage_id}/start-repair", None, headers
        )

    def restore_outage(self, outage_id, headers):
        return self._request(
            "POST", f"/equipment-outages/{outage_id}/restore", None, headers
        )

    def fail_verification(self, outage_id, headers, payload=None):
        return self._request(
            "POST", f"/equipment-outages/{outage_id}/fail-verification", payload, headers
        )

    def close_outage(self, outage_id, headers):
        return self._request(
            "POST", f"/equipment-outages/{outage_id}/close", None, headers
        )

    # ------------------------------------------------------------------
    # Alert events
    # ------------------------------------------------------------------
    def create_alert_event(self, payload, headers):
        return self._request("POST", "/alert-events", payload, headers)

    def get_alert_event(self, alert_id, headers):
        return self._request("GET", f"/alert-events/{alert_id}", headers=headers)

    def list_alert_events(self, headers, params=None):
        return self._request("GET", "/alert-events", headers=headers, params=params)

    def confirm_relay(self, alert_id, headers):
        return self._request(
            "POST", f"/alert-events/{alert_id}/confirm-relay", None, headers
        )

    def verify_accessibility(self, alert_id, payload, headers):
        return self._request(
            "POST", f"/alert-events/{alert_id}/verify-accessibility", payload, headers
        )

    # ------------------------------------------------------------------
    # Wireless alert notices
    # ------------------------------------------------------------------
    def create_wireless_alert_notice(self, payload, headers):
        return self._request("POST", "/wireless-alert-notices", payload, headers)

    def get_wireless_alert_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/wireless-alert-notices/{notice_id}", headers=headers
        )

    def list_wireless_alert_notices(self, headers, params=None):
        return self._request(
            "GET", "/wireless-alert-notices", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Test events
    # ------------------------------------------------------------------
    def create_test_event(self, payload, headers):
        return self._request("POST", "/test-events", payload, headers)

    def get_test_event(self, event_id, headers):
        return self._request("GET", f"/test-events/{event_id}", headers=headers)

    def list_test_events(self, headers, params=None):
        return self._request("GET", "/test-events", headers=headers, params=params)

    def evaluate_readiness(self, event_id, headers):
        return self._request(
            "POST", f"/test-events/{event_id}/evaluate-readiness", None, headers
        )

    def close_logging(self, event_id, headers):
        return self._request(
            "POST", f"/test-events/{event_id}/close-logging", None, headers
        )

    # ------------------------------------------------------------------
    # Test log entries
    # ------------------------------------------------------------------
    def create_test_log_entry(self, payload, headers):
        return self._request("POST", "/test-log-entries", payload, headers)

    def get_test_log_entry(self, entry_id, headers):
        return self._request("GET", f"/test-log-entries/{entry_id}", headers=headers)

    def list_test_log_entries(self, headers, params=None):
        return self._request("GET", "/test-log-entries", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Filing records
    # ------------------------------------------------------------------
    def create_filing_record(self, payload, headers):
        return self._request("POST", "/filing-records", payload, headers)

    def get_filing_record(self, filing_id, headers):
        return self._request("GET", f"/filing-records/{filing_id}", headers=headers)

    def list_filing_records(self, headers, params=None):
        return self._request("GET", "/filing-records", headers=headers, params=params)

    def accept_filing(self, filing_id, headers):
        return self._request(
            "POST", f"/filing-records/{filing_id}/accept", None, headers
        )

    def reverse_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/filing-records/{filing_id}/reverse", payload, headers
        )

    # ------------------------------------------------------------------
    # Inspection requests
    # ------------------------------------------------------------------
    def create_inspection_request(self, payload, headers):
        return self._request("POST", "/inspection-requests", payload, headers)

    def get_inspection_request(self, inspection_id, headers):
        return self._request(
            "GET", f"/inspection-requests/{inspection_id}", headers=headers
        )

    def list_inspection_requests(self, headers, params=None):
        return self._request(
            "GET", "/inspection-requests", headers=headers, params=params
        )

    def draft_response(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspection-requests/{inspection_id}/draft-response", payload, headers
        )

    def submit_response(self, inspection_id, headers):
        return self._request(
            "POST", f"/inspection-requests/{inspection_id}/submit-response", None, headers
        )

    def close_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/inspection-requests/{inspection_id}/close", None, headers
        )


api_client = ApiClient()
