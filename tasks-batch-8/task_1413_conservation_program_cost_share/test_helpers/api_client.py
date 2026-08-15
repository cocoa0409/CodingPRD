"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ConservationProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/eqip/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/eqip/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/eqip/programs/{program_id}", headers=headers)

    def open_program(self, program_id, headers):
        return self._request("POST", f"/eqip/programs/{program_id}/open", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/eqip/programs/{program_id}/close", {}, headers)

    def run_ranking(self, program_id, headers):
        return self._request("POST", f"/eqip/programs/{program_id}/run-ranking", {}, headers)

    # --- FundingPool ---
    def create_pool(self, program_id, payload, headers):
        return self._request("POST", f"/eqip/programs/{program_id}/pools", payload, headers)

    def list_pools(self, program_id, headers, params=None):
        return self._request("GET", f"/eqip/programs/{program_id}/pools", headers=headers, params=params)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/eqip/pools/{pool_id}", headers=headers)

    # --- PaymentScheduleRate ---
    def create_rate(self, program_id, payload, headers):
        return self._request("POST", f"/eqip/programs/{program_id}/rates", payload, headers)

    def list_rates(self, program_id, headers, params=None):
        return self._request("GET", f"/eqip/programs/{program_id}/rates", headers=headers, params=params)

    # --- RankingCriterion ---
    def create_criterion(self, program_id, payload, headers):
        return self._request("POST", f"/eqip/programs/{program_id}/ranking-criteria", payload, headers)

    def list_criteria(self, program_id, headers, params=None):
        return self._request("GET", f"/eqip/programs/{program_id}/ranking-criteria", headers=headers, params=params)

    # --- Applicant ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/eqip/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/eqip/applicants/{applicant_id}", headers=headers)

    # --- Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/eqip/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/eqip/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/eqip/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/eqip/applications/{application_id}/submit", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/eqip/applications/{application_id}/withdraw", {}, headers)

    def screen_application(self, application_id, payload, headers):
        return self._request("POST", f"/eqip/applications/{application_id}/screen", payload, headers)

    # --- Contract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/eqip/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/eqip/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/eqip/contracts", headers=headers, params=params)

    def add_practice_item(self, contract_id, payload, headers):
        return self._request("POST", f"/eqip/contracts/{contract_id}/practice-items", payload, headers)

    def list_contract_items(self, contract_id, headers, params=None):
        return self._request("GET", f"/eqip/contracts/{contract_id}/practice-items", headers=headers, params=params)

    def obligate_contract(self, contract_id, headers):
        return self._request("POST", f"/eqip/contracts/{contract_id}/obligate", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/eqip/contracts/{contract_id}/terminate", {}, headers)

    def complete_contract(self, contract_id, headers):
        return self._request("POST", f"/eqip/contracts/{contract_id}/complete", {}, headers)

    # --- ContractPracticeItem ---
    def get_practice_item(self, item_id, headers):
        return self._request("GET", f"/eqip/practice-items/{item_id}", headers=headers)

    def list_practice_items(self, headers, params=None):
        return self._request("GET", "/eqip/practice-items", headers=headers, params=params)

    def patch_practice_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/eqip/practice-items/{item_id}", payload, headers)

    def report_installed(self, item_id, headers):
        return self._request("POST", f"/eqip/practice-items/{item_id}/report-installed", {}, headers)

    def certify_item(self, item_id, payload, headers):
        return self._request("POST", f"/eqip/practice-items/{item_id}/certify", payload, headers)

    def fail_certification(self, item_id, headers):
        return self._request("POST", f"/eqip/practice-items/{item_id}/fail-certification", {}, headers)

    # --- PaymentRequest ---
    def create_payment_request(self, payload, headers):
        return self._request("POST", "/eqip/payment-requests", payload, headers)

    def get_payment_request(self, request_id, headers):
        return self._request("GET", f"/eqip/payment-requests/{request_id}", headers=headers)

    def list_payment_requests(self, headers, params=None):
        return self._request("GET", "/eqip/payment-requests", headers=headers, params=params)

    def review_payment_request(self, request_id, headers):
        return self._request("POST", f"/eqip/payment-requests/{request_id}/review", {}, headers)

    def approve_payment_request(self, request_id, headers):
        return self._request("POST", f"/eqip/payment-requests/{request_id}/approve", {}, headers)

    def reject_payment_request(self, request_id, headers):
        return self._request("POST", f"/eqip/payment-requests/{request_id}/reject", {}, headers)

    def disburse_payment_request(self, request_id, headers):
        return self._request("POST", f"/eqip/payment-requests/{request_id}/disburse", {}, headers)

    # --- AdvancePayment ---
    def issue_advance(self, contract_id, payload, headers):
        return self._request("POST", f"/eqip/contracts/{contract_id}/advance-payments", payload, headers)

    def list_contract_advances(self, contract_id, headers, params=None):
        return self._request("GET", f"/eqip/contracts/{contract_id}/advance-payments", headers=headers, params=params)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/eqip/advance-payments/{advance_id}", headers=headers)

    def list_advances(self, headers, params=None):
        return self._request("GET", "/eqip/advance-payments", headers=headers, params=params)

    def return_advance(self, advance_id, payload, headers):
        return self._request("POST", f"/eqip/advance-payments/{advance_id}/return", payload, headers)

    # --- ContractModification ---
    def request_modification(self, contract_id, payload, headers):
        return self._request("POST", f"/eqip/contracts/{contract_id}/modifications", payload, headers)

    def list_contract_modifications(self, contract_id, headers, params=None):
        return self._request("GET", f"/eqip/contracts/{contract_id}/modifications", headers=headers, params=params)

    def get_modification(self, modification_id, headers):
        return self._request("GET", f"/eqip/modifications/{modification_id}", headers=headers)

    def list_modifications(self, headers, params=None):
        return self._request("GET", "/eqip/modifications", headers=headers, params=params)

    def approve_modification(self, modification_id, payload, headers):
        return self._request("POST", f"/eqip/modifications/{modification_id}/approve", payload, headers)

    def reject_modification(self, modification_id, payload, headers):
        return self._request("POST", f"/eqip/modifications/{modification_id}/reject", payload, headers)

    # --- SpotCheck ---
    def create_spot_check(self, payload, headers):
        return self._request("POST", "/eqip/spot-checks", payload, headers)

    def get_spot_check(self, spot_check_id, headers):
        return self._request("GET", f"/eqip/spot-checks/{spot_check_id}", headers=headers)

    def list_spot_checks(self, headers, params=None):
        return self._request("GET", "/eqip/spot-checks", headers=headers, params=params)

    def record_spot_check_result(self, spot_check_id, payload, headers):
        return self._request("POST", f"/eqip/spot-checks/{spot_check_id}/record-result", payload, headers)

    # --- MaintenanceObligation ---
    def get_maintenance_obligation(self, obligation_id, headers):
        return self._request("GET", f"/eqip/maintenance-obligations/{obligation_id}", headers=headers)

    def list_maintenance_obligations(self, headers, params=None):
        return self._request("GET", "/eqip/maintenance-obligations", headers=headers, params=params)

    def report_violation(self, obligation_id, headers):
        return self._request("POST", f"/eqip/maintenance-obligations/{obligation_id}/report-violation", {}, headers)

    def confirm_violation(self, obligation_id, headers):
        return self._request("POST", f"/eqip/maintenance-obligations/{obligation_id}/confirm-violation", {}, headers)

    def dismiss_violation(self, obligation_id, headers):
        return self._request("POST", f"/eqip/maintenance-obligations/{obligation_id}/dismiss-violation", {}, headers)

    # --- RecoupmentDemand ---
    def get_recoupment_demand(self, demand_id, headers):
        return self._request("GET", f"/eqip/recoupment-demands/{demand_id}", headers=headers)

    def list_recoupment_demands(self, headers, params=None):
        return self._request("GET", "/eqip/recoupment-demands", headers=headers, params=params)

    def pay_recoupment_demand(self, demand_id, payload, headers):
        return self._request("POST", f"/eqip/recoupment-demands/{demand_id}/pay", payload, headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
