"""Typed endpoint methods for every operation the PRD §4 endpoint table declares.

Each method returns the raw ``requests.Response`` so tests can assert status
codes directly. All business resources are mounted beneath ``/amnesty``; the
logical-clock capability is the sole exception (PRD §2.4).
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/amnesty"


class ApiClient(GenericApiClient):
    """One method per PRD-declared endpoint."""

    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Amnesty programs (PRD §3.1, §3.8)
    # ------------------------------------------------------------------

    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/programs", payload, headers)

    def list_programs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/programs", None, headers, params)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/programs/{program_id}", None, headers)

    def create_tax_type_term(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/tax-type-terms", payload, headers
        )

    def list_program_tax_type_terms(
        self,
        program_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/programs/{program_id}/tax-type-terms",
            None,
            headers,
            params,
        )

    def get_tax_type_term(self, term_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/tax-type-terms/{term_id}", None, headers
        )

    def open_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/open", {}, headers
        )

    def close_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/close", {}, headers
        )

    def reconcile_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/reconcile", {}, headers
        )

    def run_installment_sweep(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/installment-sweep", {}, headers
        )

    def get_revenue_summary(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/programs/{program_id}/revenue-summary", None, headers
        )

    # ------------------------------------------------------------------
    # Taxpayer registry (PRD §3.2)
    # ------------------------------------------------------------------

    def create_taxpayer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/taxpayers", payload, headers)

    def list_taxpayers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/taxpayers", None, headers, params)

    def get_taxpayer(self, taxpayer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/taxpayers/{taxpayer_id}", None, headers)

    def get_compliance_behavior(self, taxpayer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{PREFIX}/taxpayers/{taxpayer_id}/compliance-behavior",
            None,
            headers,
        )

    def list_taxpayer_enforcement_cases(
        self,
        taxpayer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/taxpayers/{taxpayer_id}/enforcement-cases",
            None,
            headers,
            params,
        )

    # ------------------------------------------------------------------
    # Enforcement cases (PRD §3.2)
    # ------------------------------------------------------------------

    def create_enforcement_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/enforcement-cases", payload, headers)

    def get_enforcement_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/enforcement-cases/{case_id}", None, headers
        )

    def close_enforcement_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/close", {}, headers
        )

    def refer_enforcement_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/refer", {}, headers
        )

    # ------------------------------------------------------------------
    # Representatives (PRD §3.2)
    # ------------------------------------------------------------------

    def create_representative(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/representatives", payload, headers)

    def get_representative(self, representative_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/representatives/{representative_id}", None, headers
        )

    def suspend_representative(self, representative_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/representatives/{representative_id}/suspend",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Pre-clearance and negotiation (PRD §3.3)
    # ------------------------------------------------------------------

    def create_pre_clearance(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/pre-clearances", payload, headers)

    def list_pre_clearances(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/pre-clearances", None, headers, params)

    def get_pre_clearance(self, pre_clearance_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/pre-clearances/{pre_clearance_id}", None, headers
        )

    def begin_pre_clearance_review(
        self, pre_clearance_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/pre-clearances/{pre_clearance_id}/begin-review",
            {},
            headers,
        )

    def offer_terms(
        self,
        pre_clearance_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{PREFIX}/pre-clearances/{pre_clearance_id}/offer-terms",
            payload,
            headers,
        )

    def counter_terms(
        self,
        pre_clearance_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{PREFIX}/pre-clearances/{pre_clearance_id}/counter",
            payload,
            headers,
        )

    def disclose_identity(
        self,
        pre_clearance_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{PREFIX}/pre-clearances/{pre_clearance_id}/disclose-identity",
            payload,
            headers,
        )

    def accept_pre_clearance(self, pre_clearance_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/pre-clearances/{pre_clearance_id}/accept", {}, headers
        )

    def reject_pre_clearance(
        self,
        pre_clearance_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{PREFIX}/pre-clearances/{pre_clearance_id}/reject",
            payload,
            headers,
        )

    def list_negotiation_rounds(
        self,
        pre_clearance_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/pre-clearances/{pre_clearance_id}/negotiation-rounds",
            None,
            headers,
            params,
        )

    def get_negotiation_round(self, round_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/negotiation-rounds/{round_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Agreements (PRD §3.4, §3.7)
    # ------------------------------------------------------------------

    def create_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def list_agreements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/agreements", None, headers, params)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/agreements/{agreement_id}", None, headers
        )

    def execute_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/execute", {}, headers
        )

    def amend_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/amend", payload, headers
        )

    def certify_compliance(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/agreements/{agreement_id}/certify-compliance",
            {},
            headers,
        )

    def declare_breach(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/agreements/{agreement_id}/declare-breach",
            payload,
            headers,
        )

    def rescind_breach(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/agreements/{agreement_id}/rescind-breach",
            payload,
            headers,
        )

    def list_agreement_payment_plans(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/agreements/{agreement_id}/payment-plans",
            None,
            headers,
            params,
        )

    def list_agreement_payments(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/agreements/{agreement_id}/payments",
            None,
            headers,
            params,
        )

    # ------------------------------------------------------------------
    # Disclosure returns (PRD §3.5)
    # ------------------------------------------------------------------

    def create_return(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/returns", payload, headers
        )

    def list_agreement_returns(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/agreements/{agreement_id}/returns",
            None,
            headers,
            params,
        )

    def get_return(self, return_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/returns/{return_id}", None, headers)

    def file_return(self, return_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/returns/{return_id}/file", {}, headers
        )

    def assess_return(self, return_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/returns/{return_id}/assess", {}, headers
        )

    # ------------------------------------------------------------------
    # Payment plans and installments (PRD §3.6)
    # ------------------------------------------------------------------

    def create_payment_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/payment-plans/{plan_id}", None, headers
        )

    def approve_payment_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/payment-plans/{plan_id}/approve", {}, headers
        )

    def reject_payment_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/payment-plans/{plan_id}/reject", payload, headers
        )

    def default_payment_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/payment-plans/{plan_id}/default", payload, headers
        )

    def list_plan_installments(
        self,
        plan_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/payment-plans/{plan_id}/installments",
            None,
            headers,
            params,
        )

    def get_installment(self, installment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/installments/{installment_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Payments (PRD §3.6)
    # ------------------------------------------------------------------

    def create_payment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/payments", payload, headers)

    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/payments/{payment_id}", None, headers)

    def reverse_payment(
        self, payment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/payments/{payment_id}/reverse", payload, headers
        )

    # ------------------------------------------------------------------
    # Enforcement actions (PRD §3.9)
    # ------------------------------------------------------------------

    def create_enforcement_action(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{PREFIX}/enforcement-actions", payload, headers)

    def list_enforcement_actions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/enforcement-actions", None, headers, params
        )

    def get_enforcement_action(self, action_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/enforcement-actions/{action_id}", None, headers
        )

    def issue_enforcement_action(self, action_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/enforcement-actions/{action_id}/issue", {}, headers
        )

    def abate_enforcement_action(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/enforcement-actions/{action_id}/abate",
            payload,
            headers,
        )


# Module-level singleton reused by the pytest bridge in test_suite/conftest.py.
api_client = ApiClient()
