"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the ``/paywall`` prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/paywall"


class ApiClient(GenericApiClient):
    """Endpoint methods for the News Paywall & Digital Subscription API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        """POST /paywall/_clock/set_current_utc — available to all five roles."""
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------------
    # Offer plans and the price ladder
    # ------------------------------------------------------------------

    def create_offer_plan(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/offer-plans", payload, headers)

    def activate_offer_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/offer-plans/{plan_id}/activate", {}, headers
        )

    def schedule_price_change(
        self, plan_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/offer-plans/{plan_id}/price-change", payload, headers
        )

    def dispatch_price_change_notices(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/offer-plans/{plan_id}/price-change/notices",
            {},
            headers,
        )

    def apply_price_change(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/offer-plans/{plan_id}/price-change/apply", {}, headers
        )

    def get_offer_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/offer-plans/{plan_id}", headers=headers)

    def list_offer_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/offer-plans", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Paywall rules, articles and the access decision
    # ------------------------------------------------------------------

    def create_paywall_rule(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/paywall-rules", payload, headers)

    def get_paywall_rule(self, rule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/paywall-rules/{rule_id}", headers=headers)

    def list_paywall_rules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/paywall-rules", headers=headers, params=params
        )

    def create_article(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/articles", payload, headers)

    def get_article(self, article_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/articles/{article_id}", headers=headers)

    def create_access_decision(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/access-decisions", payload, headers)

    # ------------------------------------------------------------------
    # Readers, cards and events
    # ------------------------------------------------------------------

    def create_reader(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/readers", payload, headers)

    def get_reader(self, reader_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/readers/{reader_id}", headers=headers)

    def replace_reader_card(
        self, reader_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/readers/{reader_id}/card", payload, headers
        )

    def create_reader_event(
        self, reader_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/readers/{reader_id}/events", payload, headers
        )

    def list_reader_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/reader-events", headers=headers, params=params
        )

    def get_reader_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/reader-events/{event_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Subscriptions and invoices
    # ------------------------------------------------------------------

    def create_subscription(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def get_subscription(self, subscription_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/subscriptions", headers=headers, params=params
        )

    def list_subscription_invoices(
        self, subscription_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/subscriptions/{subscription_id}/invoices",
            headers=headers,
            params=params,
        )

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def create_payment_attempt(
        self, invoice_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/payment-attempts", payload, headers
        )

    def list_payment_attempts(
        self, invoice_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/invoices/{invoice_id}/payment-attempts",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Holds
    # ------------------------------------------------------------------

    def create_hold(self, subscription_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/holds", payload, headers
        )

    def list_holds(
        self, subscription_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/subscriptions/{subscription_id}/holds",
            headers=headers,
            params=params,
        )

    def get_hold(self, hold_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/holds/{hold_id}", headers=headers)

    def release_hold(self, hold_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/holds/{hold_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Cancellation flow and save offers
    # ------------------------------------------------------------------

    def create_cancellation_request(
        self, subscription_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/subscriptions/{subscription_id}/cancellation-requests",
            payload,
            headers,
        )

    def list_cancellation_requests(
        self, subscription_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/subscriptions/{subscription_id}/cancellation-requests",
            headers=headers,
            params=params,
        )

    def get_cancellation_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/cancellation-requests/{request_id}", headers=headers
        )

    def create_save_offer(
        self, request_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/cancellation-requests/{request_id}/save-offers",
            payload,
            headers,
        )

    def list_save_offers(
        self, request_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/cancellation-requests/{request_id}/save-offers",
            headers=headers,
            params=params,
        )

    def get_save_offer(self, offer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/save-offers/{offer_id}", headers=headers)

    def decide_save_offer(self, offer_id: str, decision: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/save-offers/{offer_id}/decision",
            {"decision": decision},
            headers,
        )

    def confirm_cancellation(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/cancellation-requests/{request_id}/confirm",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Institutional access
    # ------------------------------------------------------------------

    def create_group_account(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/group-accounts", payload, headers)

    def get_group_account(self, group_account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/group-accounts/{group_account_id}", headers=headers
        )

    def list_group_accounts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/group-accounts", headers=headers, params=params
        )

    def create_seat(
        self, group_account_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/group-accounts/{group_account_id}/seats",
            payload,
            headers,
        )

    def get_seat(self, seat_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/seats/{seat_id}", headers=headers)

    def list_seats(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/seats", headers=headers, params=params)

    def activate_seat(self, seat_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/seats/{seat_id}/activate", {}, headers)

    def reclaim_seat(self, seat_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/seats/{seat_id}/reclaim", {}, headers)

    # ------------------------------------------------------------------
    # The nightly billing run
    # ------------------------------------------------------------------

    def create_billing_run(self, scope: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/billing-runs", {"scope": scope}, headers
        )

    def create_billing_run_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/billing-runs", payload, headers)


api_client = ApiClient()
