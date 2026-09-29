"""One method per API endpoint.

Every method returns the raw ``requests.Response`` so tests can assert on status
codes as well as bodies.  Query filters are passed through ``params``; request
bodies are passed through ``payload``.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP client for the Home Improvement Point-of-Sale Financing API."""

    # ─── Logical clock and operations checkpoint ──────

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_expiration_sweep(self, payload: Optional[Dict] = None,
                             headers: Optional[Dict] = None):
        return self._request(
            "POST", "/servicing/expiration-sweeps", payload or {}, headers
        )

    # ─── Trade rules ──────────────────────────────────

    def create_trade_rule(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/trade-rules", payload, headers)

    def list_trade_rules(self, headers: Optional[Dict] = None,
                         params: Optional[Dict] = None):
        return self._request("GET", "/trade-rules", None, headers, params)

    # ─── Promotion plans ──────────────────────────────

    def create_promotion_plan(self, payload: Dict[str, Any],
                              headers: Optional[Dict] = None):
        return self._request("POST", "/promotion-plans", payload, headers)

    def list_promotion_plans(self, headers: Optional[Dict] = None,
                             params: Optional[Dict] = None):
        return self._request("GET", "/promotion-plans", None, headers, params)

    # ─── Merchants ────────────────────────────────────

    def create_merchant(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/merchants", payload, headers)

    def get_merchant(self, merchant_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/merchants/{merchant_id}", None, headers)

    def list_merchants(self, headers: Optional[Dict] = None,
                       params: Optional[Dict] = None):
        return self._request("GET", "/merchants", None, headers, params)

    # ─── Licences ─────────────────────────────────────

    def file_license(self, merchant_id: str, payload: Dict[str, Any],
                     headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/merchants/{merchant_id}/licenses", payload, headers
        )

    def list_licenses(self, merchant_id: str, headers: Optional[Dict] = None,
                      params: Optional[Dict] = None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/licenses", None, headers, params
        )

    def verify_license(self, merchant_id: str, license_id: str,
                       payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"/merchants/{merchant_id}/licenses/{license_id}/verification",
            payload,
            headers,
        )

    # ─── Enrollment review and posture ────────────────

    def submit_enrollment(self, merchant_id: str, payload: Dict[str, Any],
                          headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/merchants/{merchant_id}/enrollment-submission", payload, headers
        )

    def decide_enrollment(self, merchant_id: str, payload: Dict[str, Any],
                          headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/merchants/{merchant_id}/enrollment-decision", payload, headers
        )

    def program_action(self, merchant_id: str, payload: Dict[str, Any],
                       headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/merchants/{merchant_id}/program-action", payload, headers
        )

    # ─── Promotion enrollments ────────────────────────

    def create_promotion_enrollment(self, merchant_id: str, payload: Dict[str, Any],
                                    headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/merchants/{merchant_id}/promotion-enrollments", payload, headers
        )

    def list_merchant_promotion_enrollments(self, merchant_id: str,
                                            headers: Optional[Dict] = None,
                                            params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/merchants/{merchant_id}/promotion-enrollments",
            None,
            headers,
            params,
        )

    def get_promotion_enrollment(self, enrollment_id: str,
                                 headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/promotion-enrollments/{enrollment_id}", None, headers
        )

    def list_promotion_enrollments(self, headers: Optional[Dict] = None,
                                   params: Optional[Dict] = None):
        return self._request("GET", "/promotion-enrollments", None, headers, params)

    # ─── Reserve adjustments ──────────────────────────

    def post_holdback_adjustment(self, merchant_id: str, payload: Dict[str, Any],
                                 headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/merchants/{merchant_id}/holdback-adjustments", payload, headers
        )

    # ─── Fraud alerts ─────────────────────────────────

    def create_fraud_alert(self, merchant_id: str, payload: Dict[str, Any],
                           headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/merchants/{merchant_id}/fraud-alerts", payload, headers
        )

    def list_fraud_alerts(self, merchant_id: str, headers: Optional[Dict] = None,
                          params: Optional[Dict] = None):
        return self._request(
            "GET", f"/merchants/{merchant_id}/fraud-alerts", None, headers, params
        )

    def investigate_fraud_alert(self, merchant_id: str, alert_id: str,
                                payload: Dict[str, Any],
                                headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"/merchants/{merchant_id}/fraud-alerts/{alert_id}/investigation",
            payload,
            headers,
        )

    # ─── Consumers ────────────────────────────────────

    def create_consumer(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/consumers", payload, headers)

    def get_consumer(self, consumer_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/consumers/{consumer_id}", None, headers)

    # ─── Credit applications ──────────────────────────

    def create_credit_application(self, payload: Dict[str, Any],
                                  headers: Optional[Dict] = None):
        return self._request("POST", "/credit-applications", payload, headers)

    def get_credit_application(self, application_id: str,
                               headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/credit-applications/{application_id}", None, headers
        )

    def list_credit_applications(self, headers: Optional[Dict] = None,
                                 params: Optional[Dict] = None):
        return self._request("GET", "/credit-applications", None, headers, params)

    def deliver_disclosure(self, application_id: str, payload: Dict[str, Any],
                           headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"/credit-applications/{application_id}/disclosure-delivery",
            payload,
            headers,
        )

    def acknowledge_disclosure(self, application_id: str, payload: Dict[str, Any],
                               headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"/credit-applications/{application_id}/disclosure-acknowledgement",
            payload,
            headers,
        )

    def accept_offer(self, application_id: str, payload: Optional[Dict] = None,
                     headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"/credit-applications/{application_id}/acceptance",
            payload or {},
            headers,
        )

    # ─── Loan accounts ────────────────────────────────

    def get_loan_account(self, loan_account_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/loan-accounts/{loan_account_id}", None, headers)

    def list_loan_accounts(self, headers: Optional[Dict] = None,
                           params: Optional[Dict] = None):
        return self._request("GET", "/loan-accounts", None, headers, params)

    # ─── Projects ─────────────────────────────────────

    def create_project(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/projects/{project_id}", None, headers)

    def list_projects(self, headers: Optional[Dict] = None,
                      params: Optional[Dict] = None):
        return self._request("GET", "/projects", None, headers, params)

    # ─── Milestones ───────────────────────────────────

    def create_milestone(self, project_id: str, payload: Dict[str, Any],
                         headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/projects/{project_id}/milestones", payload, headers
        )

    def list_milestones(self, project_id: str, headers: Optional[Dict] = None,
                        params: Optional[Dict] = None):
        return self._request(
            "GET", f"/projects/{project_id}/milestones", None, headers, params
        )

    def claim_milestone(self, project_id: str, milestone_id: str,
                        payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"/projects/{project_id}/milestones/{milestone_id}/claim",
            payload,
            headers,
        )

    def verify_milestone(self, project_id: str, milestone_id: str,
                         payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"/projects/{project_id}/milestones/{milestone_id}/verification",
            payload,
            headers,
        )

    def certify_completion(self, project_id: str, payload: Dict[str, Any],
                           headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/projects/{project_id}/completion-certification", payload, headers
        )

    # ─── Funding draws ────────────────────────────────

    def create_funding_draw(self, payload: Dict[str, Any],
                            headers: Optional[Dict] = None):
        return self._request("POST", "/funding-draws", payload, headers)

    def get_funding_draw(self, draw_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/funding-draws/{draw_id}", None, headers)

    def list_funding_draws(self, headers: Optional[Dict] = None,
                           params: Optional[Dict] = None):
        return self._request("GET", "/funding-draws", None, headers, params)

    def settle_funding_draw(self, draw_id: str, payload: Dict[str, Any],
                            headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/funding-draws/{draw_id}/settlement", payload, headers
        )

    def reverse_funding_draw(self, draw_id: str, payload: Dict[str, Any],
                             headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/funding-draws/{draw_id}/reversal", payload, headers
        )

    # ─── Dispute cases ────────────────────────────────

    def create_dispute_case(self, payload: Dict[str, Any],
                            headers: Optional[Dict] = None):
        return self._request("POST", "/dispute-cases", payload, headers)

    def get_dispute_case(self, case_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/dispute-cases/{case_id}", None, headers)

    def list_dispute_cases(self, headers: Optional[Dict] = None,
                           params: Optional[Dict] = None):
        return self._request("GET", "/dispute-cases", None, headers, params)

    def respond_to_dispute(self, case_id: str, payload: Dict[str, Any],
                           headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/dispute-cases/{case_id}/merchant-response", payload, headers
        )

    def resolve_dispute(self, case_id: str, payload: Dict[str, Any],
                        headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/dispute-cases/{case_id}/resolution", payload, headers
        )

    # ─── Payments ─────────────────────────────────────

    def create_payment(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, loan_account_id: str, headers: Optional[Dict] = None,
                      params: Optional[Dict] = None):
        return self._request(
            "GET", f"/loan-accounts/{loan_account_id}/payments", None, headers, params
        )
