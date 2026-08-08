"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving / configuration ─────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Testing sites ────────────────────────────────────────────────────
    def create_testing_site(self, payload, headers):
        return self._request("POST", "/testing-sites", payload, headers)

    def get_testing_site(self, site_id, headers):
        return self._request("GET", f"/testing-sites/{site_id}", headers=headers)

    def list_site_drug_tests(self, site_id, headers, params=None):
        return self._request("GET", f"/testing-sites/{site_id}/drug-tests",
                             headers=headers, params=params)

    # ─── EM devices ───────────────────────────────────────────────────────
    def create_em_device(self, payload, headers):
        return self._request("POST", "/em-devices", payload, headers)

    def get_em_device(self, device_id, headers):
        return self._request("GET", f"/em-devices/{device_id}", headers=headers)

    def list_device_enrollments(self, device_id, headers, params=None):
        return self._request("GET", f"/em-devices/{device_id}/enrollments",
                             headers=headers, params=params)

    # ─── Defendants ───────────────────────────────────────────────────────
    def create_defendant(self, payload, headers):
        return self._request("POST", "/defendants", payload, headers)

    def get_defendant(self, defendant_id, headers):
        return self._request("GET", f"/defendants/{defendant_id}", headers=headers)

    def list_defendants(self, headers, params=None):
        return self._request("GET", "/defendants", headers=headers, params=params)

    def transition_defendant(self, defendant_id, to_status, headers):
        return self._request("POST", f"/defendants/{defendant_id}/transition",
                             {"to_status": to_status}, headers)

    def create_level_adjustment(self, defendant_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/level-adjustments",
                             payload, headers)

    def list_level_adjustments(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/level-adjustments",
                             headers=headers, params=params)

    def create_fee(self, defendant_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/fees", payload, headers)

    def create_ledger_entry(self, defendant_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/ledger-entries",
                             payload, headers)

    def list_ledger(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/ledger",
                             headers=headers, params=params)

    # ─── Risk assessments ─────────────────────────────────────────────────
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def transition_assessment(self, assessment_id, to_status, headers):
        return self._request("POST", f"/assessments/{assessment_id}/transition",
                             {"to_status": to_status}, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_defendant_assessments(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/assessments",
                             headers=headers, params=params)

    # ─── Release orders ───────────────────────────────────────────────────
    def create_release_order(self, payload, headers):
        return self._request("POST", "/release-orders", payload, headers)

    def transition_release_order(self, order_id, to_status, headers):
        return self._request("POST", f"/release-orders/{order_id}/transition",
                             {"to_status": to_status}, headers)

    def list_defendant_release_orders(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/release-orders",
                             headers=headers, params=params)

    def list_assessment_release_orders(self, assessment_id, headers, params=None):
        return self._request("GET", f"/assessments/{assessment_id}/release-orders",
                             headers=headers, params=params)

    # ─── Check-ins ────────────────────────────────────────────────────────
    def create_check_in(self, payload, headers):
        return self._request("POST", "/check-ins", payload, headers)

    def transition_check_in(self, check_in_id, to_status, headers):
        return self._request("POST", f"/check-ins/{check_in_id}/transition",
                             {"to_status": to_status}, headers)

    def list_defendant_check_ins(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/check-ins",
                             headers=headers, params=params)

    # ─── EM enrollments ───────────────────────────────────────────────────
    def create_em_enrollment(self, payload, headers):
        return self._request("POST", "/em-enrollments", payload, headers)

    def transition_em_enrollment(self, enrollment_id, to_status, headers):
        return self._request("POST", f"/em-enrollments/{enrollment_id}/transition",
                             {"to_status": to_status}, headers)

    def get_em_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/em-enrollments/{enrollment_id}", headers=headers)

    def list_defendant_em_enrollments(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/em-enrollments",
                             headers=headers, params=params)

    def create_curfew_window(self, enrollment_id, payload, headers):
        return self._request("POST", f"/em-enrollments/{enrollment_id}/curfew-windows",
                             payload, headers)

    def list_curfew_windows(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/em-enrollments/{enrollment_id}/curfew-windows",
                             headers=headers, params=params)

    def create_ping(self, enrollment_id, payload, headers):
        return self._request("POST", f"/em-enrollments/{enrollment_id}/pings",
                             payload, headers)

    def list_pings(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/em-enrollments/{enrollment_id}/pings",
                             headers=headers, params=params)

    # ─── Violations ───────────────────────────────────────────────────────
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def transition_violation(self, violation_id, to_status, headers):
        return self._request("POST", f"/violations/{violation_id}/transition",
                             {"to_status": to_status}, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def list_defendant_violations(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/violations",
                             headers=headers, params=params)

    # ─── Court events ─────────────────────────────────────────────────────
    def create_court_event(self, payload, headers):
        return self._request("POST", "/court-events", payload, headers)

    def transition_court_event(self, court_event_id, to_status, headers):
        return self._request("POST", f"/court-events/{court_event_id}/transition",
                             {"to_status": to_status}, headers)

    def list_defendant_court_events(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/court-events",
                             headers=headers, params=params)

    # ─── Drug tests ───────────────────────────────────────────────────────
    def create_drug_test(self, payload, headers):
        return self._request("POST", "/drug-tests", payload, headers)

    def transition_drug_test(self, drug_test_id, to_status, headers):
        return self._request("POST", f"/drug-tests/{drug_test_id}/transition",
                             {"to_status": to_status}, headers)

    def list_defendant_drug_tests(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/drug-tests",
                             headers=headers, params=params)


api_client = ApiClient()
