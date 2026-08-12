"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- intake & client lifecycle ---------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/dmm/clients", payload, headers)

    def record_capacity_determination(self, client_id, payload, headers):
        return self._request(
            "POST", f"/dmm/clients/{client_id}/capacity-determination", payload, headers
        )

    def change_client_status(self, client_id, payload, headers):
        return self._request(
            "POST", f"/dmm/clients/{client_id}/status-change", payload, headers
        )

    def get_client(self, client_id, headers):
        return self._request("GET", f"/dmm/clients/{client_id}", headers=headers)

    def list_client_authorizations(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/dmm/clients/{client_id}/authorizations", headers=headers, params=params
        )

    def list_client_accounts(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/dmm/clients/{client_id}/accounts", headers=headers, params=params
        )

    def list_client_payees(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/dmm/clients/{client_id}/payees", headers=headers, params=params
        )

    def list_client_budget_categories(self, client_id, headers, params=None):
        return self._request(
            "GET",
            f"/dmm/clients/{client_id}/budget-categories",
            headers=headers,
            params=params,
        )

    def list_client_coordination_requests(self, client_id, headers, params=None):
        return self._request(
            "GET",
            f"/dmm/clients/{client_id}/coordination-requests",
            headers=headers,
            params=params,
        )

    def list_client_audit_entries(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/dmm/clients/{client_id}/audit-entries", headers=headers, params=params
        )

    # ---- authorization instrument ----------------------------------------
    def create_authorization(self, payload, headers):
        return self._request("POST", "/dmm/authorizations", payload, headers)

    def change_authorization_status(self, authorization_id, payload, headers):
        return self._request(
            "POST", f"/dmm/authorizations/{authorization_id}/status", payload, headers
        )

    def get_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"/dmm/authorizations/{authorization_id}", headers=headers
        )

    # ---- accounts & monitoring -------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/dmm/accounts", payload, headers)

    def post_account_adjustment(self, account_id, payload, headers):
        return self._request(
            "POST", f"/dmm/accounts/{account_id}/adjustments", payload, headers
        )

    def change_fraud_posture(self, account_id, payload, headers):
        return self._request(
            "POST", f"/dmm/accounts/{account_id}/fraud-posture", payload, headers
        )

    def get_account(self, account_id, headers):
        return self._request("GET", f"/dmm/accounts/{account_id}", headers=headers)

    def list_account_reconciliation_periods(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/dmm/accounts/{account_id}/reconciliation-periods",
            headers=headers,
            params=params,
        )

    # ---- payees -----------------------------------------------------------
    def create_payee(self, payload, headers):
        return self._request("POST", "/dmm/payees", payload, headers)

    def block_payee(self, payee_id, payload, headers):
        return self._request("POST", f"/dmm/payees/{payee_id}/block", payload, headers)

    def get_payee(self, payee_id, headers):
        return self._request("GET", f"/dmm/payees/{payee_id}", headers=headers)

    # ---- budget -----------------------------------------------------------
    def create_budget_category(self, payload, headers):
        return self._request("POST", "/dmm/budget-categories", payload, headers)

    def grant_budget_override(self, budget_category_id, payload, headers):
        return self._request(
            "POST", f"/dmm/budget-categories/{budget_category_id}/overrides", payload, headers
        )

    def get_budget_category(self, budget_category_id, headers):
        return self._request(
            "GET", f"/dmm/budget-categories/{budget_category_id}", headers=headers
        )

    # ---- bill pay ---------------------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/dmm/payments", payload, headers)

    def decide_payment_approval(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/dmm/payments/{payment_id}/approval-decision", payload, headers
        )

    def revise_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/dmm/payments/{payment_id}/revise", payload, headers
        )

    def release_payment(self, payment_id, headers):
        return self._request("POST", f"/dmm/payments/{payment_id}/release", {}, headers)

    def record_settlement_event(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/dmm/payments/{payment_id}/settlement-event", payload, headers
        )

    def cancel_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/dmm/payments/{payment_id}/cancel", payload, headers
        )

    def stop_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/dmm/payments/{payment_id}/stop-payment", payload, headers
        )

    def list_payments(self, headers, params=None):
        return self._request("GET", "/dmm/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/dmm/payments/{payment_id}", headers=headers)

    def list_payment_disputes(self, payment_id, headers, params=None):
        return self._request(
            "GET", f"/dmm/payments/{payment_id}/disputes", headers=headers, params=params
        )

    # ---- disputes ---------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/dmm/disputes", payload, headers)

    def apply_provisional_credit(self, dispute_id, headers):
        return self._request(
            "POST", f"/dmm/disputes/{dispute_id}/provisional-credit", {}, headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/dmm/disputes/{dispute_id}/resolve", payload, headers
        )

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/dmm/disputes/{dispute_id}", headers=headers)

    # ---- bookkeeping & reconciliation ------------------------------------
    def create_reconciliation_period(self, payload, headers):
        return self._request("POST", "/dmm/reconciliation-periods", payload, headers)

    def import_statement_line(self, period_id, payload, headers):
        return self._request(
            "POST", f"/dmm/reconciliation-periods/{period_id}/statement-lines", payload, headers
        )

    def change_period_status(self, period_id, payload, headers):
        return self._request(
            "POST", f"/dmm/reconciliation-periods/{period_id}/status", payload, headers
        )

    def dispose_statement_line(self, statement_line_id, payload, headers):
        return self._request(
            "POST", f"/dmm/statement-lines/{statement_line_id}/disposition", payload, headers
        )

    def get_reconciliation_period(self, period_id, headers):
        return self._request(
            "GET", f"/dmm/reconciliation-periods/{period_id}", headers=headers
        )

    def list_statement_lines(self, headers, params=None):
        return self._request(
            "GET", "/dmm/statement-lines", headers=headers, params=params
        )

    def get_statement_line(self, statement_line_id, headers):
        return self._request(
            "GET", f"/dmm/statement-lines/{statement_line_id}", headers=headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/dmm/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/dmm/ledger-entries/{entry_id}", headers=headers)

    # ---- fraud / scam alerts ---------------------------------------------
    def create_fraud_alert(self, payload, headers):
        return self._request("POST", "/dmm/fraud-alerts", payload, headers)

    def dispose_fraud_alert(self, alert_id, payload, headers):
        return self._request(
            "POST", f"/dmm/fraud-alerts/{alert_id}/disposition", payload, headers
        )

    def list_fraud_alerts(self, headers, params=None):
        return self._request("GET", "/dmm/fraud-alerts", headers=headers, params=params)

    def get_fraud_alert(self, alert_id, headers):
        return self._request("GET", f"/dmm/fraud-alerts/{alert_id}", headers=headers)

    # ---- benefit applications --------------------------------------------
    def create_benefit_application(self, payload, headers):
        return self._request("POST", "/dmm/benefit-applications", payload, headers)

    def change_benefit_application_status(self, application_id, payload, headers):
        return self._request(
            "POST", f"/dmm/benefit-applications/{application_id}/status", payload, headers
        )

    def record_benefit_decision(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/dmm/benefit-applications/{application_id}/record-decision",
            payload,
            headers,
        )

    def list_benefit_applications(self, headers, params=None):
        return self._request(
            "GET", "/dmm/benefit-applications", headers=headers, params=params
        )

    def get_benefit_application(self, application_id, headers):
        return self._request(
            "GET", f"/dmm/benefit-applications/{application_id}", headers=headers
        )

    # ---- bonded / insured -------------------------------------------------
    def create_surety_bond(self, payload, headers):
        return self._request("POST", "/dmm/surety-bonds", payload, headers)

    def get_surety_bond(self, bond_id, headers):
        return self._request("GET", f"/dmm/surety-bonds/{bond_id}", headers=headers)

    # ---- family reporting -------------------------------------------------
    def create_family_recipient(self, payload, headers):
        return self._request("POST", "/dmm/family-recipients", payload, headers)

    def record_consent(self, recipient_id, payload, headers):
        return self._request(
            "POST", f"/dmm/family-recipients/{recipient_id}/consent", payload, headers
        )

    def create_family_report(self, payload, headers):
        return self._request("POST", "/dmm/family-reports", payload, headers)

    def list_family_recipients(self, headers, params=None):
        return self._request(
            "GET", "/dmm/family-recipients", headers=headers, params=params
        )

    def get_family_recipient(self, recipient_id, headers):
        return self._request(
            "GET", f"/dmm/family-recipients/{recipient_id}", headers=headers
        )

    def list_family_reports(self, headers, params=None):
        return self._request("GET", "/dmm/family-reports", headers=headers, params=params)

    def get_family_report(self, report_id, headers):
        return self._request("GET", f"/dmm/family-reports/{report_id}", headers=headers)

    # ---- care-team coordination ------------------------------------------
    def create_coordination_request(self, payload, headers):
        return self._request("POST", "/dmm/coordination-requests", payload, headers)

    def dispose_coordination_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/dmm/coordination-requests/{request_id}/disposition", payload, headers
        )

    def get_coordination_request(self, request_id, headers):
        return self._request(
            "GET", f"/dmm/coordination-requests/{request_id}", headers=headers
        )

    # ---- clock & operations ----------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_checkpoint(self, headers):
        return self._request("POST", "/dmm/ops/checkpoint", {}, headers)


api_client = ApiClient()
