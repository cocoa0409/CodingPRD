"""API client: one method per Renters Insurance API endpoint.

Subclasses the framework GenericApiClient; the base _request() handles
transport, JSON bodies, and query params.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Policyholders ----
    def create_policyholder(self, payload, headers):
        return self._request("POST", "/policyholders", payload, headers)

    def get_policyholder(self, policyholder_id, headers):
        return self._request("GET", f"/policyholders/{policyholder_id}", headers=headers)

    def list_policyholders(self, headers, params=None):
        return self._request("GET", "/policyholders", headers=headers, params=params)

    # ---- Bundles ----
    def create_bundle(self, payload, headers):
        return self._request("POST", "/bundles", payload, headers)

    def get_bundle(self, bundle_id, headers):
        return self._request("GET", f"/bundles/{bundle_id}", headers=headers)

    def list_bundles(self, headers, params=None):
        return self._request("GET", "/bundles", headers=headers, params=params)

    # ---- Policies ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def add_coverage_line(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/coverage-lines", payload, headers
        )

    def list_coverage_lines(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/policies/{policy_id}/coverage-lines", headers=headers, params=params
        )

    def add_scheduled_item(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/scheduled-items", payload, headers
        )

    def list_scheduled_items(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/policies/{policy_id}/scheduled-items", headers=headers, params=params
        )

    def add_additional_insured(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/additional-insureds", payload, headers
        )

    def list_additional_insureds(self, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/policies/{policy_id}/additional-insureds",
            headers=headers,
            params=params,
        )

    def issue_policy(self, policy_id, headers, payload=None):
        return self._request("POST", f"/policies/{policy_id}/issue", payload or {}, headers)

    def cancel_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", payload, headers)

    def reinstate_policy(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/policies/{policy_id}/reinstate", payload or {}, headers
        )

    def process_billing(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/policies/{policy_id}/process-billing", payload or {}, headers
        )

    # ---- Claims ----
    def file_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def add_claim_item(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/items", payload, headers)

    def get_claim_item(self, claim_item_id, headers):
        return self._request("GET", f"/claim-items/{claim_item_id}", headers=headers)

    def list_claim_items(self, headers, params=None):
        return self._request("GET", "/claim-items", headers=headers, params=params)

    def start_review(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/claims/{claim_id}/start-review", payload or {}, headers
        )

    def approve_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/approve", payload or {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def appeal_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/appeal", payload or {}, headers)

    def reverse_approval(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/reverse-approval", payload, headers
        )

    def pay_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/pay", payload or {}, headers)

    # ---- Billing ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/premium-invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/premium-invoices", headers=headers, params=params)

    def record_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/premium-invoices/{invoice_id}/payments", payload, headers
        )

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request(
            "GET",
            f"/premium-invoices/{invoice_id}/payments",
            headers=headers,
            params=params,
        )

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def void_payment(self, payment_id, headers, payload=None):
        return self._request("POST", f"/payments/{payment_id}/void", payload or {}, headers)


api_client = ApiClient()
