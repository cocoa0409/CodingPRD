"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Producers (PRD §3.1) ---
    def create_producer(self, payload, headers):
        return self._request("POST", "/agency/producers", payload, headers)

    def list_producers(self, headers, params=None):
        return self._request("GET", "/agency/producers", headers=headers, params=params)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/agency/producers/{producer_id}", headers=headers)

    def reactivate_producer(self, producer_id, headers):
        return self._request(
            "POST", f"/agency/producers/{producer_id}/reactivate", {}, headers
        )

    def terminate_producer(self, producer_id, headers):
        return self._request(
            "POST", f"/agency/producers/{producer_id}/terminate", {}, headers
        )

    # --- Payouts (PRD §3.8) ---
    def create_payout(self, producer_id, payload, headers):
        return self._request(
            "POST", f"/agency/producers/{producer_id}/payouts", payload, headers
        )

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/agency/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/agency/payouts", headers=headers, params=params)

    def mark_payout_paid(self, payout_id, headers):
        return self._request("POST", f"/agency/payouts/{payout_id}/mark-paid", {}, headers)

    # --- Carriers (PRD §3.2, §3.4) ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/agency/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/agency/carriers/{carrier_id}", headers=headers)

    def remit_carrier(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"/agency/carriers/{carrier_id}/remit", payload, headers
        )

    # --- Products (PRD §3.2) ---
    def create_product(self, payload, headers):
        return self._request("POST", "/agency/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/agency/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/agency/products/{product_id}", headers=headers)

    # --- Commission schedules (PRD §3.2) ---
    def create_commission_schedule(self, product_id, payload, headers):
        return self._request(
            "POST",
            f"/agency/products/{product_id}/commission-schedules",
            payload,
            headers,
        )

    def list_commission_schedules(self, product_id, headers, params=None):
        return self._request(
            "GET",
            f"/agency/products/{product_id}/commission-schedules",
            headers=headers,
            params=params,
        )

    def get_commission_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/agency/commission-schedules/{schedule_id}", headers=headers
        )

    # --- Policies (PRD §3.3, §3.6) ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/agency/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/agency/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/agency/policies/{policy_id}", headers=headers)

    def bind_policy(self, policy_id, headers):
        return self._request("POST", f"/agency/policies/{policy_id}/bind", {}, headers)

    def cancel_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/agency/policies/{policy_id}/cancel", payload, headers
        )

    # --- Premium invoices (PRD §3.4) ---
    def list_policy_invoices(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/agency/policies/{policy_id}/invoices", headers=headers, params=params
        )

    def get_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/agency/premium-invoices/{invoice_id}", headers=headers
        )

    def record_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/agency/premium-invoices/{invoice_id}/payments", payload, headers
        )

    def reverse_payments(self, invoice_id, headers):
        return self._request(
            "POST", f"/agency/premium-invoices/{invoice_id}/reverse-payments", {}, headers
        )

    # --- Carrier statements (PRD §3.7) ---
    def create_carrier_statement(self, payload, headers):
        return self._request("POST", "/agency/carrier-statements", payload, headers)

    def list_carrier_statements(self, headers, params=None):
        return self._request(
            "GET", "/agency/carrier-statements", headers=headers, params=params
        )

    def get_carrier_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/agency/carrier-statements/{statement_id}", headers=headers
        )

    def start_reconciliation(self, statement_id, headers):
        return self._request(
            "POST",
            f"/agency/carrier-statements/{statement_id}/start-reconciliation",
            {},
            headers,
        )

    def dispute_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/agency/carrier-statements/{statement_id}/dispute", {}, headers
        )

    def resume_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/agency/carrier-statements/{statement_id}/resume", {}, headers
        )

    def close_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/agency/carrier-statements/{statement_id}/close", {}, headers
        )

    def waive_statement_line(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"/agency/carrier-statements/{statement_id}/waive-line",
            payload,
            headers,
        )

    # --- Commission entries (PRD §3.7) ---
    def list_commission_entries(self, headers, params=None):
        return self._request(
            "GET", "/agency/commission-entries", headers=headers, params=params
        )

    def get_commission_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/agency/commission-entries/{entry_id}", headers=headers
        )

    def resolve_variance(self, entry_id, payload, headers):
        return self._request(
            "POST",
            f"/agency/commission-entries/{entry_id}/resolve-variance",
            payload,
            headers,
        )

    # --- Chargebacks (PRD §3.6) ---
    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/agency/chargebacks", headers=headers, params=params)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/agency/chargebacks/{chargeback_id}", headers=headers)

    def record_recovery(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/agency/chargebacks/{chargeback_id}/recoveries", payload, headers
        )

    def write_off_chargeback(self, chargeback_id, headers):
        return self._request(
            "POST", f"/agency/chargebacks/{chargeback_id}/write-off", {}, headers
        )

    # --- Producer disclosures (PRD §3.3) ---
    def list_disclosures(self, headers, params=None):
        return self._request(
            "GET", "/agency/producer-disclosures", headers=headers, params=params
        )

    def get_disclosure(self, disclosure_id, headers):
        return self._request(
            "GET", f"/agency/producer-disclosures/{disclosure_id}", headers=headers
        )

    def deliver_disclosure(self, disclosure_id, headers):
        return self._request(
            "POST", f"/agency/producer-disclosures/{disclosure_id}/deliver", {}, headers
        )

    def acknowledge_disclosure(self, disclosure_id, headers):
        return self._request(
            "POST",
            f"/agency/producer-disclosures/{disclosure_id}/acknowledge",
            {},
            headers,
        )

    # --- 1099 tax forms (PRD §3.9) ---
    def generate_tax_forms(self, payload, headers):
        return self._request("POST", "/agency/tax-forms/generate", payload, headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/agency/tax-forms", headers=headers, params=params)

    def get_tax_form(self, form_id, headers):
        return self._request("GET", f"/agency/tax-forms/{form_id}", headers=headers)

    def finalize_tax_form(self, form_id, headers):
        return self._request(
            "POST", f"/agency/tax-forms/{form_id}/finalize", {}, headers
        )


api_client = ApiClient()
