"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Configuration & resources ----
    def create_meter_size_schedule(self, payload, headers):
        return self._request("POST", "/meter-size-schedules", payload, headers)

    def list_meter_size_schedules(self, headers, params=None):
        return self._request("GET", "/meter-size-schedules", headers=headers, params=params)

    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/inspectors", headers=headers, params=params)

    def create_meter_crew(self, payload, headers):
        return self._request("POST", "/meter-crews", payload, headers)

    def list_meter_crews(self, headers, params=None):
        return self._request("GET", "/meter-crews", headers=headers, params=params)

    # ---- Connection application lifecycle ----
    def create_application(self, payload, headers):
        return self._request("POST", "/connection-applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/connection-applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/connection-applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/connection-applications/{application_id}/submit", payload, headers)

    def start_review(self, application_id, headers, payload=None):
        return self._request("POST", f"/connection-applications/{application_id}/start-review", payload, headers)

    def request_revision(self, application_id, headers, payload=None):
        return self._request("POST", f"/connection-applications/{application_id}/request-revision", payload, headers)

    def approve_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/connection-applications/{application_id}/approve", payload, headers)

    def deny_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/connection-applications/{application_id}/deny", payload, headers)

    def pay_fees(self, application_id, payload, headers):
        return self._request("POST", f"/connection-applications/{application_id}/pay-fees", payload, headers)

    def activate_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/connection-applications/{application_id}/activate", payload, headers)

    def withdraw_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/connection-applications/{application_id}/withdraw", payload, headers)

    # ---- Availability ----
    def create_availability_determination(self, payload, headers):
        return self._request("POST", "/availability-determinations", payload, headers)

    def list_availability_determinations(self, headers, params=None):
        return self._request("GET", "/availability-determinations", headers=headers, params=params)

    def get_availability_determination(self, determination_id, headers):
        return self._request("GET", f"/availability-determinations/{determination_id}", headers=headers)

    # ---- Main extension & developer agreement ----
    def create_project(self, payload, headers):
        return self._request("POST", "/main-extension-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/main-extension-projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/main-extension-projects/{project_id}", headers=headers)

    def start_construction(self, project_id, headers, payload=None):
        return self._request("POST", f"/main-extension-projects/{project_id}/start-construction", payload, headers)

    def record_inspection(self, project_id, headers, payload=None):
        return self._request("POST", f"/main-extension-projects/{project_id}/record-inspection", payload, headers)

    def accept_project(self, project_id, payload, headers):
        return self._request("POST", f"/main-extension-projects/{project_id}/accept", payload, headers)

    def cancel_project(self, project_id, headers, payload=None):
        return self._request("POST", f"/main-extension-projects/{project_id}/cancel", payload, headers)

    def create_agreement(self, payload, headers):
        return self._request("POST", "/developer-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/developer-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/developer-agreements/{agreement_id}", headers=headers)

    def offer_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/developer-agreements/{agreement_id}/offer", payload, headers)

    def execute_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/developer-agreements/{agreement_id}/execute", payload, headers)

    def create_escrow_transaction(self, agreement_id, payload, headers):
        return self._request("POST", f"/developer-agreements/{agreement_id}/escrow-transactions", payload, headers)

    def list_escrow_transactions(self, agreement_id, headers, params=None):
        return self._request("GET", f"/developer-agreements/{agreement_id}/escrow-transactions", headers=headers, params=params)

    def close_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/developer-agreements/{agreement_id}/close", payload, headers)

    def terminate_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/developer-agreements/{agreement_id}/terminate", payload, headers)

    # ---- Inspection & meter set ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def schedule_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/inspections/{inspection_id}/schedule", payload, headers)

    def start_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/inspections/{inspection_id}/start", payload, headers)

    def pass_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/inspections/{inspection_id}/pass", payload, headers)

    def fail_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/inspections/{inspection_id}/fail", payload, headers)

    def cancel_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/inspections/{inspection_id}/cancel", payload, headers)

    def create_meter_set(self, payload, headers):
        return self._request("POST", "/meter-sets", payload, headers)

    def list_meter_sets(self, headers, params=None):
        return self._request("GET", "/meter-sets", headers=headers, params=params)

    def get_meter_set(self, meter_set_id, headers):
        return self._request("GET", f"/meter-sets/{meter_set_id}", headers=headers)

    def schedule_meter_set(self, meter_set_id, headers, payload=None):
        return self._request("POST", f"/meter-sets/{meter_set_id}/schedule", payload, headers)

    def complete_install_meter_set(self, meter_set_id, headers, payload=None):
        return self._request("POST", f"/meter-sets/{meter_set_id}/complete-install", payload, headers)

    def remove_meter_set(self, meter_set_id, headers, payload=None):
        return self._request("POST", f"/meter-sets/{meter_set_id}/remove", payload, headers)

    # ---- Backflow ----
    def list_backflow_assemblies(self, headers, params=None):
        return self._request("GET", "/backflow-assemblies", headers=headers, params=params)

    def get_backflow_assembly(self, assembly_id, headers):
        return self._request("GET", f"/backflow-assemblies/{assembly_id}", headers=headers)

    def install_backflow_assembly(self, assembly_id, payload, headers):
        return self._request("POST", f"/backflow-assemblies/{assembly_id}/install", payload, headers)

    # ---- Service account ----
    def list_service_accounts(self, headers, params=None):
        return self._request("GET", "/service-accounts", headers=headers, params=params)

    def get_service_account(self, account_id, headers):
        return self._request("GET", f"/service-accounts/{account_id}", headers=headers)

    def suspend_service_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/service-accounts/{account_id}/suspend", payload, headers)

    def reinstate_service_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/service-accounts/{account_id}/reinstate", payload, headers)

    def close_service_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/service-accounts/{account_id}/close", payload, headers)

    # ---- Latecomer / reimbursement ----
    def create_latecomer_reimbursement(self, payload, headers):
        return self._request("POST", "/latecomer-reimbursements", payload, headers)

    def list_latecomer_reimbursements(self, headers, params=None):
        return self._request("GET", "/latecomer-reimbursements", headers=headers, params=params)

    def get_latecomer_reimbursement(self, reimbursement_id, headers):
        return self._request("GET", f"/latecomer-reimbursements/{reimbursement_id}", headers=headers)

    def collect_latecomer_reimbursement(self, reimbursement_id, headers, payload=None):
        return self._request("POST", f"/latecomer-reimbursements/{reimbursement_id}/collect", payload, headers)

    def waive_latecomer_reimbursement(self, reimbursement_id, headers, payload=None):
        return self._request("POST", f"/latecomer-reimbursements/{reimbursement_id}/waive", payload, headers)


api_client = ApiClient()
