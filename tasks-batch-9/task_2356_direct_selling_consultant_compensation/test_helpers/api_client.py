"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/direct-selling"


def _wire_params(params):
    """Render query-string values in their canonical wire form.

    Python's ``requests`` serialises ``True``/``False`` with ``str()``, producing
    ``is_starter_kit=True``. The PRD declares these filters as booleans (PRD §3.1
    for `is_starter_kit`, `buyback_eligible` and `facilitator_agreement_active`,
    PRD §3.2 for `payout_hold`), and the canonical JSON spelling of a boolean is
    lower case, so send ``true``/``false`` rather than the Python repr.
    """
    if not params:
        return params
    return {
        key: ("true" if value else "false") if isinstance(value, bool) else value
        for key, value in params.items()
    }


class ApiClient(GenericApiClient):
    """Thin typed wrapper over the Direct Selling Consultant Compensation API."""

    def _request(self, method, path, payload=None, headers=None, params=None):
        if method.upper() in ("GET", "DELETE"):
            payload = _wire_params(payload)
        return super()._request(
            method, path, payload=payload, headers=headers, params=_wire_params(params)
        )

    # ---- Logical clock (PRD §2.5) -------------------------------------------
    def get_clock(self, headers=None):
        return self._request("GET", f"{PREFIX}/_clock", headers=headers)

    def set_clock(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---- Compensation plans (PRD §3.1) --------------------------------------
    def create_compensation_plan(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/compensation-plans", payload, headers)

    def update_compensation_plan(self, plan_id, payload, headers=None):
        return self._request("PATCH", f"{PREFIX}/compensation-plans/{plan_id}", payload, headers)

    def list_compensation_plans(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/compensation-plans", headers=headers, params=params)

    def get_compensation_plan(self, plan_id, headers=None):
        return self._request("GET", f"{PREFIX}/compensation-plans/{plan_id}", headers=headers)

    # ---- Tax jurisdictions (PRD §3.1) --------------------------------------
    def create_tax_jurisdiction(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/tax-jurisdictions", payload, headers)

    def list_tax_jurisdictions(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/tax-jurisdictions", headers=headers, params=params)

    def get_tax_jurisdiction(self, jurisdiction_id, headers=None):
        return self._request("GET", f"{PREFIX}/tax-jurisdictions/{jurisdiction_id}", headers=headers)

    # ---- Products (PRD §3.1) ------------------------------------------------
    def create_product(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def list_products(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    def get_product(self, product_id, headers=None):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    # ---- Enrollment applications (PRD §3.2) --------------------------------
    def create_enrollment_application(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/enrollment-applications", payload, headers)

    def list_enrollment_applications(self, headers=None, params=None):
        return self._request(
            "GET", f"{PREFIX}/enrollment-applications", headers=headers, params=params
        )

    def get_enrollment_application(self, application_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/enrollment-applications/{application_id}", headers=headers
        )

    def accept_agreement(self, application_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/enrollment-applications/{application_id}/accept-agreement",
            payload,
            headers,
        )

    def submit_identity_documents(self, application_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/enrollment-applications/{application_id}/identity-submission",
            payload,
            headers,
        )

    def decide_identity(self, application_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/enrollment-applications/{application_id}/identity-decision",
            payload,
            headers,
        )

    def pay_starter_kit(self, application_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/enrollment-applications/{application_id}/pay-starter-kit",
            payload,
            headers,
        )

    def withdraw_enrollment_application(self, application_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/enrollment-applications/{application_id}/withdraw",
            payload,
            headers,
        )

    def approve_enrollment_application(self, application_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/enrollment-applications/{application_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    # ---- Consultants (PRD §3.2, §3.8) --------------------------------------
    def list_consultants(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/consultants", headers=headers, params=params)

    def get_consultant(self, consultant_id, headers=None):
        return self._request("GET", f"{PREFIX}/consultants/{consultant_id}", headers=headers)

    def terminate_consultant(self, consultant_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/consultants/{consultant_id}/terminate", payload, headers
        )

    def reinstate_consultant(self, consultant_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/consultants/{consultant_id}/reinstate",
            payload if payload is not None else {},
            headers,
        )

    def adjust_consultant_rank(self, consultant_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/consultants/{consultant_id}/rank-adjustment", payload, headers
        )

    # ---- Product orders (PRD §3.3) -----------------------------------------
    def create_product_order(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/product-orders", payload, headers)

    def list_product_orders(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/product-orders", headers=headers, params=params)

    def get_product_order(self, order_id, headers=None):
        return self._request("GET", f"{PREFIX}/product-orders/{order_id}", headers=headers)

    def pay_product_order(self, order_id, payload, headers=None):
        return self._request("POST", f"{PREFIX}/product-orders/{order_id}/pay", payload, headers)

    def advance_fulfillment(self, order_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/product-orders/{order_id}/fulfillment", payload, headers
        )

    # ---- Qualification periods (PRD §3.4) ----------------------------------
    def create_qualification_period(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/qualification-periods", payload, headers)

    def list_qualification_periods(self, headers=None, params=None):
        return self._request(
            "GET", f"{PREFIX}/qualification-periods", headers=headers, params=params
        )

    def get_qualification_period(self, period_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/qualification-periods/{period_id}", headers=headers
        )

    def lock_qualification_period(self, period_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/qualification-periods/{period_id}/lock",
            payload if payload is not None else {},
            headers,
        )

    def close_qualification_period(self, period_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/qualification-periods/{period_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def reopen_qualification_period(self, period_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/qualification-periods/{period_id}/reopen", payload, headers
        )

    # ---- Period qualifications (PRD §3.4) ----------------------------------
    def list_period_qualifications(self, headers=None, params=None):
        return self._request(
            "GET", f"{PREFIX}/period-qualifications", headers=headers, params=params
        )

    def get_period_qualification(self, period_qualification_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/period-qualifications/{period_qualification_id}", headers=headers
        )

    def attest_personal_use(self, period_qualification_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/period-qualifications/{period_qualification_id}/personal-use-attestation",
            payload,
            headers,
        )

    # ---- Commission runs (PRD §3.5) ----------------------------------------
    def create_commission_run(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/commission-runs", payload, headers)

    def list_commission_runs(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/commission-runs", headers=headers, params=params)

    def get_commission_run(self, run_id, headers=None):
        return self._request("GET", f"{PREFIX}/commission-runs/{run_id}", headers=headers)

    def calculate_commission_run(self, run_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/commission-runs/{run_id}/calculate",
            payload if payload is not None else {},
            headers,
        )

    def decide_commission_run_approval(self, run_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/commission-runs/{run_id}/approval-decision", payload, headers
        )

    def pay_commission_run(self, run_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/commission-runs/{run_id}/pay",
            payload if payload is not None else {},
            headers,
        )

    def reverse_commission_run(self, run_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/commission-runs/{run_id}/reverse", payload, headers
        )

    # ---- Commission statements (PRD §3.5) ----------------------------------
    def list_commission_statements(self, headers=None, params=None):
        return self._request(
            "GET", f"{PREFIX}/commission-statements", headers=headers, params=params
        )

    def get_commission_statement(self, statement_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/commission-statements/{statement_id}", headers=headers
        )

    # ---- Buyback requests (PRD §3.6) ---------------------------------------
    def create_buyback_request(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/buyback-requests", payload, headers)

    def list_buyback_requests(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/buyback-requests", headers=headers, params=params)

    def get_buyback_request(self, buyback_id, headers=None):
        return self._request("GET", f"{PREFIX}/buyback-requests/{buyback_id}", headers=headers)

    def decide_buyback_request(self, buyback_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/buyback-requests/{buyback_id}/decision", payload, headers
        )

    def refund_buyback_request(self, buyback_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/buyback-requests/{buyback_id}/refund",
            payload if payload is not None else {},
            headers,
        )

    # ---- Compliance cases (PRD §3.7) ---------------------------------------
    def create_compliance_case(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/compliance-cases", payload, headers)

    def list_compliance_cases(self, headers=None, params=None):
        return self._request("GET", f"{PREFIX}/compliance-cases", headers=headers, params=params)

    def get_compliance_case(self, case_id, headers=None):
        return self._request("GET", f"{PREFIX}/compliance-cases/{case_id}", headers=headers)

    def review_compliance_case(self, case_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/compliance-cases/{case_id}/review",
            payload if payload is not None else {},
            headers,
        )

    def decide_compliance_case(self, case_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/compliance-cases/{case_id}/decision", payload, headers
        )

    def appeal_compliance_case(self, case_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/compliance-cases/{case_id}/appeal", payload, headers
        )

    # ---- Income disclosure statements (PRD §3.9) ---------------------------
    def create_income_disclosure_statement(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/income-disclosure-statements", payload, headers)

    def list_income_disclosure_statements(self, headers=None, params=None):
        return self._request(
            "GET", f"{PREFIX}/income-disclosure-statements", headers=headers, params=params
        )

    def get_income_disclosure_statement(self, statement_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/income-disclosure-statements/{statement_id}", headers=headers
        )

    def submit_disclosure_for_legal_review(self, statement_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/income-disclosure-statements/{statement_id}/submit-legal-review",
            payload if payload is not None else {},
            headers,
        )

    def decide_disclosure_legal_review(self, statement_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/income-disclosure-statements/{statement_id}/legal-decision",
            payload,
            headers,
        )


api_client = ApiClient()
