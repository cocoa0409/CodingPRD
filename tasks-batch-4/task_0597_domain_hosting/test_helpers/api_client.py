"""API client: one method per endpoint defined in the PRD (all under the /registrar prefix)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/registrar"


class ApiClient(GenericApiClient):
    # ─── Accounts ──────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def set_payment_method(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/payment-method", payload, headers
        )

    def grant_credit(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/credits", payload, headers
        )

    def list_ledger_entries(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/accounts/{account_id}/ledger-entries", params, headers
        )

    def reinstate_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/reinstate", payload, headers
        )

    # ─── Domain search / registration / WHOIS ──────────────────────────────
    def domain_search(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/domain-search", params, headers)

    def create_domain(self, payload, headers):
        return self._request("POST", f"{PREFIX}/domains", payload, headers)

    def get_domain(self, domain_id, headers):
        return self._request("GET", f"{PREFIX}/domains/{domain_id}", headers=headers)

    def list_domains(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/domains", params, headers)

    def update_domain_settings(self, domain_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/domains/{domain_id}/settings", payload, headers
        )

    def get_renewal_quote(self, domain_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/domains/{domain_id}/renewal-quote", params, headers
        )

    def renew_domain(self, domain_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/domains/{domain_id}/renew", payload, headers
        )

    def reinstate_domain(self, domain_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/domains/{domain_id}/reinstate", payload, headers
        )

    # ─── DNS management ────────────────────────────────────────────────────
    def create_dns_record(self, domain_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/domains/{domain_id}/dns-records", payload, headers
        )

    def list_dns_records(self, domain_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/domains/{domain_id}/dns-records", params, headers
        )

    def delete_dns_record(self, record_id, headers):
        return self._request(
            "DELETE", f"{PREFIX}/dns-records/{record_id}", headers=headers
        )

    # ─── Transfers ─────────────────────────────────────────────────────────
    def create_transfer_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfer-requests", payload, headers)

    def get_transfer_request(self, transfer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_id}", headers=headers
        )

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transfer-requests", params, headers)

    def submit_transfer_request(self, transfer_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transfer-requests/{transfer_id}/submit", {}, headers
        )

    def registry_response(self, transfer_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-requests/{transfer_id}/registry-response",
            payload,
            headers,
        )

    def retry_transfer_request(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transfer-requests/{transfer_id}/retry", payload, headers
        )

    # ─── Hosting ───────────────────────────────────────────────────────────
    def create_hosting_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hosting-plans", payload, headers)

    def create_hosting_subscription(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hosting-subscriptions", payload, headers
        )

    def get_hosting_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/hosting-subscriptions/{subscription_id}", headers=headers
        )

    def list_hosting_subscriptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hosting-subscriptions", params, headers)

    def create_usage_record(self, subscription_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/hosting-subscriptions/{subscription_id}/usage-records",
            payload,
            headers,
        )

    def list_usage_records(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/hosting-subscriptions/{subscription_id}/usage-records",
            params,
            headers,
        )

    def create_billing_period(self, subscription_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/hosting-subscriptions/{subscription_id}/billing-periods",
            payload,
            headers,
        )

    def list_billing_periods(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/hosting-subscriptions/{subscription_id}/billing-periods",
            params,
            headers,
        )

    def close_billing_period(self, period_id, headers):
        return self._request(
            "POST", f"{PREFIX}/billing-periods/{period_id}/close", {}, headers
        )

    # ─── SSL & email add-ons ───────────────────────────────────────────────
    def create_add_on(self, payload, headers):
        return self._request("POST", f"{PREFIX}/add-ons", payload, headers)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"{PREFIX}/add-ons/{add_on_id}", headers=headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/add-ons", params, headers)

    def validate_add_on(self, add_on_id, headers):
        return self._request(
            "POST", f"{PREFIX}/add-ons/{add_on_id}/validate", {}, headers
        )

    def delete_add_on(self, add_on_id, headers):
        return self._request(
            "DELETE", f"{PREFIX}/add-ons/{add_on_id}", headers=headers
        )

    # ─── Billing & upsell ──────────────────────────────────────────────────
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", params, headers)

    def list_invoice_line_items(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/invoices/{invoice_id}/line-items", params, headers
        )

    def apply_promo(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/apply-promo", payload, headers
        )

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/pay", payload, headers
        )

    def refund_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/refund", payload, headers
        )

    def create_promo_code(self, payload, headers):
        return self._request("POST", f"{PREFIX}/promo-codes", payload, headers)

    # ─── Abuse / suspension ────────────────────────────────────────────────
    def create_abuse_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/abuse-reports", payload, headers)

    def get_abuse_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/abuse-reports/{report_id}", headers=headers
        )

    def list_abuse_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/abuse-reports", params, headers)

    def review_abuse_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/abuse-reports/{report_id}/review", {}, headers
        )

    def uphold_abuse_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/abuse-reports/{report_id}/uphold", payload, headers
        )

    def dismiss_abuse_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/abuse-reports/{report_id}/dismiss", payload, headers
        )

    # ─── System (logical clock + sweep) ────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    def run_expiry_sweep(self, headers):
        return self._request("POST", f"{PREFIX}/_ops/run-expiry-sweep", {}, headers)


api_client = ApiClient()
