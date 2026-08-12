"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Insured persons (PRD §3.1)
    # ------------------------------------------------------------------
    def create_insured_person(self, payload, headers):
        return self._request("POST", "/insured-persons", payload, headers)

    def list_insured_persons(self, headers, params=None):
        return self._request("GET", "/insured-persons", headers=headers, params=params)

    def get_insured_person(self, insured_id, headers):
        return self._request("GET", f"/insured-persons/{insured_id}", headers=headers)

    # ------------------------------------------------------------------
    # Product templates (PRD §3.1)
    # ------------------------------------------------------------------
    def create_product_template(self, payload, headers):
        return self._request("POST", "/product-templates", payload, headers)

    def list_product_templates(self, headers, params=None):
        return self._request("GET", "/product-templates", headers=headers, params=params)

    def get_product_template(self, template_id, headers):
        return self._request("GET", f"/product-templates/{template_id}", headers=headers)

    # ------------------------------------------------------------------
    # Policy applications and underwriting (PRD §3.2, §3.3)
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def begin_review(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/begin-review", {}, headers)

    def request_evidence(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/request-evidence", {}, headers)

    def submit_evidence(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit-evidence", {}, headers)

    def approve_application(self, application_id, underwriting_class, headers):
        return self._request("POST", f"/applications/{application_id}/approve",
                             {"underwriting_class": underwriting_class}, headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/decline", {}, headers)

    def issue_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/issue", {}, headers)

    # ------------------------------------------------------------------
    # Policies (PRD §3.4, §3.7)
    # ------------------------------------------------------------------
    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def change_mode(self, policy_id, premium_mode, expected_policy_version, headers):
        return self._request("POST", f"/policies/{policy_id}/mode-change",
                             {"premium_mode": premium_mode,
                              "expected_policy_version": expected_policy_version}, headers)

    def change_dividend_option(self, policy_id, dividend_option, expected_policy_version, headers):
        return self._request("POST", f"/policies/{policy_id}/dividend-option",
                             {"dividend_option": dividend_option,
                              "expected_policy_version": expected_policy_version}, headers)

    # ------------------------------------------------------------------
    # Billing cycles and premium payments (PRD §3.4)
    # ------------------------------------------------------------------
    def list_billing_cycles(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/billing-cycles",
                             headers=headers, params=params)

    def record_premium_payment(self, policy_id, amount_cents, headers):
        return self._request("POST", f"/policies/{policy_id}/premium-payments",
                             {"amount_cents": amount_cents}, headers)

    # ------------------------------------------------------------------
    # Policy loans (PRD §3.6)
    # ------------------------------------------------------------------
    def create_loan(self, policy_id, requested_amount_cents, headers):
        return self._request("POST", f"/policies/{policy_id}/loans",
                             {"requested_amount_cents": requested_amount_cents}, headers)

    def list_loans(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/loans", headers=headers, params=params)

    def get_loan(self, policy_id, loan_id, headers):
        return self._request("GET", f"/policies/{policy_id}/loans/{loan_id}", headers=headers)

    def accrue_interest(self, policy_id, loan_id, headers, as_of_date=None):
        payload = {} if as_of_date is None else {"as_of_date": as_of_date}
        return self._request("POST", f"/policies/{policy_id}/loans/{loan_id}/accrue-interest",
                             payload, headers)

    def repay_loan(self, policy_id, loan_id, amount_cents, headers):
        return self._request("POST", f"/policies/{policy_id}/loans/{loan_id}/repayments",
                             {"amount_cents": amount_cents}, headers)

    def list_loan_accruals(self, policy_id, loan_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/loans/{loan_id}/accruals",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Flat filtered-list GETs (PRD §3.11 reverse-reachability listings)
    # ------------------------------------------------------------------
    def list_policy_loans(self, headers, params=None):
        return self._request("GET", "/policy-loans", headers=headers, params=params)

    def get_policy_loan(self, loan_id, headers):
        return self._request("GET", f"/policy-loans/{loan_id}", headers=headers)

    def list_loan_interest_accruals(self, headers, params=None):
        return self._request("GET", "/loan-interest-accruals", headers=headers, params=params)

    def get_loan_interest_accrual(self, accrual_id, headers):
        return self._request("GET", f"/loan-interest-accruals/{accrual_id}", headers=headers)

    def list_premium_billing_cycles(self, headers, params=None):
        return self._request("GET", "/premium-billing-cycles", headers=headers, params=params)

    def get_premium_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/premium-billing-cycles/{cycle_id}", headers=headers)

    def list_dividend_declarations(self, headers, params=None):
        return self._request("GET", "/dividend-declarations", headers=headers, params=params)

    def get_dividend_declaration(self, declaration_id, headers):
        return self._request("GET", f"/dividend-declarations/{declaration_id}", headers=headers)

    def list_nonforfeiture_elections(self, headers, params=None):
        return self._request("GET", "/nonforfeiture-elections", headers=headers, params=params)

    def get_nonforfeiture_election(self, election_id, headers):
        return self._request("GET", f"/nonforfeiture-elections/{election_id}", headers=headers)

    def list_reinstatement_requests(self, headers, params=None):
        return self._request("GET", "/reinstatement-requests", headers=headers, params=params)

    def get_reinstatement_request(self, request_id, headers):
        return self._request("GET", f"/reinstatement-requests/{request_id}", headers=headers)

    def list_riders(self, headers, params=None):
        return self._request("GET", "/riders", headers=headers, params=params)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/riders/{rider_id}", headers=headers)

    def list_conversion_requests(self, headers, params=None):
        return self._request("GET", "/conversion-requests", headers=headers, params=params)

    def get_conversion_request(self, request_id, headers):
        return self._request("GET", f"/conversion-requests/{request_id}", headers=headers)

    def list_cash_value_ledger_entries(self, headers, params=None):
        return self._request("GET", "/cash-value-ledger-entries", headers=headers, params=params)

    def get_cash_value_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/cash-value-ledger-entries/{entry_id}", headers=headers)

    # ------------------------------------------------------------------
    # Non-forfeiture elections (PRD §3.8)
    # ------------------------------------------------------------------
    def create_nonforfeiture_election(self, policy_id, election_type, headers):
        return self._request("POST", f"/policies/{policy_id}/nonforfeiture-elections",
                             {"election_type": election_type}, headers)

    def list_policy_nonforfeiture_elections(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/nonforfeiture-elections",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Dividend declarations (PRD §3.7)
    # ------------------------------------------------------------------
    def create_dividend_declaration(self, policy_id, policy_year, declared_amount_cents, headers):
        return self._request("POST", f"/policies/{policy_id}/dividend-declarations",
                             {"policy_year": policy_year,
                              "declared_amount_cents": declared_amount_cents}, headers)

    def list_policy_dividend_declarations(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/dividend-declarations",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Reinstatement requests (PRD §3.9)
    # ------------------------------------------------------------------
    def create_reinstatement_request(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/reinstatement-requests", {}, headers)

    def list_policy_reinstatement_requests(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/reinstatement-requests",
                             headers=headers, params=params)

    def pay_reinstatement(self, policy_id, request_id, amount_cents, headers):
        return self._request("POST",
                             f"/policies/{policy_id}/reinstatement-requests/{request_id}/payments",
                             {"amount_cents": amount_cents}, headers)

    def request_reinstatement_evidence(self, policy_id, request_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/reinstatement-requests/{request_id}/request-evidence",
            {}, headers)

    def submit_reinstatement_evidence(self, policy_id, request_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/reinstatement-requests/{request_id}/submit-evidence",
            {}, headers)

    def approve_reinstatement(self, policy_id, request_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/reinstatement-requests/{request_id}/approve",
            {}, headers)

    def decline_reinstatement(self, policy_id, request_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/reinstatement-requests/{request_id}/decline",
            {}, headers)

    # ------------------------------------------------------------------
    # Riders (PRD §3.10)
    # ------------------------------------------------------------------
    def create_rider(self, policy_id, rider_type, rider_face_amount_cents, headers):
        return self._request("POST", f"/policies/{policy_id}/riders",
                             {"rider_type": rider_type,
                              "rider_face_amount_cents": rider_face_amount_cents}, headers)

    def list_policy_riders(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/riders", headers=headers, params=params)

    def terminate_rider(self, policy_id, rider_id, headers):
        return self._request("POST", f"/policies/{policy_id}/riders/{rider_id}/terminate",
                             {}, headers)

    def exercise_rider(self, policy_id, rider_id, headers):
        return self._request("POST", f"/policies/{policy_id}/riders/{rider_id}/exercise",
                             {}, headers)

    # ------------------------------------------------------------------
    # Conversion requests (PRD §3.10)
    # ------------------------------------------------------------------
    def create_conversion_request(self, policy_id, target_product_template_id,
                                  requested_face_amount_cents, headers):
        return self._request("POST", f"/policies/{policy_id}/conversion-requests",
                             {"target_product_template_id": target_product_template_id,
                              "requested_face_amount_cents": requested_face_amount_cents},
                             headers)

    def list_policy_conversion_requests(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/conversion-requests",
                             headers=headers, params=params)

    def approve_conversion(self, policy_id, conversion_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/conversion-requests/{conversion_id}/approve",
            {}, headers)

    def decline_conversion(self, policy_id, conversion_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/conversion-requests/{conversion_id}/decline",
            {}, headers)

    # ------------------------------------------------------------------
    # Cash value ledger (PRD §2.7)
    # ------------------------------------------------------------------
    def list_policy_cash_value_ledger(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/cash-value-ledger",
                             headers=headers, params=params)


api_client = ApiClient()
