"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/grain-drying/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/grain-drying/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/grain-drying/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/grain-drying/customers/{customer_id}", payload, headers)

    def get_customer_statement(self, customer_id, headers):
        return self._request("GET", f"/grain-drying/customers/{customer_id}/statement", headers=headers)

    # --- Grain lots ---
    def create_grain_lot(self, payload, headers):
        return self._request("POST", "/grain-drying/grain-lots", payload, headers)

    def list_grain_lots(self, headers, params=None):
        return self._request("GET", "/grain-drying/grain-lots", headers=headers, params=params)

    def get_grain_lot(self, lot_id, headers):
        return self._request("GET", f"/grain-drying/grain-lots/{lot_id}", headers=headers)

    def load_out_lot(self, lot_id, headers):
        return self._request("POST", f"/grain-drying/grain-lots/{lot_id}/load-out", {}, headers)

    def get_charge_preview(self, lot_id, headers):
        return self._request("GET", f"/grain-drying/grain-lots/{lot_id}/charge-preview", headers=headers)

    # --- Moisture tests ---
    def create_moisture_test(self, payload, headers):
        return self._request("POST", "/grain-drying/moisture-tests", payload, headers)

    def list_moisture_tests(self, headers, params=None):
        return self._request("GET", "/grain-drying/moisture-tests", headers=headers, params=params)

    def get_moisture_test(self, test_id, headers):
        return self._request("GET", f"/grain-drying/moisture-tests/{test_id}", headers=headers)

    def certify_moisture_test(self, test_id, headers):
        return self._request("POST", f"/grain-drying/moisture-tests/{test_id}/certify", {}, headers)

    def dispute_moisture_test(self, test_id, headers):
        return self._request("POST", f"/grain-drying/moisture-tests/{test_id}/dispute", {}, headers)

    # --- Charge schedules ---
    def create_charge_schedule(self, payload, headers):
        return self._request("POST", "/grain-drying/charge-schedules", payload, headers)

    def list_charge_schedules(self, headers, params=None):
        return self._request("GET", "/grain-drying/charge-schedules", headers=headers, params=params)

    def get_charge_schedule(self, schedule_id, headers):
        return self._request("GET", f"/grain-drying/charge-schedules/{schedule_id}", headers=headers)

    def update_charge_schedule(self, schedule_id, payload, headers):
        return self._request("PATCH", f"/grain-drying/charge-schedules/{schedule_id}", payload, headers)

    # --- Dryer units ---
    def create_dryer_unit(self, payload, headers):
        return self._request("POST", "/grain-drying/dryer-units", payload, headers)

    def get_dryer_unit(self, unit_id, headers):
        return self._request("GET", f"/grain-drying/dryer-units/{unit_id}", headers=headers)

    def get_capacity_calendar(self, unit_id, date, headers):
        return self._request(
            "GET", f"/grain-drying/dryer-units/{unit_id}/capacity-calendar",
            headers=headers, params={"date": date},
        )

    # --- Queue tickets ---
    def create_queue_ticket(self, payload, headers):
        return self._request("POST", "/grain-drying/queue-tickets", payload, headers)

    def list_queue_tickets(self, headers, params=None):
        return self._request("GET", "/grain-drying/queue-tickets", headers=headers, params=params)

    def get_queue_ticket(self, ticket_id, headers):
        return self._request("GET", f"/grain-drying/queue-tickets/{ticket_id}", headers=headers)

    def confirm_queue_ticket(self, ticket_id, headers):
        return self._request("POST", f"/grain-drying/queue-tickets/{ticket_id}/confirm", {}, headers)

    def cancel_queue_ticket(self, ticket_id, headers):
        return self._request("POST", f"/grain-drying/queue-tickets/{ticket_id}/cancel", {}, headers)

    def preempt_queue_ticket(self, ticket_id, headers):
        return self._request("POST", f"/grain-drying/queue-tickets/{ticket_id}/preempt", {}, headers)

    def requeue_queue_ticket(self, ticket_id, headers):
        return self._request("POST", f"/grain-drying/queue-tickets/{ticket_id}/requeue", {}, headers)

    # --- Dryer runs ---
    def create_dryer_run(self, payload, headers):
        return self._request("POST", "/grain-drying/dryer-runs", payload, headers)

    def list_dryer_runs(self, headers, params=None):
        return self._request("GET", "/grain-drying/dryer-runs", headers=headers, params=params)

    def get_dryer_run(self, run_id, headers):
        return self._request("GET", f"/grain-drying/dryer-runs/{run_id}", headers=headers)

    def start_dryer_run(self, run_id, payload, headers):
        return self._request("POST", f"/grain-drying/dryer-runs/{run_id}/start", payload, headers)

    def complete_dryer_run(self, run_id, payload, headers):
        return self._request("POST", f"/grain-drying/dryer-runs/{run_id}/complete", payload, headers)

    def abort_dryer_run(self, run_id, headers):
        return self._request("POST", f"/grain-drying/dryer-runs/{run_id}/abort", {}, headers)

    def cancel_dryer_run(self, run_id, headers):
        return self._request("POST", f"/grain-drying/dryer-runs/{run_id}/cancel", {}, headers)

    # --- Blend orders ---
    def create_blend_order(self, payload, headers):
        return self._request("POST", "/grain-drying/blend-orders", payload, headers)

    def list_blend_orders(self, headers, params=None):
        return self._request("GET", "/grain-drying/blend-orders", headers=headers, params=params)

    def get_blend_order(self, order_id, headers):
        return self._request("GET", f"/grain-drying/blend-orders/{order_id}", headers=headers)

    def approve_blend_order(self, order_id, headers):
        return self._request("POST", f"/grain-drying/blend-orders/{order_id}/approve", {}, headers)

    def execute_blend_order(self, order_id, headers):
        return self._request("POST", f"/grain-drying/blend-orders/{order_id}/execute", {}, headers)

    def cancel_blend_order(self, order_id, headers):
        return self._request("POST", f"/grain-drying/blend-orders/{order_id}/cancel", {}, headers)

    # --- Damage claims ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/grain-drying/damage-claims", payload, headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/grain-drying/damage-claims", headers=headers, params=params)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/grain-drying/damage-claims/{claim_id}", headers=headers)

    def review_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/grain-drying/damage-claims/{claim_id}/review", {}, headers)

    def assess_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/grain-drying/damage-claims/{claim_id}/assess", {}, headers)

    def deny_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/grain-drying/damage-claims/{claim_id}/deny", {}, headers)

    def appeal_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/grain-drying/damage-claims/{claim_id}/appeal", {}, headers)

    def withdraw_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/grain-drying/damage-claims/{claim_id}/withdraw", {}, headers)

    def pay_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/grain-drying/damage-claims/{claim_id}/pay", {}, headers)

    # --- Storage agreements ---
    def create_storage_agreement(self, payload, headers):
        return self._request("POST", "/grain-drying/storage-agreements", payload, headers)

    def list_storage_agreements(self, headers, params=None):
        return self._request("GET", "/grain-drying/storage-agreements", headers=headers, params=params)

    def get_storage_agreement(self, agreement_id, headers):
        return self._request("GET", f"/grain-drying/storage-agreements/{agreement_id}", headers=headers)

    def close_storage_agreement(self, agreement_id, headers):
        return self._request("POST", f"/grain-drying/storage-agreements/{agreement_id}/close", {}, headers)

    def declare_default_storage_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/grain-drying/storage-agreements/{agreement_id}/declare-default", {}, headers,
        )

    # --- Invoices & payments ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/grain-drying/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/grain-drying/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/grain-drying/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/grain-drying/invoices/{invoice_id}/issue", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/grain-drying/invoices/{invoice_id}/void", {}, headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/grain-drying/invoices/{invoice_id}/payments", payload, headers)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/grain-drying/invoices/{invoice_id}/payments", headers=headers, params=params,
        )

    def list_payments(self, headers, params=None):
        return self._request("GET", "/grain-drying/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/grain-drying/payments/{payment_id}", headers=headers)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/grain-drying/payments/{payment_id}/reverse", {}, headers)

    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/grain-drying/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
