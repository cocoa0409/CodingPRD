"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/rep-agency/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- principals ---
    def create_principal(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/principals", payload, headers)

    def list_principals(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rep-agency/principals", headers=headers, params=params)

    def get_principal(self, principal_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/principals/{principal_id}", headers=headers)

    def issue_termination_notice(self, principal_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/principals/{principal_id}/issue_termination_notice",
            {}, headers,
        )

    def rescind_termination_notice(self, principal_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/principals/{principal_id}/rescind_termination_notice",
            {}, headers,
        )

    # --- territory agreements ---
    def create_agreement(self, principal_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/principals/{principal_id}/agreements", payload, headers,
        )

    def list_agreements(self, principal_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/rep-agency/principals/{principal_id}/agreements",
            headers=headers, params=params,
        )

    def get_agreement(self, agreement_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/agreements/{agreement_id}/activate", {}, headers)

    def suspend_agreement(self, agreement_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/agreements/{agreement_id}/suspend", {}, headers)

    # --- rate schedules ---
    def create_rate_schedule(self, principal_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/principals/{principal_id}/rate-schedules", payload, headers,
        )

    def list_rate_schedules(self, principal_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/rep-agency/principals/{principal_id}/rate-schedules",
            headers=headers, params=params,
        )

    def get_rate_schedule(self, rate_schedule_id: str, headers: Dict):
        return self._request(
            "GET", f"/rep-agency/rate-schedules/{rate_schedule_id}", headers=headers,
        )

    # --- reps ---
    def create_rep(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/reps", payload, headers)

    def list_reps(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rep-agency/reps", headers=headers, params=params)

    def get_rep(self, rep_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/reps/{rep_id}", headers=headers)

    def post_rep_adjustment(self, rep_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/rep-agency/reps/{rep_id}/adjustments", payload, headers)

    # --- customers ---
    def create_customer(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/customers", payload, headers)

    def list_customers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rep-agency/customers", headers=headers, params=params)

    def get_customer(self, customer_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/customers/{customer_id}", headers=headers)

    # --- project registrations ---
    def create_registration(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/project-registrations", payload, headers)

    def list_registrations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rep-agency/project-registrations", headers=headers, params=params,
        )

    def get_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "GET", f"/rep-agency/project-registrations/{registration_id}", headers=headers,
        )

    def approve_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/project-registrations/{registration_id}/approve", {}, headers,
        )

    def reject_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/project-registrations/{registration_id}/reject", {}, headers,
        )

    def resubmit_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/project-registrations/{registration_id}/resubmit", {}, headers,
        )

    def renew_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/project-registrations/{registration_id}/renew", {}, headers,
        )

    def withdraw_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/project-registrations/{registration_id}/withdraw", {}, headers,
        )

    # --- orders ---
    def create_order(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/orders", payload, headers)

    def list_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rep-agency/orders", headers=headers, params=params)

    def get_order(self, order_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/orders/{order_id}", headers=headers)

    def ship_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/orders/{order_id}/ship", {}, headers)

    def invoice_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/orders/{order_id}/invoice", {}, headers)

    def mark_order_paid(self, order_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/orders/{order_id}/mark_paid", {}, headers)

    def cancel_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/orders/{order_id}/cancel", {}, headers)

    def put_order_splits(self, order_id: str, payload: Dict, headers: Dict):
        return self._request("PUT", f"/rep-agency/orders/{order_id}/splits", payload, headers)

    # --- order splits ---
    def list_order_splits(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rep-agency/order-splits", headers=headers, params=params)

    def get_order_split(self, order_split_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/order-splits/{order_split_id}", headers=headers)

    # --- return authorizations ---
    def create_rma(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/rmas", payload, headers)

    def list_rmas(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rep-agency/rmas", headers=headers, params=params)

    def get_rma(self, rma_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/rmas/{rma_id}", headers=headers)

    def approve_rma(self, rma_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/rmas/{rma_id}/approve", {}, headers)

    def reject_rma(self, rma_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/rmas/{rma_id}/reject", {}, headers)

    def receive_rma(self, rma_id: str, headers: Dict):
        return self._request("POST", f"/rep-agency/rmas/{rma_id}/receive", {}, headers)

    # --- commission ledger ---
    def list_commission_entries(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rep-agency/commission-entries", headers=headers, params=params,
        )

    def get_commission_entry(self, entry_id: str, headers: Dict):
        return self._request(
            "GET", f"/rep-agency/commission-entries/{entry_id}", headers=headers,
        )

    # --- commission statements ---
    def create_statement(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/statements", payload, headers)

    def list_statements(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rep-agency/statements", headers=headers, params=params)

    def get_statement(self, statement_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/statements/{statement_id}", headers=headers)

    def start_reconciliation(self, statement_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/statements/{statement_id}/start_reconciliation", {}, headers,
        )

    def accept_variance(self, statement_id: str, line_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/statements/{statement_id}/lines/{line_id}/accept_variance",
            {}, headers,
        )

    def dispute_statement_line(self, statement_id: str, line_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/statements/{statement_id}/lines/{line_id}/dispute",
            payload, headers,
        )

    def respond_dispute(self, statement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/statements/{statement_id}/respond_dispute", payload, headers,
        )

    def settle_statement(self, statement_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/statements/{statement_id}/settle", {}, headers,
        )

    # --- sample units & checkouts ---
    def create_sample_unit(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/sample-units", payload, headers)

    def list_sample_units(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rep-agency/sample-units", headers=headers, params=params)

    def get_sample_unit(self, sample_unit_id: str, headers: Dict):
        return self._request("GET", f"/rep-agency/sample-units/{sample_unit_id}", headers=headers)

    def create_sample_checkout(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rep-agency/sample-checkouts", payload, headers)

    def list_sample_checkouts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rep-agency/sample-checkouts", headers=headers, params=params,
        )

    def get_sample_checkout(self, checkout_id: str, headers: Dict):
        return self._request(
            "GET", f"/rep-agency/sample-checkouts/{checkout_id}", headers=headers,
        )

    def return_sample_checkout(self, checkout_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/sample-checkouts/{checkout_id}/return", payload, headers,
        )

    def convert_sample_checkout(self, checkout_id: str, headers: Dict):
        return self._request(
            "POST", f"/rep-agency/sample-checkouts/{checkout_id}/convert", {}, headers,
        )


api_client = ApiClient()
