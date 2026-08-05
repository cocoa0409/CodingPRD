"""API client: one method per endpoint defined in the WIOA PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/wioa/_clock/set_current_utc", payload, headers)

    # --- LocalArea ---
    def create_local_area(self, payload, headers):
        return self._request("POST", "/wioa/local-areas", payload, headers)

    def get_local_area(self, la_id, headers):
        return self._request("GET", f"/wioa/local-areas/{la_id}", headers=headers)

    def list_area_participants(self, la_id, headers, params=None):
        return self._request("GET", f"/wioa/local-areas/{la_id}/participants",
                             headers=headers, params=params)

    def get_performance_summary(self, la_id, headers):
        return self._request("GET", f"/wioa/local-areas/{la_id}/performance-summary",
                             headers=headers)

    # --- Participant ---
    def create_participant(self, la_id, payload, headers):
        return self._request("POST", f"/wioa/local-areas/{la_id}/participants", payload, headers)

    def get_participant(self, p_id, headers):
        return self._request("GET", f"/wioa/participants/{p_id}", headers=headers)

    def determine_eligibility(self, p_id, payload, headers):
        return self._request("POST", f"/wioa/participants/{p_id}/determine-eligibility",
                             payload, headers)

    def enroll_participant(self, p_id, headers, payload=None):
        return self._request("POST", f"/wioa/participants/{p_id}/enroll", payload or {}, headers)

    def exit_participant(self, p_id, headers, payload=None):
        return self._request("POST", f"/wioa/participants/{p_id}/exit", payload or {}, headers)

    # --- CareerPlan ---
    def create_career_plan(self, p_id, payload, headers):
        return self._request("POST", f"/wioa/participants/{p_id}/career-plans", payload, headers)

    def list_career_plans(self, p_id, headers, params=None):
        return self._request("GET", f"/wioa/participants/{p_id}/career-plans",
                             headers=headers, params=params)

    def get_career_plan(self, cp_id, headers):
        return self._request("GET", f"/wioa/career-plans/{cp_id}", headers=headers)

    def activate_career_plan(self, cp_id, headers, payload=None):
        return self._request("POST", f"/wioa/career-plans/{cp_id}/activate", payload or {}, headers)

    def request_revision(self, cp_id, headers, payload=None):
        return self._request("POST", f"/wioa/career-plans/{cp_id}/request-revision",
                             payload or {}, headers)

    def approve_revision(self, cp_id, headers, payload=None):
        return self._request("POST", f"/wioa/career-plans/{cp_id}/approve-revision",
                             payload or {}, headers)

    # --- TrainingProvider (ETPL) ---
    def create_training_provider(self, la_id, payload, headers):
        return self._request("POST", f"/wioa/local-areas/{la_id}/training-providers",
                             payload, headers)

    def get_training_provider(self, prov_id, headers):
        return self._request("GET", f"/wioa/training-providers/{prov_id}", headers=headers)

    def list_training_providers(self, headers, params=None):
        return self._request("GET", "/wioa/training-providers", headers=headers, params=params)

    def approve_provider(self, prov_id, headers, payload=None):
        return self._request("POST", f"/wioa/training-providers/{prov_id}/approve",
                             payload or {}, headers)

    def suspend_provider(self, prov_id, headers, payload=None):
        return self._request("POST", f"/wioa/training-providers/{prov_id}/suspend",
                             payload or {}, headers)

    # --- TrainingProgram ---
    def create_program(self, prov_id, payload, headers):
        return self._request("POST", f"/wioa/training-providers/{prov_id}/programs",
                             payload, headers)

    def get_program(self, prog_id, headers):
        return self._request("GET", f"/wioa/training-programs/{prog_id}", headers=headers)

    def list_provider_programs(self, prov_id, headers, params=None):
        return self._request("GET", f"/wioa/training-providers/{prov_id}/programs",
                             headers=headers, params=params)

    # --- ITAVoucher ---
    def create_voucher(self, p_id, payload, headers):
        return self._request("POST", f"/wioa/participants/{p_id}/ita-vouchers", payload, headers)

    def get_voucher(self, v_id, headers):
        return self._request("GET", f"/wioa/ita-vouchers/{v_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/wioa/ita-vouchers", headers=headers, params=params)

    def obligate_voucher(self, v_id, payload, headers):
        return self._request("POST", f"/wioa/ita-vouchers/{v_id}/obligate", payload, headers)

    def disburse_voucher(self, v_id, payload, headers):
        return self._request("POST", f"/wioa/ita-vouchers/{v_id}/disburse", payload, headers)

    def list_disbursements(self, v_id, headers, params=None):
        return self._request("GET", f"/wioa/ita-vouchers/{v_id}/disbursements",
                             headers=headers, params=params)

    def complete_voucher(self, v_id, payload, headers):
        return self._request("POST", f"/wioa/ita-vouchers/{v_id}/complete", payload, headers)

    def cancel_voucher(self, v_id, headers, payload=None):
        return self._request("POST", f"/wioa/ita-vouchers/{v_id}/cancel", payload or {}, headers)

    # --- SupportiveServicePayment ---
    def create_supportive(self, p_id, payload, headers):
        return self._request("POST", f"/wioa/participants/{p_id}/supportive-services",
                             payload, headers)

    def get_supportive(self, ss_id, headers):
        return self._request("GET", f"/wioa/supportive-services/{ss_id}", headers=headers)

    def list_supportive(self, p_id, headers, params=None):
        return self._request("GET", f"/wioa/participants/{p_id}/supportive-services",
                             headers=headers, params=params)

    def approve_supportive(self, ss_id, headers, payload=None):
        return self._request("POST", f"/wioa/supportive-services/{ss_id}/approve",
                             payload or {}, headers)

    def pay_supportive(self, ss_id, headers, payload=None):
        return self._request("POST", f"/wioa/supportive-services/{ss_id}/pay",
                             payload or {}, headers)

    def void_supportive(self, ss_id, headers, payload=None):
        return self._request("POST", f"/wioa/supportive-services/{ss_id}/void",
                             payload or {}, headers)

    # --- Employer ---
    def create_employer(self, la_id, payload, headers):
        return self._request("POST", f"/wioa/local-areas/{la_id}/employers", payload, headers)

    def get_employer(self, emp_id, headers):
        return self._request("GET", f"/wioa/employers/{emp_id}", headers=headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/wioa/employers", headers=headers, params=params)

    # --- OJTContract ---
    def create_ojt(self, emp_id, payload, headers):
        return self._request("POST", f"/wioa/employers/{emp_id}/ojt-contracts", payload, headers)

    def get_ojt(self, c_id, headers):
        return self._request("GET", f"/wioa/ojt-contracts/{c_id}", headers=headers)

    def list_ojt(self, headers, params=None):
        return self._request("GET", "/wioa/ojt-contracts", headers=headers, params=params)

    def activate_ojt(self, c_id, headers, payload=None):
        return self._request("POST", f"/wioa/ojt-contracts/{c_id}/activate", payload or {}, headers)

    def reimburse_ojt(self, c_id, payload, headers):
        return self._request("POST", f"/wioa/ojt-contracts/{c_id}/reimburse", payload, headers)

    def complete_ojt(self, c_id, headers, payload=None):
        return self._request("POST", f"/wioa/ojt-contracts/{c_id}/complete", payload or {}, headers)

    def terminate_ojt(self, c_id, headers, payload=None):
        return self._request("POST", f"/wioa/ojt-contracts/{c_id}/terminate", payload or {}, headers)

    # --- JobReferral ---
    def create_referral(self, p_id, payload, headers):
        return self._request("POST", f"/wioa/participants/{p_id}/job-referrals", payload, headers)

    def get_referral(self, jr_id, headers):
        return self._request("GET", f"/wioa/job-referrals/{jr_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/wioa/job-referrals", headers=headers, params=params)

    def place_referral(self, jr_id, headers, payload=None):
        return self._request("POST", f"/wioa/job-referrals/{jr_id}/place", payload or {}, headers)

    def reject_referral(self, jr_id, headers, payload=None):
        return self._request("POST", f"/wioa/job-referrals/{jr_id}/reject", payload or {}, headers)


api_client = ApiClient()
