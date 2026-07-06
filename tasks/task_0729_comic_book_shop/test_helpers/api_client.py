"""API client: one method per endpoint defined in the PRD.

All paths carry the /api prefix. The logical clock endpoint lives at
/api/_clock/set_current_utc.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def create_credit_adjustment(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/credit-adjustments", payload, headers,
        )

    def ban_customer(self, customer_id, headers):
        return self._request("POST", f"/api/customers/{customer_id}/ban", {}, headers)

    # ---- CreditTransaction (read) ----
    def get_credit_transaction(self, txn_id, headers):
        return self._request("GET", f"/api/credit-transactions/{txn_id}", headers=headers)

    def list_credit_transactions(self, headers, params=None):
        return self._request("GET", "/api/credit-transactions", headers=headers, params=params)

    # ---- ComicSeries ----
    def create_comic_series(self, payload, headers):
        return self._request("POST", "/api/comic-series", payload, headers)

    def get_comic_series(self, series_id, headers):
        return self._request("GET", f"/api/comic-series/{series_id}", headers=headers)

    def list_comic_series(self, headers, params=None):
        return self._request("GET", "/api/comic-series", headers=headers, params=params)

    def discontinue_comic_series(self, series_id, headers):
        return self._request(
            "POST", f"/api/comic-series/{series_id}/discontinue", {}, headers,
        )

    # ---- ComicIssue ----
    def create_comic_issue(self, payload, headers):
        return self._request("POST", "/api/comic-issues", payload, headers)

    def get_comic_issue(self, issue_id, headers):
        return self._request("GET", f"/api/comic-issues/{issue_id}", headers=headers)

    def list_comic_issues(self, headers, params=None):
        return self._request("GET", "/api/comic-issues", headers=headers, params=params)

    def transition_comic_issue(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/api/comic-issues/{issue_id}/transition", payload, headers,
        )

    def run_allocation(self, issue_id, headers):
        return self._request(
            "POST", f"/api/comic-issues/{issue_id}/run-allocation", {}, headers,
        )

    # ---- PullSubscription ----
    def create_pull_subscription(self, payload, headers):
        return self._request("POST", "/api/pull-subscriptions", payload, headers)

    def get_pull_subscription(self, sub_id, headers):
        return self._request("GET", f"/api/pull-subscriptions/{sub_id}", headers=headers)

    def list_pull_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/pull-subscriptions", headers=headers, params=params)

    def transition_pull_subscription(self, sub_id, payload, headers):
        return self._request(
            "POST", f"/api/pull-subscriptions/{sub_id}/transition", payload, headers,
        )

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/api/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/api/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/api/reservations", headers=headers, params=params)

    def transition_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/api/reservations/{reservation_id}/transition", payload, headers,
        )

    # ---- PreOrder ----
    def create_pre_order(self, payload, headers):
        return self._request("POST", "/api/pre-orders", payload, headers)

    def get_pre_order(self, pre_order_id, headers):
        return self._request("GET", f"/api/pre-orders/{pre_order_id}", headers=headers)

    def list_pre_orders(self, headers, params=None):
        return self._request("GET", "/api/pre-orders", headers=headers, params=params)

    def transition_pre_order(self, pre_order_id, payload, headers):
        return self._request(
            "POST", f"/api/pre-orders/{pre_order_id}/transition", payload, headers,
        )

    # ---- BackIssue ----
    def create_back_issue(self, payload, headers):
        return self._request("POST", "/api/back-issues", payload, headers)

    def get_back_issue(self, back_issue_id, headers):
        return self._request("GET", f"/api/back-issues/{back_issue_id}", headers=headers)

    def list_back_issues(self, headers, params=None):
        return self._request("GET", "/api/back-issues", headers=headers, params=params)

    def transition_back_issue(self, back_issue_id, payload, headers):
        return self._request(
            "POST", f"/api/back-issues/{back_issue_id}/transition", payload, headers,
        )

    # ---- GradingSubmission ----
    def create_grading_submission(self, payload, headers):
        return self._request("POST", "/api/grading-submissions", payload, headers)

    def get_grading_submission(self, gs_id, headers):
        return self._request("GET", f"/api/grading-submissions/{gs_id}", headers=headers)

    def list_grading_submissions(self, headers, params=None):
        return self._request("GET", "/api/grading-submissions", headers=headers, params=params)

    def transition_grading_submission(self, gs_id, payload, headers):
        return self._request(
            "POST", f"/api/grading-submissions/{gs_id}/transition", payload, headers,
        )

    # ---- Event ----
    def create_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/api/events", headers=headers, params=params)

    def transition_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/api/events/{event_id}/transition", payload, headers,
        )

    # ---- EventRegistration ----
    def create_event_registration(self, payload, headers):
        return self._request("POST", "/api/event-registrations", payload, headers)

    def get_event_registration(self, reg_id, headers):
        return self._request("GET", f"/api/event-registrations/{reg_id}", headers=headers)

    def list_event_registrations(self, headers, params=None):
        return self._request("GET", "/api/event-registrations", headers=headers, params=params)

    def transition_event_registration(self, reg_id, payload, headers):
        return self._request(
            "POST", f"/api/event-registrations/{reg_id}/transition", payload, headers,
        )

    # ---- Consignment ----
    def create_consignment(self, payload, headers):
        return self._request("POST", "/api/consignments", payload, headers)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/api/consignments/{consignment_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/api/consignments", headers=headers, params=params)

    def transition_consignment(self, consignment_id, payload, headers):
        return self._request(
            "POST", f"/api/consignments/{consignment_id}/transition", payload, headers,
        )

    # ---- Checkout ----
    def checkout(self, payload, headers):
        return self._request("POST", "/api/checkout", payload, headers)


api_client = ApiClient()
