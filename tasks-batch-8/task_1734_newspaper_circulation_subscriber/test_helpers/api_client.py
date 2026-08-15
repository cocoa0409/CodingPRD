"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ops / logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_daily_cycle(self, headers: Dict):
        return self._request("POST", "/api/ops/run-daily-cycle", {}, headers)

    # --- subscription plans ---
    def create_subscription_plan(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/subscription-plans", payload, headers)

    def list_subscription_plans(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/subscription-plans", headers=headers, params=params)

    def get_subscription_plan(self, plan_id: str, headers: Dict):
        return self._request("GET", f"/api/subscription-plans/{plan_id}", headers=headers)

    def retire_subscription_plan(self, plan_id: str, headers: Dict):
        return self._request("POST", f"/api/subscription-plans/{plan_id}/retire", {}, headers)

    # --- subscribers ---
    def create_subscriber(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/subscribers", payload, headers)

    def list_subscribers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/subscribers", headers=headers, params=params)

    def get_subscriber(self, subscriber_id: str, headers: Dict):
        return self._request("GET", f"/api/subscribers/{subscriber_id}", headers=headers)

    def close_subscriber(self, subscriber_id: str, headers: Dict):
        return self._request("POST", f"/api/subscribers/{subscriber_id}/close", {}, headers)

    # --- subscriptions ---
    def create_subscription(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def list_subscriptions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id: str, headers: Dict):
        return self._request("GET", f"/api/subscriptions/{subscription_id}", headers=headers)

    def plan_change_subscription(self, subscription_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/plan-change", payload, headers
        )

    def cancel_subscription(self, subscription_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/cancel", payload, headers
        )

    # --- vacation holds ---
    def create_vacation_hold(self, subscription_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/vacation-holds", payload, headers
        )

    def list_vacation_holds(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/vacation-holds", headers=headers, params=params)

    def get_vacation_hold(self, hold_id: str, headers: Dict):
        return self._request("GET", f"/api/vacation-holds/{hold_id}", headers=headers)

    def cancel_vacation_hold(self, hold_id: str, headers: Dict):
        return self._request("POST", f"/api/vacation-holds/{hold_id}/cancel", {}, headers)

    def resume_vacation_hold(self, hold_id: str, headers: Dict):
        return self._request("POST", f"/api/vacation-holds/{hold_id}/resume", {}, headers)

    # --- complaints ---
    def create_complaint(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/complaints", payload, headers)

    def list_complaints(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id: str, headers: Dict):
        return self._request("GET", f"/api/complaints/{complaint_id}", headers=headers)

    def credit_complaint(self, complaint_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/complaints/{complaint_id}/credit", payload, headers
        )

    def deny_complaint(self, complaint_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/complaints/{complaint_id}/deny", payload, headers
        )

    # --- credit memos ---
    def create_credit_memo(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/credit-memos", payload, headers)

    def list_credit_memos(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/credit-memos", headers=headers, params=params)

    def get_credit_memo(self, memo_id: str, headers: Dict):
        return self._request("GET", f"/api/credit-memos/{memo_id}", headers=headers)

    def void_credit_memo(self, memo_id: str, headers: Dict):
        return self._request("POST", f"/api/credit-memos/{memo_id}/void", {}, headers)

    # --- save offers ---
    def create_save_offer(self, subscription_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/save-offers", payload, headers
        )

    def list_save_offers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/save-offers", headers=headers, params=params)

    def get_save_offer(self, offer_id: str, headers: Dict):
        return self._request("GET", f"/api/save-offers/{offer_id}", headers=headers)

    def accept_save_offer(self, offer_id: str, headers: Dict):
        return self._request("POST", f"/api/save-offers/{offer_id}/accept", {}, headers)

    def decline_save_offer(self, offer_id: str, headers: Dict):
        return self._request("POST", f"/api/save-offers/{offer_id}/decline", {}, headers)

    # --- routes ---
    def create_route(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/routes", payload, headers)

    def list_routes(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/routes", headers=headers, params=params)

    def get_route(self, route_id: str, headers: Dict):
        return self._request("GET", f"/api/routes/{route_id}", headers=headers)

    def update_route(self, route_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/api/routes/{route_id}", payload, headers)

    # --- carriers ---
    def create_carrier(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/carriers", payload, headers)

    def list_carriers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id: str, headers: Dict):
        return self._request("GET", f"/api/carriers/{carrier_id}", headers=headers)

    def get_carrier_settlement(self, carrier_id: str, week_start_date: str, headers: Dict):
        return self._request(
            "GET",
            f"/api/carriers/{carrier_id}/settlement",
            headers=headers,
            params={"week_start_date": week_start_date},
        )

    # --- route assignments ---
    def create_route_assignment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/route-assignments", payload, headers)

    def list_route_assignments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/route-assignments", headers=headers, params=params)

    def get_route_assignment(self, assignment_id: str, headers: Dict):
        return self._request("GET", f"/api/route-assignments/{assignment_id}", headers=headers)

    def end_route_assignment(self, assignment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/route-assignments/{assignment_id}/end", payload, headers
        )

    # --- rack locations ---
    def create_rack_location(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/rack-locations", payload, headers)

    def list_rack_locations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/rack-locations", headers=headers, params=params)

    def get_rack_location(self, rack_id: str, headers: Dict):
        return self._request("GET", f"/api/rack-locations/{rack_id}", headers=headers)

    def update_rack_location(self, rack_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/api/rack-locations/{rack_id}", payload, headers)

    # --- rack sales reports ---
    def create_rack_sales_report(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/rack-sales-reports", payload, headers)

    def list_rack_sales_reports(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/rack-sales-reports", headers=headers, params=params)

    def get_rack_sales_report(self, report_id: str, headers: Dict):
        return self._request("GET", f"/api/rack-sales-reports/{report_id}", headers=headers)

    def update_rack_sales_report(self, report_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/api/rack-sales-reports/{report_id}", payload, headers)

    def submit_rack_sales_report(self, report_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/rack-sales-reports/{report_id}/submit", {}, headers
        )

    def reconcile_rack_sales_report(self, report_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/rack-sales-reports/{report_id}/reconcile", {}, headers
        )

    def dispute_rack_sales_report(self, report_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/api/rack-sales-reports/{report_id}/dispute", payload or {}, headers
        )

    # --- payments ---
    def create_payment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/payments", payload, headers)

    def list_payments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/payments", headers=headers, params=params)

    def get_payment(self, payment_id: str, headers: Dict):
        return self._request("GET", f"/api/payments/{payment_id}", headers=headers)

    def mark_payment_cleared(self, payment_id: str, headers: Dict):
        return self._request("POST", f"/api/payments/{payment_id}/mark-cleared", {}, headers)

    def mark_payment_failed(self, payment_id: str, headers: Dict):
        return self._request("POST", f"/api/payments/{payment_id}/mark-failed", {}, headers)

    def reverse_payment(self, payment_id: str, headers: Dict):
        return self._request("POST", f"/api/payments/{payment_id}/reverse", {}, headers)

    # --- billing charges ---
    def list_billing_charges(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/billing-charges", headers=headers, params=params)

    def get_billing_charge(self, charge_id: str, headers: Dict):
        return self._request("GET", f"/api/billing-charges/{charge_id}", headers=headers)

    def write_off_billing_charge(self, charge_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/billing-charges/{charge_id}/write-off", {}, headers
        )

    # --- audit reports ---
    def create_audit_report(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/audit-reports", payload, headers)

    def list_audit_reports(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/audit-reports", headers=headers, params=params)

    def get_audit_report(self, report_id: str, headers: Dict):
        return self._request("GET", f"/api/audit-reports/{report_id}", headers=headers)

    def certify_audit_report(self, report_id: str, headers: Dict):
        return self._request("POST", f"/api/audit-reports/{report_id}/certify", {}, headers)

    def submit_audit_report(self, report_id: str, headers: Dict):
        return self._request("POST", f"/api/audit-reports/{report_id}/submit", {}, headers)


api_client = ApiClient()
