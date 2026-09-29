"""API client: one method per endpoint defined in the PRD (§4)."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the 51 endpoints of the retention API."""

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------
    def create_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plans", payload, headers=headers)

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/plans", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Save-offer templates
    # ------------------------------------------------------------------
    def create_save_offer_template(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/save-offer-templates", payload, headers=headers)

    def get_save_offer_template(self, template_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/save-offer-templates/{template_id}", headers=headers)

    # ------------------------------------------------------------------
    # Subscribers
    # ------------------------------------------------------------------
    def create_subscriber(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/subscribers", payload, headers=headers)

    def update_subscriber(self, subscriber_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/subscribers/{subscriber_id}", payload, headers=headers)

    def get_subscriber(self, subscriber_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    # ------------------------------------------------------------------
    # Payment methods
    # ------------------------------------------------------------------
    def create_payment_method(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/payment-methods", payload, headers=headers)

    def submit_updater_result(self, payment_method_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/payment-methods/{payment_method_id}/updater-result",
                             payload, headers=headers)

    def get_payment_method(self, payment_method_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/payment-methods/{payment_method_id}", headers=headers)

    def list_payment_methods(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/payment-methods", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------
    def create_subscription(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/subscriptions", payload, headers=headers)

    def get_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def create_modification(self, subscription_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/subscriptions/{subscription_id}/modifications",
                             payload, headers=headers)

    def run_renewal(self, subscription_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/subscriptions/{subscription_id}/renewals",
                             {}, headers=headers)

    def list_subscription_compliance_notices(self, subscription_id: str, headers: Dict[str, str],
                                             params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/subscriptions/{subscription_id}/compliance-notices",
                             headers=headers, params=params)

    def schedule_compliance_notice(self, subscription_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", f"/subscriptions/{subscription_id}/compliance-notices",
                             payload, headers=headers)

    def send_compliance_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/compliance-notices/{notice_id}/send", {}, headers=headers)

    # ------------------------------------------------------------------
    # Subscription modifications
    # ------------------------------------------------------------------
    def reverse_modification(self, modification_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/subscription-modifications/{modification_id}/reverse",
                             payload if payload is not None else {}, headers=headers)

    def get_modification(self, modification_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/subscription-modifications/{modification_id}",
                             headers=headers)

    def list_modifications(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/subscription-modifications", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Invoices and dunning
    # ------------------------------------------------------------------
    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def create_dunning_attempt(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/invoices/{invoice_id}/dunning-attempts",
                             {}, headers=headers)

    def get_dunning_attempt(self, attempt_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dunning-attempts/{attempt_id}", headers=headers)

    def list_dunning_attempts(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/dunning-attempts", headers=headers, params=params)

    def simulate_payment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_payments/simulate", payload, headers=headers)

    # ------------------------------------------------------------------
    # Cancellation flow
    # ------------------------------------------------------------------
    def create_cancellation_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cancellation-sessions", payload, headers=headers)

    def get_cancellation_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cancellation-sessions/{session_id}", headers=headers)

    def list_cancellation_sessions(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/cancellation-sessions", headers=headers, params=params)

    def capture_reason(self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/cancellation-sessions/{session_id}/reason",
                             payload, headers=headers)

    def present_offers(self, session_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/cancellation-sessions/{session_id}/present-offers",
                             {}, headers=headers)

    def complete_cancellation(self, session_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/cancellation-sessions/{session_id}/complete",
                             payload, headers=headers)

    # ------------------------------------------------------------------
    # Save-offer grants
    # ------------------------------------------------------------------
    def get_save_offer_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/save-offer-grants/{grant_id}", headers=headers)

    def list_save_offer_grants(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/save-offer-grants", headers=headers, params=params)

    def accept_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/save-offer-grants/{grant_id}/accept", {}, headers=headers)

    def decline_grant(self, grant_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/save-offer-grants/{grant_id}/decline",
                             payload if payload is not None else {}, headers=headers)

    def decide_margin_exception(self, grant_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/save-offer-grants/{grant_id}/margin-exception",
                             payload, headers=headers)

    # ------------------------------------------------------------------
    # Win-back
    # ------------------------------------------------------------------
    def create_winback_campaign(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/winback-campaigns", payload, headers=headers)

    def launch_winback_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/winback-campaigns/{campaign_id}/launch",
                             {}, headers=headers)

    def get_winback_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/winback-campaigns/{campaign_id}", headers=headers)

    def create_winback_target(self, campaign_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/winback-campaigns/{campaign_id}/targets",
                             payload, headers=headers)

    def send_winback_target(self, target_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/winback-targets/{target_id}/send", {}, headers=headers)

    def reevaluate_winback_target(self, target_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/winback-targets/{target_id}/reevaluate",
                             {}, headers=headers)

    def get_winback_target(self, target_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/winback-targets/{target_id}", headers=headers)

    def list_winback_targets(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/winback-targets", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    def create_cohort_snapshot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/retention-cohort-snapshots", payload, headers=headers)

    def get_cohort_snapshot(self, snapshot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/retention-cohort-snapshots/{snapshot_id}", headers=headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
