"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def activate_facility(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/activate", headers=headers)

    def suspend_facility(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/suspend", headers=headers)

    def reinstate_facility(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/reinstate", headers=headers)

    def offboard_facility(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/offboard", headers=headers)

    # --- Compressor ---
    def create_compressor(self, payload, headers):
        return self._request("POST", "/compressors", payload, headers)

    def list_compressors(self, headers, params=None):
        return self._request("GET", "/compressors", headers=headers, params=params)

    def get_compressor(self, compressor_id, headers):
        return self._request("GET", f"/compressors/{compressor_id}", headers=headers)

    def log_run_hours(self, compressor_id, payload, headers):
        return self._request("POST", f"/compressors/{compressor_id}/log-run-hours", payload, headers)

    def mark_down(self, compressor_id, headers):
        return self._request("POST", f"/compressors/{compressor_id}/mark-down", headers=headers)

    def return_to_service(self, compressor_id, headers):
        return self._request("POST", f"/compressors/{compressor_id}/return-to-service", headers=headers)

    def decommission_compressor(self, compressor_id, headers):
        return self._request("POST", f"/compressors/{compressor_id}/decommission", headers=headers)

    # --- DemandProfile ---
    def create_demand_profile(self, payload, headers):
        return self._request("POST", "/demand-profiles", payload, headers)

    def list_demand_profiles(self, headers, params=None):
        return self._request("GET", "/demand-profiles", headers=headers, params=params)

    def get_demand_profile(self, demand_profile_id, headers):
        return self._request("GET", f"/demand-profiles/{demand_profile_id}", headers=headers)

    def lock_demand_profile(self, demand_profile_id, payload, headers):
        return self._request("POST", f"/demand-profiles/{demand_profile_id}/lock", payload, headers)

    # --- LeakSurvey / LeakTag ---
    def create_leak_survey(self, payload, headers):
        return self._request("POST", "/leak-surveys", payload, headers)

    def list_leak_surveys(self, headers, params=None):
        return self._request("GET", "/leak-surveys", headers=headers, params=params)

    def get_leak_survey(self, leak_survey_id, headers):
        return self._request("GET", f"/leak-surveys/{leak_survey_id}", headers=headers)

    def create_leak_tag(self, leak_survey_id, payload, headers):
        return self._request("POST", f"/leak-surveys/{leak_survey_id}/leak-tags", payload, headers)

    def list_leak_tags(self, headers, params=None):
        return self._request("GET", "/leak-tags", headers=headers, params=params)

    def get_leak_tag(self, leak_tag_id, headers):
        return self._request("GET", f"/leak-tags/{leak_tag_id}", headers=headers)

    def submit_leak_survey(self, leak_survey_id, headers):
        return self._request("POST", f"/leak-surveys/{leak_survey_id}/submit", headers=headers)

    def verify_leak_survey(self, leak_survey_id, headers):
        return self._request("POST", f"/leak-surveys/{leak_survey_id}/verify", headers=headers)

    def authorize_repair(self, leak_tag_id, headers):
        return self._request("POST", f"/leak-tags/{leak_tag_id}/authorize-repair", headers=headers)

    def mark_repaired(self, leak_tag_id, headers):
        return self._request("POST", f"/leak-tags/{leak_tag_id}/mark-repaired", headers=headers)

    def verify_closure(self, leak_tag_id, headers):
        return self._request("POST", f"/leak-tags/{leak_tag_id}/verify-closure", headers=headers)

    def mark_wont_fix(self, leak_tag_id, headers):
        return self._request("POST", f"/leak-tags/{leak_tag_id}/mark-wont-fix", headers=headers)

    # --- MaintenanceSchedule ---
    def create_maintenance_schedule(self, payload, headers):
        return self._request("POST", "/maintenance-schedules", payload, headers)

    def list_maintenance_schedules(self, headers, params=None):
        return self._request("GET", "/maintenance-schedules", headers=headers, params=params)

    def get_maintenance_schedule(self, maintenance_schedule_id, headers):
        return self._request("GET", f"/maintenance-schedules/{maintenance_schedule_id}", headers=headers)

    def record_service(self, maintenance_schedule_id, payload, headers):
        return self._request("POST", f"/maintenance-schedules/{maintenance_schedule_id}/record-service", payload, headers)

    def retire_maintenance_schedule(self, maintenance_schedule_id, headers):
        return self._request("POST", f"/maintenance-schedules/{maintenance_schedule_id}/retire", headers=headers)

    # --- RetrofitProject ---
    def create_retrofit_project(self, payload, headers):
        return self._request("POST", "/retrofit-projects", payload, headers)

    def list_retrofit_projects(self, headers, params=None):
        return self._request("GET", "/retrofit-projects", headers=headers, params=params)

    def get_retrofit_project(self, retrofit_project_id, headers):
        return self._request("GET", f"/retrofit-projects/{retrofit_project_id}", headers=headers)

    def approve_retrofit_project(self, retrofit_project_id, headers):
        return self._request("POST", f"/retrofit-projects/{retrofit_project_id}/approve", headers=headers)

    def mark_retrofit_installed(self, retrofit_project_id, headers):
        return self._request("POST", f"/retrofit-projects/{retrofit_project_id}/mark-installed", headers=headers)

    def commission_retrofit_project(self, retrofit_project_id, headers):
        return self._request("POST", f"/retrofit-projects/{retrofit_project_id}/commission", headers=headers)

    def accept_retrofit_project(self, retrofit_project_id, headers):
        return self._request("POST", f"/retrofit-projects/{retrofit_project_id}/accept", headers=headers)

    # --- SavingsCase ---
    def create_savings_case(self, payload, headers):
        return self._request("POST", "/savings-cases", payload, headers)

    def list_savings_cases(self, headers, params=None):
        return self._request("GET", "/savings-cases", headers=headers, params=params)

    def get_savings_case(self, savings_case_id, headers):
        return self._request("GET", f"/savings-cases/{savings_case_id}", headers=headers)

    def model_savings_case(self, savings_case_id, headers):
        return self._request("POST", f"/savings-cases/{savings_case_id}/model", headers=headers)

    def rebase_savings_case(self, savings_case_id, payload, headers):
        return self._request("POST", f"/savings-cases/{savings_case_id}/rebase", payload, headers)

    def open_measurement(self, savings_case_id, headers):
        return self._request("POST", f"/savings-cases/{savings_case_id}/open-measurement", headers=headers)

    def close_measurement(self, savings_case_id, payload, headers):
        return self._request("POST", f"/savings-cases/{savings_case_id}/close-measurement", payload, headers)

    def file_rebate(self, savings_case_id, headers):
        return self._request("POST", f"/savings-cases/{savings_case_id}/file-rebate", headers=headers)

    def record_rebate_decision(self, savings_case_id, payload, headers):
        return self._request("POST", f"/savings-cases/{savings_case_id}/record-rebate-decision", payload, headers)

    # --- ServiceContract ---
    def create_service_contract(self, payload, headers):
        return self._request("POST", "/service-contracts", payload, headers)

    def list_service_contracts(self, headers, params=None):
        return self._request("GET", "/service-contracts", headers=headers, params=params)

    def get_service_contract(self, service_contract_id, headers):
        return self._request("GET", f"/service-contracts/{service_contract_id}", headers=headers)

    def activate_service_contract(self, service_contract_id, payload, headers):
        return self._request("POST", f"/service-contracts/{service_contract_id}/activate", payload, headers)

    def suspend_service_contract(self, service_contract_id, headers):
        return self._request("POST", f"/service-contracts/{service_contract_id}/suspend", headers=headers)

    def reinstate_service_contract(self, service_contract_id, headers):
        return self._request("POST", f"/service-contracts/{service_contract_id}/reinstate", headers=headers)

    def terminate_service_contract(self, service_contract_id, headers):
        return self._request("POST", f"/service-contracts/{service_contract_id}/terminate", headers=headers)

    def expire_service_contract(self, service_contract_id, headers):
        return self._request("POST", f"/service-contracts/{service_contract_id}/expire", headers=headers)

    # --- ServiceTicket ---
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def get_service_ticket(self, service_ticket_id, headers):
        return self._request("GET", f"/service-tickets/{service_ticket_id}", headers=headers)

    def dispatch_ticket(self, service_ticket_id, headers):
        return self._request("POST", f"/service-tickets/{service_ticket_id}/dispatch", headers=headers)

    def record_response(self, service_ticket_id, headers):
        return self._request("POST", f"/service-tickets/{service_ticket_id}/record-response", headers=headers)

    def resolve_ticket(self, service_ticket_id, headers):
        return self._request("POST", f"/service-tickets/{service_ticket_id}/resolve", headers=headers)

    def cancel_ticket(self, service_ticket_id, headers):
        return self._request("POST", f"/service-tickets/{service_ticket_id}/cancel", headers=headers)

    # --- RentalAsset ---
    def create_rental_asset(self, payload, headers):
        return self._request("POST", "/rental-assets", payload, headers)

    def list_rental_assets(self, headers, params=None):
        return self._request("GET", "/rental-assets", headers=headers, params=params)

    def get_rental_asset(self, rental_asset_id, headers):
        return self._request("GET", f"/rental-assets/{rental_asset_id}", headers=headers)

    def set_rental_asset_maintenance(self, rental_asset_id, payload, headers):
        return self._request("POST", f"/rental-assets/{rental_asset_id}/set-maintenance", payload, headers)

    # --- RentalReservation ---
    def create_rental_reservation(self, payload, headers):
        return self._request("POST", "/rental-reservations", payload, headers)

    def list_rental_reservations(self, headers, params=None):
        return self._request("GET", "/rental-reservations", headers=headers, params=params)

    def get_rental_reservation(self, rental_reservation_id, headers):
        return self._request("GET", f"/rental-reservations/{rental_reservation_id}", headers=headers)

    def deliver_reservation(self, rental_reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{rental_reservation_id}/deliver", headers=headers)

    def return_reservation(self, rental_reservation_id, payload, headers):
        return self._request("POST", f"/rental-reservations/{rental_reservation_id}/return", payload, headers)

    def cancel_reservation(self, rental_reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{rental_reservation_id}/cancel", headers=headers)

    def invoice_reservation(self, rental_reservation_id, headers):
        return self._request("POST", f"/rental-reservations/{rental_reservation_id}/invoice", headers=headers)

    # --- GuaranteeCertificate ---
    def create_guarantee_certificate(self, payload, headers):
        return self._request("POST", "/guarantee-certificates", payload, headers)

    def list_guarantee_certificates(self, headers, params=None):
        return self._request("GET", "/guarantee-certificates", headers=headers, params=params)

    def get_guarantee_certificate(self, guarantee_certificate_id, headers):
        return self._request("GET", f"/guarantee-certificates/{guarantee_certificate_id}", headers=headers)

    def settle_certificate(self, guarantee_certificate_id, headers):
        return self._request("POST", f"/guarantee-certificates/{guarantee_certificate_id}/settle", headers=headers)

    def pay_certificate(self, guarantee_certificate_id, headers):
        return self._request("POST", f"/guarantee-certificates/{guarantee_certificate_id}/pay", headers=headers)

    def dispute_certificate(self, guarantee_certificate_id, payload, headers):
        return self._request("POST", f"/guarantee-certificates/{guarantee_certificate_id}/dispute", payload, headers)

    def resolve_dispute(self, guarantee_certificate_id, payload, headers):
        return self._request("POST", f"/guarantee-certificates/{guarantee_certificate_id}/resolve-dispute", payload, headers)

    # --- ServiceCredit ---
    def list_service_credits(self, headers, params=None):
        return self._request("GET", "/service-credits", headers=headers, params=params)

    def get_service_credit(self, service_credit_id, headers):
        return self._request("GET", f"/service-credits/{service_credit_id}", headers=headers)

    def apply_service_credit(self, service_credit_id, headers):
        return self._request("POST", f"/service-credits/{service_credit_id}/apply", headers=headers)

    def expire_service_credit(self, service_credit_id, headers):
        return self._request("POST", f"/service-credits/{service_credit_id}/expire", headers=headers)


api_client = ApiClient()
