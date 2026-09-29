"""Typed API client: one method per declared endpoint.

Every method returns the raw `requests.Response` so that tests can assert on
status codes as well as bodies.  Paths carry no prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Logical clock
    # =====================================================================
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # =====================================================================
    # StateRateRule
    # =====================================================================
    def create_state_rate_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/state-rate-rules", payload, headers)

    def get_state_rate_rule(self, rule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/state-rate-rules/{rule_id}", None, headers)

    # =====================================================================
    # License
    # =====================================================================
    def create_license(
        self, rule_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/state-rate-rules/{rule_id}/licenses", payload, headers
        )

    def list_licenses(
        self, rule_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/state-rate-rules/{rule_id}/licenses", params or {}, headers
        )

    def suspend_license(self, license_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/suspend", {}, headers)

    # =====================================================================
    # Insured
    # =====================================================================
    def create_insured(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/insureds", payload, headers)

    # =====================================================================
    # ProducerAgent
    # =====================================================================
    def create_agent(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agents/{agent_id}", None, headers)

    def suspend_agent(
        self,
        agent_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/agents/{agent_id}/suspend", payload or {}, headers
        )

    # =====================================================================
    # Insurer
    # =====================================================================
    def create_insurer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/insurers", payload, headers)

    # =====================================================================
    # PremiumFinanceAgreement
    # =====================================================================
    def create_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agreements/{agreement_id}", None, headers)

    def list_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/agreements", params or {}, headers)

    def submit_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/agreements/{agreement_id}/submit", {}, headers)

    def activate_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/agreements/{agreement_id}/activate", {}, headers
        )

    def void_agreement(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/agreements/{agreement_id}/void", payload or {}, headers
        )

    def restructure_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/agreements/{agreement_id}/restructure", payload, headers
        )

    def approve_rate_exception(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/agreements/{agreement_id}/rate-exception-approvals",
            payload,
            headers,
        )

    def get_payoff_quote(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"/agreements/{agreement_id}/payoff-quote", params or {}, headers
        )

    # =====================================================================
    # FinancedPolicy
    # =====================================================================
    def attach_policy(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/agreements/{agreement_id}/policies", payload, headers
        )

    def get_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/policies/{policy_id}", None, headers)

    def list_policies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/policies", params or {}, headers)

    # =====================================================================
    # PremiumVerification
    # =====================================================================
    def create_verification(
        self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/policies/{policy_id}/verifications", payload, headers
        )

    def list_verifications(
        self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/policies/{policy_id}/verifications", params or {}, headers
        )

    def reopen_verification(self, policy_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/policies/{policy_id}/reopen-verification", {}, headers
        )

    # =====================================================================
    # Installment
    # =====================================================================
    def list_installments(
        self, agreement_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/agreements/{agreement_id}/installments", params or {}, headers
        )

    # =====================================================================
    # Payment
    # =====================================================================
    def create_payment(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/agreements/{agreement_id}/payments", payload, headers
        )

    def list_payments(
        self, agreement_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/agreements/{agreement_id}/payments", params or {}, headers
        )

    def reverse_payment(
        self, payment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/payments/{payment_id}/reverse", payload, headers
        )

    # =====================================================================
    # LateFeeAssessment
    # =====================================================================
    def list_late_fees(
        self, agreement_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/agreements/{agreement_id}/late-fees", params or {}, headers
        )

    def waive_late_fee(
        self, late_fee_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/late-fees/{late_fee_id}/waive", payload, headers
        )

    # =====================================================================
    # Servicing
    # =====================================================================
    def run_servicing(
        self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request("POST", "/servicing-runs", payload or {}, headers)

    # =====================================================================
    # CancellationNotice
    # =====================================================================
    def issue_cancellation_notice(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/agreements/{agreement_id}/cancellation-notices",
            payload or {},
            headers,
        )

    def list_cancellation_notices(
        self, agreement_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/agreements/{agreement_id}/cancellation-notices",
            params or {},
            headers,
        )

    def execute_cancellation(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/agreements/{agreement_id}/cancellation-executions",
            payload or {},
            headers,
        )

    # =====================================================================
    # CarrierCancellationRequest
    # =====================================================================
    def list_carrier_cancellation_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/carrier-cancellation-requests", params or {}, headers
        )

    def get_carrier_cancellation_request(
        self, request_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/carrier-cancellation-requests/{request_id}", None, headers
        )

    def post_carrier_return(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/carrier-cancellation-requests/{request_id}/return-posting",
            payload,
            headers,
        )

    # =====================================================================
    # PremiumEndorsement
    # =====================================================================
    def create_endorsement(
        self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/policies/{policy_id}/endorsements", payload, headers
        )

    def list_endorsements(
        self, policy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/policies/{policy_id}/endorsements", params or {}, headers
        )

    def decline_endorsement(
        self,
        endorsement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/endorsements/{endorsement_id}/decline", payload or {}, headers
        )

    def finance_endorsements(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/agreements/{agreement_id}/endorsement-financings",
            payload,
            headers,
        )

    # =====================================================================
    # AgentChargeback
    # =====================================================================
    def list_agent_chargebacks(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/agent-chargebacks", params or {}, headers)

    def get_agent_chargeback(self, chargeback_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/agent-chargebacks/{chargeback_id}", None, headers
        )

    def offset_chargeback(
        self, chargeback_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/agent-chargebacks/{chargeback_id}/offset", payload, headers
        )
