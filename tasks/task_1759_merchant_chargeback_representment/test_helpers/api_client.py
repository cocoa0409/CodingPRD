"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Merchant ---
    def create_merchant(self, payload, headers):
        return self._request("POST", "/acquirer/merchants", payload, headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/acquirer/merchants", headers=headers, params=params)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/acquirer/merchants/{merchant_id}", headers=headers)

    def patch_reserve_policy(self, merchant_id, payload, headers):
        return self._request(
            "PATCH", f"/acquirer/merchants/{merchant_id}/reserve-policy", payload, headers
        )

    def suspend_merchant(self, merchant_id, headers):
        return self._request("POST", f"/acquirer/merchants/{merchant_id}/suspend", {}, headers)

    def reinstate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/acquirer/merchants/{merchant_id}/reinstate", {}, headers)

    # --- ReasonCodeRule ---
    def create_reason_code_rule(self, payload, headers):
        return self._request("POST", "/acquirer/reason-code-rules", payload, headers)

    def list_reason_code_rules(self, headers, params=None):
        return self._request("GET", "/acquirer/reason-code-rules", headers=headers, params=params)

    # --- Transaction ---
    def create_transaction(self, payload, headers):
        return self._request("POST", "/acquirer/transactions", payload, headers)

    def create_transactions_batch(self, payload, headers):
        return self._request("POST", "/acquirer/transactions/batch", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/acquirer/transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/acquirer/transactions/{transaction_id}", headers=headers)

    # --- Chargeback ---
    def create_chargeback(self, payload, headers):
        return self._request("POST", "/acquirer/chargebacks", payload, headers)

    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/acquirer/chargebacks", headers=headers, params=params)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/acquirer/chargebacks/{chargeback_id}", headers=headers)

    def notify_chargeback(self, chargeback_id, headers):
        return self._request("POST", f"/acquirer/chargebacks/{chargeback_id}/notify", {}, headers)

    def accept_chargeback(self, chargeback_id, headers):
        return self._request("POST", f"/acquirer/chargebacks/{chargeback_id}/accept", {}, headers)

    def reverse_chargeback(self, chargeback_id, headers):
        return self._request("POST", f"/acquirer/chargebacks/{chargeback_id}/reverse", {}, headers)

    def escalate_pre_arbitration(self, chargeback_id, headers):
        return self._request(
            "POST", f"/acquirer/chargebacks/{chargeback_id}/pre-arbitration", {}, headers
        )

    def pre_arbitration_outcome(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/acquirer/chargebacks/{chargeback_id}/pre-arbitration/outcome", payload, headers
        )

    # --- EvidenceItem ---
    def create_evidence_item(self, payload, headers):
        return self._request("POST", "/acquirer/evidence-items", payload, headers)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", "/acquirer/evidence-items", headers=headers, params=params)

    def get_evidence_item(self, evidence_item_id, headers):
        return self._request("GET", f"/acquirer/evidence-items/{evidence_item_id}", headers=headers)

    def withdraw_evidence_item(self, evidence_item_id, headers):
        return self._request(
            "POST", f"/acquirer/evidence-items/{evidence_item_id}/withdraw", {}, headers
        )

    # --- Representment ---
    def create_representment(self, payload, headers):
        return self._request("POST", "/acquirer/representments", payload, headers)

    def list_representments(self, headers, params=None):
        return self._request("GET", "/acquirer/representments", headers=headers, params=params)

    def get_representment(self, representment_id, headers):
        return self._request("GET", f"/acquirer/representments/{representment_id}", headers=headers)

    def submit_representment(self, representment_id, headers):
        return self._request(
            "POST", f"/acquirer/representments/{representment_id}/submit", {}, headers
        )

    def post_network_outcome(self, representment_id, payload, headers):
        return self._request(
            "POST", f"/acquirer/representments/{representment_id}/network-outcome", payload, headers
        )

    # --- FeeAssessment ---
    def create_fee_assessment(self, payload, headers):
        return self._request("POST", "/acquirer/fee-assessments", payload, headers)

    def list_fee_assessments(self, headers, params=None):
        return self._request("GET", "/acquirer/fee-assessments", headers=headers, params=params)

    def get_fee_assessment(self, fee_assessment_id, headers):
        return self._request("GET", f"/acquirer/fee-assessments/{fee_assessment_id}", headers=headers)

    def waive_fee_assessment(self, fee_assessment_id, headers):
        return self._request(
            "POST", f"/acquirer/fee-assessments/{fee_assessment_id}/waive", {}, headers
        )

    def settle_fee_assessment(self, fee_assessment_id, headers):
        return self._request(
            "POST", f"/acquirer/fee-assessments/{fee_assessment_id}/settle", {}, headers
        )

    # --- ReserveAccount / ReserveLedgerEntry ---
    def list_reserve_accounts(self, headers, params=None):
        return self._request("GET", "/acquirer/reserve-accounts", headers=headers, params=params)

    def get_reserve_account(self, reserve_account_id, headers):
        return self._request(
            "GET", f"/acquirer/reserve-accounts/{reserve_account_id}", headers=headers
        )

    def release_reserve(self, reserve_account_id, headers):
        return self._request(
            "POST", f"/acquirer/reserve-accounts/{reserve_account_id}/release", {}, headers
        )

    def list_ledger_entries(self, reserve_account_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquirer/reserve-accounts/{reserve_account_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    # --- RatioSnapshot (sub-resource) ---
    def list_ratio_snapshots(self, merchant_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquirer/merchants/{merchant_id}/ratio-snapshots",
            headers=headers,
            params=params,
        )

    # --- ProgramEnrollment ---
    def create_program_enrollment(self, payload, headers):
        return self._request("POST", "/acquirer/program-enrollments", payload, headers)

    def list_program_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/acquirer/program-enrollments", headers=headers, params=params
        )

    def get_program_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/acquirer/program-enrollments/{enrollment_id}", headers=headers
        )

    def exit_review_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/acquirer/program-enrollments/{enrollment_id}/exit-review", payload, headers
        )

    def list_remediation_plans(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquirer/program-enrollments/{enrollment_id}/remediation-plans",
            headers=headers,
            params=params,
        )

    # --- RemediationPlan ---
    def create_remediation_plan(self, payload, headers):
        return self._request("POST", "/acquirer/remediation-plans", payload, headers)

    def submit_remediation_plan(self, plan_id, headers):
        return self._request("POST", f"/acquirer/remediation-plans/{plan_id}/submit", {}, headers)

    def review_remediation_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/acquirer/remediation-plans/{plan_id}/review", payload, headers)

    # --- PreventionAlert ---
    def create_prevention_alert(self, payload, headers):
        return self._request("POST", "/acquirer/prevention-alerts", payload, headers)

    def list_prevention_alerts(self, headers, params=None):
        return self._request("GET", "/acquirer/prevention-alerts", headers=headers, params=params)

    def get_prevention_alert(self, alert_id, headers):
        return self._request("GET", f"/acquirer/prevention-alerts/{alert_id}", headers=headers)

    def action_prevention_alert(self, alert_id, payload, headers):
        return self._request(
            "POST", f"/acquirer/prevention-alerts/{alert_id}/action", payload, headers
        )

    # --- EducationAssignment ---
    def list_education_assignments(self, merchant_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquirer/merchants/{merchant_id}/education-assignments",
            headers=headers,
            params=params,
        )

    def complete_education_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/acquirer/education-assignments/{assignment_id}/complete", {}, headers
        )

    # --- Analytics ---
    def get_win_rate(self, headers, params=None):
        return self._request("GET", "/acquirer/analytics/win-rate", headers=headers, params=params)

    # --- Ops & clock ---
    def advance_month(self, payload, headers):
        return self._request("POST", "/acquirer/ops/advance-month", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/acquirer/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
