"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Machines and modifications
    # ------------------------------------------------------------------
    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/machines", headers=headers, params=params)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    def create_machine_modification(self, machine_id, payload, headers):
        return self._request("POST", f"/machines/{machine_id}/modifications",
                             payload, headers)

    def list_machine_modifications(self, machine_id, headers, params=None):
        return self._request("GET", f"/machines/{machine_id}/modifications",
                             headers=headers, params=params)

    def out_of_service_machine(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/out-of-service",
                             {}, headers)

    def return_to_service_machine(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/return-to-service",
                             {}, headers)

    # ------------------------------------------------------------------
    # Energy surveys
    # ------------------------------------------------------------------
    def create_energy_survey(self, payload, headers):
        return self._request("POST", "/energy-surveys", payload, headers)

    def list_energy_surveys(self, headers, params=None):
        return self._request("GET", "/energy-surveys", headers=headers, params=params)

    def get_energy_survey(self, survey_id, headers):
        return self._request("GET", f"/energy-surveys/{survey_id}", headers=headers)

    def submit_energy_survey(self, survey_id, headers):
        return self._request("POST", f"/energy-surveys/{survey_id}/submit", {}, headers)

    def approve_energy_survey(self, survey_id, headers):
        return self._request("POST", f"/energy-surveys/{survey_id}/approve", {}, headers)

    def reject_energy_survey(self, survey_id, headers, payload=None):
        return self._request("POST", f"/energy-surveys/{survey_id}/reject",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Lockout procedures
    # ------------------------------------------------------------------
    def create_lockout_procedure(self, payload, headers):
        return self._request("POST", "/lockout-procedures", payload, headers)

    def list_lockout_procedures(self, headers, params=None):
        return self._request("GET", "/lockout-procedures", headers=headers, params=params)

    def get_lockout_procedure(self, procedure_id, headers):
        return self._request("GET", f"/lockout-procedures/{procedure_id}", headers=headers)

    def activate_lockout_procedure(self, procedure_id, payload, headers):
        return self._request("POST", f"/lockout-procedures/{procedure_id}/activate",
                             payload or {}, headers)

    def retire_lockout_procedure(self, procedure_id, headers):
        return self._request("POST", f"/lockout-procedures/{procedure_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Employees and training
    # ------------------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def create_training_record(self, payload, headers):
        return self._request("POST", "/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}", headers=headers)

    def complete_training_record(self, record_id, headers):
        return self._request("POST", f"/training-records/{record_id}/complete",
                             {}, headers)

    # ------------------------------------------------------------------
    # Lockout sessions
    # ------------------------------------------------------------------
    def create_lockout_session(self, payload, headers):
        return self._request("POST", "/lockout-sessions", payload, headers)

    def list_lockout_sessions(self, headers, params=None):
        return self._request("GET", "/lockout-sessions", headers=headers, params=params)

    def get_lockout_session(self, session_id, headers):
        return self._request("GET", f"/lockout-sessions/{session_id}", headers=headers)

    def lock_lockout_session(self, session_id, payload, headers):
        return self._request("POST", f"/lockout-sessions/{session_id}/lock",
                             payload, headers)

    def clear_lockout_session(self, session_id, headers):
        return self._request("POST", f"/lockout-sessions/{session_id}/clear",
                             {}, headers)

    def release_lockout_session(self, session_id, headers):
        return self._request("POST", f"/lockout-sessions/{session_id}/release",
                             {}, headers)

    def cancel_lockout_session(self, session_id, headers):
        return self._request("POST", f"/lockout-sessions/{session_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Employee locks
    # ------------------------------------------------------------------
    def create_employee_lock(self, payload, headers):
        return self._request("POST", "/employee-locks", payload, headers)

    def list_employee_locks(self, headers, params=None):
        return self._request("GET", "/employee-locks", headers=headers, params=params)

    def get_employee_lock(self, lock_id, headers):
        return self._request("GET", f"/employee-locks/{lock_id}", headers=headers)

    def apply_employee_lock(self, lock_id, headers):
        return self._request("POST", f"/employee-locks/{lock_id}/apply", {}, headers)

    def remove_employee_lock(self, lock_id, headers):
        return self._request("POST", f"/employee-locks/{lock_id}/remove", {}, headers)

    def force_remove_employee_lock(self, lock_id, payload, headers):
        return self._request("POST", f"/employee-locks/{lock_id}/force-remove",
                             payload, headers)

    # ------------------------------------------------------------------
    # Procedure audits
    # ------------------------------------------------------------------
    def create_procedure_audit(self, payload, headers):
        return self._request("POST", "/procedure-audits", payload, headers)

    def list_procedure_audits(self, headers, params=None):
        return self._request("GET", "/procedure-audits", headers=headers, params=params)

    def get_procedure_audit(self, audit_id, headers):
        return self._request("GET", f"/procedure-audits/{audit_id}", headers=headers)

    def complete_procedure_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/procedure-audits/{audit_id}/complete",
                             payload, headers)

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/incident-reports/{incident_id}", headers=headers)

    def link_incident_report(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/link",
                             {}, headers)

    def dismiss_incident_report(self, incident_id, headers):
        return self._request("POST", f"/incident-reports/{incident_id}/dismiss",
                             {}, headers)

    # ------------------------------------------------------------------
    # Contractor permits
    # ------------------------------------------------------------------
    def create_contractor_permit(self, payload, headers):
        return self._request("POST", "/contractor-permits", payload, headers)

    def list_contractor_permits(self, headers, params=None):
        return self._request("GET", "/contractor-permits", headers=headers, params=params)

    def get_contractor_permit(self, permit_id, headers):
        return self._request("GET", f"/contractor-permits/{permit_id}", headers=headers)

    def approve_contractor_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/contractor-permits/{permit_id}/approve",
                             payload, headers)

    def reject_contractor_permit(self, permit_id, headers):
        return self._request("POST", f"/contractor-permits/{permit_id}/reject",
                             {}, headers)

    def activate_contractor_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/contractor-permits/{permit_id}/activate",
                             payload, headers)

    # ------------------------------------------------------------------
    # Minor-servicing exceptions
    # ------------------------------------------------------------------
    def create_minor_servicing_exception(self, payload, headers):
        return self._request("POST", "/minor-servicing-exceptions", payload, headers)

    def list_minor_servicing_exceptions(self, headers, params=None):
        return self._request("GET", "/minor-servicing-exceptions",
                             headers=headers, params=params)

    def get_minor_servicing_exception(self, exception_id, headers):
        return self._request("GET", f"/minor-servicing-exceptions/{exception_id}",
                             headers=headers)

    def determine_minor_servicing_exception(self, exception_id, headers):
        return self._request("POST",
                             f"/minor-servicing-exceptions/{exception_id}/determine",
                             {}, headers)

    def revoke_minor_servicing_exception(self, exception_id, headers):
        return self._request("POST",
                             f"/minor-servicing-exceptions/{exception_id}/revoke",
                             {}, headers)


api_client = ApiClient()
