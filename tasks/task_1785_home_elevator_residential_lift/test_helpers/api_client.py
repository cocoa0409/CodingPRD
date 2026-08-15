"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/api/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/api/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/api/properties/{property_id}", headers=headers)

    # --- SiteSurvey ---
    def create_survey(self, payload, headers):
        return self._request("POST", "/api/surveys", payload, headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/api/surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/api/surveys/{survey_id}", headers=headers)

    def complete_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/api/surveys/{survey_id}/complete", payload, headers)

    def cancel_survey(self, survey_id, headers):
        return self._request("POST", f"/api/surveys/{survey_id}/cancel", {}, headers)

    # --- ProductModel ---
    def create_product_model(self, payload, headers):
        return self._request("POST", "/api/product-models", payload, headers)

    def list_product_models(self, headers, params=None):
        return self._request("GET", "/api/product-models", headers=headers, params=params)

    def get_product_model(self, product_model_id, headers):
        return self._request("GET", f"/api/product-models/{product_model_id}", headers=headers)

    def discontinue_product_model(self, product_model_id, headers):
        return self._request("POST", f"/api/product-models/{product_model_id}/discontinue", {}, headers)

    # --- Technician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/api/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/api/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/api/technicians/{technician_id}", headers=headers)

    def deactivate_technician(self, technician_id, headers):
        return self._request("POST", f"/api/technicians/{technician_id}/deactivate", {}, headers)

    # --- Contractor ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/api/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/api/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/api/contractors/{contractor_id}", headers=headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/api/contractors/{contractor_id}/suspend", {}, headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def update_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/api/projects/{project_id}", payload, headers)

    def schedule_installation(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/schedule-installation", payload, headers)

    def complete_installation(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/complete-installation", payload, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/cancel", {}, headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/close", {}, headers)

    # --- PermitApplication ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/api/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/api/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/api/permits/{permit_id}", headers=headers)

    def request_corrections(self, permit_id, payload, headers):
        return self._request("POST", f"/api/permits/{permit_id}/request-corrections", payload, headers)

    def resubmit_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/resubmit", {}, headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/api/permits/{permit_id}/approve", {}, headers)

    def deny_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/api/permits/{permit_id}/deny", payload, headers)

    # --- StructuralWorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/api/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/api/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/api/work-orders/{work_order_id}", headers=headers)

    def release_work_order(self, work_order_id, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/release", {}, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/complete-work", payload, headers)

    def verify_work_order(self, work_order_id, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/verify", {}, headers)

    def reject_work_order_verification(self, work_order_id, payload, headers):
        return self._request("POST", f"/api/work-orders/{work_order_id}/reject-verification", payload, headers)

    # --- ElevatorUnit ---
    def list_units(self, headers, params=None):
        return self._request("GET", "/api/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/api/units/{unit_id}", headers=headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/api/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/api/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/api/inspections/{inspection_id}", headers=headers)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request("POST", f"/api/inspections/{inspection_id}/record-result", payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/api/inspections/{inspection_id}/cancel", {}, headers)

    # --- RegistrationCertificate ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/api/registration-certificates", payload, headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/api/registration-certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/api/registration-certificates/{certificate_id}", headers=headers)

    def issue_certificate(self, certificate_id, headers):
        return self._request("POST", f"/api/registration-certificates/{certificate_id}/issue", {}, headers)

    def renew_certificate(self, certificate_id, headers):
        return self._request("POST", f"/api/registration-certificates/{certificate_id}/renew", {}, headers)

    # --- ServiceContract ---
    def create_service_contract(self, payload, headers):
        return self._request("POST", "/api/service-contracts", payload, headers)

    def list_service_contracts(self, headers, params=None):
        return self._request("GET", "/api/service-contracts", headers=headers, params=params)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/api/service-contracts/{contract_id}", headers=headers)

    def update_service_contract(self, contract_id, payload, headers):
        return self._request("PATCH", f"/api/service-contracts/{contract_id}", payload, headers)

    def activate_service_contract(self, contract_id, headers):
        return self._request("POST", f"/api/service-contracts/{contract_id}/activate", {}, headers)

    def suspend_service_contract(self, contract_id, headers):
        return self._request("POST", f"/api/service-contracts/{contract_id}/suspend", {}, headers)

    def resume_service_contract(self, contract_id, headers):
        return self._request("POST", f"/api/service-contracts/{contract_id}/resume", {}, headers)

    def terminate_service_contract(self, contract_id, headers):
        return self._request("POST", f"/api/service-contracts/{contract_id}/terminate", {}, headers)

    # --- ServiceCall ---
    def create_service_call(self, payload, headers):
        return self._request("POST", "/api/service-calls", payload, headers)

    def list_service_calls(self, headers, params=None):
        return self._request("GET", "/api/service-calls", headers=headers, params=params)

    def get_service_call(self, service_call_id, headers):
        return self._request("GET", f"/api/service-calls/{service_call_id}", headers=headers)

    def dispatch_service_call(self, service_call_id, payload, headers):
        return self._request("POST", f"/api/service-calls/{service_call_id}/dispatch", payload, headers)

    def arrive_service_call(self, service_call_id, headers):
        return self._request("POST", f"/api/service-calls/{service_call_id}/arrive", {}, headers)

    def resolve_service_call(self, service_call_id, payload, headers):
        return self._request("POST", f"/api/service-calls/{service_call_id}/resolve", payload, headers)

    def cancel_service_call(self, service_call_id, headers):
        return self._request("POST", f"/api/service-calls/{service_call_id}/cancel", {}, headers)

    # --- GrantProgram ---
    def create_grant_program(self, payload, headers):
        return self._request("POST", "/api/grant-programs", payload, headers)

    def list_grant_programs(self, headers, params=None):
        return self._request("GET", "/api/grant-programs", headers=headers, params=params)

    def get_grant_program(self, program_id, headers):
        return self._request("GET", f"/api/grant-programs/{program_id}", headers=headers)

    def pause_grant_program(self, program_id, headers):
        return self._request("POST", f"/api/grant-programs/{program_id}/pause", {}, headers)

    def resume_grant_program(self, program_id, headers):
        return self._request("POST", f"/api/grant-programs/{program_id}/resume", {}, headers)

    def close_grant_program(self, program_id, headers):
        return self._request("POST", f"/api/grant-programs/{program_id}/close", {}, headers)

    # --- GrantApplication ---
    def create_grant_application(self, payload, headers):
        return self._request("POST", "/api/grant-applications", payload, headers)

    def list_grant_applications(self, headers, params=None):
        return self._request("GET", "/api/grant-applications", headers=headers, params=params)

    def get_grant_application(self, application_id, headers):
        return self._request("GET", f"/api/grant-applications/{application_id}", headers=headers)

    def approve_grant_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/grant-applications/{application_id}/approve", payload, headers)

    def deny_grant_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/grant-applications/{application_id}/deny", payload, headers)

    def withdraw_grant_application(self, application_id, headers):
        return self._request("POST", f"/api/grant-applications/{application_id}/withdraw", {}, headers)

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/api/change-orders", payload, headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/api/change-orders", headers=headers, params=params)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/api/change-orders/{change_order_id}", headers=headers)

    def approve_change_order(self, change_order_id, headers):
        return self._request("POST", f"/api/change-orders/{change_order_id}/approve", {}, headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/api/change-orders/{change_order_id}/reject", {}, headers)


api_client = ApiClient()
