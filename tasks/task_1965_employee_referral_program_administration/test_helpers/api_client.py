"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ops / clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/erp/_clock/set_current_utc", payload, headers)

    def ops_evaluate(self, headers):
        return self._request("POST", "/erp/_ops/evaluate", headers=headers)

    # --- employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/erp/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/erp/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/erp/employees/{employee_id}", headers=headers)

    def terminate_employee(self, employee_id, headers):
        return self._request("POST", f"/erp/employees/{employee_id}/terminate", headers=headers)

    def put_tax_profile(self, employee_id, payload, headers):
        return self._request("PUT", f"/erp/employees/{employee_id}/tax-profile", payload, headers)

    def verify_tax_profile(self, employee_id, headers):
        return self._request("POST", f"/erp/employees/{employee_id}/tax-profile/verify", headers=headers)

    def get_tax_profile(self, employee_id, headers):
        return self._request("GET", f"/erp/employees/{employee_id}/tax-profile", headers=headers)

    def list_employee_referrals(self, employee_id, headers, params=None):
        return self._request("GET", f"/erp/employees/{employee_id}/referrals", headers=headers, params=params)

    def list_employee_abuse_cases(self, employee_id, headers, params=None):
        return self._request("GET", f"/erp/employees/{employee_id}/abuse-cases", headers=headers, params=params)

    # --- candidates ---
    def create_candidate(self, payload, headers):
        return self._request("POST", "/erp/candidates", payload, headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/erp/candidates", headers=headers, params=params)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/erp/candidates/{candidate_id}", headers=headers)

    def list_candidate_referrals(self, candidate_id, headers, params=None):
        return self._request("GET", f"/erp/candidates/{candidate_id}/referrals", headers=headers, params=params)

    def record_departure(self, candidate_id, payload, headers):
        return self._request("POST", f"/erp/candidates/{candidate_id}/record-departure", payload, headers)

    # --- job requisitions ---
    def create_requisition(self, payload, headers):
        return self._request("POST", "/erp/job-requisitions", payload, headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/erp/job-requisitions", headers=headers, params=params)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/erp/job-requisitions/{requisition_id}", headers=headers)

    def open_requisition(self, requisition_id, headers):
        return self._request("POST", f"/erp/job-requisitions/{requisition_id}/open", headers=headers)

    def pause_requisition(self, requisition_id, headers):
        return self._request("POST", f"/erp/job-requisitions/{requisition_id}/pause", headers=headers)

    def resume_requisition(self, requisition_id, headers):
        return self._request("POST", f"/erp/job-requisitions/{requisition_id}/resume", headers=headers)

    def cancel_requisition(self, requisition_id, headers):
        return self._request("POST", f"/erp/job-requisitions/{requisition_id}/cancel", headers=headers)

    def list_requisition_referrals(self, requisition_id, headers, params=None):
        return self._request("GET", f"/erp/job-requisitions/{requisition_id}/referrals", headers=headers, params=params)

    def list_requisition_campaigns(self, requisition_id, headers, params=None):
        return self._request("GET", f"/erp/job-requisitions/{requisition_id}/campaigns", headers=headers, params=params)

    # --- policy versions ---
    def create_policy_version(self, payload, headers):
        return self._request("POST", "/erp/policy-versions", payload, headers)

    def list_policy_versions(self, headers, params=None):
        return self._request("GET", "/erp/policy-versions", headers=headers, params=params)

    def get_policy_version(self, policy_id, headers):
        return self._request("GET", f"/erp/policy-versions/{policy_id}", headers=headers)

    def activate_policy_version(self, policy_id, headers):
        return self._request("POST", f"/erp/policy-versions/{policy_id}/activate", headers=headers)

    def retire_policy_version(self, policy_id, headers):
        return self._request("POST", f"/erp/policy-versions/{policy_id}/retire", headers=headers)

    # --- campaigns ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/erp/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/erp/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/erp/campaigns/{campaign_id}", headers=headers)

    def patch_campaign(self, campaign_id, payload, headers):
        return self._request("PATCH", f"/erp/campaigns/{campaign_id}", payload, headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/erp/campaigns/{campaign_id}/activate", headers=headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"/erp/campaigns/{campaign_id}/pause", headers=headers)

    def end_campaign(self, campaign_id, headers):
        return self._request("POST", f"/erp/campaigns/{campaign_id}/end", headers=headers)

    # --- referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/erp/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/erp/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/erp/referrals/{referral_id}", headers=headers)

    def review_referral(self, referral_id, headers):
        return self._request("POST", f"/erp/referrals/{referral_id}/review", headers=headers)

    def request_info_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/erp/referrals/{referral_id}/request-info", payload, headers)

    def provide_info_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/erp/referrals/{referral_id}/provide-info", payload, headers)

    def qualify_referral(self, referral_id, headers):
        return self._request("POST", f"/erp/referrals/{referral_id}/qualify", headers=headers)

    def reject_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/erp/referrals/{referral_id}/reject", payload, headers)

    def advance_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/erp/referrals/{referral_id}/advance", payload, headers)

    def offer_declined_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/erp/referrals/{referral_id}/offer-declined", payload, headers)

    def hire_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/erp/referrals/{referral_id}/hire", payload, headers)

    def not_selected_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/erp/referrals/{referral_id}/not-selected", payload, headers)

    def withdraw_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/erp/referrals/{referral_id}/withdraw", payload, headers)

    def list_referral_milestones(self, referral_id, headers):
        return self._request("GET", f"/erp/referrals/{referral_id}/milestones", headers=headers)

    def list_referral_events(self, referral_id, headers, params=None):
        return self._request("GET", f"/erp/referrals/{referral_id}/events", headers=headers, params=params)

    # --- milestones ---
    def list_milestones(self, headers, params=None):
        return self._request("GET", "/erp/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/erp/milestones/{milestone_id}", headers=headers)

    def approve_milestone(self, milestone_id, headers):
        return self._request("POST", f"/erp/milestones/{milestone_id}/approve", headers=headers)

    def forfeit_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/erp/milestones/{milestone_id}/forfeit", payload, headers)

    # --- payroll batches ---
    def create_payroll_batch(self, payload, headers):
        return self._request("POST", "/erp/payroll-batches", payload, headers)

    def list_payroll_batches(self, headers, params=None):
        return self._request("GET", "/erp/payroll-batches", headers=headers, params=params)

    def get_payroll_batch(self, batch_id, headers):
        return self._request("GET", f"/erp/payroll-batches/{batch_id}", headers=headers)

    def add_milestone_to_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/erp/payroll-batches/{batch_id}/milestones", payload, headers)

    def remove_milestone_from_batch(self, batch_id, milestone_id, payload, headers):
        return self._request(
            "POST",
            f"/erp/payroll-batches/{batch_id}/milestones/{milestone_id}/remove",
            payload,
            headers,
        )

    def seal_payroll_batch(self, batch_id, headers):
        return self._request("POST", f"/erp/payroll-batches/{batch_id}/seal", headers=headers)

    def export_payroll_batch(self, batch_id, headers):
        return self._request("POST", f"/erp/payroll-batches/{batch_id}/export", headers=headers)

    def confirm_paid_payroll_batch(self, batch_id, headers):
        return self._request("POST", f"/erp/payroll-batches/{batch_id}/confirm-paid", headers=headers)

    def cancel_payroll_batch(self, batch_id, headers):
        return self._request("POST", f"/erp/payroll-batches/{batch_id}/cancel", headers=headers)

    # --- abuse cases ---
    def create_abuse_case(self, payload, headers):
        return self._request("POST", "/erp/abuse-cases", payload, headers)

    def list_abuse_cases(self, headers, params=None):
        return self._request("GET", "/erp/abuse-cases", headers=headers, params=params)

    def get_abuse_case(self, case_id, headers):
        return self._request("GET", f"/erp/abuse-cases/{case_id}", headers=headers)

    def start_review_abuse_case(self, case_id, headers):
        return self._request("POST", f"/erp/abuse-cases/{case_id}/start-review", headers=headers)

    def confirm_abuse_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/erp/abuse-cases/{case_id}/confirm", payload, headers)

    def dismiss_abuse_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/erp/abuse-cases/{case_id}/dismiss", payload, headers)

    # --- analytics ---
    def get_source_quality(self, headers, params=None):
        return self._request("GET", "/erp/analytics/source-quality", headers=headers, params=params)


api_client = ApiClient()
