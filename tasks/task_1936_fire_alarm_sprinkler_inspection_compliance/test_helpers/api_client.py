"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/fire-compliance"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Contractors
    # ------------------------------------------------------------------
    def create_contractor(self, payload, headers):
        return self._request("POST", f"{BASE}/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"{BASE}/contractors/{contractor_id}",
                             headers=headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", f"{BASE}/contractors",
                             headers=headers, params=params)

    def deactivate_contractor(self, contractor_id, headers):
        return self._request("POST", f"{BASE}/contractors/{contractor_id}/deactivate",
                             {}, headers)

    def audit_score(self, contractor_id, headers):
        return self._request("POST", f"{BASE}/contractors/{contractor_id}/audit-score",
                             {}, headers)

    # ------------------------------------------------------------------
    # Technicians
    # ------------------------------------------------------------------
    def create_technician(self, contractor_id, payload, headers):
        return self._request("POST", f"{BASE}/contractors/{contractor_id}/technicians",
                             payload, headers)

    def list_technicians(self, contractor_id, headers, params=None):
        return self._request("GET", f"{BASE}/contractors/{contractor_id}/technicians",
                             headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"{BASE}/technicians/{technician_id}",
                             headers=headers)

    def deactivate_technician(self, technician_id, headers):
        return self._request("POST", f"{BASE}/technicians/{technician_id}/deactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # License records
    # ------------------------------------------------------------------
    def create_license_record(self, technician_id, payload, headers):
        return self._request("POST",
                             f"{BASE}/technicians/{technician_id}/license-records",
                             payload, headers)

    def list_license_records(self, technician_id, headers, params=None):
        return self._request("GET",
                             f"{BASE}/technicians/{technician_id}/license-records",
                             headers=headers, params=params)

    def get_license_record(self, license_id, headers):
        return self._request("GET", f"{BASE}/license-records/{license_id}",
                             headers=headers)

    def revoke_license(self, license_id, headers):
        return self._request("POST", f"{BASE}/license-records/{license_id}/revoke",
                             {}, headers)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", f"{BASE}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{BASE}/properties/{property_id}",
                             headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", f"{BASE}/properties",
                             headers=headers, params=params)

    def archive_property(self, property_id, headers):
        return self._request("POST", f"{BASE}/properties/{property_id}/archive",
                             {}, headers)

    # ------------------------------------------------------------------
    # Protected systems
    # ------------------------------------------------------------------
    def create_system(self, property_id, payload, headers):
        return self._request("POST", f"{BASE}/properties/{property_id}/systems",
                             payload, headers)

    def list_systems(self, property_id, headers, params=None):
        return self._request("GET", f"{BASE}/properties/{property_id}/systems",
                             headers=headers, params=params)

    def get_system(self, system_id, headers):
        return self._request("GET", f"{BASE}/systems/{system_id}", headers=headers)

    def decommission_system(self, system_id, headers):
        return self._request("POST", f"{BASE}/systems/{system_id}/decommission",
                             {}, headers)

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    def create_device(self, system_id, payload, headers):
        return self._request("POST", f"{BASE}/systems/{system_id}/devices",
                             payload, headers)

    def list_devices(self, system_id, headers, params=None):
        return self._request("GET", f"{BASE}/systems/{system_id}/devices",
                             headers=headers, params=params)

    def get_device(self, device_id, headers):
        return self._request("GET", f"{BASE}/devices/{device_id}", headers=headers)

    def replace_device(self, device_id, payload, headers):
        return self._request("POST", f"{BASE}/devices/{device_id}/replace",
                             payload, headers)

    def remove_device(self, device_id, headers):
        return self._request("POST", f"{BASE}/devices/{device_id}/remove",
                             {}, headers)

    def list_devices_filtered(self, headers, params=None):
        return self._request("GET", f"{BASE}/devices", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Inspection plans
    # ------------------------------------------------------------------
    def create_plan(self, property_id, payload, headers):
        return self._request("POST",
                             f"{BASE}/properties/{property_id}/inspection-plans",
                             payload, headers)

    def list_plans(self, property_id, headers, params=None):
        return self._request("GET",
                             f"{BASE}/properties/{property_id}/inspection-plans",
                             headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"{BASE}/inspection-plans/{plan_id}",
                             headers=headers)

    def publish_plan(self, plan_id, headers):
        return self._request("POST", f"{BASE}/inspection-plans/{plan_id}/publish",
                             {}, headers)

    # ------------------------------------------------------------------
    # Inspection events
    # ------------------------------------------------------------------
    def create_event(self, plan_id, payload, headers):
        return self._request("POST", f"{BASE}/inspection-plans/{plan_id}/events",
                             payload, headers)

    def list_events(self, plan_id, headers, params=None):
        return self._request("GET", f"{BASE}/inspection-plans/{plan_id}/events",
                             headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"{BASE}/inspection-events/{event_id}",
                             headers=headers)

    def list_events_filtered(self, headers, params=None):
        return self._request("GET", f"{BASE}/inspection-events",
                             headers=headers, params=params)

    def start_event(self, event_id, headers):
        return self._request("POST", f"{BASE}/inspection-events/{event_id}/start",
                             {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"{BASE}/inspection-events/{event_id}/complete",
                             {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"{BASE}/inspection-events/{event_id}/cancel",
                             {}, headers)

    def mark_no_access(self, event_id, headers):
        return self._request("POST",
                             f"{BASE}/inspection-events/{event_id}/mark-no-access",
                             {}, headers)

    # ------------------------------------------------------------------
    # Deficiencies
    # ------------------------------------------------------------------
    def create_deficiency(self, event_id, payload, headers):
        return self._request("POST",
                             f"{BASE}/inspection-events/{event_id}/deficiencies",
                             payload, headers)

    def list_deficiencies(self, event_id, headers, params=None):
        return self._request("GET",
                             f"{BASE}/inspection-events/{event_id}/deficiencies",
                             headers=headers, params=params)

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"{BASE}/deficiencies/{deficiency_id}",
                             headers=headers)

    def list_deficiencies_filtered(self, headers, params=None):
        return self._request("GET", f"{BASE}/deficiencies",
                             headers=headers, params=params)

    def attest_correction(self, deficiency_id, headers):
        return self._request("POST",
                             f"{BASE}/deficiencies/{deficiency_id}/attest-correction",
                             {}, headers)

    def verify_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"{BASE}/deficiencies/{deficiency_id}/verify",
                             {}, headers)

    def reject_correction(self, deficiency_id, headers):
        return self._request("POST",
                             f"{BASE}/deficiencies/{deficiency_id}/reject-correction",
                             {}, headers)

    def waive_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"{BASE}/deficiencies/{deficiency_id}/waive",
                             {}, headers)

    def extend_deadline(self, deficiency_id, headers):
        return self._request("POST",
                             f"{BASE}/deficiencies/{deficiency_id}/extend-deadline",
                             {}, headers)

    # ------------------------------------------------------------------
    # Impairments
    # ------------------------------------------------------------------
    def create_impairment(self, system_id, payload, headers):
        return self._request("POST", f"{BASE}/systems/{system_id}/impairments",
                             payload, headers)

    def list_impairments(self, system_id, headers, params=None):
        return self._request("GET", f"{BASE}/systems/{system_id}/impairments",
                             headers=headers, params=params)

    def get_impairment(self, impairment_id, headers):
        return self._request("GET", f"{BASE}/impairments/{impairment_id}",
                             headers=headers)

    def notify_authority(self, impairment_id, headers):
        return self._request("POST",
                             f"{BASE}/impairments/{impairment_id}/notify-authority",
                             {}, headers)

    def restore_impairment(self, impairment_id, headers):
        return self._request("POST", f"{BASE}/impairments/{impairment_id}/restore",
                             {}, headers)

    def close_impairment(self, impairment_id, headers):
        return self._request("POST", f"{BASE}/impairments/{impairment_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Marshal reports
    # ------------------------------------------------------------------
    def list_event_reports(self, event_id, headers, params=None):
        return self._request("GET",
                             f"{BASE}/inspection-events/{event_id}/marshal-reports",
                             headers=headers, params=params)

    def create_revision_report(self, event_id, payload, headers):
        return self._request("POST",
                             f"{BASE}/inspection-events/{event_id}/marshal-reports",
                             payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"{BASE}/marshal-reports/{report_id}",
                             headers=headers)

    def list_reports_filtered(self, headers, params=None):
        return self._request("GET", f"{BASE}/marshal-reports",
                             headers=headers, params=params)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"{BASE}/marshal-reports/{report_id}/submit",
                             {}, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"{BASE}/marshal-reports/{report_id}/accept",
                             {}, headers)

    def reject_report(self, report_id, headers):
        return self._request("POST", f"{BASE}/marshal-reports/{report_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Backflow tests
    # ------------------------------------------------------------------
    def create_backflow_test(self, system_id, payload, headers):
        return self._request("POST", f"{BASE}/systems/{system_id}/backflow-tests",
                             payload, headers)

    def list_backflow_tests(self, system_id, headers, params=None):
        return self._request("GET", f"{BASE}/systems/{system_id}/backflow-tests",
                             headers=headers, params=params)

    def get_backflow_test(self, test_id, headers):
        return self._request("GET", f"{BASE}/backflow-tests/{test_id}",
                             headers=headers)

    def list_backflow_tests_filtered(self, headers, params=None):
        return self._request("GET", f"{BASE}/backflow-tests",
                             headers=headers, params=params)

    def invoice_backflow_test(self, test_id, headers):
        return self._request("POST", f"{BASE}/backflow-tests/{test_id}/invoice",
                             {}, headers)

    def record_backflow_payment(self, test_id, headers):
        return self._request("POST",
                             f"{BASE}/backflow-tests/{test_id}/record-payment",
                             {}, headers)

    # ------------------------------------------------------------------
    # Fire pump tests
    # ------------------------------------------------------------------
    def create_pump_test(self, system_id, payload, headers):
        return self._request("POST", f"{BASE}/systems/{system_id}/fire-pump-tests",
                             payload, headers)

    def list_pump_tests(self, system_id, headers, params=None):
        return self._request("GET", f"{BASE}/systems/{system_id}/fire-pump-tests",
                             headers=headers, params=params)

    def get_pump_test(self, test_id, headers):
        return self._request("GET", f"{BASE}/fire-pump-tests/{test_id}",
                             headers=headers)

    def list_pump_tests_filtered(self, headers, params=None):
        return self._request("GET", f"{BASE}/fire-pump-tests",
                             headers=headers, params=params)

    def attest_pump_test(self, test_id, headers):
        return self._request("POST", f"{BASE}/fire-pump-tests/{test_id}/attest",
                             {}, headers)

    # ------------------------------------------------------------------
    # False alarm cases
    # ------------------------------------------------------------------
    def create_false_alarm(self, property_id, payload, headers):
        return self._request("POST",
                             f"{BASE}/properties/{property_id}/false-alarm-cases",
                             payload, headers)

    def list_false_alarms(self, property_id, headers, params=None):
        return self._request("GET",
                             f"{BASE}/properties/{property_id}/false-alarm-cases",
                             headers=headers, params=params)

    def get_false_alarm(self, case_id, headers):
        return self._request("GET", f"{BASE}/false-alarm-cases/{case_id}",
                             headers=headers)

    def assess_false_alarm(self, case_id, headers):
        return self._request("POST", f"{BASE}/false-alarm-cases/{case_id}/assess",
                             {}, headers)

    def waive_false_alarm(self, case_id, headers):
        return self._request("POST", f"{BASE}/false-alarm-cases/{case_id}/waive",
                             {}, headers)

    def record_false_alarm_payment(self, case_id, headers):
        return self._request("POST",
                             f"{BASE}/false-alarm-cases/{case_id}/record-payment",
                             {}, headers)

    # ------------------------------------------------------------------
    # Modification permits
    # ------------------------------------------------------------------
    def create_permit(self, system_id, payload, headers):
        return self._request("POST", f"{BASE}/systems/{system_id}/modification-permits",
                             payload, headers)

    def list_permits(self, system_id, headers, params=None):
        return self._request("GET", f"{BASE}/systems/{system_id}/modification-permits",
                             headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{BASE}/modification-permits/{permit_id}",
                             headers=headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"{BASE}/modification-permits/{permit_id}/issue",
                             {}, headers)

    def commence_work(self, permit_id, headers):
        return self._request("POST",
                             f"{BASE}/modification-permits/{permit_id}/commence-work",
                             {}, headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"{BASE}/modification-permits/{permit_id}/close",
                             {}, headers)

    def cite_unpermitted_work(self, permit_id, payload, headers):
        return self._request("POST",
                             f"{BASE}/modification-permits/{permit_id}/cite-unpermitted-work",
                             payload, headers)


api_client = ApiClient()
