"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/psm/_clock/set_current_utc", payload, headers)

    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/psm/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/psm/facilities/{facility_id}", headers=headers)

    def get_charge_summary(self, facility_id, headers):
        return self._request("GET", f"/psm/facilities/{facility_id}/charge-summary",
                             headers=headers)

    # --- RefrigerationSystem ---
    def create_refrigeration_system(self, payload, headers):
        return self._request("POST", "/psm/refrigeration-systems", payload, headers)

    def get_refrigeration_system(self, system_id, headers):
        return self._request("GET", f"/psm/refrigeration-systems/{system_id}",
                             headers=headers)

    def list_refrigeration_systems(self, headers, params=None):
        return self._request("GET", "/psm/refrigeration-systems",
                             headers=headers, params=params)

    def set_system_status(self, system_id, payload, headers):
        return self._request("POST", f"/psm/refrigeration-systems/{system_id}/status",
                             payload, headers)

    def post_gauge_reading(self, system_id, payload, headers):
        return self._request("POST",
                             f"/psm/refrigeration-systems/{system_id}/gauge-readings",
                             payload, headers)

    def head_pressure_target(self, system_id, payload, headers):
        return self._request(
            "POST", f"/psm/refrigeration-systems/{system_id}/head-pressure-target",
            payload, headers)

    # --- Equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/psm/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/psm/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/psm/equipment", headers=headers, params=params)

    # --- PsidDocument ---
    def create_psid_document(self, payload, headers):
        return self._request("POST", "/psm/psid-documents", payload, headers)

    def get_psid_document(self, document_id, headers):
        return self._request("GET", f"/psm/psid-documents/{document_id}",
                             headers=headers)

    def list_psid_documents(self, headers, params=None):
        return self._request("GET", "/psm/psid-documents", headers=headers,
                             params=params)

    def start_psid_review(self, document_id, headers):
        return self._request("POST",
                             f"/psm/psid-documents/{document_id}/start-review",
                             headers=headers)

    def reaffirm_psid_document(self, document_id, headers):
        return self._request("POST", f"/psm/psid-documents/{document_id}/reaffirm",
                             headers=headers)

    # --- ChargeAdjustment ---
    def create_charge_adjustment(self, payload, headers):
        return self._request("POST", "/psm/charge-adjustments", payload, headers)

    def get_charge_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/psm/charge-adjustments/{adjustment_id}",
                             headers=headers)

    def list_charge_adjustments(self, headers, params=None):
        return self._request("GET", "/psm/charge-adjustments", headers=headers,
                             params=params)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/psm/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/psm/inspections/{inspection_id}",
                             headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/psm/inspections", headers=headers,
                             params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/psm/inspections/{inspection_id}/complete",
                             payload, headers)

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/psm/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/psm/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/psm/employees", headers=headers, params=params)

    # --- TrainingRecord ---
    def create_training_record(self, payload, headers):
        return self._request("POST", "/psm/training-records", payload, headers)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/psm/training-records/{record_id}",
                             headers=headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/psm/training-records", headers=headers,
                             params=params)

    # --- DrillEvent ---
    def create_drill_event(self, payload, headers):
        return self._request("POST", "/psm/drill-events", payload, headers)

    def get_drill_event(self, drill_id, headers):
        return self._request("GET", f"/psm/drill-events/{drill_id}", headers=headers)

    def list_drill_events(self, headers, params=None):
        return self._request("GET", "/psm/drill-events", headers=headers,
                             params=params)

    def conduct_drill(self, drill_id, payload, headers):
        return self._request("POST", f"/psm/drill-events/{drill_id}/conduct",
                             payload, headers)

    # --- Incident ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/psm/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/psm/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/psm/incidents", headers=headers, params=params)

    def assign_investigator(self, incident_id, payload, headers):
        return self._request("POST",
                             f"/psm/incidents/{incident_id}/assign-investigator",
                             payload, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/psm/incidents/{incident_id}/close",
                             headers=headers)

    def reopen_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/psm/incidents/{incident_id}/reopen",
                             payload, headers)

    # --- CorrectiveAction ---
    def create_corrective_action(self, payload, headers):
        return self._request("POST", "/psm/corrective-actions", payload, headers)

    def get_corrective_action(self, action_id, headers):
        return self._request("GET", f"/psm/corrective-actions/{action_id}",
                             headers=headers)

    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/psm/corrective-actions", headers=headers,
                             params=params)

    def complete_corrective_action(self, action_id, headers):
        return self._request("POST", f"/psm/corrective-actions/{action_id}/complete",
                             headers=headers)

    def verify_corrective_action(self, action_id, headers):
        return self._request("POST", f"/psm/corrective-actions/{action_id}/verify",
                             headers=headers)

    def reject_corrective_action(self, action_id, headers):
        return self._request("POST", f"/psm/corrective-actions/{action_id}/reject",
                             headers=headers)

    # --- ComplianceAudit ---
    def create_compliance_audit(self, payload, headers):
        return self._request("POST", "/psm/compliance-audits", payload, headers)

    def get_compliance_audit(self, audit_id, headers):
        return self._request("GET", f"/psm/compliance-audits/{audit_id}",
                             headers=headers)

    def list_compliance_audits(self, headers, params=None):
        return self._request("GET", "/psm/compliance-audits", headers=headers,
                             params=params)

    def start_compliance_audit(self, audit_id, headers):
        return self._request("POST", f"/psm/compliance-audits/{audit_id}/start",
                             headers=headers)

    def close_compliance_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/psm/compliance-audits/{audit_id}/close",
                             payload, headers)

    # --- Contractor ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/psm/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/psm/contractors/{contractor_id}",
                             headers=headers)

    def qualify_contractor(self, contractor_id, payload, headers):
        return self._request("POST", f"/psm/contractors/{contractor_id}/qualify",
                             payload, headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/psm/contractors/{contractor_id}/suspend",
                             headers=headers)

    def reinstate_contractor(self, contractor_id, headers):
        return self._request("POST", f"/psm/contractors/{contractor_id}/reinstate",
                             headers=headers)

    # --- HotWorkPermit ---
    def create_hot_work_permit(self, payload, headers):
        return self._request("POST", "/psm/hot-work-permits", payload, headers)

    def get_hot_work_permit(self, permit_id, headers):
        return self._request("GET", f"/psm/hot-work-permits/{permit_id}",
                             headers=headers)

    def list_hot_work_permits(self, headers, params=None):
        return self._request("GET", "/psm/hot-work-permits", headers=headers,
                             params=params)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/psm/hot-work-permits/{permit_id}/issue",
                             headers=headers)

    def start_permit(self, permit_id, headers):
        return self._request("POST", f"/psm/hot-work-permits/{permit_id}/start",
                             headers=headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"/psm/hot-work-permits/{permit_id}/close",
                             headers=headers)

    def void_permit(self, permit_id, headers):
        return self._request("POST", f"/psm/hot-work-permits/{permit_id}/void",
                             headers=headers)

    # --- LeakEvent ---
    def create_leak_event(self, payload, headers):
        return self._request("POST", "/psm/leak-events", payload, headers)

    def get_leak_event(self, leak_id, headers):
        return self._request("GET", f"/psm/leak-events/{leak_id}", headers=headers)

    def list_leak_events(self, headers, params=None):
        return self._request("GET", "/psm/leak-events", headers=headers,
                             params=params)

    def confirm_leak(self, leak_id, payload, headers):
        return self._request("POST", f"/psm/leak-events/{leak_id}/confirm",
                             payload, headers)

    def false_alarm_leak(self, leak_id, headers):
        return self._request("POST", f"/psm/leak-events/{leak_id}/false-alarm",
                             headers=headers)

    def notify_regulator(self, leak_id, headers):
        return self._request("POST", f"/psm/leak-events/{leak_id}/notify-regulator",
                             headers=headers)

    # --- Checkpoint ---
    def run_checkpoint(self, headers):
        return self._request("POST", "/psm/checkpoints/run", headers=headers)


api_client = ApiClient()
