"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/annuity/_clock/set_current_utc", payload, headers)

    # --- StateStatuteProfile ---
    def create_state_profile(self, payload, headers):
        return self._request("POST", "/annuity/state-statute-profiles", payload, headers)

    def list_state_profiles(self, headers, params=None):
        return self._request("GET", "/annuity/state-statute-profiles", headers=headers, params=params)

    def get_state_profile(self, profile_id, headers):
        return self._request("GET", f"/annuity/state-statute-profiles/{profile_id}", headers=headers)

    # --- Payee ---
    def create_payee(self, payload, headers):
        return self._request("POST", "/annuity/payees", payload, headers)

    def list_payees(self, headers, params=None):
        return self._request("GET", "/annuity/payees", headers=headers, params=params)

    def get_payee(self, payee_id, headers):
        return self._request("GET", f"/annuity/payees/{payee_id}", headers=headers)

    # --- GuardianshipCase ---
    def create_guardianship_case(self, payload, headers):
        return self._request("POST", "/annuity/guardianship-cases", payload, headers)

    def list_guardianship_cases(self, headers, params=None):
        return self._request("GET", "/annuity/guardianship-cases", headers=headers, params=params)

    def get_guardianship_case(self, case_id, headers):
        return self._request("GET", f"/annuity/guardianship-cases/{case_id}", headers=headers)

    def activate_guardianship_case(self, case_id, headers):
        return self._request("POST", f"/annuity/guardianship-cases/{case_id}/activate", {}, headers)

    def revoke_guardianship_case(self, case_id, headers):
        return self._request("POST", f"/annuity/guardianship-cases/{case_id}/revoke", {}, headers)

    # --- SettlementAgreement ---
    def create_settlement_agreement(self, payload, headers):
        return self._request("POST", "/annuity/settlement-agreements", payload, headers)

    def list_settlement_agreements(self, headers, params=None):
        return self._request("GET", "/annuity/settlement-agreements", headers=headers, params=params)

    def get_settlement_agreement(self, agreement_id, headers):
        return self._request("GET", f"/annuity/settlement-agreements/{agreement_id}", headers=headers)

    def execute_settlement_agreement(self, agreement_id, headers):
        return self._request("POST", f"/annuity/settlement-agreements/{agreement_id}/execute", {}, headers)

    # --- QualifiedAssignment ---
    def create_qualified_assignment(self, payload, headers):
        return self._request("POST", "/annuity/qualified-assignments", payload, headers)

    def list_qualified_assignments(self, headers, params=None):
        return self._request("GET", "/annuity/qualified-assignments", headers=headers, params=params)

    def get_qualified_assignment(self, assignment_id, headers):
        return self._request("GET", f"/annuity/qualified-assignments/{assignment_id}", headers=headers)

    def release_qualified_assignment(self, assignment_id, headers):
        return self._request("POST", f"/annuity/qualified-assignments/{assignment_id}/release", {}, headers)

    # --- AnnuityPolicy ---
    def create_annuity_policy(self, payload, headers):
        return self._request("POST", "/annuity/annuity-policies", payload, headers)

    def list_annuity_policies(self, headers, params=None):
        return self._request("GET", "/annuity/annuity-policies", headers=headers, params=params)

    def get_annuity_policy(self, policy_id, headers):
        return self._request("GET", f"/annuity/annuity-policies/{policy_id}", headers=headers)

    def mark_policy_in_force(self, policy_id, payload, headers):
        return self._request("POST", f"/annuity/annuity-policies/{policy_id}/mark-in-force", payload, headers)

    # --- PaymentSchedule ---
    def create_payment_schedule(self, payload, headers):
        return self._request("POST", "/annuity/payment-schedules", payload, headers)

    def list_payment_schedules(self, headers, params=None):
        return self._request("GET", "/annuity/payment-schedules", headers=headers, params=params)

    def get_payment_schedule(self, schedule_id, headers):
        return self._request("GET", f"/annuity/payment-schedules/{schedule_id}", headers=headers)

    def activate_payment_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/annuity/payment-schedules/{schedule_id}/activate", payload, headers)

    # --- ScheduledPayment ---
    def create_scheduled_payment(self, payload, headers):
        return self._request("POST", "/annuity/scheduled-payments", payload, headers)

    def list_scheduled_payments(self, headers, params=None):
        return self._request("GET", "/annuity/scheduled-payments", headers=headers, params=params)

    def get_scheduled_payment(self, payment_id, headers):
        return self._request("GET", f"/annuity/scheduled-payments/{payment_id}", headers=headers)

    def issue_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/annuity/scheduled-payments/{payment_id}/issue", payload, headers)

    def mark_payment_cleared(self, payment_id, headers):
        return self._request("POST", f"/annuity/scheduled-payments/{payment_id}/mark-cleared", {}, headers)

    def report_payment_returned(self, payment_id, payload, headers):
        return self._request("POST", f"/annuity/scheduled-payments/{payment_id}/report-returned", payload, headers)

    def reclaim_payment_escheat(self, payment_id, headers):
        return self._request("POST", f"/annuity/scheduled-payments/{payment_id}/reclaim-escheat", {}, headers)

    # --- ReturnedPaymentCase ---
    def list_returned_payment_cases(self, headers, params=None):
        return self._request("GET", "/annuity/returned-payment-cases", headers=headers, params=params)

    def get_returned_payment_case(self, case_id, headers):
        return self._request("GET", f"/annuity/returned-payment-cases/{case_id}", headers=headers)

    def authorize_reissue(self, case_id, headers):
        return self._request("POST", f"/annuity/returned-payment-cases/{case_id}/authorize-reissue", {}, headers)

    def escalate_escheat(self, case_id, headers):
        return self._request("POST", f"/annuity/returned-payment-cases/{case_id}/escalate-escheat", {}, headers)

    # --- PayeeChangeRequest ---
    def create_payee_change_request(self, payload, headers):
        return self._request("POST", "/annuity/payee-change-requests", payload, headers)

    def list_payee_change_requests(self, headers, params=None):
        return self._request("GET", "/annuity/payee-change-requests", headers=headers, params=params)

    def get_payee_change_request(self, request_id, headers):
        return self._request("GET", f"/annuity/payee-change-requests/{request_id}", headers=headers)

    def approve_change_request(self, request_id, headers):
        return self._request("POST", f"/annuity/payee-change-requests/{request_id}/approve", {}, headers)

    def reject_change_request(self, request_id, headers):
        return self._request("POST", f"/annuity/payee-change-requests/{request_id}/reject", {}, headers)

    # --- TransferPetition ---
    def create_transfer_petition(self, payload, headers):
        return self._request("POST", "/annuity/transfer-petitions", payload, headers)

    def list_transfer_petitions(self, headers, params=None):
        return self._request("GET", "/annuity/transfer-petitions", headers=headers, params=params)

    def get_transfer_petition(self, petition_id, headers):
        return self._request("GET", f"/annuity/transfer-petitions/{petition_id}", headers=headers)

    def file_petition(self, petition_id, headers):
        return self._request("POST", f"/annuity/transfer-petitions/{petition_id}/file", {}, headers)

    def serve_disclosure(self, petition_id, headers):
        return self._request("POST", f"/annuity/transfer-petitions/{petition_id}/serve-disclosure", {}, headers)

    def schedule_hearing(self, petition_id, payload, headers):
        return self._request("POST", f"/annuity/transfer-petitions/{petition_id}/schedule-hearing", payload, headers)

    def withdraw_petition(self, petition_id, headers):
        return self._request("POST", f"/annuity/transfer-petitions/{petition_id}/withdraw", {}, headers)

    def record_court_order(self, petition_id, payload, headers):
        return self._request("POST", f"/annuity/transfer-petitions/{petition_id}/record-court-order", payload, headers)

    def effectuate_petition(self, petition_id, headers):
        return self._request("POST", f"/annuity/transfer-petitions/{petition_id}/effectuate", {}, headers)

    # --- DeathClaim ---
    def create_death_claim(self, payload, headers):
        return self._request("POST", "/annuity/death-claims", payload, headers)

    def list_death_claims(self, headers, params=None):
        return self._request("GET", "/annuity/death-claims", headers=headers, params=params)

    def get_death_claim(self, claim_id, headers):
        return self._request("GET", f"/annuity/death-claims/{claim_id}", headers=headers)

    def settle_death_claim(self, claim_id, headers):
        return self._request("POST", f"/annuity/death-claims/{claim_id}/settle", {}, headers)

    def deny_death_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/annuity/death-claims/{claim_id}/deny", payload, headers)

    def resubmit_death_claim(self, claim_id, headers):
        return self._request("POST", f"/annuity/death-claims/{claim_id}/resubmit", {}, headers)

    # --- CommutationRequest ---
    def create_commutation_request(self, payload, headers):
        return self._request("POST", "/annuity/commutation-requests", payload, headers)

    def list_commutation_requests(self, headers, params=None):
        return self._request("GET", "/annuity/commutation-requests", headers=headers, params=params)

    def get_commutation_request(self, commutation_id, headers):
        return self._request("GET", f"/annuity/commutation-requests/{commutation_id}", headers=headers)

    def approve_commutation(self, commutation_id, headers):
        return self._request("POST", f"/annuity/commutation-requests/{commutation_id}/approve", {}, headers)

    def deny_commutation(self, commutation_id, headers):
        return self._request("POST", f"/annuity/commutation-requests/{commutation_id}/deny", {}, headers)

    def payout_commutation(self, commutation_id, headers):
        return self._request("POST", f"/annuity/commutation-requests/{commutation_id}/pay-out", {}, headers)

    # --- EscheatmentBatch ---
    def create_escheatment_batch(self, payload, headers):
        return self._request("POST", "/annuity/escheatment-batches", payload, headers)

    def list_escheatment_batches(self, headers, params=None):
        return self._request("GET", "/annuity/escheatment-batches", headers=headers, params=params)

    def get_escheatment_batch(self, batch_id, headers):
        return self._request("GET", f"/annuity/escheatment-batches/{batch_id}", headers=headers)

    def finalize_escheatment_batch(self, batch_id, headers):
        return self._request("POST", f"/annuity/escheatment-batches/{batch_id}/finalize", {}, headers)


api_client = ApiClient()
