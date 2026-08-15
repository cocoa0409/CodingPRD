"""API client: one method per endpoint defined in the PRD (endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/carrier/_clock/set_current_utc", payload, headers)

    # --- State filing profiles ---
    def create_state_profile(self, payload, headers):
        return self._request("POST", "/carrier/state-profiles", payload, headers)

    def get_state_profile(self, profile_id, headers):
        return self._request("GET", f"/carrier/state-profiles/{profile_id}", headers=headers)

    def list_state_profiles(self, headers, params=None):
        return self._request("GET", "/carrier/state-profiles", headers=headers, params=params)

    def activate_state_profile(self, profile_id, headers):
        return self._request("POST", f"/carrier/state-profiles/{profile_id}/activate", {}, headers)

    def retire_state_profile(self, profile_id, headers):
        return self._request("POST", f"/carrier/state-profiles/{profile_id}/retire", {}, headers)

    # --- Policyholders ---
    def create_policyholder(self, payload, headers):
        return self._request("POST", "/carrier/policyholders", payload, headers)

    def get_policyholder(self, policyholder_id, headers):
        return self._request("GET", f"/carrier/policyholders/{policyholder_id}", headers=headers)

    # --- Policies ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/carrier/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/carrier/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/carrier/policies", headers=headers, params=params)

    # --- Insured interests ---
    def create_interest(self, policy_id, payload, headers):
        return self._request("POST", f"/carrier/policies/{policy_id}/interests", payload, headers)

    def list_interests(self, policy_id, headers):
        return self._request("GET", f"/carrier/policies/{policy_id}/interests", headers=headers)

    # --- Cancellation cases ---
    def create_cancellation_case(self, payload, headers):
        return self._request("POST", "/carrier/cancellation-cases", payload, headers)

    def get_cancellation_case(self, case_id, headers):
        return self._request("GET", f"/carrier/cancellation-cases/{case_id}", headers=headers)

    def list_cancellation_cases(self, headers, params=None):
        return self._request("GET", "/carrier/cancellation-cases", headers=headers, params=params)

    def approve_cancellation_case(self, case_id, payload, headers):
        return self._request("POST", f"/carrier/cancellation-cases/{case_id}/approve", payload, headers)

    def withdraw_cancellation_case(self, case_id, headers):
        return self._request("POST", f"/carrier/cancellation-cases/{case_id}/withdraw", {}, headers)

    def rescind_cancellation_case(self, case_id, payload, headers):
        return self._request("POST", f"/carrier/cancellation-cases/{case_id}/rescind", payload, headers)

    def dispatch_cancellation_notices(self, case_id, payload, headers):
        return self._request("POST", f"/carrier/cancellation-cases/{case_id}/dispatch-notices", payload, headers)

    # --- Nonrenewal cases ---
    def create_nonrenewal_case(self, payload, headers):
        return self._request("POST", "/carrier/nonrenewal-cases", payload, headers)

    def get_nonrenewal_case(self, case_id, headers):
        return self._request("GET", f"/carrier/nonrenewal-cases/{case_id}", headers=headers)

    def list_nonrenewal_cases(self, headers, params=None):
        return self._request("GET", "/carrier/nonrenewal-cases", headers=headers, params=params)

    def approve_nonrenewal_case(self, case_id, headers):
        return self._request("POST", f"/carrier/nonrenewal-cases/{case_id}/approve", {}, headers)

    def rescind_nonrenewal_case(self, case_id, payload, headers):
        return self._request("POST", f"/carrier/nonrenewal-cases/{case_id}/rescind", payload, headers)

    def dispatch_nonrenewal_notices(self, case_id, payload, headers):
        return self._request("POST", f"/carrier/nonrenewal-cases/{case_id}/dispatch-notices", payload, headers)

    # --- Notices ---
    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/carrier/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/carrier/notices", headers=headers, params=params)

    def confirm_delivery(self, notice_id, headers):
        return self._request("POST", f"/carrier/notices/{notice_id}/confirm-delivery", {}, headers)

    def mark_undeliverable(self, notice_id, headers):
        return self._request("POST", f"/carrier/notices/{notice_id}/mark-undeliverable", {}, headers)

    # --- Premium ledger ---
    def list_case_ledger_entries(self, case_id, headers):
        return self._request("GET", f"/carrier/cancellation-cases/{case_id}/ledger-entries", headers=headers)

    def list_policy_ledger_entries(self, policy_id, headers):
        return self._request("GET", f"/carrier/policies/{policy_id}/ledger-entries", headers=headers)

    # --- Reinstatement requests ---
    def create_reinstatement_request(self, payload, headers):
        return self._request("POST", "/carrier/reinstatement-requests", payload, headers)

    def get_reinstatement_request(self, request_id, headers):
        return self._request("GET", f"/carrier/reinstatement-requests/{request_id}", headers=headers)

    def list_reinstatement_requests(self, headers, params=None):
        return self._request("GET", "/carrier/reinstatement-requests", headers=headers, params=params)

    def approve_reinstatement_request(self, request_id, headers):
        return self._request("POST", f"/carrier/reinstatement-requests/{request_id}/approve", {}, headers)

    def deny_reinstatement_request(self, request_id, headers):
        return self._request("POST", f"/carrier/reinstatement-requests/{request_id}/deny", {}, headers)

    # --- Appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/carrier/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/carrier/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/carrier/appeals", headers=headers, params=params)

    def accept_appeal_for_review(self, appeal_id, headers):
        return self._request("POST", f"/carrier/appeals/{appeal_id}/accept-for-review", {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/carrier/appeals/{appeal_id}/decide", payload, headers)

    # --- Regulatory reports ---
    def list_regulatory_reports(self, headers, params=None):
        return self._request("GET", "/carrier/regulatory-reports", headers=headers, params=params)

    def get_regulatory_report(self, report_id, headers):
        return self._request("GET", f"/carrier/regulatory-reports/{report_id}", headers=headers)

    def finalize_regulatory_report(self, report_id, headers):
        return self._request("POST", f"/carrier/regulatory-reports/{report_id}/finalize", {}, headers)


api_client = ApiClient()
