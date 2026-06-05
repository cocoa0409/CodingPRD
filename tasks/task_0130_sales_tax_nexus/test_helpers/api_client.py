"""API client: one method per endpoint defined in the Sales Tax Nexus PRD.

Subclasses GenericApiClient; the base _request() handles HTTP plumbing.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Tax jurisdictions ────────────────────────────────────────────
    def create_tax_jurisdiction(self, payload, headers):
        return self._request("POST", "/tax-jurisdictions", payload, headers)

    def get_tax_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/tax-jurisdictions/{jurisdiction_id}", headers=headers)

    def list_tax_jurisdictions(self, headers, params=None):
        return self._request("GET", "/tax-jurisdictions", headers=headers, params=params)

    # ─── Product categories ───────────────────────────────────────────
    def create_product_category(self, payload, headers):
        return self._request("POST", "/product-categories", payload, headers)

    def get_product_category(self, category_id, headers):
        return self._request("GET", f"/product-categories/{category_id}", headers=headers)

    def list_product_categories(self, headers, params=None):
        return self._request("GET", "/product-categories", headers=headers, params=params)

    # ─── Sellers ──────────────────────────────────────────────────────
    def create_seller(self, payload, headers):
        return self._request("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", "/sellers", headers=headers, params=params)

    def suspend_seller(self, seller_id, headers):
        return self._request("POST", f"/sellers/{seller_id}/suspend", headers=headers)

    # ─── Marketplace facilitators ─────────────────────────────────────
    def create_marketplace_facilitator(self, payload, headers):
        return self._request("POST", "/marketplace-facilitators", payload, headers)

    def get_marketplace_facilitator(self, facilitator_id, headers):
        return self._request("GET", f"/marketplace-facilitators/{facilitator_id}", headers=headers)

    def list_marketplace_facilitators(self, headers, params=None):
        return self._request("GET", "/marketplace-facilitators", headers=headers, params=params)

    # ─── Nexus profiles ───────────────────────────────────────────────
    def create_nexus_profile(self, payload, headers):
        return self._request("POST", "/nexus-profiles", payload, headers)

    def get_nexus_profile(self, profile_id, headers):
        return self._request("GET", f"/nexus-profiles/{profile_id}", headers=headers)

    def list_nexus_profiles(self, headers, params=None):
        return self._request("GET", "/nexus-profiles", headers=headers, params=params)

    def register_nexus_profile(self, profile_id, headers):
        return self._request("POST", f"/nexus-profiles/{profile_id}/register", headers=headers)

    # ─── Exemption certificates ───────────────────────────────────────
    def create_exemption_certificate(self, payload, headers):
        return self._request("POST", "/exemption-certificates", payload, headers)

    def get_exemption_certificate(self, certificate_id, headers):
        return self._request("GET", f"/exemption-certificates/{certificate_id}", headers=headers)

    def list_exemption_certificates(self, headers, params=None):
        return self._request("GET", "/exemption-certificates", headers=headers, params=params)

    def revoke_exemption_certificate(self, certificate_id, headers):
        return self._request("POST", f"/exemption-certificates/{certificate_id}/revoke", headers=headers)

    def reinstate_exemption_certificate(self, certificate_id, headers):
        return self._request("POST", f"/exemption-certificates/{certificate_id}/reinstate", headers=headers)

    # ─── Transactions + line items ────────────────────────────────────
    def create_transaction(self, payload, headers):
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def create_line_item(self, payload, headers):
        return self._request("POST", "/line-items", payload, headers)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    def settle_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/settle", headers=headers)

    def void_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/void", headers=headers)

    def flag_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/flag", headers=headers)

    def clear_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/clear", headers=headers)

    # ─── Use-tax accruals ─────────────────────────────────────────────
    def create_use_tax_accrual(self, payload, headers):
        return self._request("POST", "/use-tax-accruals", payload, headers)

    def get_use_tax_accrual(self, accrual_id, headers):
        return self._request("GET", f"/use-tax-accruals/{accrual_id}", headers=headers)

    def list_use_tax_accruals(self, headers, params=None):
        return self._request("GET", "/use-tax-accruals", headers=headers, params=params)

    # ─── Tax returns + remittance ─────────────────────────────────────
    def create_tax_return(self, payload, headers):
        return self._request("POST", "/tax-returns", payload, headers)

    def get_tax_return(self, return_id, headers):
        return self._request("GET", f"/tax-returns/{return_id}", headers=headers)

    def list_tax_returns(self, headers, params=None):
        return self._request("GET", "/tax-returns", headers=headers, params=params)

    def accept_tax_return(self, return_id, headers):
        return self._request("POST", f"/tax-returns/{return_id}/accept", headers=headers)

    def reject_tax_return(self, return_id, headers):
        return self._request("POST", f"/tax-returns/{return_id}/reject", headers=headers)

    def reopen_tax_return(self, return_id, headers):
        return self._request("POST", f"/tax-returns/{return_id}/reopen", headers=headers)

    def file_tax_return(self, return_id, headers):
        return self._request("POST", f"/tax-returns/{return_id}/file", headers=headers)

    def create_remittance_payment(self, payload, headers):
        return self._request("POST", "/remittance-payments", payload, headers)

    def get_remittance_payment(self, payment_id, headers):
        return self._request("GET", f"/remittance-payments/{payment_id}", headers=headers)

    def list_remittance_payments(self, headers, params=None):
        return self._request("GET", "/remittance-payments", headers=headers, params=params)

    # ─── Audit log entries ────────────────────────────────────────────
    def get_audit_log_entry(self, entry_id, headers):
        return self._request("GET", f"/audit-log-entries/{entry_id}", headers=headers)

    def list_audit_log_entries(self, headers, params=None):
        return self._request("GET", "/audit-log-entries", headers=headers, params=params)

    # ─── Test-driving clock ───────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
