"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- RetentionPolicy ---
    def create_retention_policy(self, payload, headers=None):
        return self._request("POST", "/privacy/retention-policies", payload, headers)

    # --- DataElement ---
    def create_data_element(self, payload, headers=None):
        return self._request("POST", "/privacy/data-elements", payload, headers)

    def get_data_element(self, element_id, headers=None):
        return self._request("GET", f"/privacy/data-elements/{element_id}", headers=headers)

    def reclassify_data_element(self, element_id, payload, headers=None):
        return self._request("POST", f"/privacy/data-elements/{element_id}/reclassify", payload, headers)

    def retire_data_element(self, element_id, headers=None):
        return self._request("POST", f"/privacy/data-elements/{element_id}/retire", headers=headers)

    # --- DataSystem ---
    def create_data_system(self, payload, headers=None):
        return self._request("POST", "/privacy/data-systems", payload, headers)

    def list_data_systems(self, headers=None, params=None):
        return self._request("GET", "/privacy/data-systems", headers=headers, params=params)

    def decommission_data_system(self, system_id, headers=None):
        return self._request("POST", f"/privacy/data-systems/{system_id}/decommission", headers=headers)

    # --- Notice ---
    def create_notice(self, payload, headers=None):
        return self._request("POST", "/privacy/notices", payload, headers)

    def list_notices(self, headers=None, params=None):
        return self._request("GET", "/privacy/notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers=None):
        return self._request("GET", f"/privacy/notices/{notice_id}", headers=headers)

    def publish_notice(self, notice_id, headers=None):
        return self._request("POST", f"/privacy/notices/{notice_id}/publish", headers=headers)

    def retract_notice(self, notice_id, headers=None):
        return self._request("POST", f"/privacy/notices/{notice_id}/retract", headers=headers)

    # --- StateLawRule ---
    def create_state_law_rule(self, payload, headers=None):
        return self._request("POST", "/privacy/state-law-rules", payload, headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers=None):
        return self._request("POST", "/privacy/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers=None):
        return self._request("GET", f"/privacy/vendors/{vendor_id}", headers=headers)

    def submit_vendor_assessment(self, vendor_id, headers=None):
        return self._request("POST", f"/privacy/vendors/{vendor_id}/submit-assessment", headers=headers)

    def approve_vendor(self, vendor_id, headers=None):
        return self._request("POST", f"/privacy/vendors/{vendor_id}/approve", headers=headers)

    def reject_vendor(self, vendor_id, headers=None):
        return self._request("POST", f"/privacy/vendors/{vendor_id}/reject", headers=headers)

    def offboard_vendor(self, vendor_id, headers=None):
        return self._request("POST", f"/privacy/vendors/{vendor_id}/offboard", headers=headers)

    # --- VendorContract ---
    def create_contract(self, vendor_id, payload, headers=None):
        return self._request("POST", f"/privacy/vendors/{vendor_id}/contracts", payload, headers)

    def list_contracts(self, vendor_id, headers=None, params=None):
        return self._request("GET", f"/privacy/vendors/{vendor_id}/contracts", headers=headers, params=params)

    def verify_contract(self, contract_id, headers=None):
        return self._request("POST", f"/privacy/contracts/{contract_id}/verify", headers=headers)

    def execute_contract(self, contract_id, headers=None):
        return self._request("POST", f"/privacy/contracts/{contract_id}/execute", headers=headers)

    # --- ProcessingActivity ---
    def create_activity(self, payload, headers=None):
        return self._request("POST", "/privacy/processing-activities", payload, headers)

    def list_activities(self, headers=None, params=None):
        return self._request("GET", "/privacy/processing-activities", headers=headers, params=params)

    def get_activity(self, activity_id, headers=None):
        return self._request("GET", f"/privacy/processing-activities/{activity_id}", headers=headers)

    def activate_activity(self, activity_id, headers=None):
        return self._request("POST", f"/privacy/processing-activities/{activity_id}/activate", headers=headers)

    def resume_activity(self, activity_id, headers=None):
        return self._request("POST", f"/privacy/processing-activities/{activity_id}/resume", headers=headers)

    def retire_activity(self, activity_id, headers=None):
        return self._request("POST", f"/privacy/processing-activities/{activity_id}/retire", headers=headers)

    # --- Purpose ---
    def create_purpose(self, activity_id, payload, headers=None):
        return self._request("POST", f"/privacy/processing-activities/{activity_id}/purposes", payload, headers)

    def list_activity_purposes(self, activity_id, headers=None, params=None):
        return self._request("GET", f"/privacy/processing-activities/{activity_id}/purposes", headers=headers, params=params)

    def get_purpose(self, purpose_id, headers=None):
        return self._request("GET", f"/privacy/purposes/{purpose_id}", headers=headers)

    def list_purposes(self, headers=None, params=None):
        return self._request("GET", "/privacy/purposes", headers=headers, params=params)

    def relink_purpose(self, purpose_id, headers=None):
        return self._request("POST", f"/privacy/purposes/{purpose_id}/relink", headers=headers)

    def retire_purpose(self, purpose_id, headers=None):
        return self._request("POST", f"/privacy/purposes/{purpose_id}/retire", headers=headers)

    # --- PrivacyImpactAssessment ---
    def create_assessment(self, activity_id, headers=None):
        return self._request("POST", f"/privacy/processing-activities/{activity_id}/assessments", headers=headers)

    def list_activity_assessments(self, activity_id, headers=None, params=None):
        return self._request("GET", f"/privacy/processing-activities/{activity_id}/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers=None):
        return self._request("GET", f"/privacy/assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, assessment_id, headers=None):
        return self._request("POST", f"/privacy/assessments/{assessment_id}/submit", headers=headers)

    def approve_assessment(self, assessment_id, headers=None):
        return self._request("POST", f"/privacy/assessments/{assessment_id}/approve", headers=headers)

    def request_changes_assessment(self, assessment_id, headers=None):
        return self._request("POST", f"/privacy/assessments/{assessment_id}/request-changes", headers=headers)

    def reject_assessment(self, assessment_id, headers=None):
        return self._request("POST", f"/privacy/assessments/{assessment_id}/reject", headers=headers)

    # --- Consumer ---
    def create_consumer(self, payload, headers=None):
        return self._request("POST", "/privacy/consumers", payload, headers)

    def get_consumer(self, consumer_id, headers=None):
        return self._request("GET", f"/privacy/consumers/{consumer_id}", headers=headers)

    # --- RightsRequest ---
    def create_rights_request(self, consumer_id, payload, headers=None):
        return self._request("POST", f"/privacy/consumers/{consumer_id}/rights-requests", payload, headers)

    def list_consumer_requests(self, consumer_id, headers=None, params=None):
        return self._request("GET", f"/privacy/consumers/{consumer_id}/rights-requests", headers=headers, params=params)

    def get_rights_request(self, request_id, headers=None):
        return self._request("GET", f"/privacy/rights-requests/{request_id}", headers=headers)

    def verify_rights_request(self, request_id, headers=None):
        return self._request("POST", f"/privacy/rights-requests/{request_id}/verify", headers=headers)

    def fail_verification_rights_request(self, request_id, headers=None):
        return self._request("POST", f"/privacy/rights-requests/{request_id}/fail-verification", headers=headers)

    def route_rights_request(self, request_id, headers=None):
        return self._request("POST", f"/privacy/rights-requests/{request_id}/route", headers=headers)

    def deny_rights_request(self, request_id, payload=None, headers=None):
        return self._request("POST", f"/privacy/rights-requests/{request_id}/deny", payload or {}, headers)

    def respond_rights_request(self, request_id, headers=None):
        return self._request("POST", f"/privacy/rights-requests/{request_id}/respond", headers=headers)

    # --- RequestTask ---
    def list_request_tasks(self, request_id, headers=None, params=None):
        return self._request("GET", f"/privacy/rights-requests/{request_id}/tasks", headers=headers, params=params)

    def get_task(self, task_id, headers=None):
        return self._request("GET", f"/privacy/tasks/{task_id}", headers=headers)

    def list_tasks(self, headers=None, params=None):
        return self._request("GET", "/privacy/tasks", headers=headers, params=params)

    def start_task(self, task_id, headers=None):
        return self._request("POST", f"/privacy/tasks/{task_id}/start", headers=headers)

    def complete_task(self, task_id, payload=None, headers=None):
        return self._request("POST", f"/privacy/tasks/{task_id}/complete", payload or {}, headers)

    # --- CrossBorderTransfer ---
    def create_transfer(self, payload, headers=None):
        return self._request("POST", "/privacy/transfers", payload, headers)

    def list_transfers(self, headers=None, params=None):
        return self._request("GET", "/privacy/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers=None):
        return self._request("GET", f"/privacy/transfers/{transfer_id}", headers=headers)

    def assess_transfer(self, transfer_id, headers=None):
        return self._request("POST", f"/privacy/transfers/{transfer_id}/assess", headers=headers)

    def approve_transfer(self, transfer_id, headers=None):
        return self._request("POST", f"/privacy/transfers/{transfer_id}/approve", headers=headers)

    def reject_transfer(self, transfer_id, headers=None):
        return self._request("POST", f"/privacy/transfers/{transfer_id}/reject", headers=headers)

    # --- ApplicabilityEvaluation ---
    def run_applicability_evaluations(self, payload, headers=None):
        return self._request("POST", "/privacy/applicability-evaluations/run", payload, headers)

    def list_applicability_evaluations(self, headers=None, params=None):
        return self._request("GET", "/privacy/applicability-evaluations", headers=headers, params=params)

    def get_applicability_evaluation(self, evaluation_id, headers=None):
        return self._request("GET", f"/privacy/applicability-evaluations/{evaluation_id}", headers=headers)


api_client = ApiClient()
