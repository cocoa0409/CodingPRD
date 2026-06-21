"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def enroll_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/enroll", {}, headers)

    def suspend_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/suspend", {}, headers)

    def terminate_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/terminate", {}, headers)

    def list_provider_settlements(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/providers/{provider_id}/settlements", headers=headers, params=params
        )

    # ---- PromotionalPlan ----
    def create_promotional_plan(self, payload, headers):
        return self._request("POST", "/promotional-plans", payload, headers)

    def get_promotional_plan(self, plan_id, headers):
        return self._request("GET", f"/promotional-plans/{plan_id}", headers=headers)

    def list_promotional_plans(self, headers, params=None):
        return self._request("GET", "/promotional-plans", headers=headers, params=params)

    def activate_promotional_plan(self, plan_id, headers):
        return self._request("POST", f"/promotional-plans/{plan_id}/activate", {}, headers)

    def retire_promotional_plan(self, plan_id, headers):
        return self._request("POST", f"/promotional-plans/{plan_id}/retire", {}, headers)

    # ---- ProviderPromotion ----
    def create_provider_promotion(self, payload, headers):
        return self._request("POST", "/provider-promotions", payload, headers)

    def get_provider_promotion(self, pp_id, headers):
        return self._request("GET", f"/provider-promotions/{pp_id}", headers=headers)

    def list_provider_promotions(self, headers, params=None):
        return self._request("GET", "/provider-promotions", headers=headers, params=params)

    def withdraw_provider_promotion(self, pp_id, headers):
        return self._request("POST", f"/provider-promotions/{pp_id}/withdraw", {}, headers)

    # ---- CreditApplication ----
    def create_credit_application(self, payload, headers):
        return self._request("POST", "/credit-applications", payload, headers)

    def get_credit_application(self, app_id, headers):
        return self._request("GET", f"/credit-applications/{app_id}", headers=headers)

    def list_credit_applications(self, headers, params=None):
        return self._request("GET", "/credit-applications", headers=headers, params=params)

    def approve_credit_application(self, app_id, headers):
        return self._request("POST", f"/credit-applications/{app_id}/approve", {}, headers)

    def decline_credit_application(self, app_id, headers):
        return self._request("POST", f"/credit-applications/{app_id}/decline", {}, headers)

    # ---- PatientAccount ----
    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def list_account_financed_purchases(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/financed-purchases", headers=headers, params=params
        )

    def list_account_payments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/payments", headers=headers, params=params
        )

    def list_account_statements(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/statements", headers=headers, params=params
        )

    def list_account_autopay_enrollments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/autopay-enrollments", headers=headers, params=params
        )

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    # ---- AutopayEnrollment ----
    def create_autopay_enrollment(self, payload, headers):
        return self._request("POST", "/autopay-enrollments", payload, headers)

    def get_autopay_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/autopay-enrollments/{enrollment_id}", headers=headers)

    def pause_autopay_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/autopay-enrollments/{enrollment_id}/pause", {}, headers)

    def resume_autopay_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/autopay-enrollments/{enrollment_id}/resume", {}, headers)

    def revoke_autopay_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/autopay-enrollments/{enrollment_id}/revoke", {}, headers)

    # ---- FinancedPurchase ----
    def create_financed_purchase(self, payload, headers):
        return self._request("POST", "/financed-purchases", payload, headers)

    def get_financed_purchase(self, fp_id, headers):
        return self._request("GET", f"/financed-purchases/{fp_id}", headers=headers)

    def list_financed_purchases(self, headers, params=None):
        return self._request("GET", "/financed-purchases", headers=headers, params=params)

    def get_payoff_projection(self, fp_id, headers):
        return self._request(
            "GET", f"/financed-purchases/{fp_id}/payoff-projection", headers=headers
        )

    def settle_financed_purchase(self, fp_id, payload, headers):
        return self._request("POST", f"/financed-purchases/{fp_id}/settle", payload, headers)

    # ---- Settlement ----
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/pay", {}, headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    # ---- Refund ----
    def create_refund(self, payload, headers):
        return self._request("POST", "/refunds", payload, headers)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    # ---- BillingStatement ----
    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    # ---- Test-driving clock / cycle / autopay endpoints ----
    def clock_set(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    def clock_advance(self, to_iso8601, headers):
        return self._request("POST", "/_clock/advance", {"to_iso8601": to_iso8601}, headers)

    def open_statement(self, payload, headers):
        return self._request("POST", "/_cycle/open_statement", payload, headers)

    def close_statement(self, patient_account_id, headers):
        return self._request(
            "POST", "/_cycle/close_statement", {"patient_account_id": patient_account_id}, headers
        )

    def autopay_run(self, autopay_enrollment_id, headers):
        return self._request(
            "POST", "/_autopay/run", {"autopay_enrollment_id": autopay_enrollment_id}, headers
        )


api_client = ApiClient()
