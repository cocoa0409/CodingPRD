"""API client: one method per endpoint defined in the PRD (Section 4).

Every method returns the raw ``requests.Response`` so tests can assert both the
HTTP status and the envelope body.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Warranty program endpoints. All warranty resources live under /warranty."""

    # ------------------------------------------------------------------
    # Builder enrollment file
    # ------------------------------------------------------------------
    def create_builder(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/warranty/builders", payload, headers)

    def submit_builder(self, builder_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/builders/{builder_id}/submission", payload, headers
        )

    def take_builder_into_review(self, builder_id: str,
                                 payload: Optional[Dict[str, Any]],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/builders/{builder_id}/review-intake",
            payload if payload is not None else {}, headers,
        )

    def create_underwriting_review(self, builder_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/builders/{builder_id}/underwriting-reviews",
            payload, headers,
        )

    def reassess_builder(self, builder_id: str, payload: Optional[Dict[str, Any]],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/builders/{builder_id}/reassessment",
            payload if payload is not None else {}, headers,
        )

    def suspend_builder(self, builder_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/builders/{builder_id}/suspension", payload, headers
        )

    def reinstate_builder(self, builder_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/builders/{builder_id}/reinstatement", payload, headers
        )

    def declare_builder_default(self, builder_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/builders/{builder_id}/default-declaration",
            payload, headers,
        )

    def get_builder(self, builder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/warranty/builders/{builder_id}", headers=headers)

    def list_builders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/warranty/builders", headers=headers, params=params)

    def list_underwriting_reviews(self, builder_id: str, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"/warranty/builders/{builder_id}/underwriting-reviews",
            headers=headers, params=params,
        )

    def get_loss_monitor(self, builder_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/warranty/builders/{builder_id}/loss-monitor", headers=headers
        )

    # ------------------------------------------------------------------
    # Home buyers
    # ------------------------------------------------------------------
    def create_homeowner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/warranty/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/warranty/homeowners/{homeowner_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Panel of neutrals
    # ------------------------------------------------------------------
    def create_neutral(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/warranty/neutrals", payload, headers)

    def deactivate_neutral(self, neutral_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/neutrals/{neutral_id}/deactivation", payload, headers
        )

    def get_neutral(self, neutral_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/warranty/neutrals/{neutral_id}", headers=headers)

    def list_neutrals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/warranty/neutrals", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Home enrollment, billing, activation and coverage terms
    # ------------------------------------------------------------------
    def create_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/warranty/policies", payload, headers)

    def create_premium_invoice(self, policy_id: str, payload: Optional[Dict[str, Any]],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/policies/{policy_id}/premium-invoice",
            payload if payload is not None else {}, headers,
        )

    def create_premium_payment(self, policy_id: str, payload: Optional[Dict[str, Any]],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/policies/{policy_id}/premium-payments",
            payload if payload is not None else {}, headers,
        )

    def activate_policy(self, policy_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/warranty/policies/{policy_id}/activation",
            payload if payload is not None else {}, headers,
        )

    def create_coverage_term(self, policy_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/policies/{policy_id}/coverage-terms", payload, headers
        )

    def get_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/warranty/policies/{policy_id}", headers=headers)

    def list_policies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/warranty/policies", headers=headers, params=params)

    def list_policy_coverage_terms(self, policy_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/warranty/policies/{policy_id}/coverage-terms",
            headers=headers, params=params,
        )

    def get_coverage_term(self, coverage_term_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/warranty/coverage-terms/{coverage_term_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Warranty transfers
    # ------------------------------------------------------------------
    def create_transfer(self, policy_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/policies/{policy_id}/transfers", payload, headers
        )

    def request_transfer_documentation(self, transfer_id: str, payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/transfers/{transfer_id}/documentation-request",
            payload, headers,
        )

    def resubmit_transfer(self, transfer_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/transfers/{transfer_id}/resubmission", payload, headers
        )

    def decide_transfer(self, transfer_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/transfers/{transfer_id}/decision", payload, headers
        )

    def record_transfer(self, transfer_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/warranty/transfers/{transfer_id}/recording",
            payload if payload is not None else {}, headers,
        )

    def get_transfer(self, transfer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/warranty/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/warranty/transfers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Claims: intake, investigation, assessment, routing, adjudication
    # ------------------------------------------------------------------
    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/warranty/claims", payload, headers)

    def create_investigation(self, claim_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/investigation", payload, headers
        )

    def create_structural_assessment(self, claim_id: str, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/structural-assessments",
            payload, headers,
        )

    def route_claim_obligation(self, claim_id: str, payload: Optional[Dict[str, Any]],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/obligation-routing",
            payload if payload is not None else {}, headers,
        )

    def create_builder_response(self, claim_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/builder-response", payload, headers
        )

    def create_repair_completion(self, claim_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/repair-completion", payload, headers
        )

    def create_adjudication(self, claim_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/adjudication", payload, headers
        )

    # ------------------------------------------------------------------
    # Reserve ledger
    # ------------------------------------------------------------------
    def create_reserve_entry(self, claim_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/reserve-entries", payload, headers
        )

    def create_payment(self, claim_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/payments", payload, headers
        )

    def create_payment_reversal(self, claim_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/payment-reversals", payload, headers
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/warranty/claims/{claim_id}", headers=headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/warranty/claims", headers=headers, params=params)

    def list_structural_assessments(self, claim_id: str, headers: Dict[str, str],
                                    params: Optional[Dict] = None):
        return self._request(
            "GET", f"/warranty/claims/{claim_id}/structural-assessments",
            headers=headers, params=params,
        )

    def get_reserve_entry(self, reserve_entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/warranty/reserve-entries/{reserve_entry_id}", headers=headers
        )

    def list_reserve_entries(self, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request(
            "GET", "/warranty/reserve-entries", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Escalation ladder
    # ------------------------------------------------------------------
    def create_escalation(self, claim_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/claims/{claim_id}/escalations", payload, headers
        )

    def record_session_outcome(self, escalation_case_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/escalation-cases/{escalation_case_id}/session-outcome",
            payload, headers,
        )

    def create_award(self, escalation_case_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty/escalation-cases/{escalation_case_id}/award",
            payload, headers,
        )

    def get_escalation_case(self, escalation_case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/warranty/escalation-cases/{escalation_case_id}", headers=headers
        )

    def list_escalation_cases(self, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request(
            "GET", "/warranty/escalation-cases", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Logical clock (outside the /warranty prefix)
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
